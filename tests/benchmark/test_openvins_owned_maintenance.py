"""Real coordinator/parser/filter with injected daemon, identity and wall clock."""
import pytest

from tests.benchmark.test_openvins_owned_bootstrap import Connection, body, frame, make, stream_ready


def completed(journal=None):
    obj, backend = make(journal)
    stream_ready(obj)
    for index in range(1, 500):
        backend.now += 10_000_000
        obj.reserve_reply(*body(index)[:2])
        backend.connections[2].reads.append(frame(index))
        obj.poll()
    backend.connections[2].reads.extend([b'\0\0', b''])
    obj.poll()
    assert obj.poll()['transport_bootstrap_complete']
    return obj, backend


def raw(index, ordinal):
    return b'\x1b[2J\n\x1b[H' + f'\nTOPIC: timesync_status instance 0 #{ordinal}\n'.encode() + body(index)[2]


def begin(obj, backend, deadline=300_000_000_010):
    assert callable(getattr(obj, 'begin_maintenance', None)), 'owned maintenance binding missing'
    context = obj.begin_maintenance(deadline)
    backend.connections.append(Connection([raw(499, 1)]))
    obj.poll()
    return context


def test_owned_handoff_keeps500_then_correlates_beyond_original_deadline():
    events = []
    obj, backend = completed(events.append)
    context = begin(obj, backend)
    assert context.progress['modeled_accepted_samples'] == 500
    assert not obj.progress['maintenance_healthy']
    for index in range(500, 505):
        backend.now += 900_000_000
        obj.reserve_reply(*body(index)[:2])
        backend.connections[3].reads.append(raw(index, index - 498))
        result = obj.poll()
    assert backend.now > 8_000_000_010
    assert result['phase'] == 'ready' and result['maintenance_healthy']
    assert result['modeled_accepted_samples'] == 505
    assert result['bootstrap_completed'] and result['transport_bootstrap_complete']
    assert len(backend.used) == 4
    assert backend.used[3].sent == b'listener timesync_status -i 0 -n 4096\0'
    assert events == obj.evidence['events']
    assert obj.evidence['bootstrap_progress']['modeled_accepted_samples'] == 500
    assert obj.evidence['maintenance_progress']['maintenance_correlated_samples'] == 5
    assert not any(result[k] for k in ('network_authorized', 'fusion_qualified', 'live_convergence_qualified'))
    obj.close()


@pytest.mark.parametrize('condition', ['early', 'late', 'invalid-deadline', 'repeated', 'owner'])
def test_handoff_refuses_ineligible_transition_without_extra_listener(condition):
    obj, backend = make() if condition == 'early' else completed()
    assert callable(getattr(obj, 'begin_maintenance', None)), 'owned maintenance binding missing'
    if condition == 'late':
        backend.now = 8_000_000_010
    elif condition == 'owner':
        backend.owner['start_ticks'] += 1
    elif condition == 'repeated':
        obj.begin_maintenance(300_000_000_010)
    used = len(backend.used)
    with pytest.raises(ValueError):
        obj.begin_maintenance(True if condition == 'invalid-deadline' else 300_000_000_010)
    assert len(backend.used) == used
    assert obj.progress['failure']
    with pytest.raises(ValueError):
        obj.poll()


@pytest.mark.parametrize('fault', ['journal', 'late-journal', 'reentrant'])
def test_transition_journal_cannot_hide_failure_or_extend_startup(fault):
    holder = {}

    def journal(event):
        if event['event'].get('kind') != 'maintenance_started':
            return
        if fault == 'journal':
            raise OSError('handoff log')
        if fault == 'late-journal':
            holder['backend'].now = 8_000_000_010
        if fault == 'reentrant':
            with pytest.raises(ValueError):
                holder['obj'].poll()

    obj, backend = completed(journal)
    holder.update(obj=obj, backend=backend)
    assert callable(getattr(obj, 'begin_maintenance', None)), 'owned maintenance binding missing'
    with pytest.raises(ValueError):
        obj.begin_maintenance(300_000_000_010)
    assert obj.progress['failure']
    assert len(backend.used) == 3


@pytest.mark.parametrize('fault', ['bad-boundary', 'duplicate', 'silence', 'owner', 'deadline'])
def test_maintenance_fault_latches_and_cancels_only_owned_listener(fault):
    obj, backend = completed()
    assert callable(getattr(obj, 'begin_maintenance', None)), 'owned maintenance binding missing'
    obj.begin_maintenance(6_000_000_010 if fault == 'deadline' else 300_000_000_010)
    backend.connections.append(Connection([raw(498 if fault == 'bad-boundary' else 499, 1)]))
    with pytest.raises(ValueError):
        obj.poll()
        if fault == 'duplicate':
            backend.connections[3].reads.append(raw(499, 1))
        elif fault == 'silence':
            backend.now += 2_000_000_000
        elif fault == 'owner':
            backend.owner['start_ticks'] += 1
        elif fault == 'deadline':
            backend.now = 6_000_000_010
        obj.poll()
    assert obj.progress['failure'] and not obj.progress['maintenance_healthy']
    assert obj.progress['bootstrap_completed']
    assert not obj.progress['modeled_bootstrap_ready']
    assert backend.used[3].closed == 1
    assert obj.evidence['maintenance_progress']['phase'] == 'cancelled'
    used = len(backend.used)
    with pytest.raises(ValueError):
        obj.poll()
    assert len(backend.used) == used


def test_close_retains_pending_partial_bytes_and_does_not_claim_finite_exit():
    events = []
    obj, backend = completed(events.append)
    begin(obj, backend)
    obj.reserve_reply(*body(500)[:2])
    backend.connections[3].reads.append(raw(500, 2)[:30])
    obj.poll()
    obj.close()
    obj.close()
    evidence = obj.evidence
    assert evidence['maintenance_progress']['pending_reply']
    assert evidence['maintenance_progress']['incomplete_frame_bytes'] == 30
    assert evidence['maintenance_progress']['phase'] == 'cancelled'
    assert evidence['maintenance_closed']
    assert backend.used[3].closed == 1
    assert not evidence['transports'][3]['transport_complete']
    assert not evidence['transports'][3]['daemon_exit_proven']
    assert events == evidence['events']
    with pytest.raises(ValueError):
        obj.reserve_reply(*body(501)[:2])


def test_legacy_completion_stays_terminal_without_explicit_handoff():
    obj, backend = completed()
    with pytest.raises(ValueError, match='completed'):
        obj.poll()
    assert obj.progress['transport_bootstrap_complete']
    assert len(backend.used) == 3


@pytest.mark.parametrize('fault', ['journal', 'close', 'interrupt', 'reentrant'])
def test_cleanup_faults_are_retained_without_losing_partial_cancellation(fault):
    holder = {}

    def journal(event):
        if event['source'] == 'transport' and event['event']['kind'] == 'cancellation_result':
            if fault == 'journal':
                raise OSError('cancel log unavailable')
            if fault == 'interrupt':
                raise KeyboardInterrupt('cancel interrupted')
            if fault == 'reentrant':
                with pytest.raises(ValueError):
                    holder['obj'].reserve_reply(*body(501)[:2])

    obj, backend = completed(journal)
    holder['obj'] = obj
    begin(obj, backend)
    obj.reserve_reply(*body(500)[:2])
    backend.connections[3].reads.append(raw(500, 2)[:30])
    obj.poll()
    if fault == 'close':
        def failing_close(connection):
            connection.closed += 1
            raise OSError('close unavailable')
        backend.close = failing_close
    if fault == 'interrupt':
        with pytest.raises(KeyboardInterrupt):
            obj.close()
    else:
        obj.close()
    assert obj.progress['failure']
    if fault == 'reentrant':
        # The competing operation is the primary coordinator refusal, not a
        # socket/journal failure. Preserve that distinction in the evidence.
        assert 'concurrent' in obj.progress['failure']
        assert any(e['source'] == 'coordinator' and e['event']['kind'] == 'refusal'
                   for e in obj.evidence['events'])
    else:
        assert obj.evidence['cleanup_errors']
    assert obj.evidence['maintenance_progress']['phase'] == 'cancelled'
    assert obj.evidence['maintenance_progress']['pending_reply']
    assert backend.used[3].closed == 1
    assert not obj.evidence['transports'][3]['daemon_exit_proven']
    with pytest.raises(ValueError):
        obj.poll()
