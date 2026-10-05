import math

import pytest

from tools.benchmark.capture_disarmed_sensors import parse_capture_args
from tools.benchmark.supported_excitation import MASSES, SupportedPolicy, validate_links


def test_fixed_masses_and_link_set():
    assert validate_links(MASSES) == pytest.approx(2.1253076923076923)
    for wrong in [dict(MASSES, extra=1.0), {"base_link": 2.0}, dict(MASSES, camera_link=0.1), dict(MASSES, base_link=True)]:
        with pytest.raises(ValueError):
            validate_links(wrong)


@pytest.mark.parametrize("fault", [None, "disabled", "wrong_world", "missing", "duplicate"])
def test_sdf_gravity_configuration(tmp_path, fault):
    from tools.benchmark.supported_excitation import validate_gravity_configuration

    world = tmp_path / "world.sdf"
    model = tmp_path / "model.sdf"
    world.write_text("<sdf><world><gravity>0 0 " + ("-9.8" if fault == "wrong_world" else "-9.81") + "</gravity></world></sdf>")
    names = list(MASSES)
    if fault == "missing":
        names.pop()
    if fault == "duplicate":
        names.append(names[0])
    model.write_text(
        "<sdf><model>"
        + "".join(
            '<link name="' + n + '">' + ("<gravity>false</gravity>" if fault == "disabled" else "") + "</link>" for n in names
        )
        + "</model></sdf>"
    )
    if fault:
        with pytest.raises(ValueError):
            validate_gravity_configuration(world, [model])
    else:
        assert (
            validate_gravity_configuration(world, [model])["per_link_scope"]
            == "SDF configuration, not runtime GravityEnabled readback"
        )


def test_force_mechanics_and_no_feedback():
    p = SupportedPolicy()
    mass = sum(MASSES.values())
    vz = z = vy = y = 0.0
    maxspeed = 0.0
    for i in range(1, 25001):
        t = i * 1000000
        force = p.step(t, 1000000, unarmed_wall_ns=100, wall_ns=101)
        if t >= 2000000000:
            vz += (force[2] / mass - 9.81) * 0.001
            z += vz * 0.001
        vy += force[1] / mass * 0.001
        y += vy * 0.001
        maxspeed = max(maxspeed, math.hypot(vy, vz))
    assert z == pytest.approx(0.4, abs=2e-6) and abs(vz) < 1e-10
    assert abs(y) < 1e-9 and abs(vy) < 1e-9 and maxspeed < 3
    assert p.finish()["full_profile_requested"]


@pytest.mark.parametrize("stamp", [None, True, 0, 102, -1, -2000000000])
def test_support_requires_fresh_disarmed(stamp):
    p = SupportedPolicy()
    p.last_ns = 1999000000
    with pytest.raises(ValueError):
        p.step(2000000000, 1000000, unarmed_wall_ns=stamp, wall_ns=101)
    with pytest.raises(ValueError):
        p.step(2001000000, 1000000, unarmed_wall_ns=100, wall_ns=101)


@pytest.mark.parametrize("clearance", [None, True, float("nan"), float("inf"), -0.1, 0.099])
def test_ground_separation_required_after_lift(clearance):
    p = SupportedPolicy()
    with pytest.raises(ValueError):
        p.check_clearance(4000000000, clearance)


def test_partial_profile_is_not_complete():
    p = SupportedPolicy()
    p.step(1000000, 1000000, unarmed_wall_ns=None, wall_ns=101)
    assert not p.finish()["full_profile_requested"]


def test_clearance_and_motion_bounds():
    p = SupportedPolicy()
    p.check_clearance(1000000, -0.001)
    p.check_clearance(4000000000, 0.1)
    p.observe([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
    with pytest.raises(ValueError):
        p.observe([0.0, 0.0, 1.01], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0])


def test_supported_cli_pairing():
    def args(m, t):
        return ["--output", "x", "--motion-profile", m, "--physics-trace-profile", t]

    a = parse_capture_args(args("supported-lateral-v1", "substep-supported-v1"))
    assert a.shadow_binary is None
    for m, t in [("supported-lateral-v1", "substep-lateral-v1"), ("lateral-wrench-v1", "substep-supported-v1")]:
        with pytest.raises(SystemExit):
            parse_capture_args(args(m, t))
    with pytest.raises(SystemExit):
        parse_capture_args(
            ["--output", "x", "--motion-profile", "supported-lateral-v1", "--shadow-binary", "x", "--shadow-config", "y"]
        )


@pytest.mark.parametrize("fault", ["partial_force", "short_write", "close", "missing_box", "nan_box"])
def test_probe_failure_retains_attempt_and_stops(tmp_path, monkeypatch, fault):
    import io
    import sys
    import time
    from datetime import timedelta
    from types import SimpleNamespace as NS

    from tools.benchmark.disarmed_motion_probe import GazeboMotionProbe
    from tools.benchmark.supported_excitation import SupportedProbe

    class Vector:
        def __init__(self, *v):
            self.v = v

        def x(self):
            return self.v[0]

        def y(self):
            return self.v[1]

        def z(self):
            return self.v[2]

    monkeypatch.setitem(sys.modules, "gz.math7", NS(Vector3d=Vector))
    monkeypatch.setitem(sys.modules, "gz.sim8", NS(K_NULL_ENTITY=0, Link=None, Model=None, World=None, world_entity=None))
    calls = []

    def apply(name):
        def f(ecm, force):
            calls.append(name)
            if fault == "partial_force" and len(calls) == 3:
                raise OSError("third force failed")

        return f

    minimum = Vector(0.0, 0.0, float("nan") if fault == "nan_box" else 0.4)
    box = NS(min=lambda: minimum, max=lambda: Vector(1.0, 1.0, 1.0))
    probe = SupportedProbe(tmp_path, [], time.monotonic_ns, trace=NS(observe=lambda *a: None))
    probe.links = {
        k: NS(add_world_force=apply(k), world_axis_aligned_box=lambda e: None if fault == "missing_box" else box) for k in MASSES
    }
    probe.link = probe.links["base_link"]
    probe.policy.last_ns = 1999000000
    if fault in ("short_write", "close"):
        original = probe.commands
        original.close()

        class Fault(io.StringIO):
            def write(self, s):
                return len(s) - 1 if fault == "short_write" else super().write(s)

            def close(self):
                if fault == "close":
                    raise OSError("close failure")
                super().close()

        probe.commands = Fault()
    info = NS(sim_time=timedelta(seconds=2), dt=timedelta(milliseconds=1), paused=False)
    probe.pre_update(info, None)
    if fault in ("missing_box", "nan_box"):
        monkeypatch.setattr(GazeboMotionProbe, "post_update", lambda *a: None)
        probe.post_update(info, None)
    summary = probe.finish()
    assert summary["failure"] and probe.errors
    if fault == "partial_force":
        assert len(summary["last_attempt"]["per_link"]) == 3
        assert [c["call_returned"] for c in summary["last_attempt"]["per_link"]] == [True, True, False]
    if fault == "short_write":
        assert summary["recorded_commands"] == 0 and summary["last_attempt"]["call_returned"]
    before = len(calls)
    probe.pre_update(info, None)
    assert len(calls) == before
