"""Deterministic fixed-input OpenVINS health and fault replay.

The runner is shadow-only.  It never sends MAVLink, publishes ODOMETRY, arms,
or grants fusion.  Fault definitions and all selected input hashes are frozen
before any native process is started.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from pathlib import Path

from tools.benchmark.motion_intent_gate import MotionIntentGate
from tools.benchmark.openvins_health_contract import CovarianceProfile
from tools.benchmark.openvins_online_shadow import (
    NativeClient,
    OnlineHealthEvidence,
    ShadowInput,
    SourceWatchdog,
    validate_frozen_config,
)

FAULT_PROFILES = {
    "normal": {
        "trigger_sim_ns": None,
        "stop_sim_ns": 4_000_000_000,
        "expected_quality": 0,
        "expected_reset_total": 0,
        "fusion_eligible": False,
    },
    "imu_silence": {
        "trigger_sim_ns": 3_100_000_000,
        "stop_sim_ns": 5_200_000_000,
        "expected_quality": -1,
        "expected_reset_total": 0,
        "fusion_eligible": False,
    },
    "camera_silence": {
        "trigger_sim_ns": 3_100_000_000,
        "stop_sim_ns": 5_200_000_000,
        "expected_quality": -1,
        "expected_reset_total": 0,
        "fusion_eligible": False,
    },
    "truncated_image": {
        "trigger_sim_ns": 3_100_000_000,
        "stop_sim_ns": 3_300_000_000,
        "expected_quality": -1,
        "expected_reset_total": 0,
        "fusion_eligible": False,
    },
    "time_regression": {
        "trigger_sim_ns": 3_100_000_000,
        "stop_sim_ns": 3_300_000_000,
        "expected_quality": -1,
        "expected_reset_total": 0,
        "fusion_eligible": False,
    },
    "processing_timeout": {
        "trigger_sim_ns": 1_000_000,
        "stop_sim_ns": 1_000_000,
        "expected_quality": -1,
        "expected_reset_total": 0,
        "fusion_eligible": False,
    },
    "process_restart": {
        "trigger_sim_ns": 3_100_000_000,
        "stop_sim_ns": 3_200_000_000,
        "expected_quality": 0,
        "expected_reset_total": 1,
        "fusion_eligible": False,
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def freeze_fault_matrix(*, binary: Path, config: Path, sealed_capture: Path) -> dict:
    binary = Path(binary).resolve()
    config = Path(config).resolve()
    sealed_capture = Path(sealed_capture).resolve()
    events = sealed_capture / "events.jsonl"
    for path in (binary, config, events):
        if not path.is_file() or path.is_symlink():
            raise ValueError("missing or linked frozen health replay input")
    manifest = {
        "schema": "openvins-health-fault-matrix-v1",
        "binary": {"path": str(binary), "bytes": binary.stat().st_size, "sha256": _sha256(binary)},
        "config": {"path": str(config), "bytes": config.stat().st_size, "sha256": _sha256(config)},
        "source": {
            "capture": str(sealed_capture),
            "events_path": str(events),
            "events_bytes": events.stat().st_size,
            "events_sha256": _sha256(events),
        },
        "covariance_profile": {
            "name": CovarianceProfile().name,
            "sim_domain_qualified": False,
        },
        "profiles": copy.deepcopy(FAULT_PROFILES),
        "network_output": False,
        "odometry_output": False,
        "fusion_eligible": False,
    }
    manifest["matrix_sha256"] = _canonical_sha(manifest)
    return manifest


def validate_fault_matrix(manifest: object, *, binary: Path, config: Path, sealed_capture: Path) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("invalid health fault matrix")
    expected = freeze_fault_matrix(binary=binary, config=config, sealed_capture=sealed_capture)
    if manifest != expected:
        raise ValueError("health fault matrix or frozen input changed")
    if manifest["matrix_sha256"] != _canonical_sha({k: v for k, v in manifest.items() if k != "matrix_sha256"}):
        raise ValueError("health fault matrix digest mismatch")
    return copy.deepcopy(manifest)


def audit_fault_results(manifest: object, result_roots: object) -> dict:
    """Verify a complete frozen matrix without granting fusion authority."""
    if not isinstance(manifest, dict) or manifest.get("schema") != "openvins-health-fault-matrix-v1":
        raise ValueError("invalid frozen health fault matrix")
    digest = manifest.get("matrix_sha256")
    unsigned = {key: value for key, value in manifest.items() if key != "matrix_sha256"}
    if digest != _canonical_sha(unsigned) or manifest.get("profiles") != FAULT_PROFILES:
        raise ValueError("health fault matrix digest/profile mismatch")
    if not isinstance(result_roots, dict) or set(result_roots) != set(FAULT_PROFILES):
        raise ValueError("incomplete health fault result set")
    audited = {}
    for profile, expected in FAULT_PROFILES.items():
        root = Path(result_roots[profile])
        matrix_path = root / "fault-matrix.json"
        direct_result = root / "fault-result.json"
        nested_result = root / profile / "fault-result.json"
        candidates = [path for path in (direct_result, nested_result) if path.is_file()]
        if len(candidates) != 1:
            raise ValueError("ambiguous or missing health fault result")
        result_path = candidates[0]
        try:
            embedded = json.loads(matrix_path.read_text())
            result = json.loads(result_path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("unreadable health fault evidence") from exc
        if embedded != manifest:
            raise ValueError("health fault result used a different frozen matrix")
        if (
            result.get("schema") != "openvins-health-fault-result-v1"
            or result.get("profile") != profile
            or result.get("qualified") is not True
            or result.get("fusion_eligible") is not False
            or result.get("network_output") is not False
            or result.get("odometry_output") is not False
        ):
            raise ValueError("invalid health fault result claims")
        health = result.get("health")
        if (
            not isinstance(health, dict)
            or health.get("last_quality") != expected["expected_quality"]
            or health.get("reset_total") != expected["expected_reset_total"]
            or health.get("fusion_eligible") is not False
        ):
            raise ValueError("health quality/reset result mismatch")
        native_rows = [result.get("native")] if profile == "processing_timeout" else [
            session.get("native") for session in result.get("sessions", []) if isinstance(session, dict)
        ]
        expected_sessions = 2 if profile == "process_restart" else 1
        if len(native_rows) != expected_sessions or any(not isinstance(row, dict) for row in native_rows):
            raise ValueError("health native-session evidence missing")
        for row in native_rows:
            if row.get("quality") is not None or row.get("reset_counter") is not None or row.get("fusion_eligible") is not False:
                raise ValueError("native process falsely claimed derived health")
        if profile == "processing_timeout":
            if native_rows[0].get("exit") == 0 or not native_rows[0].get("failure"):
                raise ValueError("processing timeout cleanup/refusal missing")
        elif any(row.get("exit") != 0 or row.get("failure") is not None for row in native_rows):
            raise ValueError("fixed replay native process failed cleanup")
        audited[profile] = {
            "matrix_sha256": _sha256(matrix_path),
            "result_sha256": _sha256(result_path),
            "quality": health["last_quality"],
            "reset_total": health["reset_total"],
            "native_exits": [row["exit"] for row in native_rows],
            "qualified": True,
            "fusion_eligible": False,
        }
    return {
        "schema": "openvins-health-fault-matrix-audit-v1",
        "matrix_sha256": digest,
        "profiles": audited,
        "qualified": True,
        "fusion_eligible": False,
        "network_output": False,
        "odometry_output": False,
    }


def _read_ppm_rgb(path: Path) -> bytes:
    data = path.read_bytes()
    if not data.startswith(b"P6\n"):
        raise ValueError("unsupported PPM encoding")
    offset = 3
    tokens: list[bytes] = []
    while len(tokens) < 3:
        end = data.find(b"\n", offset)
        if end < 0:
            raise ValueError("truncated PPM header")
        line = data[offset:end]
        offset = end + 1
        if not line.startswith(b"#"):
            tokens.extend(line.split())
    if tokens != [b"160", b"120", b"255"] or len(data) - offset != 57600:
        raise ValueError("unexpected PPM geometry/payload")
    return data[offset:]


def _native_command(binary: Path, config: Path, output: Path) -> list[str]:
    return [str(binary), str(config), str(output / "states.jsonl"), str(output / "fast.jsonl")]


def _source_health_failure(evidence: OnlineHealthEvidence, reason: str) -> dict:
    return evidence.fail(reason)


def _motion_command(session_id: str, clock_id: str, effective_ns: int) -> dict:
    return {
        "session_id": session_id,
        "clock_id": clock_id,
        "command_sequence": 0,
        "effective_sim_ns": effective_ns,
        "issued_monotonic_ns": time.monotonic_ns(),
        "unarmed": True,
        "safety_authorized": True,
        "velocity_setpoint_frd_m_s": [0.0, 0.4, 0.0],
        "yaw_rate_setpoint_rad_s": 0.0,
        "source": "px4-safe-setpoint-supervisor",
    }


class _MotionIntentReplayClient:
    """Inject the one required native intent while retaining original C acks."""

    def __init__(self, native, output: Path, *, session_id: str, clock_id: str, fault: str | None, trigger_ns):
        self.native = native
        self.session_id = session_id
        self.clock_id = clock_id
        self.fault = fault
        self.trigger_ns = trigger_ns
        gate_output = output / "motion-gate"
        gate_output.mkdir()
        self.gate = MotionIntentGate(
            session_id=session_id,
            clock_id=clock_id,
            output=gate_output,
            native_adapter_integrated=True,
        )
        self.intent_ack = None
        self.last_camera_sample_ns = None
        self.time_regression_injected = False

    def send(self, action, pixels=None):
        row = self.native.send(action, pixels)
        if row["kind"] != "C":
            return row
        original = copy.deepcopy(row)
        if row["internal_initialized"] is True and self.intent_ack is None:
            self.gate.observe_estimator(
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
            effective = max(2_621_000_000, row["sample_ns"] + 200_000_000)
            request = self.gate.request(_motion_command(self.session_id, self.clock_id, effective))
            self.intent_ack = self.native.send_motion_intent(request)
            self.gate.acknowledge(self.intent_ack)
        if (
            self.fault == "time_regression"
            and not self.time_regression_injected
            and self.last_camera_sample_ns is not None
            and row["sample_ns"] >= self.trigger_ns
        ):
            row = copy.deepcopy(row)
            row["sample_ns"] = self.last_camera_sample_ns
            self.time_regression_injected = True
        self.last_camera_sample_ns = original["sample_ns"]
        return row

    def finish(self):
        return self.gate.finish()


def _payload_for(row: dict, sealed_capture: Path) -> bytes | None:
    if row["kind"] == "rgb":
        return _read_ppm_rgb(sealed_capture / "rgb-frames" / f"{row['sample_ns']}.ppm")
    if row["kind"] == "info":
        path = sealed_capture / row["payload_path"]
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != row["payload_sha256"]:
            raise ValueError("camera-info payload changed")
        return payload
    return None


def _run_stream_session(
    *,
    binary: Path,
    config: Path,
    sealed_capture: Path,
    output: Path,
    evidence: OnlineHealthEvidence,
    session_id: str,
    fault: str,
    trigger_ns: int | None,
    stop_ns: int,
) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    validate_frozen_config(config)
    native = NativeClient(_native_command(binary, config, output), output)
    adapter = _MotionIntentReplayClient(
        native,
        output,
        session_id=session_id,
        clock_id="fixed-health-replay-sim+linux-monotonic",
        fault=fault,
        trigger_ns=trigger_ns,
    )
    shadow = ShadowInput(adapter, output, session_id=session_id, now=time.monotonic_ns, health=evidence)
    watchdog = SourceWatchdog(timeout_ns=2_000_000_000, startup_timeout_ns=10_000_000_000)
    watchdog.start(1)
    source_rows = 0
    delivered_rows = 0
    skipped_rows = 0
    injected_fault = None
    replay_arrival_ns = 0
    try:
        with (sealed_capture / "events.jsonl").open(encoding="utf8") as stream:
            for line in stream:
                source_row = json.loads(line)
                row = copy.deepcopy(source_row)
                now = row["observed_sim_ns"]
                if now > stop_ns:
                    break
                if row["kind"] not in {"imu", "rgb", "info"}:
                    continue
                source_rows += 1
                replay_arrival_ns = max(replay_arrival_ns + 1, time.monotonic_ns() - 1)
                row["arrival_monotonic_ns"] = replay_arrival_ns
                suppressed = bool(
                    trigger_ns is not None
                    and now >= trigger_ns
                    and (
                        (fault == "imu_silence" and row["kind"] == "imu")
                        or (fault == "camera_silence" and row["kind"] in {"rgb", "info"})
                    )
                )
                if suppressed:
                    skipped_rows += 1
                else:
                    watchdog.observe(row["kind"], max(1, now))
                    payload = _payload_for(row, sealed_capture)
                    if (
                        fault == "truncated_image"
                        and injected_fault is None
                        and row["kind"] == "rgb"
                        and now >= trigger_ns
                    ):
                        payload = b"truncated"
                        injected_fault = "truncated_image"
                    shadow.on_record(row, payload)
                    delivered_rows += 1
                    if shadow.failure:
                        injected_fault = injected_fault or fault
                        break
                try:
                    watchdog.check(max(1, now))
                except TimeoutError:
                    evidence.fail("source_failure")
                    injected_fault = fault
                    break
        if fault in {"imu_silence", "camera_silence"} and injected_fault is None:
            try:
                watchdog.check(stop_ns)
            except TimeoutError:
                evidence.fail("source_failure")
                injected_fault = fault
    finally:
        shadow_result = shadow.finish()
        gate_result = adapter.finish()
        native_result = native.finish()
    return {
        "session_id": session_id,
        "source_rows": source_rows,
        "delivered_rows": delivered_rows,
        "skipped_rows": skipped_rows,
        "arrival_mapping": "current-monotonic-order-only-not-latency-evidence",
        "injected_fault": injected_fault,
        "watchdog": watchdog.snapshot(),
        "shadow": shadow_result,
        "gate": gate_result,
        "native": native_result,
        "intent_ack": adapter.intent_ack,
        "fusion_eligible": False,
    }


def run_fixed_profile(
    *, binary: Path, config: Path, sealed_capture: Path, output: Path, profile: str
) -> dict:
    if profile not in FAULT_PROFILES or profile == "processing_timeout":
        raise ValueError("invalid fixed-source health profile")
    output.mkdir(parents=True, exist_ok=False)
    selected = FAULT_PROFILES[profile]
    evidence = OnlineHealthEvidence(output, session_id=f"health-{profile}-session-0")
    sessions = [
        _run_stream_session(
            binary=binary,
            config=config,
            sealed_capture=sealed_capture,
            output=output / "session-0",
            evidence=evidence,
            session_id=f"health-{profile}-session-0",
            fault=profile,
            trigger_ns=selected["trigger_sim_ns"],
            stop_ns=selected["stop_sim_ns"],
        )
    ]
    if profile == "process_restart":
        evidence.replace_session("health-process_restart-session-1")
        sessions.append(
            _run_stream_session(
                binary=binary,
                config=config,
                sealed_capture=sealed_capture,
                output=output / "session-1",
                evidence=evidence,
                session_id="health-process_restart-session-1",
                fault="normal",
                trigger_ns=None,
                stop_ns=selected["stop_sim_ns"],
            )
        )
    health = evidence.finish()
    qualified = bool(
        health["last_quality"] == selected["expected_quality"]
        and health["reset_total"] == selected["expected_reset_total"]
        and all(session["native"]["exit"] == 0 for session in sessions)
        and all(session["gate"]["qualified"] for session in sessions)
    )
    if profile not in {"normal", "process_restart"}:
        qualified &= health["last_quality"] == -1
    result = {
        "schema": "openvins-health-fault-result-v1",
        "profile": profile,
        "sessions": sessions,
        "health": health,
        "qualified": qualified,
        "fusion_eligible": False,
        "network_output": False,
        "odometry_output": False,
    }
    (output / "fault-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if not qualified:
        raise RuntimeError(f"{profile} fixed health replay did not qualify")
    return result


def run_processing_timeout(*, output: Path, session_id: str) -> dict:
    """Exercise NativeClient's real bounded write/ack deadline with an owned child."""
    output.mkdir(parents=True, exist_ok=False)
    evidence = OnlineHealthEvidence(output, session_id=session_id)
    client = NativeClient(
        ["python3", "-c", "import time; time.sleep(5)"],
        output,
        timeout_s=0.05,
    )
    refusal = None
    try:
        client.send(
            {
                "kind": "imu",
                "sample_ns": 1_000_000,
                "source_arrival_ns": max(1, time.monotonic_ns() - 1),
                "wm": [0.0, 0.0, 0.0],
                "am": [0.0, 0.0, 9.81],
            }
        )
    except BaseException as exc:
        refusal = repr(exc)
        _source_health_failure(evidence, "native_failure")
    native = client.finish()
    health = evidence.finish()
    result = {
        "schema": "openvins-health-fault-result-v1",
        "profile": "processing_timeout",
        "refusal": refusal,
        "native": native,
        "health": health,
        "qualified": bool(refusal and native["failure"] and health["last_quality"] == -1),
        "fusion_eligible": False,
        "network_output": False,
        "odometry_output": False,
    }
    (output / "fault-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if not result["qualified"]:
        raise RuntimeError("processing-timeout replay did not qualify")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--sealed-capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--fault", choices=sorted(FAULT_PROFILES))
    args = parser.parse_args()
    manifest = freeze_fault_matrix(binary=args.binary, config=args.config, sealed_capture=args.sealed_capture)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "fault-matrix.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if args.freeze_only:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return
    if args.fault == "processing_timeout":
        result = run_processing_timeout(output=args.output / args.fault, session_id="health-timeout-session")
    else:
        result = run_fixed_profile(
            binary=args.binary,
            config=args.config,
            sealed_capture=args.sealed_capture,
            output=args.output / args.fault,
            profile=args.fault,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
