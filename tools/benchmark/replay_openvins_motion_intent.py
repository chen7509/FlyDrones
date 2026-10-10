"""Replay sealed sensor inputs through the GPL-linked motion-intent adapter."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from pathlib import Path

from tools.benchmark.motion_intent_gate import MotionIntentGate
from tools.benchmark.openvins_online_shadow import NativeClient, validate_frozen_config


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_ppm_rgb(path):
    data = Path(path).read_bytes()
    if not data.startswith(b"P6\n"):
        raise ValueError("unsupported PPM encoding")
    offset = 3
    tokens = []
    while len(tokens) < 3:
        end = data.find(b"\n", offset)
        if end < 0:
            raise ValueError("truncated PPM header")
        line = data[offset:end]
        offset = end + 1
        if line.startswith(b"#"):
            continue
        tokens.extend(line.split())
    if tokens != [b"160", b"120", b"255"] or len(data) - offset != 57600:
        raise ValueError("unexpected PPM geometry/payload")
    return data[offset:]


def _motion_action(session_id, clock_id, effective_ns):
    issued = time.monotonic_ns()
    command = {
        "session_id": session_id,
        "clock_id": clock_id,
        "command_sequence": 0,
        "effective_sim_ns": effective_ns,
        "issued_monotonic_ns": issued,
        "unarmed": True,
        "safety_authorized": True,
        "velocity_setpoint_frd_m_s": [0.0, 0.4, 0.0],
        "yaw_rate_setpoint_rad_s": 0.0,
        "source": "px4-safe-setpoint-supervisor",
    }
    return command


def _native_command(binary, config, output):
    return [str(binary), str(config), str(output / "states.jsonl"), str(output / "fast.jsonl")]


def run_preinit_refusal(*, binary, config, output, session_id, clock_id):
    output.mkdir(parents=True, exist_ok=False)
    validate_frozen_config(config)
    client = NativeClient(_native_command(binary, config, output), output)
    action = {
        "kind": "motion_intent",
        "sample_ns": 2_621_000_000,
        "source_arrival_ns": time.monotonic_ns(),
        "session_id": session_id,
        "clock_id": clock_id,
        "command_sequence": 0,
        "intent_sha256": "a" * 64,
    }
    refusal = None
    try:
        client.send_motion_intent(action)
    except BaseException as exc:
        refusal = repr(exc)
    result = client.finish()
    native_log = (output / "native.log").read_text(errors="replace")
    summary = {
        "schema": "openvins-motion-intent-preinit-refusal-v1",
        "binary_sha256": _sha256(binary),
        "config_sha256": _sha256(config),
        "refusal": refusal,
        "native_result": result,
        "native_log_sha256": _sha256(output / "native.log"),
        "qualified": bool(refusal) and result["exit"] == 2 and "motion intent before internal initialization" in native_log,
        "truth_used": False,
        "physical_replay": False,
        "fusion_eligible": False,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    if not summary["qualified"]:
        raise RuntimeError("native pre-initialization refusal did not qualify")
    return summary


def run_duplicate_refusal(*, binary, config, sealed_capture, output, session_id, clock_id, effective_ns):
    output.mkdir(parents=True, exist_ok=False)
    validate_frozen_config(config)
    requests = [
        json.loads(line)
        for line in (sealed_capture / "shadow" / "native-requests.jsonl").read_text().splitlines()
    ]
    client = NativeClient(_native_command(binary, config, output), output)
    gate_dir = output / "motion-gate"
    gate_dir.mkdir()
    gate = MotionIntentGate(
        session_id=session_id,
        clock_id=clock_id,
        output=gate_dir,
        native_adapter_integrated=True,
    )
    initialized = None
    first_ack = None
    refusal = None
    source_records = 0
    for original in requests:
        replay_action = copy.deepcopy(original["action"])
        replay_action["source_arrival_ns"] = max(1, time.monotonic_ns() - 1)
        pixels = None
        if replay_action["kind"] == "camera":
            pixels = _read_ppm_rgb(sealed_capture / "rgb-frames" / f"{replay_action['sample_ns']}.ppm")
        row = client.send(replay_action, pixels)
        source_records += 1
        if row["kind"] == "C" and row.get("internal_initialized") is True:
            initialized = copy.deepcopy(row)
            break
    if initialized is None:
        raise RuntimeError("sealed input did not initialize native estimator")
    gate.observe_estimator(
        {
            "kind": "C",
            "native_sequence": initialized["sequence"],
            "sample_ns": initialized["sample_ns"],
            "acknowledged_ns": initialized["acknowledged_ns"],
            "internal_initialized": True,
            "has_moved_since_zupt": initialized["has_moved_since_zupt"],
            "reset_counter": initialized["reset_counter"],
        }
    )
    action = gate.request(_motion_action(session_id, clock_id, effective_ns))
    first_ack = client.send_motion_intent(action)
    gate.acknowledge(first_ack)
    try:
        client.send_motion_intent(copy.deepcopy(action))
    except BaseException as exc:
        refusal = repr(exc)
    gate_result = gate.finish()
    native_result = client.finish()
    native_log = (output / "native.log").read_text(errors="replace")
    summary = {
        "schema": "openvins-motion-intent-duplicate-refusal-v1",
        "binary_sha256": _sha256(binary),
        "config_sha256": _sha256(config),
        "source_records_before_intent": source_records,
        "initialized_sample_ns": initialized["sample_ns"],
        "first_ack": first_ack,
        "gate": gate_result,
        "duplicate_refusal": refusal,
        "native": native_result,
        "native_log_sha256": _sha256(output / "native.log"),
        "qualified": bool(
            gate_result["qualified"]
            and refusal
            and native_result["exit"] == 2
            and "duplicate native motion intent" in native_log
        ),
        "truth_used": False,
        "physical_replay": False,
        "fusion_eligible": False,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    if not summary["qualified"]:
        raise RuntimeError("native duplicate motion-intent refusal did not qualify")
    return summary


def run_fixed_replay(*, binary, config, sealed_capture, output, session_id, clock_id, effective_ns, stop_ns):
    output.mkdir(parents=True, exist_ok=False)
    validate_frozen_config(config)
    request_path = sealed_capture / "shadow" / "native-requests.jsonl"
    requests = [json.loads(line) for line in request_path.read_text().splitlines()]
    client = NativeClient(_native_command(binary, config, output), output)
    gate_dir = output / "motion-gate"
    gate_dir.mkdir()
    gate = MotionIntentGate(
        session_id=session_id,
        clock_id=clock_id,
        output=gate_dir,
        native_adapter_integrated=True,
    )
    replay = (output / "replay.jsonl").open("x", encoding="utf8")
    initialized = None
    intent_ack = None
    camera_rows = []
    failure = None
    replayed_source_records = 0
    try:
        for original in requests:
            original_action = original["action"]
            replay_action = copy.deepcopy(original_action)
            replay_action["source_arrival_ns"] = max(1, time.monotonic_ns() - 1)
            pixels = None
            if replay_action["kind"] == "camera":
                pixels = _read_ppm_rgb(sealed_capture / "rgb-frames" / f"{replay_action['sample_ns']}.ppm")
            row = client.send(replay_action, pixels)
            replayed_source_records += 1
            replay.write(
                json.dumps(
                    {
                        "source_sequence": original["sequence"],
                        "source_packet_sha256": original["packet_sha256"],
                        "source_rgb_sha256": original["rgb_sha256"],
                        "replay_sequence": row["sequence"],
                        "kind": row["kind"],
                        "sample_ns": row["sample_ns"],
                        "internal_initialized": row.get("internal_initialized"),
                        "has_moved_since_zupt": row.get("has_moved_since_zupt"),
                        "zupt_flag_latched": row.get("zupt_flag_latched"),
                        "imu_state": row.get("imu_state"),
                    },
                    allow_nan=False,
                    sort_keys=True,
                )
                + "\n"
            )
            replay.flush()
            if row["kind"] == "C":
                camera_rows.append(copy.deepcopy(row))
                if initialized is None and row.get("internal_initialized") is True:
                    initialized = copy.deepcopy(row)
                    gate.observe_estimator(
                        {
                            "kind": "C",
                            "native_sequence": row["sequence"],
                            "sample_ns": row["sample_ns"],
                            "acknowledged_ns": row["acknowledged_ns"],
                            "internal_initialized": True,
                            "has_moved_since_zupt": row["has_moved_since_zupt"],
                            "reset_counter": row["reset_counter"],
                        }
                    )
                    action = gate.request(_motion_action(session_id, clock_id, effective_ns))
                    intent_ack = client.send_motion_intent(action)
                    gate.acknowledge(intent_ack)
                    if gate.authorize_step(effective_ns) is not True:
                        raise RuntimeError("motion-intent gate did not authorize effective time")
            if initialized is not None and row["kind"] == "C" and row["sample_ns"] >= stop_ns:
                break
    except BaseException as exc:
        failure = repr(exc)
        raise
    finally:
        replay.close()
        gate_result = gate.finish()
        native_result = client.finish()
        summary = {
            "schema": "openvins-fixed-input-motion-intent-replay-v1",
            "source_capture": str(sealed_capture),
            "source_requests_sha256": _sha256(request_path),
            "binary_sha256": _sha256(binary),
            "config_sha256": _sha256(config),
            "effective_sim_ns": effective_ns,
            "stop_sim_ns": stop_ns,
            "replayed_source_records": replayed_source_records,
            "transport_accepted": native_result["accepted"],
            "initialized_sample_ns": initialized["sample_ns"] if initialized else None,
            "intent_ack": intent_ack,
            "post_intent_camera_states": [
                {
                    "sample_ns": row["sample_ns"],
                    "has_moved_since_zupt": row["has_moved_since_zupt"],
                    "zupt_flag_latched": row["zupt_flag_latched"],
                    "imu_state": row["imu_state"],
                }
                for row in camera_rows
                if intent_ack is not None and row["sample_ns"] >= intent_ack["sample_ns"]
            ],
            "gate": gate_result,
            "native": native_result,
            "failure": failure,
            "qualified": bool(
                initialized
                and intent_ack
                and gate_result["qualified"]
                and native_result["exit"] == 0
                and any(
                    row["sample_ns"] >= effective_ns
                    and row["has_moved_since_zupt"] is True
                    and row["zupt_flag_latched"] is False
                    for row in camera_rows
                )
            ),
            "truth_used": False,
            "physical_replay": False,
            "fusion_eligible": False,
            "online_latency_qualified": False,
        }
        (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    if failure or not summary["qualified"]:
        raise RuntimeError("fixed-input native motion-intent replay did not qualify")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--sealed-capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--session-id", default="fixed-input-native-motion-intent-v1")
    parser.add_argument("--clock-id", default="fixed-replay-sim+linux-monotonic")
    parser.add_argument("--effective-ns", type=int, default=2_621_000_000)
    parser.add_argument("--stop-ns", type=int, default=3_000_000_000)
    parser.add_argument("--preinit-refusal", action="store_true")
    parser.add_argument("--duplicate-refusal", action="store_true")
    args = parser.parse_args()
    if args.preinit_refusal and args.duplicate_refusal:
        parser.error("choose only one refusal mode")
    if args.preinit_refusal:
        summary = run_preinit_refusal(
            binary=args.binary,
            config=args.config,
            output=args.output,
            session_id=args.session_id,
            clock_id=args.clock_id,
        )
    elif args.duplicate_refusal:
        if args.sealed_capture is None:
            parser.error("--sealed-capture is required for duplicate refusal")
        summary = run_duplicate_refusal(
            binary=args.binary,
            config=args.config,
            sealed_capture=args.sealed_capture,
            output=args.output,
            session_id=args.session_id,
            clock_id=args.clock_id,
            effective_ns=args.effective_ns,
        )
    else:
        if args.sealed_capture is None:
            parser.error("--sealed-capture is required for fixed replay")
        summary = run_fixed_replay(
            binary=args.binary,
            config=args.config,
            sealed_capture=args.sealed_capture,
            output=args.output,
            session_id=args.session_id,
            clock_id=args.clock_id,
            effective_ns=args.effective_ns,
            stop_ns=args.stop_ns,
        )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
