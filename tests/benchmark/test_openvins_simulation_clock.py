"""Injected UpdateInfo and journal only; never constructs a simulator/socket."""
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from threading import Event, RLock, Thread, current_thread
from types import SimpleNamespace

import pytest

from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock
from tools.benchmark.openvins_simulation_clock import JournaledSimulationClock


def info(iteration=1, **changes):
    fields = dict(iterations=iteration, sim_time=timedelta(milliseconds=iteration),
                  dt=timedelta(milliseconds=1), paused=False)
    fields.update(changes)
    return SimpleNamespace(**fields)


class Rig:
    def __init__(self):
        self.now, self.records, self.hook, self.guard_hook = 100, [], None, None
        self.lane = JournaledSimulationClock('session-1', lambda: self.now, self.journal, self.now, self.guard)

    def guard(self):
        if self.guard_hook:
            return self.guard_hook()

    def journal(self, event):
        self.records.append(event)
        if self.hook:
            return self.hook(event)


def test_normal_distinct_arrival_journal_and_reply_clocks():
    r = Rig()
    r.hook = lambda _: setattr(r, 'now', 300)
    r.lane.post_update(info())
    r.now = 500
    selection = r.lane.snapshot(200)
    assert (selection.observation.sim_ns, selection.observation.callback_ns,
            selection.observation.journal_return_ns, selection.received_ns, selection.selected_ns) == (
                1_000_000, 100, 300, 200, 500)
    assert r.records[0]['kind'] == 'clock_observation_attempt'
    assert 'journal_return_ns' not in r.records[0]
    assert r.lane.evidence['observations'][0]['journal_return_ns'] == 300
    with pytest.raises(FrozenInstanceError):
        selection.observation.sim_ns = 10
    assert not any(r.lane.evidence[k] for k in (
        'runtime_source_proven', 'px4_clock_consumption_proven', 'network_authorized', 'fusion_qualified'))


def test_callback_timestamp_precedes_guard_work():
    r = Rig()
    r.guard_hook = lambda: setattr(r, 'now', 300)
    r.lane.post_update(info())
    assert r.lane.snapshot(100).observation.callback_ns == 100


def test_slow_initial_guard_cannot_refresh_callback():
    r = Rig()
    r.guard_hook = lambda: setattr(r, 'now', 2_000_000_100)
    with pytest.raises(ValueError, match='freshness'):
        r.lane.post_update(info())
    assert not r.lane.evidence['observations']


def test_request_does_not_supply_sim_clock_and_reuse_not_fresh():
    r = Rig()
    remote = RemoteMonotonicClock('session-1', sim_origin_ns=0, remote_origin_ns=1_000_000_000)
    r.lane.post_update(info())
    selected = r.lane.snapshot(100)
    reply = remote.respond_to_px4_request(tc1_ns=0, ts1_ns=999_000, observed_sim_ns=selected.observation.sim_ns)
    assert reply['tc1_ns'] == 1_001_000_000 and reply['ts1_ns'] == 999_000
    again = r.lane.snapshot(100)
    assert again.observation is selected.observation
    with pytest.raises(ValueError, match='paused or regressed'):
        remote.respond_to_px4_request(tc1_ns=0, ts1_ns=999_999_000, observed_sim_ns=again.observation.sim_ns)


def test_selected_clock_stays_old_when_latest_source_is_fresh():
    r = Rig()
    r.lane.post_update(info())
    selected = r.lane.snapshot(100)
    assert r.lane.validate_selection(selected) is None
    r.now = 1_500_000_100
    r.lane.post_update(info(2))
    r.now = 2_000_000_100
    r.lane.check()
    with pytest.raises(ValueError, match='selected.*freshness'):
        r.lane.validate_selection(selected)
    assert r.lane.progress['failure']
    assert r.lane.progress['committed_samples'] == 2


def test_other_lane_observation_not_accepted_by_matching_values():
    r, other = Rig(), Rig()
    r.lane.post_update(info())
    other.lane.post_update(info())
    with pytest.raises(ValueError, match='belongs'):
        r.lane.validate_selection(other.lane.snapshot(100))


@pytest.mark.parametrize('fields', [dict(received_ns=True), dict(received_ns=99), dict(selected_ns=101),
                                  dict(selected_ns=99), dict(selected_ns=1.0)])
def test_malformed_selection_timestamps_refused(fields):
    r = Rig()
    r.lane.post_update(info())
    selected = replace(r.lane.snapshot(100), **fields)
    with pytest.raises(ValueError):
        r.lane.validate_selection(selected)


@pytest.mark.parametrize('changes', [
    dict(paused=True), dict(paused=0), dict(iterations=True), dict(iterations=1.0),
    dict(iterations=0), dict(iterations=2), dict(sim_time=timedelta()),
    dict(sim_time=timedelta(milliseconds=2)), dict(sim_time=0.001),
    dict(dt=timedelta()), dict(dt=timedelta(microseconds=999)), dict(dt=None),
])
def test_invalid_first_observation_latches(changes):
    r = Rig()
    with pytest.raises(ValueError):
        r.lane.post_update(info(**changes))
    with pytest.raises(ValueError, match='latched'):
        r.lane.post_update(info())
    assert r.lane.evidence['failure']
    assert r.lane.evidence['observations'] == []


@pytest.mark.parametrize('next_info', [info(), info(3), info(2, sim_time=timedelta(milliseconds=1)),
                                       info(2, sim_time=timedelta(milliseconds=3)), info(2, paused=True)])
def test_gap_reset_pause_rejected(next_info):
    r = Rig()
    r.lane.post_update(info())
    with pytest.raises(ValueError):
        r.lane.post_update(next_info)
    assert len(r.lane.evidence['observations']) == 1


def test_missing_first_observation_refuses_and_latches():
    r = Rig()
    with pytest.raises(ValueError, match='no committed'):
        r.lane.snapshot(100)
    with pytest.raises(ValueError, match='latched'):
        r.lane.check()


@pytest.mark.parametrize('now', [99, True, float('inf'), 2**64, 2_000_000_100])
def test_bad_clock_or_exact_source_expiry_refuses(now):
    r = Rig()
    r.lane.post_update(info())
    r.now = now
    with pytest.raises(ValueError):
        r.lane.snapshot(100)


def test_delayed_journal_cannot_refresh_source():
    r = Rig()
    r.hook = lambda _: setattr(r, 'now', 2_000_000_100)
    with pytest.raises(ValueError, match='freshness'):
        r.lane.post_update(info())
    assert not r.lane.evidence['observations']
    assert r.lane.evidence['attempts'][0]['journal_return_ns'] == 2_000_000_100


def test_reader_during_pending_writer_only_gets_prior_commit():
    r = Rig()
    r.lane.post_update(info())
    reads = []
    r.now = 200
    r.hook = lambda _: reads.append(r.lane.snapshot(150))
    r.lane.post_update(info(2))
    assert reads[0].observation.iteration == 1
    assert r.lane.snapshot(200).observation.iteration == 2


def test_suppressed_reentrant_writer_cannot_publish():
    r = Rig()
    def recurse(_):
        with pytest.raises(ValueError, match='concurrent'):
            r.lane.post_update(info())
    r.hook = recurse
    with pytest.raises(ValueError, match='latched'):
        r.lane.post_update(info())
    assert not r.lane.evidence['observations']


@pytest.mark.parametrize('outcome', [RuntimeError('disk full'), False])
def test_journal_failures_preserve_attempt_and_latch(outcome):
    r = Rig()
    def fail(_):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    r.hook = fail
    with pytest.raises(ValueError):
        r.lane.post_update(info())
    assert len(r.lane.evidence['attempts']) == 1
    assert not r.lane.evidence['observations']
    with pytest.raises(ValueError):
        r.lane.snapshot(100)


def test_journal_cannot_mutate_accepted_observation_or_evidence():
    r = Rig()
    r.hook = lambda event: event.update(sim_ns=99)
    r.lane.post_update(info())
    e = r.lane.evidence
    e['observations'][0]['sim_ns'] = 77
    assert r.lane.snapshot(100).observation.sim_ns == 1_000_000
    assert r.lane.evidence['attempts'][0]['sim_ns'] == 1_000_000


@pytest.mark.parametrize('received', [True, 99, 101, 1.0, -1])
def test_invalid_receive_time_refused(received):
    r = Rig()
    r.lane.post_update(info())
    with pytest.raises(ValueError):
        r.lane.snapshot(received)


def test_guard_replacement_rejected():
    r = Rig()
    r.lane.post_update(info())
    r.guard_hook = lambda: False
    with pytest.raises(ValueError, match='guard'):
        r.lane.snapshot(100)


def test_guard_reentry_cannot_revive_lane():
    r = Rig()
    def recurse():
        r.guard_hook = None
        with pytest.raises(ValueError):
            r.lane.post_update(info())
    r.guard_hook = recurse
    with pytest.raises(ValueError):
        r.lane.post_update(info())
    assert not r.lane.evidence['observations']


def test_original_sample_limit_preserved():
    r = Rig()
    for i in range(1, 25_001):
        r.lane.post_update(info(i))
    assert r.lane.snapshot(100).observation.sim_ns == 25_000_000_000
    with pytest.raises(ValueError, match='limit'):
        r.lane.post_update(info(25_001))
    assert len(r.lane.evidence['observations']) == 25_000


def test_session_is_readonly_and_requires_new_object():
    r = Rig()
    with pytest.raises(AttributeError):
        r.lane.session_id = 'replacement'
    with pytest.raises(ValueError):
        JournaledSimulationClock('', lambda: 100, lambda _: None, 100, lambda: None)


def test_callback_waiting_for_reader_lock_cannot_become_fresh():
    r = Rig()
    reader_inside, writer_entered, release = Event(), Event(), Event()
    errors = []

    class SignaledStateLock:
        def __init__(self):
            self.inner = RLock()

        def __enter__(self):
            if current_thread() is writer:
                writer_entered.set()
            return self.inner.__enter__()

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

    r.lane._state = SignaledStateLock()
    def guard():
        reader_inside.set()
        if not release.wait(2):
            raise RuntimeError('test synchronization timeout')
    r.guard_hook = guard
    def invoke(fn):
        try:
            fn()
        except Exception as exc:
            errors.append(str(exc))
    reader = Thread(target=invoke, args=(r.lane.check,))
    writer = Thread(target=invoke, args=(lambda: r.lane.post_update(info()),))
    try:
        reader.start()
        assert reader_inside.wait(2)
        writer.start()
        assert writer_entered.wait(2)
        r.now = 3_000_000_100
    finally:
        release.set()
        reader.join(2)
        if writer.ident is not None:
            writer.join(2)
    assert not reader.is_alive() and not writer.is_alive()
    assert errors and r.lane.evidence['failure']
    assert not r.lane.evidence['observations']


def test_journal_return_clock_reentry_latches_before_publication():
    r = Rig()
    armed = False
    def clock():
        nonlocal armed
        if armed:
            armed = False
            r.lane.check()
        return r.now
    def journal(_):
        nonlocal armed
        armed = True
    r.lane._now, r.hook = clock, journal
    with pytest.raises(ValueError, match='latched|reentrant'):
        r.lane.post_update(info())
    assert not r.lane.evidence['observations']
