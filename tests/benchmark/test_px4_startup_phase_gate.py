"""Fresh owned PX4 log and status must jointly precede cold TIMESYNC."""

import copy

import pytest

from tests.benchmark.test_px4_owned_startup_probe import OWNER, STATUS, Backend, make_probe
from tools.benchmark.px4_startup_phase_gate import StartupPhaseGate, StartupPhaseRefusal


def make_gate(tmp_path, backend=None, source_guard=None):
    backend = backend or Backend([])
    path = tmp_path / 'px4.log'
    path.write_bytes(b'')
    stat = path.stat()
    events = []
    gate = StartupPhaseGate(
        process=type('Process', (), {'pid': 321})(), expected=OWNER, log_path=path,
        initial_log=dict(device=stat.st_dev, inode=stat.st_ino, size=0),
        spawn_ns=10, deadline_ns=60_000_000_010, journal=events.append,
        source_guard=source_guard or (lambda: None), backend=backend)
    return gate, path, backend, events


def ready_probe():
    probe, _, _ = make_probe([STATUS + b'\0\0', b''])
    assert probe.poll() is None
    assert probe.poll()['phase'] == 'ready'
    return probe


def test_status_and_fresh_complete_log_line_are_both_required(tmp_path):
    gate, log, _, events = make_gate(tmp_path)
    gate.accept_status(ready_probe())
    assert gate.progress['phase'] == 'startup'
    with pytest.raises(StartupPhaseRefusal, match='not ready'):
        gate.transition()
    log.write_bytes(b'INFO Startup script returned success')
    gate.poll_log()
    assert gate.progress['phase'] == 'startup'
    with log.open('ab') as stream:
        stream.write(b'fully\n')
    gate.poll_log()
    transition = gate.transition()
    assert transition['phase'] == 'ready'
    assert transition['fusion_qualified'] is False
    assert transition['startup_ready_monotonic_ns'] >= 10
    assert gate.evidence['status']['raw_stdout_hex'] == STATUS.hex()
    assert gate.evidence['log']['marker_line'] == 1
    assert any(event['kind'] == 'startup_ready' for event in events)


def test_no_instance_status_remains_pending_even_after_success_marker(tmp_path):
    gate, log, _, _ = make_gate(tmp_path)
    log.write_bytes(b'INFO Startup script returned successfully\n')
    gate.poll_log()
    probe, _, _ = make_probe([b'\0\x01', b''])
    probe.poll()
    assert probe.poll()['phase'] == 'pending'
    gate.accept_status(probe)
    assert gate.progress['phase'] == 'startup'
    gate.accept_status(ready_probe())
    assert gate.transition()['phase'] == 'ready'


def test_ready_phase_rechecks_fresh_log_and_latches_late_startup_failure(tmp_path):
    gate, log, _, _ = make_gate(tmp_path)
    log.write_bytes(b'INFO Startup script returned successfully\n')
    gate.poll_log()
    gate.accept_status(ready_probe())
    gate.transition()
    assert gate.poll_log(after_transition=True)['phase'] == 'ready'
    with log.open('ab') as stream:
        stream.write(b'ERROR Startup script returned with return value: 1\n')
    with pytest.raises(StartupPhaseRefusal, match='startup failure'):
        gate.poll_log(after_transition=True)
    assert gate.progress['phase'] == 'failed'


def test_successful_transition_before_spawn_cap_uses_original_cold_eight_seconds(tmp_path):
    gate, log, backend, _ = make_gate(tmp_path)
    log.write_bytes(b'INFO Startup script returned successfully\n')
    gate.poll_log()
    gate.accept_status(ready_probe())
    backend.now = 60_000_000_009
    ready = gate.transition()['startup_ready_monotonic_ns']
    backend.now = 60_000_000_011  # Spawn-phase cap passed after valid transition.
    assert gate.poll_log(after_transition=True)['phase'] == 'ready'
    backend.now = ready + 8_000_000_000
    with pytest.raises(StartupPhaseRefusal, match='deadline'):
        gate.poll_log(after_transition=True)


@pytest.mark.parametrize('change', ['replace', 'truncate', 'rewrite', 'symlink'])
def test_log_identity_prefix_and_type_must_remain_stable(tmp_path, change):
    gate, log, _, _ = make_gate(tmp_path)
    log.write_bytes(b'INFO before\n')
    gate.poll_log()
    if change == 'replace':
        other = tmp_path / 'other'
        other.write_bytes(b'INFO Startup script returned successfully\n')
        other.replace(log)
    elif change == 'truncate':
        log.write_bytes(b'')
    elif change == 'rewrite':
        log.write_bytes(b'XXXX before\n')
    else:
        other = tmp_path / 'other'
        other.write_bytes(b'INFO Startup script returned successfully\n')
        log.unlink()
        try:
            log.symlink_to(other)
        except OSError:
            pytest.skip('symlink creation unavailable')
    with pytest.raises(StartupPhaseRefusal):
        gate.poll_log()
    assert gate.progress['phase'] == 'failed'


@pytest.mark.parametrize('fault', ['deadline', 'regression', 'owner', 'source', 'journal'])
def test_startup_failures_never_grant_transition(tmp_path, fault):
    failed = {'source': False}

    def guard():
        if failed['source']:
            raise ValueError('source lost')

    gate, log, backend, _ = make_gate(tmp_path, source_guard=guard)
    log.write_bytes(b'INFO Startup script returned successfully\n')
    if fault == 'deadline':
        backend.now = 60_000_000_010
    elif fault == 'regression':
        backend.now = 9
    elif fault == 'owner':
        backend.owner = copy.deepcopy(OWNER)
        backend.owner['start_ticks'] += 1
    elif fault == 'source':
        failed['source'] = True
    else:
        gate._journal = lambda event: (_ for _ in ()).throw(OSError('journal failed'))
    with pytest.raises(StartupPhaseRefusal):
        gate.poll_log()
    assert gate.progress['phase'] == 'failed'


def test_failure_line_outweighs_success_and_late_line_is_rejected(tmp_path):
    gate, log, _, _ = make_gate(tmp_path)
    log.write_bytes(b'INFO Startup script returned successfully\n'
                    b'ERROR Startup script returned with return value: 15\n')
    with pytest.raises(StartupPhaseRefusal):
        gate.poll_log()
    assert gate.progress['phase'] == 'failed'
    assert gate.evidence['log']['bytes_read'] == len(log.read_bytes())
    assert gate.evidence['log']['sha256']
    late_dir = tmp_path / 'late'
    late_dir.mkdir()
    late_gate, late_log, backend, _ = make_gate(late_dir)
    late_log.write_bytes(b'INFO Startup script returned successfully\n')
    backend.now = 60_000_000_010
    with pytest.raises(StartupPhaseRefusal):
        late_gate.poll_log()
    assert late_gate.progress['phase'] == 'failed'


def test_invalid_baseline_or_wrong_probe_never_authorizes(tmp_path):
    path = tmp_path / 'px4.log'
    path.write_bytes(b'')
    stat = path.stat()
    with pytest.raises(StartupPhaseRefusal):
        StartupPhaseGate(type('Process', (), {'pid': 321})(), OWNER, path,
                         dict(device=stat.st_dev, inode=stat.st_ino, size=1),
                         10, 60_000_000_010, lambda _: None, lambda: None, backend=Backend([]))
    gate, _, _, _ = make_gate(tmp_path)
    with pytest.raises(StartupPhaseRefusal):
        gate.accept_status(object())


def test_status_reply_from_different_owned_identity_is_refused(tmp_path):
    gate, _, _, _ = make_gate(tmp_path)
    probe = ready_probe()
    probe._expected['start_ticks'] += 1
    with pytest.raises(StartupPhaseRefusal):
        gate.accept_status(probe)
    assert gate.progress['phase'] == 'failed'


def test_transition_time_is_after_journal_returns(tmp_path):
    gate, log, backend, _ = make_gate(tmp_path)
    log.write_bytes(b'INFO Startup script returned successfully\n')
    gate.poll_log()
    gate.accept_status(ready_probe())

    def delayed_journal(event):
        if event['kind'] == 'startup_ready':
            backend.now += 100

    gate._journal = delayed_journal
    assert gate.transition()['startup_ready_monotonic_ns'] == 110
