"""A diagnostic log observer must never invent a PX4 startup transition."""

import json

import pytest


class Clock:
    def __init__(self):
        self.ns = 1_000_000_000
        self.on_sleep = lambda: None

    def now(self):
        return self.ns

    def sleep(self, seconds):
        self.ns += round(seconds * 1_000_000_000)
        self.on_sleep()


def test_observer_records_first_read_time_and_terminal_without_inventing_missing_markers(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    clock = Clock()
    log = tmp_path / "px4.log"
    output = tmp_path / "observed.json"
    count = 0

    def produce():
        nonlocal count
        count += 1
        if count == 1:
            log.write_bytes(b"INFO Gazebo world is ready\nINFO PX4_GZ_MODEL_NAME set\n")
        elif count == 2:
            with log.open("ab") as stream:
                stream.write(b"INFO setting initial absolute time\n")
        elif count == 3:
            with log.open("ab") as stream:
                stream.write(b"ERROR Startup script returned with return value: 15\n")

    clock.on_sleep = produce
    result = observe_px4_startup(log, output, max_wall_ns=500_000_000,
                                  now_ns=clock.now, sleep=clock.sleep)
    assert result["status"] == "startup_failed"
    assert result["markers"]["Gazebo world is ready"]["observed_mono_ns"] == 1_020_000_000
    assert result["markers"]["setting initial absolute time"]["observed_mono_ns"] == 1_040_000_000
    assert result["markers"]["[mavlink] mode: Onboard"] is None
    assert result["time_semantics"] == "first_observed_not_px4_event_time"
    assert json.loads(output.read_text()) == result


def test_observer_times_out_with_missing_markers_and_no_log(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    clock = Clock()
    result = observe_px4_startup(tmp_path / "missing.log", tmp_path / "observed.json",
                                  max_wall_ns=40_000_000, now_ns=clock.now, sleep=clock.sleep)
    assert result["status"] == "deadline_without_log"
    assert all(value is None for value in result["markers"].values())


def test_observer_announces_ready_only_after_absent_log_check(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    clock = Clock()
    log = tmp_path / "px4.log"
    ready = []

    def on_ready():
        assert not log.exists()
        ready.append(clock.now())
        log.write_bytes(b"INFO Startup script returned successfully\n")

    result = observe_px4_startup(
        log, tmp_path / "observed.json", max_wall_ns=40_000_000,
        now_ns=clock.now, sleep=clock.sleep, on_ready=on_ready,
    )
    assert ready == [1_000_000_000]
    assert result["status"] == "startup_completed"


def test_observer_ready_callback_failure_is_retained(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    output = tmp_path / "observed.json"

    def fail():
        raise RuntimeError("diagnostic readiness failed")

    with pytest.raises(RuntimeError, match="diagnostic readiness failed"):
        observe_px4_startup(tmp_path / "px4.log", output,
                            max_wall_ns=40_000_000, on_ready=fail)
    saved = json.loads(output.read_text())
    assert saved["status"] == "observer_failed"
    assert "diagnostic readiness failed" in saved["failure"]


def test_observer_never_announces_ready_for_preexisting_log(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    log = tmp_path / "px4.log"
    log.write_text("historical\n")
    called = []
    with pytest.raises(ValueError, match="existed before observer"):
        observe_px4_startup(log, tmp_path / "observed.json",
                            max_wall_ns=40_000_000, on_ready=lambda: called.append(True))
    assert called == []


def test_observer_does_not_accept_a_log_first_seen_after_deadline(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    clock = Clock()
    log = tmp_path / "px4.log"

    def late_success():
        clock.ns += 100_000_000
        log.write_bytes(b"INFO Startup script returned successfully\n")

    clock.on_sleep = late_success
    result = observe_px4_startup(log, tmp_path / "observed.json",
                                  max_wall_ns=40_000_000, now_ns=clock.now, sleep=clock.sleep)
    assert result["status"] == "deadline_without_log"
    assert result["markers"]["Startup script returned successfully"] is None


def test_observer_refuses_replaced_log_and_retains_identity_failure(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    clock = Clock()
    log = tmp_path / "px4.log"
    count = 0

    def replace():
        nonlocal count
        count += 1
        if count == 1:
            log.write_bytes(b"INFO Gazebo world is ready\n")
        elif count == 2:
            log.unlink()
            log.write_bytes(b"INFO [mavlink] mode: Onboard\n")

    clock.on_sleep = replace
    output = tmp_path / "observed.json"
    with pytest.raises(ValueError, match="identity changed"):
        observe_px4_startup(log, output, max_wall_ns=100_000_000,
                             now_ns=clock.now, sleep=clock.sleep)
    saved = json.loads(output.read_text())
    assert saved["status"] == "observer_failed"
    assert saved["markers"]["[mavlink] mode: Onboard"] is None


def test_observer_refuses_log_disappearance_after_first_read(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    clock = Clock()
    log = tmp_path / "px4.log"
    count = 0

    def disappear():
        nonlocal count
        count += 1
        if count == 1:
            log.write_bytes(b"INFO Gazebo world is ready\n")
        elif count == 2:
            log.unlink()

    clock.on_sleep = disappear
    output = tmp_path / "observed.json"
    with pytest.raises(ValueError, match="disappeared"):
        observe_px4_startup(log, output, max_wall_ns=100_000_000,
                             now_ns=clock.now, sleep=clock.sleep)
    assert json.loads(output.read_text())["status"] == "observer_failed"


def test_observer_refuses_same_inode_truncate_and_regrow(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    clock = Clock()
    log = tmp_path / "px4.log"
    first = b"INFO Gazebo world is ready\n"
    count = 0

    def rewrite():
        nonlocal count
        count += 1
        if count == 1:
            log.write_bytes(first)
        elif count == 2:
            log.write_bytes(b"X" * len(first) + b"Startup script returned successfully\n")

    clock.on_sleep = rewrite
    output = tmp_path / "observed.json"
    with pytest.raises(ValueError, match="prefix changed"):
        observe_px4_startup(log, output, max_wall_ns=100_000_000,
                             now_ns=clock.now, sleep=clock.sleep)
    saved = json.loads(output.read_text())
    assert saved["status"] == "observer_failed"
    assert saved["markers"]["Startup script returned successfully"] is None


def test_observer_refuses_dangling_symlink_as_preexisting_path(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    log = tmp_path / "px4.log"
    try:
        log.symlink_to(tmp_path / "missing-target.log")
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    output = tmp_path / "observed.json"
    with pytest.raises(ValueError, match="existed before observer"):
        observe_px4_startup(log, output, max_wall_ns=40_000_000)
    assert json.loads(output.read_text())["status"] == "observer_failed"


def test_observer_refuses_preexisting_output_without_touching_it(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    output = tmp_path / "observed.json"
    output.write_text("historical")
    with pytest.raises(FileExistsError):
        observe_px4_startup(tmp_path / "px4.log", output, max_wall_ns=40_000_000)
    assert output.read_text() == "historical"


def test_observer_refuses_log_output_alias_before_creating_log(tmp_path):
    from tools.benchmark.observe_px4_startup import observe_px4_startup

    log = tmp_path / "px4.log"
    alias = tmp_path / "child" / ".." / "px4.log"
    (tmp_path / "child").mkdir()
    with pytest.raises(ValueError, match="same path"):
        observe_px4_startup(log, alias, max_wall_ns=40_000_000)
    assert not log.exists()
