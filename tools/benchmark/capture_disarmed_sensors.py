#!/usr/bin/env python3
"""One sensor-only Gazebo/PX4 development capture. Never arms or publishes controls/VIO."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from flydrones.benchmark.camera_info_capture import camera_info_fields  # noqa: E402
from flydrones.benchmark.gateway import sim_duration_ns  # noqa: E402
from flydrones.benchmark.ulog_capture import collect_ulogs, verify_episode_ulog_evidence  # noqa: E402
from tools.benchmark.capture_contract import (  # noqa: E402
    _typed_equal,
    derive_launch_environment,
    materialize_launch_environment,
    read_declaration,
    validate_declaration,
    validate_launch_environment,
    worker_options,
)
from tools.benchmark.declared_runtime_snapshot import write_manifest  # noqa: E402
from tools.benchmark.disarmed_sensor_provenance import CaptureJournal, CaptureWriter, supervise_worker  # noqa: E402


def active_resources():
    matches = []
    for path in Path("/proc").iterdir():
        if not path.name.isdigit() or int(path.name) in {os.getpid(), os.getppid()}:
            continue
        try:
            name = (path / "comm").read_text().strip()
            argv = (path / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if name in {"px4", "gz", "gzserver", "gzclient", "state_probe", "fast_probe", "online_probe"} or (
            name.startswith("python")
            and any(s in argv for s in ["pytest", "run_episode.py", "train_", "capture_disarmed_sensors.py"])
        ):
            matches.append({"pid": int(path.name), "name": name, "command": argv})
    return matches


def parse_initial_environment(raw):
    if type(raw) is not bytes or not raw or not raw.endswith(b"\0"):
        raise ValueError("initial environment must be a terminated byte sequence")
    result = {}
    for item in raw[:-1].split(b"\0"):
        if not item or b"=" not in item:
            raise ValueError("malformed initial environment entry")
        name, value = item.split(b"=", 1)
        try:
            name = name.decode("utf-8")
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("initial environment must be UTF-8") from exc
        if not name or name in result:
            raise ValueError("duplicate or empty initial environment name")
        result[name] = value
    validate_launch_environment({key: value for key, value in result.items()})
    return result


def record_worker_environment(output, contract, contract_path, *, reader=None):
    if type(contract) is not dict or contract.get("schema") not in {
        "capture-execution-v2", "capture-execution-v3",
    }:
        raise ValueError("worker environment evidence requires execution contract v2 or v3")
    declared = validate_launch_environment(contract.get("launch_environment"))
    expected = materialize_launch_environment(declared)
    contract_path = Path(contract_path).resolve(strict=True)
    before = contract_path.stat()
    payload = contract_path.read_bytes()
    after = contract_path.stat()
    if before != after:
        raise ValueError("execution contract changed while worker read it")
    read = reader or (lambda: Path("/proc/self/environ").read_bytes())
    observed = parse_initial_environment(read())
    matches = _typed_equal(observed, expected)
    record = {
        "schema": "worker-launch-environment-v1",
        "declared": declared,
        "materialized": expected,
        "observed": observed,
        "matches": matches,
        "execution_contract": {
            "path": str(contract_path), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "runtime_environment_qualified": False,
        "physics_qualified": False,
        "fusion_eligible": False,
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_manifest(output / "execution-environment-worker.json", record)
    if not matches:
        raise ValueError("initial worker environment mismatch")
    return record


def record_worker_trajectory_policy(output, contract, policy_path):
    from tools.benchmark.capture_contract import trajectory_gauge_policy_record

    if type(contract) is not dict or contract.get("schema") != "capture-execution-v3":
        raise ValueError("worker trajectory policy evidence requires execution contract v3")
    actual = trajectory_gauge_policy_record(policy_path)
    declared = contract.get("trajectory_gauge_policy")
    matches = _typed_equal(actual, declared)
    record = {
        "schema": "worker-trajectory-gauge-policy-v1",
        **actual,
        "matches_declaration": matches,
        "physics_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }
    write_manifest(Path(output) / "trajectory-gauge-policy-worker.json", record)
    if not matches:
        raise ValueError("worker trajectory gauge policy differs from declaration")
    return record


def parse_capture_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--startup-preflight", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--execution-contract", type=Path, help="Exact prospective execution declaration")
    parser.add_argument("--runtime-binding", type=Path, help="Declared baseline, generated hashes and lookup environment")
    parser.add_argument("--trajectory-gauge-policy", type=Path,
                        help="Prospective truth-independent trajectory scoring policy")
    parser.add_argument("--shadow-binary", type=Path)
    parser.add_argument("--shadow-config", type=Path)
    parser.add_argument("--reference-module", type=Path)
    parser.add_argument("--reference-sha256")
    parser.add_argument("--reference-fault-profile", choices=["native-pre-epoch-v1"])
    parser.add_argument(
        "--source-fanout-profile",
        choices=[
            "ready-shadow-v1",
            "ready-shadow-heartbeat-v1",
            "ready-shadow-heartbeat-estimator-v1",
        ],
    )
    parser.add_argument("--motion-intent-profile", choices=["native-beginning-zupt-v1"])
    parser.add_argument("--motion-profile", choices=["lateral-wrench-v1", "supported-lateral-v1", "supported-ready-v1"])
    parser.add_argument("--physics-trace-profile", choices=["substep-lateral-v1", "substep-supported-v1", "substep-ready-v1"])
    args = parser.parse_args(argv)
    if args.runtime_binding and not args.execution_contract:
        parser.error("runtime binding requires an execution declaration")
    if args.trajectory_gauge_policy and (not args.runtime_binding or not args.execution_contract):
        parser.error("trajectory gauge policy requires runtime binding and execution declaration")
    if args.startup_preflight and (
        not args.runtime_binding or not args.execution_contract or not args.trajectory_gauge_policy
    ):
        parser.error("startup preflight requires runtime binding, execution declaration and trajectory policy")
    if args.source_fanout_profile and (
        not args.shadow_binary or not args.shadow_config or not args.reference_module or not args.reference_sha256
        or args.motion_profile != "supported-ready-v1" or args.physics_trace_profile != "substep-ready-v1"
        or args.reference_fault_profile
    ):
        parser.error("source fan-out requires complete supported native/reference configuration without fault injection")
    if args.motion_intent_profile and args.source_fanout_profile != "ready-shadow-heartbeat-estimator-v1":
        parser.error("native motion intent requires estimator-aware source fan-out")
    if args.reference_fault_profile and not args.reference_module:
        parser.error("runtime refusal requires native reference configuration")
    if bool(args.reference_module) != bool(args.reference_sha256):
        parser.error("native reference module and hash required together")
    if args.reference_module and (
        args.motion_profile != "supported-ready-v1"
        or args.physics_trace_profile != "substep-ready-v1"
        or (args.shadow_binary and not args.source_fanout_profile)
        or len(args.reference_sha256) != 64
        or any(c not in "0123456789abcdef" for c in args.reference_sha256)
    ):
        parser.error("native reference requires ready sensor-only profile and SHA256")
    if bool(args.shadow_binary) != bool(args.shadow_config):
        parser.error("shadow binary and frozen config must be specified together")
    if args.physics_trace_profile and (not args.motion_profile or (args.shadow_binary and not args.source_fanout_profile)):
        parser.error("substep trace requires explicit sensor-only motion, without native shadow")
    if (
        args.physics_trace_profile
        and args.physics_trace_profile
        != {
            "lateral-wrench-v1": "substep-lateral-v1",
            "supported-lateral-v1": "substep-supported-v1",
            "supported-ready-v1": "substep-ready-v1",
        }[args.motion_profile]
    ):
        parser.error("motion and trace profile mismatch")
    if args.motion_profile in ("supported-lateral-v1", "supported-ready-v1") and not args.physics_trace_profile:
        parser.error("supported excitation is sensor-only diagnosis")
    if args.motion_profile and not (args.shadow_binary or args.physics_trace_profile):
        parser.error("motion fixture requires the native shadow recorder")
    return args


def build_readiness(output, source_fanout_profile, *, clock=time.monotonic_ns):
    """Build the legacy source gate plus the opt-in estimator-aware wrapper."""
    from tools.benchmark.readiness_anchor import JournaledReadiness

    source_readiness = JournaledReadiness(clock=clock)
    if source_fanout_profile == "ready-shadow-heartbeat-estimator-v1":
        from tools.benchmark.estimator_aware_readiness import EstimatorAwareReadiness

        return source_readiness, EstimatorAwareReadiness(output, source_readiness, clock=clock)
    return source_readiness, source_readiness


def build_source_fanout(output, profile, readiness, shadow):
    if profile == "ready-shadow-heartbeat-estimator-v1":
        from tools.benchmark.estimator_aware_readiness import EstimatorJournaledHeartbeatFanout

        return EstimatorJournaledHeartbeatFanout(output, readiness, shadow)
    if profile == "ready-shadow-heartbeat-v1":
        from tools.benchmark.journaled_heartbeat_lane import JournaledHeartbeatFanout

        return JournaledHeartbeatFanout(output, readiness, shadow)
    from tools.benchmark.ready_shadow_fanout import ReadyShadowFanout

    return ReadyShadowFanout(output, readiness, shadow)


def finish_readiness(readiness, source_fanout_profile):
    if source_fanout_profile == "ready-shadow-heartbeat-estimator-v1":
        return readiness.finish()
    return readiness.snapshot()


def apply_native_motion_intent(gate, readiness, client, anchor_ns, proof, *, clock=time.monotonic_ns):
    """Latch beginning-only ZUPT off before the first prospectively commanded step."""
    heartbeat = proof.get("records", {}).get("heartbeat") if isinstance(proof, dict) else None
    if (
        not isinstance(heartbeat, dict)
        or type(heartbeat.get("base_mode")) is not int
        or heartbeat["base_mode"] & 128
    ):
        raise ValueError("motion intent requires causal unarmed heartbeat proof")
    issued = clock()
    gate.observe_estimator(readiness.motion_intent_state())
    action = gate.request(
        {
            "session_id": gate.session_id,
            "clock_id": gate.clock_id,
            "command_sequence": 0,
            "effective_sim_ns": anchor_ns,
            "issued_monotonic_ns": issued,
            "unarmed": True,
            "safety_authorized": True,
            "velocity_setpoint_frd_m_s": [0.0, 0.0, -0.2],
            "yaw_rate_setpoint_rad_s": 0.0,
            "source": "px4-safe-setpoint-supervisor",
        }
    )
    gate.acknowledge(client.send_motion_intent(action))
    if not gate.authorize_step(anchor_ns):
        raise ValueError(gate.failure or "native motion intent did not authorize effective step")


def dispatch_heartbeat(event, writer, fanout):
    """Opt-in independent journal; old profiles retain the original queued route."""
    from tools.benchmark.journaled_heartbeat_lane import JournaledHeartbeatFanout

    if isinstance(fanout, JournaledHeartbeatFanout):
        fanout.submit_heartbeat(event, writer)
    else:
        writer.submit(event)


def needs_supervisor_retention(summary):
    return (
        summary["status"] != "worker_exited"
        or summary.get("worker_exit", 0) != 0
        or summary.get("capture_status", "capture_completed") != "capture_completed"
        or bool(summary.get("errors"))
        or not summary.get("cleanup", {}).get("graceful_group_cleanup_verified", False)
    )


def retain_supervisor_ulogs(summary, runtime, output, *, collector=collect_ulogs):
    try:
        if summary.get("cleanup", {}).get("no_executing_members") is not True:
            raise ValueError("owned group exit unknown; do not copy possibly unflushed ULog")
        manifest = output / "px4-ulog-manifest.json"
        if manifest.exists():
            records = json.loads(manifest.read_text(encoding="utf-8"))["logs"]
            verify_episode_ulog_evidence(output, dict(px4_ulogs=records, px4_ulog_capture_accepted=True))
            return dict(px4_ulogs=records, existing_manifest_verified=True)
        return dict(px4_ulogs=collector(runtime, output), existing_manifest_verified=False)
    except Exception as exc:
        return dict(errors=[repr(exc)], runtime_retained=str(runtime))


def main():
    args = parse_capture_args()
    binding_doc = None
    if args.runtime_binding:
        from tools.benchmark.runtime_resource_binding import validate_binding

        binding_doc = validate_binding(read_declaration(args.runtime_binding))
    launch_environment = derive_launch_environment(binding_doc) if binding_doc and binding_doc["schema"] == "capture-resource-binding-v3" else None
    contract = validate_declaration(args, launch_environment)
    shadow_args = worker_options(args)
    if not args.worker:
        supervisor_options = {}
        if launch_environment is not None:
            supervisor_options.update(launch_environment=launch_environment,
                                      execution_contract=args.execution_contract)
        summary = supervise_worker(
            [sys.executable, str(Path(__file__).resolve()), "--worker", "--output", str(args.output.resolve())] + shadow_args,
            args.output.resolve(), timeout_s=contract["supervisor_s"], **supervisor_options,
        )
        if needs_supervisor_retention(summary) and (args.output / "launch.json").is_file():
            launch = json.loads((args.output / "launch.json").read_text())
            retained = retain_supervisor_ulogs(summary, Path(launch["runtime"]), args.output)
            with (args.output / "watchdog-retained-ulogs.json").open("x") as stream:
                json.dump(retained, stream, indent=2)
        return (
            0
            if summary["status"] == "worker_exited"
            and summary["worker_exit"] == 0
            and summary["capture_status"] == "capture_completed"
            and summary["cleanup"]["graceful_group_cleanup_verified"]
            and not summary["errors"]
            else 2
        )
    output = args.output.resolve()
    if contract["schema"] in {"capture-execution-v2", "capture-execution-v3"}:
        record_worker_environment(output, contract, args.execution_contract)
    if contract["schema"] == "capture-execution-v3":
        record_worker_trajectory_policy(output, contract, args.trajectory_gauge_policy)
    resources = active_resources()
    if resources:
        raise RuntimeError("existing competing resources: " + json.dumps(resources))
    px4 = Path.home() / "PX4-Autopilot"
    build = px4 / "build/px4_sitl_default"
    binary = build / "bin/px4"
    binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    if binary_sha != "e8af7cbcac255ec3c79bb5fa278459fd0b130b4b189de9269e3689cb9789f4cb":
        raise ValueError("PX4 binary differs from pinned development evidence")
    archive = ROOT / "evidence/openvins-board-pattern-dev-1701-reviewed.zip"
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    if archive_sha != "669f3646e74c4e95826f12e79b456aba861a5b4003087541ce7dc1dc8cd1f4f3":
        raise ValueError("development scene seal changed")
    # Reserve the intended local receiver before simulation; no remote endpoint is used.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 14548))
    if contract["schema"] == "capture-execution-v1":
        output.mkdir(parents=True, exist_ok=False)
    input_hashes = {}
    with zipfile.ZipFile(archive) as z:
        for name in ["world.sdf", "world.json", "ground_albedo.png", "obstacle_albedo.png", "board_albedo.png"]:
            data = z.read("results/openvins-board-pattern-dev-1701/episode-v2/" + name)
            with (output / name).open("xb") as f:
                f.write(data)
            input_hashes[name] = hashlib.sha256(data).hexdigest()
    partition = "fly_disarmed_" + str(os.getpid())
    os.environ["GZ_PARTITION"] = partition
    if contract["schema"] == "capture-execution-v1":
        os.environ["GZ_SIM_RESOURCE_PATH"] = ":".join(
            [str(ROOT / "assets/gazebo/models"), str(px4 / "Tools/simulation/gz/models"),
             os.environ.get("GZ_SIM_RESOURCE_PATH", "")]
        )
    runtime = Path(tempfile.mkdtemp(prefix="fly-disarmed-", dir=str(Path.home() / "fly-ego-benchmark/runtime")))
    (runtime / "gz_env.sh").write_bytes((build / "rootfs/gz_env.sh").read_bytes())
    env = os.environ.copy()
    env.update(
        HEADLESS="1",
        PX4_GZ_STANDALONE="1",
        PX4_SYS_AUTOSTART="4001",
        PX4_GZ_WORLD="fly_ego_benchmark",
        PX4_SIM_MODEL="gz_x500_benchmark",
        PX4_GZ_MODEL_NAME="x500_benchmark_8",
        PX4_UXRCE_DDS_PORT="18888",
    )
    with (output / "launch.json").open("x") as f:
        json.dump(
            {
                "partition": partition,
                "runtime": str(runtime),
                "instance": 8,
                "binary_sha256": binary_sha,
                "source_archive_sha256": archive_sha,
                "scene_hashes": input_hashes,
                **{key: contract[key] for key in ("simulation_duration_ns", "physics_step_ns", "imu_hz", "rgbd_hz")},
                "execution_contract": contract,
                "prospective_declaration_verified": args.execution_contract is not None,
                "command_policy": "read-only heartbeat; no arm/offboard/setpoint/ODOMETRY",
                "uxrce_port": 18888,
                "uxrce_agent_launched": False,
            },
            f,
            indent=2,
        )

    errors = []
    result = {
        "status": "incomplete",
        "errors": errors,
        "eligible_for_vio_input": False,
        "eligible_for_px4_fusion": False,
        "estimator_run": bool(args.shadow_binary),
        "capture_schema": "disarmed-sensors-v2",
        "physics_trace_profile": args.physics_trace_profile,
        "reference_profile": "supported-ready-native-reference-v1" if args.reference_module else None,
        "reference_fault_profile": args.reference_fault_profile,
        "source_fanout_profile": args.source_fanout_profile,
    }
    clock = {"sim_ns": 0}
    arming = {"unarmed_wall_ns": None}
    owned_ready = {"px4": False, "openvins": False}
    owned_processes = {}
    started = time.monotonic()
    with CaptureJournal(output, result) as journal:
        binding = None
        if binding_doc is not None:
            from tools.benchmark.runtime_resource_binding import GENERATED_NAMES, attach_binding, estimator_inputs

            if args.startup_preflight:
                from tools.benchmark.runtime_resource_binding import RuntimeBinding

                binding = RuntimeBinding(binding_doc, output)
            else:
                binding = attach_binding(journal, result, binding_doc, output)
            required = [binary, build / "rootfs/gz_env.sh", build / "etc/init.d-posix/rcS",
                        px4 / "src/modules/simulation/gz_bridge/server.config",
                        ROOT / "assets/gazebo/models/x500_benchmark/model.sdf",
                        ROOT / "assets/gazebo/models/OakD-Benchmark/model.sdf",
                        px4 / "Tools/simulation/gz/models/x500/model.sdf",
                        px4 / "Tools/simulation/gz/models/x500_base/model.sdf"]
            required += estimator_inputs(args.shadow_binary, args.shadow_config, args.reference_module)
            required += [Path(module.__file__).resolve() for module in tuple(sys.modules.values())
                         if getattr(module, "__file__", None) and Path(module.__file__).resolve().is_relative_to(ROOT)]
            binding.start({name: runtime / name if name == "gz_env.sh" else output / name for name in GENERATED_NAMES},
                          env, required)
            if args.startup_preflight:
                startup_binding = binding.finish()
                if (startup_binding["errors"] or not startup_binding["pre_recorded"]
                        or not startup_binding["declared_files_stable"]
                        or not startup_binding["local_file_graph_verified"]):
                    raise ValueError("startup runtime binding preflight failed")
                result.update(
                    status="capture_completed",
                    startup_preflight_only=True,
                    startup_preflight_completed=True,
                    runtime_binding=startup_binding,
                    physical_execution_qualified=False,
                    vio_accuracy_qualified=False,
                    estimator_health_qualified=False,
                    fusion_eligible=False,
                    flight_ready=False,
                )
                return 0
        journal.cleanup("ULog collection", lambda: result.update(px4_ulogs=collect_ulogs(runtime, output)), priority=100)
        journal.cleanup(
            "end clocks",
            lambda: result.update(end_sim_ns=clock["sim_ns"], capture_wall_s=time.monotonic() - started),
            priority=110,
        )
        import gz.math7  # noqa: F401 - register math types for sim bindings
        from gz.msgs10.camera_info_pb2 import CameraInfo
        from gz.msgs10.image_pb2 import Image
        from gz.msgs10.imu_pb2 import IMU
        from gz.sim8 import TestFixture
        from gz.transport13 import Node
        from pymavlink import mavutil

        if binding:
            binding.observe("postimports")

        shadow = None
        source_guard = None
        if args.shadow_binary:
            from tools.benchmark.openvins_online_shadow import NativeClient, ShadowInput, SourceWatchdog, validate_frozen_config

            validate_frozen_config(args.shadow_config)
            shadow_dir = output / "shadow"
            shadow_dir.mkdir()
            def openvins_ready():
                if binding and "openvins" in binding.required_owned and not owned_ready["openvins"]:
                    binding.observe_owned("openvins", "ready")
                    owned_ready["openvins"] = True

            client = NativeClient(
                [
                    str(args.shadow_binary.resolve()),
                    str(args.shadow_config.resolve()),
                    str(shadow_dir / "states.jsonl"),
                    str(shadow_dir / "fast.jsonl"),
                ],
                shadow_dir,
                on_first_ack=openvins_ready,
            )
            if binding and "openvins" in binding.required_owned:
                binding.register_owned("openvins", client.process, args.shadow_binary)
                owned_processes["openvins"] = client.process

            def finish_native():
                if binding and "openvins" in binding.required_owned and owned_ready["openvins"]:
                    try:
                        binding.observe_owned("openvins", "prestop")
                    except Exception as exc:
                        errors.append("OpenVINS runtime mapping: " + repr(exc))
                result["native"] = client.finish()
                if result["native"]["failure"] or result["native"]["exit"] != 0:
                    errors.append("native consumer failed: " + str(result["native"]))

            journal.cleanup("native consumer", finish_native, priority=95)
            native_session_id = "online-native-" + str(client.process.pid)
            shadow = ShadowInput(client, shadow_dir, session_id=native_session_id)

            def finish_shadow():
                result["shadow"] = shadow.finish()
                if result["shadow"]["failure"]:
                    errors.append("shadow input failed: " + result["shadow"]["failure"])

            journal.cleanup("shadow input", finish_shadow, priority=90)
        if args.shadow_binary or args.physics_trace_profile:
            from tools.benchmark.openvins_online_shadow import SourceWatchdog

            # Cold renderer setup is a separate bounded phase; operational silence remains2s.
            source_guard = SourceWatchdog(startup_timeout_ns=10_000_000_000)
            journal.cleanup("source health", lambda: result.update(source_health=source_guard.snapshot()), priority=85)
        readiness = None
        if args.motion_profile == "supported-ready-v1":
            _source_readiness, readiness = build_readiness(output, args.source_fanout_profile)
            journal.cleanup(
                "readiness evidence",
                lambda: result.update(
                    readiness=finish_readiness(readiness, args.source_fanout_profile)
                ),
                priority=86,
            )
        motion_intent = None
        if args.motion_intent_profile:
            from tools.benchmark.motion_intent_gate import MotionIntentGate

            motion_intent = MotionIntentGate(
                session_id=native_session_id,
                clock_id="gazebo-sim+linux-monotonic",
                output=output,
                native_adapter_integrated=True,
            )

            def finish_motion_intent():
                result["motion_intent"] = motion_intent.finish()
                if not result["motion_intent"]["qualified"]:
                    errors.append("motion intent: " + str(result["motion_intent"]["failure"]))

            journal.cleanup("motion intent", finish_motion_intent, priority=83)
        fanout = None
        if args.source_fanout_profile:
            fanout = build_source_fanout(output, args.source_fanout_profile, readiness, shadow)

            def finish_fanout():
                result["source_fanout"] = fanout.finish()
                if result["source_fanout"]["failure"]:
                    errors.append("source fan-out: " + result["source_fanout"]["failure"])

            journal.cleanup("source fan-out", finish_fanout, priority=84)
        writer = CaptureWriter(
            output, sequence_records=fanout is not None,
            on_record=fanout.on_record if fanout else readiness.on_record if readiness else shadow.on_record if shadow else None,
            on_idle=fanout.on_idle if fanout else shadow.tick_idle if shadow else None,
        )
        journal.cleanup("writer", lambda: result.update(writer=writer.finish()), priority=80)
        stop = threading.Event()
        node = Node()
        receiver = mavutil.mavlink_connection("udpin:127.0.0.1:14548", source_system=254)
        journal.cleanup("receiver", receiver.close, priority=50)

        def submit(kind, message):
            arrival = time.monotonic_ns()
            try:
                if source_guard:
                    source_guard.observe(kind, arrival)
                event = {"kind": kind, "arrival_monotonic_ns": arrival, "observed_sim_ns": clock["sim_ns"]}
                payload = None
                if kind == "info":
                    event["sample_ns"] = int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nsec)
                    event["camera_info"] = camera_info_fields(message)
                    payload = message.SerializeToString()
                else:
                    event["sample_ns"] = int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nsec)
                    if kind == "imu":
                        event["gyro_flu"] = [message.angular_velocity.x, message.angular_velocity.y, message.angular_velocity.z]
                        event["accel_flu"] = [
                            message.linear_acceleration.x,
                            message.linear_acceleration.y,
                            message.linear_acceleration.z,
                        ]
                    else:
                        event.update(width=int(message.width), height=int(message.height))
                        if kind == "rgb":
                            payload = bytes(message.data)
                writer.submit(event, payload)
            except Exception as exc:
                errors.append(repr(exc))

        def read_heartbeats():
            while not stop.is_set():
                try:
                    heartbeat = receiver.recv_match(type="HEARTBEAT", blocking=True, timeout=0.1)
                    if heartbeat is not None and heartbeat.get_srcSystem() == 9 and heartbeat.autopilot == 12:
                        arming["unarmed_wall_ns"] = None if heartbeat.base_mode & 128 else time.monotonic_ns()
                        if (binding and "px4" in binding.required_owned and not owned_ready["px4"]
                                and "px4" in owned_processes and arming["unarmed_wall_ns"] is not None):
                            try:
                                binding.observe_owned("px4", "ready")
                                owned_ready["px4"] = True
                            except Exception as exc:
                                errors.append("PX4 runtime mapping: " + repr(exc))
                        dispatch_heartbeat(
                            {
                                "kind": "heartbeat",
                                "arrival_monotonic_ns": time.monotonic_ns(),
                                "observed_sim_ns": clock["sim_ns"],
                                "system_id": 9,
                                "base_mode": int(heartbeat.base_mode),
                                "custom_mode": int(heartbeat.custom_mode),
                            }, writer, fanout
                        )
                except Exception as exc:
                    errors.append(repr(exc))
                    return

        topics = [
            (Image, "/benchmark/rgbd/image", "rgb"),
            (Image, "/benchmark/rgbd/depth_image", "depth"),
            (CameraInfo, "/benchmark/rgbd/camera_info", "info"),
            (IMU, "/world/fly_ego_benchmark/model/x500_benchmark_8/link/base_link/sensor/imu_sensor/imu", "imu"),
        ]
        callbacks = []
        for cls, topic, kind in topics:

            def callback(msg, kind=kind):
                submit(kind, msg)

            callbacks.append(callback)
            if not node.subscribe(cls, topic, callback):
                raise RuntimeError("subscription failed: " + topic)
            journal.cleanup("unsubscribe " + topic, lambda topic=topic: node.unsubscribe(topic), priority=60)
        fixture = TestFixture(str(output / "world.sdf"))
        motion = None
        reference = None
        if args.reference_module:
            from tools.benchmark.native_reference_probe import ReferenceRecorder, load_module, post_motion, pre_motion

            module = load_module(args.reference_module, args.reference_sha256)
            reference = ReferenceRecorder(output, errors, module.Probe())
            journal.cleanup("native reference", lambda: result.update(native_reference=reference.finish()), priority=74)
            metadata = json.dumps(
                dict(
                    path=str(args.reference_module.resolve()),
                    sha256=args.reference_sha256,
                    api=module.API_VERSION,
                    testing=module.TESTING,
                )
            )
            with (output / "native-reference-binary.json").open("x") as f:
                if f.write(metadata) != len(metadata):
                    raise OSError("short native reference metadata write")
                f.flush()
        if args.motion_profile:
            from tools.benchmark.disarmed_motion_probe import GazeboMotionProbe

            trace = None
            if args.physics_trace_profile:
                from tools.benchmark.physics_substep_trace import SubstepTrace, finish_capture_trace

                trace = SubstepTrace(output)

                def finish_trace():
                    finish_capture_trace(trace, result, errors)

                journal.cleanup("physics trace", finish_trace, priority=76)
            motion_type = GazeboMotionProbe
            if args.motion_profile in ("supported-lateral-v1", "supported-ready-v1"):
                from tools.benchmark.supported_excitation import SupportedProbe

                motion_type = SupportedProbe
            extra = {}
            if readiness:
                from tools.benchmark.readiness_anchor import AnchoredPolicy, anchored_profile, persist_anchor

                if motion_intent:
                    from tools.benchmark.motion_intent_physical import MotionIntentAnchoredPolicy

                    AnchoredPolicy = MotionIntentAnchoredPolicy

                extra = dict(
                    policy=(
                        AnchoredPolicy(
                            fanout.proof if fanout else readiness.proof,
                            lambda row: persist_anchor(output, row),
                            prepare_motion=lambda anchor, proof: apply_native_motion_intent(
                                motion_intent, readiness, client, anchor, proof
                            ),
                        )
                        if motion_intent
                        else AnchoredPolicy(
                            fanout.proof if fanout else readiness.proof,
                            lambda row: persist_anchor(output, row),
                        )
                    ),
                    profile_data=anchored_profile(),
                )
            motion = motion_type(output, errors, lambda: arming["unarmed_wall_ns"], trace=trace, **extra)
            journal.cleanup("motion fixture", lambda: result.update(motion=motion.finish()), priority=75)
            if reference:
                if args.reference_fault_profile:
                    from tools.benchmark.native_runtime_refusal import RuntimeRefusal

                    refusal = RuntimeRefusal(output, reference, motion, readiness.proof)
                    journal.cleanup("runtime refusal", lambda: result.update(runtime_refusal=refusal.finish()), priority=73)
                    fixture.on_pre_update(refusal.pre_motion)
                else:
                    if fanout:
                        def pre_online(info, ecm):
                            def health():
                                if errors or writer.error or shadow.failure:
                                    raise RuntimeError("pre-step source failure: " + str(errors or writer.error or shadow.failure))
                                source_guard.check(time.monotonic_ns())

                            if not fanout.pre_step(lambda: pre_motion(reference, motion, info, ecm), health):
                                if not any(e.startswith("source fan-out:") for e in errors):
                                    errors.append("source fan-out: " + str(fanout.failure))

                        fixture.on_pre_update(pre_online)
                    else:
                        fixture.on_pre_update(lambda info, ecm: pre_motion(reference, motion, info, ecm))
            else:
                fixture.on_pre_update(motion.pre_update)

        def post_update(info, _ecm):
            clock["sim_ns"] = sim_duration_ns(info.sim_time)
            if reference:
                post_motion(reference, motion, info, _ecm)
            elif motion:
                motion.post_update(info, _ecm)

        fixture.on_post_update(post_update)
        fixture.finalize()
        server = fixture.server()
        if binding:
            binding.observe("postfinalize")
        if source_guard:
            watchdog_stop = threading.Event()

            def watch_sources():
                while not watchdog_stop.wait(0.05):
                    try:
                        source_guard.check(time.monotonic_ns())
                    except Exception as exc:
                        result["source_watchdog_failure"] = dict(
                            source_guard.snapshot(), checked_ns=time.monotonic_ns(), reason=repr(exc)
                        )
                        errors.append("source watchdog: " + repr(exc))
                        return

            watchdog_thread = threading.Thread(target=watch_sources, daemon=True)
            watchdog_thread.start()
            journal.cleanup("source watchdog", lambda: (watchdog_stop.set(), watchdog_thread.join(timeout=1)), priority=10)
        heartbeat_thread = threading.Thread(target=read_heartbeats, daemon=True)
        heartbeat_thread.start()
        journal.cleanup("heartbeat", lambda: (stop.set(), heartbeat_thread.join(timeout=3)), priority=40)
        log = (output / "px4.log").open("x")
        journal.cleanup("log close", log.close, priority=70)
        process = subprocess.Popen(
            [str(binary), "-i", "8", "-d", str(build / "etc")],
            cwd=runtime,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=False,
        )
        if binding and "px4" in binding.required_owned:
            binding.register_owned("px4", process, binary)
            owned_processes["px4"] = process

        def stop_px4():
            if binding and "px4" in binding.required_owned and owned_ready["px4"]:
                try:
                    binding.observe_owned("px4", "prestop")
                except Exception as exc:
                    errors.append("PX4 runtime mapping: " + repr(exc))
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    errors.append("owned PX4 required SIGKILL")
            result["px4_exit_code"] = process.returncode

        journal.cleanup("owned PX4", stop_px4, priority=20)
        with (output / "process.json").open("x") as f:
            json.dump({"pid": process.pid, "args": process.args, "started_wall_ns": time.time_ns()}, f, indent=2)
        if source_guard:
            source_guard.start(time.monotonic_ns())
        first_step_observed = False
        while clock["sim_ns"] < contract["simulation_duration_ns"]:
            if errors or writer.error:
                raise RuntimeError("capture callback/writer failure: " + str(errors or writer.error))
            if shadow and shadow.failure:
                raise RuntimeError("shadow failure: " + shadow.failure)
            if process.poll() is not None:
                raise RuntimeError("PX4 exited during capture")
            wall_budget = contract["wall_budget_s"]
            if time.monotonic() - started > wall_budget:
                raise TimeoutError(f"capture exceeded{wall_budget}s wall budget")
            if not server.run(True, 10 if motion else 1000, False):
                raise RuntimeError("Gazebo rejected simulation run")
            if binding and binding.required_self and not first_step_observed:
                binding.observe("postfirststep")
                first_step_observed = True
        result["status"] = "capture_completed"
    print(json.dumps({k: v for k, v in result.items() if k != "writer"}, indent=2))
    return 0 if result["status"] == "capture_completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
