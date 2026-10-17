"""A declared staged startup must never enter the legacy early-cold path."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.benchmark.test_px4_owned_startup_probe import OWNER
from tools.benchmark import capture_wire_lifecycle as lifecycle
from tools.benchmark.capture_wire_lifecycle import CaptureWireOwner


def test_staged_configuration_refuses_legacy_bind_before_any_session():
    owner = CaptureWireOwner.__new__(CaptureWireOwner)
    owner.config = {'schema': 'capture-wire-startup-v2'}
    owner.driver = None
    with pytest.raises(ValueError, match='staged startup requires'):
        owner.bind(object(), object(), lambda *_: None)
    assert owner.driver is None


@pytest.mark.parametrize('fault', [None, 'missing_next_callback', 'owner_changed'])
def test_clock_callback_precedes_cold_session_and_startup_gate(tmp_path, fault):
    calls, callbacks, original = [], [], []

    class Socket:
        def bind(self, address):
            calls.append(('socket_bind', address))

        def setblocking(self, value):
            assert value is False

        def close(self):
            calls.append('socket_close')

    class Backend:
        now = 100

        def clock(self):
            return self.now

        def observe(self, process):
            assert process.pid == OWNER['pid']
            return dict(self.owner)

    class Gate:
        def __init__(self, process, expected, path, initial, spawn, deadline,
                     journal, guard, *, backend):
            assert path == tmp_path / 'px4.log'
            assert initial['size'] == 0
            assert deadline - spawn == 60_000_000_000
            assert expected == OWNER
            self._deadline = deadline
            self.log_polls = 0
            self.status = False
            journal({'kind': 'startup_phase_started'})
            calls.append('gate')

        @property
        def progress(self):
            return {'log_ready': self.log_polls >= 2, 'status_ready': self.status}

        @property
        def evidence(self):
            return {'phase': 'ready' if self.status else 'startup'}

        def poll_log(self, *, after_transition=False):
            if after_transition:
                calls.append('ready_log_recheck')
                return self.progress
            self.log_polls += 1
            return self.progress

        def accept_status(self, probe):
            assert probe.complete
            self.status = True

        def transition(self):
            assert self.log_polls >= 2 and self.status
            calls.append('transition')
            return {'startup_ready_monotonic_ns': backend.now}

    class Probe:
        def __init__(self, *args, **kwargs):
            self.complete = False
            calls.append('probe')

        def poll(self):
            if not self.complete:
                self.complete = True
                return None
            return {'phase': 'ready'}

    class Driver:
        phase = 'startup'
        _thread = None

        def __init__(self, session):
            self.session = session

        @property
        def progress(self):
            return {'phase': self.phase}

        def start(self):
            calls.append('cold_start')

        def finish(self):
            calls.append('cold_finish')
            self.session._sock.close()

    backend = Backend()
    backend.owner = dict(OWNER)
    log = tmp_path / 'px4.log'
    log.touch()
    st = log.stat()
    process = SimpleNamespace(pid=OWNER['pid'])
    journal = SimpleNamespace(cleanup=lambda *a, **k: None)
    owner = CaptureWireOwner(
        journal, {'errors': []}, tmp_path,
        dict(schema='capture-wire-startup-v2', session_id='staged', sim_origin_ns=0,
             remote_origin_ns=1_000_000, startup_max_wall_ns=60_000_000_000),
        start_ns=100, total_deadline_ns=100 + 300_000_000_000,
        source_guard=lambda: None, heartbeat_sink=lambda _: None,
        socket_factory=lambda *a: Socket(), backend=backend,
        descriptor_snapshot=lambda _: dict(fd=7, device=1, inode=2, mode=49152,
                                           net=OWNER['net']))
    fixture = SimpleNamespace(on_post_update=callbacks.append)

    def cold_session(*args, **kwargs):
        lane, start_ns = args[4], args[6]
        assert lane.progress['committed_samples'] > owner.startup_transition_count
        assert lane.progress['latest_callback_ns'] >= start_ns
        calls.append('cold_session')
        return SimpleNamespace(_sock=owner.sock, evidence={})

    try:
        with patch('tools.benchmark.px4_startup_phase_gate.StartupPhaseGate', Gate), \
             patch('tools.benchmark.px4_owned_startup_probe.OwnedMavlinkStatusProbe', Probe), \
             patch.object(Path, 'is_socket', return_value=True), \
             patch.object(lifecycle, 'ObservedWireSession',
                          side_effect=cold_session), \
             patch.object(lifecycle, 'bind_capture_wire',
                          side_effect=lambda *a, **k: Driver(a[3])):
            owner.begin_startup(process, fixture, lambda info, _: original.append(info.iterations),
                                log_path=log, initial_log=dict(device=st.st_dev, inode=st.st_ino,
                                                               size=0), spawn_ns=100)
            assert len(callbacks) == 1
            for iteration in (1, 2):
                backend.now += 1_000_000
                callbacks[0](SimpleNamespace(iterations=iteration, paused=False,
                                             dt=timedelta(milliseconds=1),
                                             sim_time=timedelta(milliseconds=iteration)), None)
                owner.advance_startup()
                assert owner.driver is None
            backend.now += 1_000_000
            callbacks[0](SimpleNamespace(iterations=3, paused=False,
                                         dt=timedelta(milliseconds=1),
                                         sim_time=timedelta(milliseconds=3)), None)
            owner.advance_startup()
            assert owner.driver is None
            owner.advance_startup()  # No new PostUpdate: old clock sample cannot start cold I/O.
            assert owner.driver is None
            if fault == 'missing_next_callback':
                backend.now += 2_000_000_000
                with pytest.raises(TimeoutError, match='post-transition source callback absent'):
                    owner.advance_startup()
                assert owner.driver is None
                return
            backend.now += 1_000_000
            callbacks[0](SimpleNamespace(iterations=4, paused=False,
                                         dt=timedelta(milliseconds=1),
                                         sim_time=timedelta(milliseconds=4)), None)
            if fault == 'owner_changed':
                backend.owner['start_ticks'] += 1
                with pytest.raises(ValueError, match='PX4 owner changed'):
                    owner.advance_startup()
                assert owner.driver is None
                return
            owner.advance_startup()
            assert original == [1, 2, 3, 4]
            assert owner.lane.progress['committed_samples'] == 4
            assert 'ready_log_recheck' in calls
            assert calls.index('transition') < calls.index('cold_session') < calls.index('cold_start')
            assert (tmp_path / 'wire-startup-events.jsonl').read_text()
    finally:
        owner.finish()
