"""Replay one retained real-source capture into the no-network EKF2 shadow."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import socket
import subprocess
from pathlib import Path
from unittest import mock

from tools.benchmark.openvins_ekf2_file_shadow import FileOnlyEkf2ShadowEvidence
from tools.benchmark.openvins_online_shadow import ShadowInput

CASES = {
    "normal": {},
    "source-loss": {"source_loss_sample_ns": 8_000_000_000},
    "native-timeout": {"native_timeout_camera_sample_ns": 12_000_000_000},
    "session-replacement": {"replace_session_sample_ns": 12_000_000_000},
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid JSON object: " + str(path))
    return value


def _jsonl(path: Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    if not text.endswith("\n"):
        raise ValueError("unterminated JSONL: " + str(path))
    rows = [json.loads(line) for line in text.splitlines() if line]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid JSONL row: " + str(path))
    return rows


def _canonical(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _read_rgb(capture: Path, sample_ns: int) -> bytes:
    data = (capture / "rgb-frames" / f"{sample_ns}.ppm").read_bytes()
    prefix = b"P6\n160 120\n255\n"
    if not data.startswith(prefix) or len(data) != len(prefix) + 57_600:
        raise ValueError("invalid retained RGB frame")
    return data[len(prefix) :]


class ArchivedNative:
    """Strict request/ack replay; it cannot create a process, socket or new estimate."""

    def __init__(self, requests: list[dict], acknowledgements: list[dict], *, timeout_camera_sample_ns=None):
        ack_by_sequence = {row.get("sequence"): row for row in acknowledgements if row.get("kind") in {"I", "C"}}
        pairs = []
        for request in requests:
            action = request.get("action")
            if not isinstance(action, dict) or action.get("kind") not in {"imu", "camera"}:
                continue
            sequence = request.get("sequence")
            acknowledgement = ack_by_sequence.get(sequence)
            if acknowledgement is None:
                raise ValueError("retained request lacks acknowledgement")
            expected_kind = "I" if action["kind"] == "imu" else "C"
            if acknowledgement.get("kind") != expected_kind or acknowledgement.get("sample_ns") != action.get("sample_ns"):
                raise ValueError("retained request/ack identity mismatch")
            if acknowledgement.get("dispatch_ns") != request.get("dispatch_ns"):
                raise ValueError("retained request/ack dispatch mismatch")
            pairs.append((copy.deepcopy(request), copy.deepcopy(acknowledgement)))
        if not pairs:
            raise ValueError("no retained source/native pairs")
        self.pairs = pairs
        self.index = 0
        self.timeout_camera_sample_ns = timeout_camera_sample_ns
        self.failure = None

    def send(self, action, pixels=None):
        if self.failure is not None:
            raise RuntimeError("archived native replay latched")
        if self.index >= len(self.pairs):
            raise ValueError("unexpected replay action")
        request, acknowledgement = self.pairs[self.index]
        if _canonical(action) != _canonical(request["action"]):
            raise ValueError("replayed action differs from retained request")
        expected_rgb = request.get("rgb_sha256")
        actual_rgb = hashlib.sha256(pixels).hexdigest() if pixels is not None else None
        if actual_rgb != expected_rgb:
            raise ValueError("replayed RGB differs from retained request")
        if (
            self.timeout_camera_sample_ns is not None
            and action["kind"] == "camera"
            and action["sample_ns"] >= self.timeout_camera_sample_ns
        ):
            self.failure = "predeclared native timeout"
            raise TimeoutError(self.failure)
        self.index += 1
        return copy.deepcopy(acknowledgement)

    def finish(self, *, require_exhausted: bool) -> dict:
        if require_exhausted and self.index != len(self.pairs):
            raise ValueError("retained native pairs not exhausted")
        return {
            "accepted": self.index,
            "available": len(self.pairs),
            "remaining": len(self.pairs) - self.index,
            "failure": self.failure,
            "fusion_eligible": False,
        }


def prepare(output: Path, capture: Path, native_binary: Path, native_config: Path, runtime_snapshot: Path) -> dict:
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    capture = Path(capture).resolve(strict=True)
    paths = {
        "source_journal": capture / "events.jsonl",
        "native_requests": capture / "shadow" / "native-requests.jsonl",
        "native_acknowledgements": capture / "shadow" / "native-acks.jsonl",
        "native_binary": Path(native_binary).resolve(strict=True),
        "native_config": Path(native_config).resolve(strict=True),
        "runtime_snapshot": Path(runtime_snapshot).resolve(strict=True),
        "replay_runner": Path(__file__).resolve(strict=True),
        "file_shadow_adapter": Path(__file__).with_name("openvins_ekf2_file_shadow.py").resolve(strict=True),
        "integration_contract": Path(__file__).with_name("openvins_ekf2_integration.py").resolve(strict=True),
        "health_contract": Path(__file__).with_name("openvins_health_contract.py").resolve(strict=True),
        "online_shadow": Path(__file__).with_name("openvins_online_shadow.py").resolve(strict=True),
    }
    manifest = {
        "schema": "openvins-ekf2-file-shadow-replay-manifest-v1",
        "capture": str(capture),
        "implementation_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "files": {name: {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)} for name, path in paths.items()},
        "cases": copy.deepcopy(CASES),
        "health_profile": "px4-d6f12ad-gate-floor-v1",
        "camera_covariance_sim_domain_qualified": True,
        "propagated_covariance_sim_domain_qualified": True,
        "network_odometry": False,
        "fusion_eligible": False,
        "truth_used_online": False,
        "test_set_tuning_allowed": False,
    }
    output.mkdir(parents=True)
    (output / "replay-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _verify_manifest(output: Path) -> dict:
    manifest = _json(output / "replay-manifest.json")
    if (
        manifest.get("schema") != "openvins-ekf2-file-shadow-replay-manifest-v1"
        or manifest.get("cases") != CASES
        or manifest.get("network_odometry") is not False
        or manifest.get("fusion_eligible") is not False
        or manifest.get("truth_used_online") is not False
        or manifest.get("test_set_tuning_allowed") is not False
    ):
        raise ValueError("file-shadow replay manifest drift")
    for record in manifest.get("files", {}).values():
        path = Path(record["path"])
        if path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
            raise ValueError("file-shadow replay input drift")
    return manifest


def run_case(output: Path, case: str) -> dict:
    output = Path(output).resolve(strict=True)
    manifest = _verify_manifest(output)
    if case not in CASES:
        raise ValueError("unknown file-shadow replay case")
    case_dir = output / case
    case_dir.mkdir()
    native_dir = case_dir / "native"
    native_dir.mkdir()
    capture = Path(manifest["capture"])
    requests = _jsonl(Path(manifest["files"]["native_requests"]["path"]))
    acknowledgements = _jsonl(Path(manifest["files"]["native_acknowledgements"]["path"]))
    events = _jsonl(Path(manifest["files"]["source_journal"]["path"]))
    settings = CASES[case]
    client = ArchivedNative(
        requests,
        acknowledgements,
        timeout_camera_sample_ns=settings.get("native_timeout_camera_sample_ns"),
    )
    declaration = {
        "schema": "openvins-ekf2-file-shadow-declaration-v1",
        "source_journal_sha256": manifest["files"]["source_journal"]["sha256"],
        "native_binary_sha256": manifest["files"]["native_binary"]["sha256"],
        "native_config_sha256": manifest["files"]["native_config"]["sha256"],
        "runtime_snapshot_sha256": manifest["files"]["runtime_snapshot"]["sha256"],
        "estimator_session_id": "retained-seed-27601-" + case,
        "clock_session_id": "retained-sim-clock-27601",
        "publisher_session_id": "file-only-publisher-27601",
        "health_profile": manifest["health_profile"],
        "sim_domain_qualified": True,
        "max_sample_age_ns": 2_000_000_000,
        "expected_camera_rate_hz": 10,
        "expected_propagated_rate_hz": 50,
        "candidate_output": "ekf2-candidates.jsonl",
        "fusion_rate_qualified": False,
    }
    evidence = FileOnlyEkf2ShadowEvidence(case_dir, declaration)
    shadow = ShadowInput(client, native_dir, session_id=declaration["estimator_session_id"], health=evidence)
    replaced = False
    with mock.patch.object(socket, "socket", side_effect=AssertionError("network attempted")):
        for row in events:
            if row.get("kind") not in {"imu", "rgb", "info"}:
                continue
            if not replaced and row["sample_ns"] >= settings.get("replace_session_sample_ns", 2**63 - 1):
                evidence.replace_session(declaration["estimator_session_id"] + "-replacement-1")
                replaced = True
            if row["sample_ns"] >= settings.get("source_loss_sample_ns", 2**63 - 1):
                evidence.fail("source_failure")
                break
            payload = None
            if row["kind"] == "rgb":
                payload = _read_rgb(capture, row["sample_ns"])
            elif row["kind"] == "info":
                payload_path = row.get("payload_path")
                if not isinstance(payload_path, str) or Path(payload_path).is_absolute():
                    raise ValueError("invalid retained CameraInfo path")
                payload = (capture / payload_path).read_bytes()
                if hashlib.sha256(payload).hexdigest() != row.get("payload_sha256"):
                    raise ValueError("retained CameraInfo changed")
            shadow.on_record(row, payload)
    shadow_result = shadow.finish()
    require_exhausted = case in {"normal", "session-replacement"}
    native_result = client.finish(require_exhausted=require_exhausted)
    evidence_result = evidence.finish()
    expected = {
        "normal": shadow_result["failure"] is None
        and evidence_result["candidate_count"] > 0
        and evidence_result["receiver_shadow_rate_qualified"] is True,
        "source-loss": evidence_result["last_quality"] == -1 and evidence_result["candidate_count"] > 0,
        "native-timeout": shadow_result["failure"] is not None and evidence_result["last_quality"] == -1,
        "session-replacement": shadow_result["failure"] is None
        and evidence_result["reset_counter"] == 1
        and evidence_result["session_count"] == 2,
    }[case]
    result = {
        "schema": "openvins-ekf2-file-shadow-replay-result-v1",
        "case": case,
        "expected_outcome_observed": bool(expected),
        "shadow": shadow_result,
        "native": native_result,
        "evidence": evidence_result,
        "network_odometry": False,
        "fusion_eligible": False,
        "truth_used_online": False,
    }
    (case_dir / "case-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not expected:
        raise RuntimeError("file-shadow replay case failed")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--native-binary", type=Path)
    parser.add_argument("--native-config", type=Path)
    parser.add_argument("--runtime-snapshot", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--run-case", choices=sorted(CASES))
    args = parser.parse_args(argv)
    if args.prepare_only == (args.run_case is not None):
        raise ValueError("select exactly one replay operation")
    if args.prepare_only:
        if any(value is None for value in (args.capture, args.native_binary, args.native_config, args.runtime_snapshot)):
            raise ValueError("prepare requires all fixed inputs")
        result = prepare(args.output, args.capture, args.native_binary, args.native_config, args.runtime_snapshot)
    else:
        result = run_case(args.output, args.run_case)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
