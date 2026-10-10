"""Actual cold/filter/parser continuation, synthetic times/status, no transport."""
import copy

import pytest

from tests.benchmark.test_openvins_timesync_bootstrap import (
    EPOCH,
    LISTENER,
    PREFIX,
    body,
    frame,
    kwargs,
    ready,
)


def completed(journal=None):
    obj = ready(journal=journal)
    for index in range(1, 500):
        now = index * 10_000_000
        obj.reserve_reply(*body(index)[:2], **kwargs(now))
        obj.feed_stream(frame(index), LISTENER, **kwargs(now + 1))
    obj.finish_stream(0, LISTENER, **kwargs(now + 2))
    return obj


START = 4_990_000_003
TOKEN = 'maintenance-listener'


def take(obj, journal=None, now=START, deadline=300_000_000_000):
    method = getattr(obj, 'take_continuation', None)
    assert callable(method), 'completed cold bootstrap has no continuation transfer'
    return method(TOKEN, deadline, journal or (lambda _: None), **kwargs(now))


def raw(index, ordinal, *, offset=0, estimated=0, rtt=2000):
    request, response, text = body(index, rtt)
    response -= offset * 1000
    # Explicit nonzero-offset sample checks that the converged filter survives.
    text = text.replace(f'remote_timestamp: {body(index, rtt)[1]//1000}'.encode(),
                        f'remote_timestamp: {response//1000}'.encode())
    text = text.replace(b'observed_offset: 0', f'observed_offset: {offset}'.encode())
    text = text.replace(b'estimated_offset: 0', f'estimated_offset: {estimated}'.encode())
    return request, response, PREFIX + f'\nTOPIC: timesync_status instance 0 #{ordinal}\n'.encode() + text


def feed(obj, packet, now=START):
    return obj.feed_stream(packet, TOKEN, **kwargs(now))


def replay(obj):
    return feed(obj, raw(499, 1)[2])


def test_qualified_transfer_keeps_filter_and_raw_boundary_separate():
    events = []
    cold = completed()
    maintained = take(cold, events.append)
    assert cold.progress['modeled_bootstrap_ready']
    assert cold.progress['continuation_taken']
    result = replay(maintained)
    assert result['modeled_accepted_samples'] == 500
    assert result['maintenance_correlated_samples'] == 0
    for index in (500, 501):
        request, response, packet = raw(index, index - 498, offset=100)
        maintained.reserve_reply(request, response, **kwargs(START + index))
        result = feed(maintained, packet, START + index + 1)
        assert result['modeled_accepted_samples'] == index + 1
        assert result['maintenance_correlated_samples'] == index - 499
        assert result['estimated_offset_us'] == 0  # converged gain .003, not a new cold filter
    accepted = [e for e in events if e['kind'] == 'maintenance_status']
    assert [e['raw_status']['ordinal'] for e in accepted] == [2, 3]
    assert [e['observer_input']['ordinal'] for e in accepted] == [501, 502]
    assert [e['raw_status']['observed_offset'] for e in accepted] == [100, 100]
    assert all(result[k] is False for k in ('live_convergence_qualified', 'network_authorized', 'fusion_qualified'))


def test_maintenance_passes_original8s_but_not_declared_deadline():
    obj = take(completed(), deadline=10_000_000_000)
    replay(obj)
    now = START
    for index in range(500, 505):
        now += 999_000_000
        req, response, packet = raw(index, index - 498)
        obj.reserve_reply(req, response, **kwargs(now))
        feed(obj, packet, now + 1)
    assert now > 8_000_000_000
    with pytest.raises(ValueError, match='deadline'):
        obj.check(**kwargs(10_000_000_000))


@pytest.mark.parametrize('mode', ['unfinished', 'late', 'bad-deadline', 'bool-deadline', 'repeat'])
def test_invalid_transfer_never_creates_a_fresh_filter(mode):
    cold = ready() if mode == 'unfinished' else completed()
    if mode == 'repeat':
        first = take(cold)
    with pytest.raises(ValueError):
        take(cold, now=8_000_000_000 if mode == 'late' else START,
             deadline=True if mode == 'bool-deadline' else START if mode == 'bad-deadline' else 300_000_000_000)
    if mode == 'repeat':
        with pytest.raises(ValueError):
            replay(first)


@pytest.mark.parametrize('mode', ['replayed', 'changed', 'unsolicited', 'missing', 'epoch', 'token'])
def test_maintenance_status_failure_latches(mode):
    obj = take(completed())
    if mode == 'changed':
        packet = raw(498, 1)[2]
    else:
        replay(obj)
        packet = raw(499 if mode == 'replayed' else 500, 2)[2]
    if mode in ('replayed', 'missing', 'epoch', 'token'):
        obj.reserve_reply(*raw(500, 2)[:2], **kwargs(START + 1))
    with pytest.raises(ValueError):
        if mode == 'missing':
            obj.check(**kwargs(START + 2_000_000_001))
        else:
            obj.feed_stream(packet, 'wrong' if mode == 'token' else TOKEN, now_ns=START + 2,
                            epoch_token='wrong' if mode == 'epoch' else EPOCH)
    assert obj.progress['failure']
    with pytest.raises(ValueError):
        obj.reserve_reply(*raw(501, 3)[:2], **kwargs(START + 3))


def test_boundary_must_precede_new_reply_and_is_not_repeatable():
    obj = take(completed())
    with pytest.raises(ValueError):
        obj.reserve_reply(*raw(500, 2)[:2], **kwargs(START))
    obj = take(completed())
    replay(obj)
    with pytest.raises(ValueError):
        replay(obj)


def test_journal_failure_and_reentry_keep_transfer_failed():
    cold = completed()
    with pytest.raises(OSError):
        take(cold, lambda _: (_ for _ in ()).throw(OSError('journal failed')))
    assert cold.progress['failure']
    with pytest.raises(ValueError):
        take(cold)
    cold = completed()
    def reenter(_):
        with pytest.raises(ValueError):
            take(cold)
    # Transfer is journaled by the supplied lifecycle journal as well as cold history.
    with pytest.raises(ValueError):
        take(cold, reenter)


def test_partial_record_cancellation_retains_bytes_without_clean_exit_claim():
    obj = take(completed())
    replay(obj)
    obj.reserve_reply(*raw(500, 2)[:2], **kwargs(START + 1))
    packet = raw(500, 2)[2][:31]
    feed(obj, packet, START + 2)
    result = obj.cancel('declared capture stop', **kwargs(START + 3))
    assert result['phase'] == 'cancelled'
    assert result['pending_reply']
    assert obj.progress['pending_reply']  # cancelling does not manufacture a matched status
    assert result['incomplete_frame_bytes'] == 31
    assert not result['listener_clean_exit']
    assert not result['maintenance_healthy']
    assert any(e.get('raw_hex') == packet.hex() for e in obj.events)
    with pytest.raises(ValueError):
        obj.reserve_reply(*raw(501, 3)[:2], **kwargs(START + 4))


def test_evidence_is_copied_and_bootstrap_cannot_resume_consumption():
    cold = completed()
    obj = take(cold)
    before = copy.deepcopy(cold.events)
    replay(obj)
    exported = obj.events
    exported.clear()
    assert obj.events
    assert cold.events == before
    with pytest.raises(ValueError):
        cold.reserve_reply(*raw(500, 2)[:2], **kwargs(START + 1))
    with pytest.raises(ValueError):
        obj.check(**kwargs(START + 2))


def test_cancel_after_source_failure_does_not_mislabel_successful_journal():
    cold = completed()
    obj = take(cold)
    replay(obj)
    with pytest.raises(ValueError):
        cold.reserve_reply(*raw(500, 2)[:2], **kwargs(START + 1))
    result = obj.cancel('source failed', **kwargs(START + 2))
    assert result['failure']
    assert result['cancel_journal_error'] is None


def test_cancellation_journal_failure_is_failed_and_success_is_idempotent():
    def journal(event):
        if event['kind'] == 'cancellation_requested':
            raise OSError('cancel write failed')
    obj = take(completed(), journal)
    replay(obj)
    result = obj.cancel('capture stop', **kwargs(START + 1))
    assert result['failure']
    assert result['cancel_journal_error']
    obj = take(completed())
    replay(obj)
    first = obj.cancel('capture stop', **kwargs(START + 1))
    assert obj.cancel('capture stop', **kwargs(START + 2)) == first


def test_high_rtt_after_handoff_does_not_reset_sample_count_or_claim_healthy():
    obj = take(completed())
    replay(obj)
    req, resp, packet = raw(500, 2, rtt=10_000)
    obj.reserve_reply(req, resp, **kwargs(START + 1))
    result = feed(obj, packet, START + 2)
    assert result['modeled_accepted_samples'] == 500
    assert result['maintenance_correlated_samples'] == 1
    assert not result['maintenance_healthy']


@pytest.mark.parametrize('mode', ['bool-clock', 'clock-backwards', 'partial', 'journal', 'non-none'])
def test_boundary_failure_never_grants_reply_permission(mode):
    def journal(event):
        if event['kind'] == 'boundary_snapshot':
            if mode == 'journal':
                raise OSError('boundary write failed')
            if mode == 'non-none':
                return True
    obj = take(completed(), journal)
    with pytest.raises((ValueError, OSError)):
        if mode == 'partial':
            feed(obj, raw(499, 1)[2] + b'\x1b', START)
        else:
            feed(obj, raw(499, 1)[2], True if mode == 'bool-clock' else START - 1 if mode == 'clock-backwards' else START)
    with pytest.raises(ValueError):
        obj.reserve_reply(*raw(500, 2)[:2], **kwargs(START + 1))


def test_finite_listener_exhaustion_keeps_last_match_and_forbids_rollover():
    obj = take(completed())
    replay(obj)
    for index in range(500, 4595):
        req, response, packet = raw(index, index - 498)
        now = START + index * 1_000_000
        obj.reserve_reply(req, response, **kwargs(now))
        if index == 4594:
            with pytest.raises(ValueError, match='exhausted'):
                feed(obj, packet, now + 1)
        else:
            feed(obj, packet, now + 1)
    result = obj.progress
    assert result['raw_records_seen'] == 4096
    assert result['maintenance_correlated_samples'] == 4095
    assert result['modeled_accepted_samples'] == 4595
    assert result['failure']
    assert not result['pending_reply']  # last status actually consumed the reservation
    assert not result['maintenance_healthy']
    with pytest.raises(ValueError):
        obj.reserve_reply(*raw(4595, 4097)[:2], **kwargs(now + 2))
