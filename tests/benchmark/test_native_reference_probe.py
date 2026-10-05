import io
from types import SimpleNamespace

import pytest

from tools.benchmark.native_reference_probe import ReferenceRecorder, validate_module


def state(ns):
    return dict(
        position=[0.0, 0.0, 0.2],
        velocity_world=[0.0, 0.0, 0.0],
        accel_world=[0.0, 0.0, 0.0],
        angular_world=[0.0, 0.0, 0.0],
        quaternion_xyzw=[0.0, 0.0, 0.0, 1.0],
        rpy=[0.0, 0.0, 0.0],
        parent_entity=2,
        child_entity=3,
        pre_ns=ns,
        post_ns=ns,
        canary_overwritten=True,
    )


class Fake:
    def pre(self, ecm, ns, dt):
        pass

    def post(self, ecm, ns):
        return state(ns)

    def status(self):
        return dict(failed=False, pending=False, last_ns=25_000_000_000)


def test_complete_recorder_and_counts(tmp_path):
    errors = []
    r = ReferenceRecorder(tmp_path, errors, Fake())
    for i in range(1, 25001):
        assert r.pre(None, i * 1000000, 1000000)
        assert r.post(None, i * 1000000)
    assert r.finish()["complete"] and not errors


@pytest.mark.parametrize("fault", ["pre", "post", "nonfinite", "quaternion", "bound", "epoch", "canary", "gap"])
def test_failure_blocks_next_force_permission(tmp_path, fault):
    class Bad(Fake):
        def pre(self, *a):
            if fault == "pre":
                raise RuntimeError("native pre")

        def post(self, ecm, ns):
            if fault == "post":
                raise RuntimeError("native post")
            s = state(ns)
            if fault == "nonfinite":
                s["accel_world"][0] = float("nan")
            if fault == "quaternion":
                s["quaternion_xyzw"] = [0.0, 0.0, 0.0, 0.0]
            if fault == "bound":
                s["velocity_world"][0] = 4.0
            if fault == "epoch":
                s["post_ns"] += 1
            if fault == "canary":
                s["canary_overwritten"] = False
            return s

    errors = []
    r = ReferenceRecorder(tmp_path, errors, Bad())
    allowed = r.pre(None, 2000000 if fault == "gap" else 1000000, 1000000)
    if allowed:
        r.post(None, 1000000)
    assert errors and not r.pre(None, 2000000, 1000000)
    assert not r.finish()["complete"]


@pytest.mark.parametrize("fault", ["short", "flush", "close"])
def test_journal_fault_retained(tmp_path, fault):
    r = ReferenceRecorder(tmp_path, [], Fake())
    r.stream.close()

    class Bad(io.StringIO):
        def write(self, s):
            return len(s) - 1 if fault == "short" else super().write(s)

        def flush(self):
            if fault == "flush":
                raise OSError("flush")

        def close(self):
            if fault == "close":
                raise OSError("close")
            super().close()

    r.stream = Bad()
    r.pre(None, 1000000, 1000000)
    r.post(None, 1000000)
    assert not r.finish()["complete"] and r.errors


@pytest.mark.parametrize("version,testing", [(2, False), (1, True), (True, False)])
def test_wrong_module_contract_refused(version, testing):
    with pytest.raises(ValueError):
        validate_module(SimpleNamespace(API_VERSION=version, TESTING=testing))


def test_native_cli_requires_paired_hash_and_ready_sensor_mode():
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    args = [
        "--output",
        "x",
        "--motion-profile",
        "supported-ready-v1",
        "--physics-trace-profile",
        "substep-ready-v1",
        "--reference-module",
        "x.so",
        "--reference-sha256",
        "a" * 64,
    ]
    assert str(parse_capture_args(args).reference_module) == "x.so"
    with pytest.raises(SystemExit):
        parse_capture_args(args[:-2])
    with pytest.raises(SystemExit):
        parse_capture_args(["--output", "x"] + args[-4:])


def test_callback_native_failure_prevents_all_later_motion(tmp_path):
    from datetime import timedelta

    from tools.benchmark.native_reference_probe import post_motion, pre_motion

    class Motion:
        def __init__(self):
            self.calls = []

        def pre_update(self, *a):
            self.calls.append("pre")

        def post_update(self, *a):
            self.calls.append("post")

    class Bad(Fake):
        def post(self, *a):
            raise RuntimeError("unconsumed canary")

    r = ReferenceRecorder(tmp_path, [], Bad())
    motion = Motion()
    info = SimpleNamespace(sim_time=timedelta(milliseconds=1), dt=timedelta(milliseconds=1), paused=False)
    pre_motion(r, motion, info, None)
    post_motion(r, motion, info, None)
    info.sim_time = timedelta(milliseconds=2)
    pre_motion(r, motion, info, None)
    assert motion.calls == ["pre"] and r.errors
    r.finish()
