"""Shared prospective test files. All binaries/assets are synthetic and never executed."""

import hashlib
import json
from pathlib import Path

from tools.benchmark import capture_contract as contract
from tools.benchmark.capture_disarmed_sensors import parse_capture_args
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot
from tools.benchmark.trajectory_gauge_contract import trajectory_gauge_policy


def graph_fixture(tmp_path):
    from tools.benchmark.native_resource_client import LOOKUP_KEYS, QUERY_ENV_KEYS
    from tools.benchmark.runtime_resource_binding import ENV_KEYS, GENERATED_NAMES

    binary = tmp_path / "selected.so"
    binary.write_bytes(b"x")
    generated = {}
    for name in GENERATED_NAMES:
        path = tmp_path / name
        path.write_bytes(name.encode())
        generated[name] = path
    generated["world.sdf"].write_text("<sdf/>")
    cpp, dep = tmp_path / "resolver.cc", tmp_path / "library.so"
    cpp.write_text("source")
    dep.write_bytes(b"lib")
    inventory = {"graph:resolver": [str(binary)], "graph:source": [str(cpp)], "graph:dependencies": [str(dep)]}
    context = dict(
        cwd=str(Path.cwd()),
        sdf_share_path=str(tmp_path),
        sdf_version="1.11",
        common_callback_observation="unavailable: SDK has no callback inspection API",
        file_paths=[],
        plugin_paths=[],
        sdf_callback_present=False,
        search_context_qualified=False,
        runtime_closure_qualified=False,
        common_file_callbacks_present=None,
        common_uri_callbacks_present=None,
        sdf_uri_paths={},
        before_environment={k: None for k in LOOKUP_KEYS},
        after_environment={k: None for k in LOOKUP_KEYS},
    )
    doc = dict(
        schema="capture-resource-binding-v2",
        inventory=inventory,
        baseline=snapshot(inventory),
        environment={k: None for k in ENV_KEYS},
        generated={name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in generated.items()},
        graph=dict(
            schema="generated-resource-graph-v1",
            cwd=str(Path.cwd()),
            environment={k: None for k in QUERY_ENV_KEYS},
            expected_context=context,
        ),
    )
    output = tmp_path / "capture"
    output.mkdir()
    return doc, generated, binary, dep, output


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def fixture(tmp_path):
    binding, _, _, _, _ = graph_fixture(tmp_path)
    binding["schema"] = "capture-resource-binding-v3"
    binding["runtime_maps"] = dict(
        self_phases=["postimports", "postfinalize", "postfirststep"],
        owned_roles={"px4": ["ready", "prestop"], "openvins": ["ready", "prestop"]},
        max_maps_bytes=8 * 1024 * 1024,
        max_observations=8,
    )
    paths = {
        k: tmp_path / name
        for k, name in dict(
            python="python",
            capture="capture.py",
            auditor="auditor.py",
            execution="execution.json",
            binding="binding.json",
            wire_config="wire.json",
            gauge_policy="gauge.json",
        ).items()
    }
    for role in ("python", "capture", "auditor"):
        paths[role].write_text("fixture only, never executed: " + role)
    native, reference, px4 = [tmp_path / n for n in ("online_probe", "reference.so", "px4")]
    for path in (native, reference, px4):
        path.write_text("fixture only, never executed: " + path.name)
    config = tmp_path / "estimator_config.yaml"
    config.write_text("relative_config_imu: kalibr_imu_chain.yaml\nrelative_config_imucam: kalibr_imucam_chain.yaml\n")
    calibrations = [tmp_path / n for n in ("kalibr_imu_chain.yaml", "kalibr_imucam_chain.yaml")]
    for path in calibrations:
        path.write_text("fixture calibration, not loaded")
    freeze = write(
        tmp_path / "freeze.json",
        {"sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [config, *calibrations]}},
    )
    wire = dict(schema="capture-wire-v1", session_id="normal-v1.clock", sim_origin_ns=0, remote_origin_ns=0)
    gauge = trajectory_gauge_policy()
    write(paths["wire_config"], wire)
    write(paths["gauge_policy"], gauge)
    binding["inventory"]["runtime-root:px4"] = [str(px4)]
    binding["inventory"]["runtime-root:openvins"] = [str(native)]
    binding["inventory"]["runtime-root:native-reference"] = [str(reference)]
    binding["inventory"]["config"] = [str(p) for p in [config, *calibrations, freeze]]
    binding["inventory"]["policy"] = [str(paths["wire_config"]), str(paths["gauge_policy"])]
    binding["baseline"] = snapshot(binding["inventory"])
    write(paths["binding"], binding)
    outputs = {
        k: str(tmp_path / n)
        for k, n in dict(
            capture="live-capture", dispatch="dispatch.json", completion="completion.json", audit="audit.json"
        ).items()
    }
    args = parse_capture_args(
        [
            "--output",
            outputs["capture"],
            "--execution-contract",
            str(paths["execution"]),
            "--runtime-binding",
            str(paths["binding"]),
            "--wire-config",
            str(paths["wire_config"]),
            "--trajectory-gauge-policy",
            str(paths["gauge_policy"]),
            "--shadow-binary",
            str(native),
            "--shadow-config",
            str(config),
            "--reference-module",
            str(reference),
            "--reference-sha256",
            hashlib.sha256(reference.read_bytes()).hexdigest(),
            "--simulation-seed",
            "27601",
            "--motion-profile",
            "supported-ready-v1",
            "--physics-trace-profile",
            "substep-ready-v1",
            "--source-fanout-profile",
            "ready-shadow-heartbeat-estimator-v1",
            "--motion-intent-profile",
            "native-beginning-zupt-v1",
            "--health-profile",
            "px4-d6f12ad-gate-floor-v1",
        ]
    )
    env = contract.derive_launch_environment(binding)
    execution = contract.execution_contract(args, env)
    write(paths["execution"], execution)
    manifest = dict(
        schema="live-wire-study-v1",
        study_id="normal-v1",
        producer_commit="a" * 40,
        role="development",
        simulation_seed=27601,
        expected_status="capture_completed",
        clock_scope="postupdate-simulation-epoch-v1",
        live_activation_authorized=False,
        endpoint=dict(
            local_host="127.0.0.1",
            local_port=14548,
            peer_host="127.0.0.1",
            peer_port=14588,
            sender_system=254,
            sender_component=191,
            target_system=9,
            target_component=1,
            instance=8,
        ),
        limits=dict(
            bootstrap_wall_ns=8_000_000_000,
            accepted_samples=500,
            operational_ns=2_000_000_000,
            source_startup_ns=10_000_000_000,
            readiness_sim_ns=8_000_000_000,
            anchor_ahead_ns=200_000_000,
            cleanup_ns=10_000_000_000,
            max_datagrams=4096,
            max_segments=64,
            segment_events=8192,
            journal_bytes=512 * 1024 * 1024,
        ),
        outputs=outputs,
        files={k: file_record(p) for k, p in paths.items()},
        command=contract.declared_command(args, str(paths["python"]), str(paths["capture"]), env),
    )
    manifest_path = write(tmp_path / "manifest.json", manifest)
    return manifest, dict(execution=execution, binding=binding, wire_config=wire, gauge_policy=gauge), manifest_path
