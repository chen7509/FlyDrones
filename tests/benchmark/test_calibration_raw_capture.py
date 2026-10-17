"""Production path behavior with explicit Python/SDK protocol fixtures only."""

import importlib
import io
from pathlib import Path

import numpy as np
import pytest

from tools.benchmark import capture_disarmed_sensors as capture


def api():
    return importlib.import_module("tools.benchmark.calibration_excitation")


def raw_args(tmp_path, *extra):
    return capture.parse_capture_args(
        [
            "--output",
            str(tmp_path / "capture"),
            "--capture-profile",
            "target-bearing-raw-v1",
            "--calibration-scene",
            str(tmp_path / "scene"),
            "--execution-contract",
            str(tmp_path / "execution.json"),
            "--runtime-binding",
            str(tmp_path / "binding.json"),
            "--wire-config",
            str(tmp_path / "wire.json"),
            "--agent-runtime-config",
            str(tmp_path / "agent.json"),
            "--logger-diagnostic-profile",
            "source-diagnostic-v1",
            "--record-owned-ulog",
            "--simulation-seed",
            "1701",
            "--motion-profile",
            "target-bearing-multiaxis-v1",
            "--physics-trace-profile",
            "substep-calibration-v1",
            *extra,
        ]
    )


def test_raw_graph_selected_without_dummy_native(tmp_path):
    selected = raw_args(tmp_path)
    assert selected.shadow_binary is None and selected.reference_module is None
    from tools.benchmark.capture_contract import worker_options

    forwarded = worker_options(selected)
    assert "--capture-profile" in forwarded and "--calibration-scene" in forwarded


@pytest.mark.parametrize(
    "extra",
    [
        ("--shadow-binary", "dummy"),
        ("--source-fanout-profile", "ready-shadow-v1"),
        ("--reference-module", "dummy"),
        ("--health-profile", "px4-d6f12ad-gate-floor-v1"),
    ],
)
def test_raw_rejects_native_profile_masquerading(tmp_path, extra):
    with pytest.raises(SystemExit):
        raw_args(tmp_path, *extra)


def geometry():
    masses = {"base_link": 2.0, **{f"rotor_{i}": 0.016076923076923075 for i in range(4)}, "camera_link": 0.061}
    return dict(
        mass_kg=sum(masses.values()),
        links={k: dict(mass=v) for k, v in masses.items()},
        inertia_com_model_kg_m2=np.diag([0.024, 0.025, 0.045]).tolist(),
        model_pose_world=[-8, 0, -0.013, 0, 0, 0],
        expected_base_position_world=[-8, 0, 0.227],
        target_plane_world_x=-7.28,
    )


def proof(armed=False):
    return {"records": {"heartbeat": {"system_id": 9, "base_mode": 128 if armed else 0}}}


def policy(ready=lambda: proof(), persist=lambda _: None):
    return api().CalibrationPolicy(geometry(), ready, persist)


def test_policy_anchor_only_from_journal_and_no_startup_force():
    saved = []
    p = policy(ready=lambda: None, persist=saved.append)
    assert not any(p.step(1_000_000, 1_000_000, unarmed_wall_ns=None, wall_ns=1)["force_world_n"])
    p.readiness = lambda: proof()
    p.step(2_000_000, 1_000_000, unarmed_wall_ns=2, wall_ns=2)
    assert p.anchor_ns == 202_000_000 and len(saved) == 1
    for ns in range(3_000_000, 203_000_000, 1_000_000):
        row = p.step(ns, 1_000_000, unarmed_wall_ns=3, wall_ns=3)
    assert row["force_world_n"][2] == pytest.approx(geometry()["mass_kg"] * 9.81)


@pytest.mark.parametrize("bad", ["armed", "stale", "wall_backwards", "sim_gap", "writer", "witness"])
def test_policy_latches_before_effects(bad):
    p = policy()
    p.step(1_000_000, 1_000_000, unarmed_wall_ns=10, wall_ns=10)
    if bad == "armed":
        p.readiness = lambda: proof(True)
    if bad in ("writer", "witness"):

        def failure():
            raise ValueError(bad)

        p.readiness = failure
    kwargs = dict(unarmed_wall_ns=10, wall_ns=10)
    if bad == "stale":
        kwargs["wall_ns"] = 2_000_000_011
    if bad == "wall_backwards":
        kwargs["wall_ns"] = 9
    with pytest.raises(ValueError):
        p.step(3_000_000 if bad == "sim_gap" else 2_000_000, 1_000_000, **kwargs)
    p.readiness = lambda: proof()
    with pytest.raises(ValueError, match="latched"):
        p.step(3_000_000, 1_000_000, unarmed_wall_ns=11, wall_ns=11)


class Link:
    def __init__(self, name, events, fail=False):
        self.name, self.events, self.fail = name, events, fail

    def add_world_force(self, ecm, v):
        self.events.append(("COM", self.name, tuple(v)))
        if self.fail:
            raise RuntimeError("injected SDK call refusal")

    def add_world_wrench(self, ecm, force, torque):
        self.events.append(("origin", self.name, tuple(force), tuple(torque)))


def test_actual_application_order_pure_torque_and_partial_failure():
    m = api()
    events = []
    links = {name: Link(name, events, name == "rotor_1") for name in geometry()["links"]}
    stream = io.StringIO()
    row = dict(sim_ns=1, force_world_n=[0, 0, 20], torque_world_nm=[0.01, 0, 0])
    attempt = {}
    with pytest.raises(RuntimeError):
        m.apply_load(links, None, row, geometry(), stream, attempt, vector=lambda *v: v)
    assert events[0][0] == "COM"
    assert not any(e[0] == "origin" for e in events)
    assert attempt["per_link"][0]["call_returned"] is True
    assert attempt["per_link"][-1]["call_returned"] is False
    assert "partial_failure" in stream.getvalue()
    events.clear()
    stream = io.StringIO()
    for link in links.values():
        link.fail = False
    m.apply_load(links, None, row, geometry(), stream, {}, vector=lambda *v: v)
    assert events[-1] == ("origin", "base_link", (0.0, 0.0, 0.0), (0.01, 0, 0))
    assert sum(e[2][2] for e in events[:-1]) == pytest.approx(20)


def test_failed_pre_effect_journal_makes_no_call():
    m = api()
    events = []
    links = {name: Link(name, events) for name in geometry()["links"]}

    class Broken:
        def write(self, _):
            raise OSError("writer refused")

    with pytest.raises(OSError):
        m.apply_load(
            links,
            None,
            dict(sim_ns=1, force_world_n=[0, 0, 20], torque_world_nm=[0.01, 0, 0]),
            geometry(),
            Broken(),
            {},
            vector=lambda *v: v,
        )
    assert events == []


def test_raw_scene_selector_uses_own_bill_and_leaves_legacy_route(tmp_path, monkeypatch):
    from tools.benchmark import calibration_capture_contract as contract

    chosen = []
    record = dict(path="sealed-v3", files={"world.sdf": {"sha256": "new-world"}})

    def copy(value, output):
        chosen.append((value, output))
        return {"world.sdf": "new-world"}

    monkeypatch.setattr(contract, "copy_scene", copy)
    result = capture.select_capture_scene(tmp_path, dict(raw_measurement=dict(scene=record)))
    assert result == {"world.sdf": "new-world"}
    assert chosen == [(record, tmp_path)]
    # Legacy selection uses its old archive; cannot be silently swapped to raw.
    with pytest.raises(FileNotFoundError):
        capture.select_capture_scene(tmp_path, {}, legacy_archive=tmp_path / "missing.zip")


def test_raw_generated_names_do_not_use_old_obstacle_placeholders():
    from tools.benchmark.runtime_resource_binding import generated_names

    scene = dict(files={"world.sdf": {}, "manifest.json": {}, "models/x500/model.sdf": {}})
    names = generated_names(dict(schema="capture-resource-binding-v4", calibration_scene=scene))
    assert set(names) == {"world.sdf", "manifest.json", "models/x500/model.sdf", "gz_env.sh"}
    assert "obstacle_albedo.png" not in names


def test_raw_readiness_requires_owned_witness_and_wire_health():
    from types import SimpleNamespace

    ready = SimpleNamespace(proof=lambda: proof())
    wire = SimpleNamespace(health_ready=lambda: True)
    source = SimpleNamespace(failure=None, logs={})
    assert capture.raw_measurement_readiness(ready, wire, source) is None
    source.logs = {"owned.ulg": {}}
    assert capture.raw_measurement_readiness(ready, wire, source) == proof()
    wire.health_ready = lambda: False
    assert capture.raw_measurement_readiness(ready, wire, source) is None
    source.failure = "denied"
    with pytest.raises(ValueError):
        capture.raw_measurement_readiness(ready, wire, source)


@pytest.mark.parametrize("scenario", ["guard", "partial_call", "invalid_collision"])
def test_callback_guard_trace_application_and_latched_failure(tmp_path, scenario):
    import datetime
    import json
    from types import SimpleNamespace

    m = api()
    events = []

    class V:
        def __init__(self, values):
            self.values = values

        def x(self):
            return self.values[0]

        def y(self):
            return self.values[1]

        def z(self):
            return self.values[2]

    class R:
        def roll(self):
            return 0.0

        def pitch(self):
            return 0.0

        def yaw(self):
            return 0.0

    class StateLink(Link):
        bad_box = False

        def world_pose(self, _):
            return SimpleNamespace(pos=lambda: V([-8, 0, 0.227]), rot=R)

        def world_linear_velocity(self, _):
            return V([0, 0, 0])

        def world_angular_velocity(self, _):
            return V([0, 0, 0])

        def world_axis_aligned_box(self, _):
            return SimpleNamespace(min=lambda: V([-7 if self.bad_box else -8.3, -0.3, 0]), max=lambda: V([-7.7, 0.3, 0.3]))

    g = geometry()
    g["links"]["base_link"]["pose_model"] = [0, 0, 0.24, 0, 0, 0]
    links = {name: StateLink(name, events) for name in g["links"]}
    errors = []
    guard_failed = [False]

    def guard():
        events.append(("guard",))
        if guard_failed[0]:
            raise ValueError("injected writer/witness failure")

    trace = SimpleNamespace(observe=lambda phase, *_: events.append(("trace", phase)))
    probe = m.CalibrationProbe(
        tmp_path,
        errors,
        lambda: 1,
        scene=dict(geometry=g, design=dict(target_pose_world=[-7.28, 0, 0.419])),
        readiness=lambda: proof(),
        guard=guard,
        trace=trace,
        clock=lambda: 1,
        resolver=lambda *_: links,
        vector=lambda *v: v,
    )
    final_step = 1 if scenario == "invalid_collision" else 201 if scenario == "partial_call" else 202
    for step in range(1, final_step + 1):
        info = SimpleNamespace(
            sim_time=datetime.timedelta(milliseconds=step), dt=datetime.timedelta(milliseconds=1), paused=False
        )
        if step == final_step:
            links["rotor_1"].fail = scenario == "partial_call"
            links["base_link"].bad_box = scenario == "invalid_collision"
        probe.pre_update(info, None)
        if scenario == "invalid_collision":
            assert probe.audit_rows == 1, "invalid envelope must be journaled before refusal"
        probe.post_update(info, None)
    if scenario != "guard":
        assert errors and probe.policy.failure
        assert events[-1] == ("trace", "post")
        rows = [json.loads(line) for line in (tmp_path / "calibration-collision-audit.jsonl").read_text().splitlines()]
        assert rows[-1]["phase"] == "post" and rows[-1]["sim_ns"] == final_step * 1_000_000
        if scenario == "invalid_collision":
            assert rows[0]["invalid_collision_box"]["name"] == "base_link"
            assert rows[0]["invalid_collision_box"]["minimum"][0] == -7
        count = sum(e[0] == "COM" for e in events)
        probe.pre_update(info, None)
        assert sum(e[0] == "COM" for e in events) == count
        summary = probe.finish()
        (tmp_path / "fixture-transcript.json").write_text(
            json.dumps(dict(scenario=scenario, events=events, errors=errors, summary=summary))
        )
        return
    assert not errors
    first = next(i for i, e in enumerate(events) if e[0] == "COM")
    assert events[first - 2] == ("trace", "pre") or events[first - 2] == ("guard",)
    assert events[first - 1] == ("guard",)
    assert probe.command_steps == 2
    guard_failed[0] = True
    info.sim_time = datetime.timedelta(milliseconds=203)
    count = sum(e[0] == "COM" for e in events)
    probe.pre_update(info, None)
    assert probe.policy.failure and errors
    guard_failed[0] = False
    probe.pre_update(info, None)
    assert sum(e[0] == "COM" for e in events) == count
    summary = probe.finish()
    assert summary["full_profile_requested"] is False
    (tmp_path / "fixture-transcript.json").write_text(
        json.dumps(dict(scenario=scenario, events=events, errors=errors, summary=summary))
    )


def test_raw_v4_binding_reuses_mapping_and_search_requirements(tmp_path, monkeypatch):
    from tools.benchmark import calibration_capture_contract as contract
    from tools.benchmark import runtime_resource_binding as binding
    from tools.benchmark.declared_runtime_snapshot import snapshot

    scene = dict(path=str(tmp_path / "sealed"), files={"world.sdf": dict(sha256="a" * 64)})
    monkeypatch.setattr(contract, "scene_record", lambda _: scene)
    monkeypatch.setattr(binding, "validate_response", lambda *_: None)
    inventory = {}
    for role in ("graph:resolver", "graph:source", "graph:dependencies"):
        p = tmp_path / role.replace(":", "-")
        p.write_bytes(b"fixture")
        inventory[role] = [str(p)]
    doc = dict(
        schema="capture-resource-binding-v4",
        capture_profile="target-bearing-raw-v1",
        calibration_scene=scene,
        inventory=inventory,
        baseline=snapshot(inventory),
        environment={k: None for k in binding.ENV_KEYS},
        generated={"world.sdf": "a" * 64, "gz_env.sh": "b" * 64},
        graph=dict(
            schema="generated-resource-graph-v1",
            cwd=str(Path.cwd()),
            environment={k: None for k in binding.QUERY_ENV_KEYS},
            expected_context={},
        ),
        runtime_maps=dict(
            self_phases=["postimports", "postfinalize", "postfirststep"],
            owned_roles={"px4": ["ready", "prestop"], "agent": ["ready", "prestop"]},
            max_maps_bytes=8 * 1024**2,
            max_observations=8,
        ),
    )
    assert binding.validate_binding(doc)["generated"] == doc["generated"]
    doc["runtime_maps"]["owned_roles"].pop("agent")
    with pytest.raises(ValueError, match="owned PX4/Agent"):
        binding.validate_binding(doc)


@pytest.mark.parametrize("wire_schema", ["capture-wire-startup-v2", "capture-wire-v1"])
def test_raw_execution_contract_declares_source_graph_and_codes(tmp_path, monkeypatch, wire_schema):
    import json

    from tools.benchmark import agent_capture_runtime
    from tools.benchmark import calibration_capture_contract as raw
    from tools.benchmark import capture_contract as common

    selected = raw_args(tmp_path)
    monkeypatch.setattr(raw, "scene_record", lambda _: dict(path="fixture", files={}))
    wire = dict(schema=wire_schema, session_id="fixture", sim_origin_ns=0, remote_origin_ns=0)
    if wire_schema == "capture-wire-startup-v2":
        wire["startup_max_wall_ns"] = 60_000_000_000
    selected.wire_config.write_text(json.dumps(wire))
    monkeypatch.setattr(agent_capture_runtime, "agent_runtime_record", lambda _: dict(configuration={}, selected_paths=[]))
    if wire_schema == "capture-wire-v1":
        with pytest.raises(ValueError, match="staged wire"):
            common.execution_contract(selected, {"HOME": "fixture"})
        return
    result = common.execution_contract(selected, {"HOME": "fixture"})
    assert result["raw_measurement"]["name"] == "target-bearing-raw-v1"
    assert result["estimator_run"] is False and result["rgbd_size"] == [160, 120]
    assert "owned_ulog_source" in result and "agent" in result and "wire" in result
    assert result["raw_measurement"]["estimator_required"] is False
