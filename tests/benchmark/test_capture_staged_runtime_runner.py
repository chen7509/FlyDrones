"""Selected capture runner's staged ordering, without PX4 or Gazebo."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.benchmark.capture_disarmed_sensors import run_capture_runtime


class StagedOwner:
    config = {'schema': 'capture-wire-startup-v2'}

    def __init__(self, events, ready_at, fail_at=None):
        self.events, self.ready_at, self.fail_at = events, ready_at, fail_at
        self.backend = SimpleNamespace(clock=lambda: 100)
        self.driver = None
        self.steps = 0

    def begin_startup(self, process, fixture, original_post, *, log_path, initial_log, spawn_ns):
        assert process.pid == 321
        assert Path(log_path).is_absolute()
        assert initial_log['size'] == 0
        assert spawn_ns == 100
        self.events.append('begin_startup')
        fixture.on_post_update(original_post)

    def advance_startup(self):
        self.steps += 1
        self.events.append('advance_startup')
        if self.steps == self.fail_at:
            raise RuntimeError('injected startup/reader failure')
        if self.steps == self.ready_at:
            self.driver = SimpleNamespace(start=lambda: self.events.append('cold_start'))
            self.driver.start()


@pytest.mark.parametrize('ready_at,fail_at,complete', [
    (2, None, True), (99, None, False), (99, 2, False), (1, 2, False),
])
def test_capture_staged_startup_keeps_clock_steps_and_cannot_complete_early(
        tmp_path, ready_at, fail_at, complete):
    events, callbacks, cleanup = [], [], []
    clock = {'sim_ns': 0}
    owner = StagedOwner(events, ready_at, fail_at)
    process = SimpleNamespace(pid=321, args=['owned-px4'], returncode=None,
                              poll=lambda: None)

    def run(blocking, count, paused):
        assert (blocking, count, paused) == (True, 10, False)
        assert len(callbacks) == 1
        clock['sim_ns'] += 1_000_000
        callbacks[0](SimpleNamespace(sim_time_ns=clock['sim_ns']), None)
        events.append('step')
        return True

    fixture = SimpleNamespace(on_post_update=callbacks.append,
                              finalize=lambda: events.append('finalize'),
                              server=lambda: SimpleNamespace(run=run))
    result = {'errors': [], 'status': 'incomplete'}
    journal = SimpleNamespace(cleanup=lambda name, fn, priority: cleanup.append((name, fn)))
    try:
        kwargs = dict(
            journal=journal, output=tmp_path, result=result, errors=result['errors'],
            fixture=fixture, post_update=lambda info, _: events.append('clock_callback'),
            wire_owner=owner, source_guard=None, binding=None, owned_ready={},
            owned_processes={}, read_heartbeats=lambda: pytest.fail('legacy heartbeat'),
            stop=SimpleNamespace(), binary=tmp_path / 'px4', build=tmp_path / 'build',
            runtime=tmp_path, env={}, clock=clock, writer=SimpleNamespace(error=None),
            shadow=None, motion=object(),
            contract={'simulation_duration_ns': 3_000_000, 'wall_budget_s': 300},
            started=0, spawn=lambda *a, **k: process, monotonic=lambda: 0,
        )
        if complete:
            run_capture_runtime(**kwargs)
            assert result['status'] == 'capture_completed'
            assert events.count('clock_callback') == 3
            assert events.index('begin_startup') < events.index('finalize') < events.index('step')
            assert events.index('cold_start') > events.index('clock_callback')
        else:
            message = ('injected startup/reader failure' if fail_at is not None
                       else 'before owned wire cold session')
            with pytest.raises(RuntimeError, match=message):
                run_capture_runtime(**kwargs)
            assert result['status'] == 'incomplete'
            assert events.count('clock_callback') == (fail_at or 3)
            assert ('cold_start' in events) is (ready_at < (fail_at or 4))
        assert json.loads((tmp_path / 'process.json').read_text())['pid'] == 321
    finally:
        for _, action in reversed(cleanup):
            if getattr(action, '__name__', None) == 'close':
                action()
