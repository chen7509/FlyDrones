"""File-only composition of actual OpenVINS native acknowledgements.

This adapter deliberately exposes no transport API.  It derives health through
the same composer that owns the estimator session, writes immutable JSONL
evidence, and never grants fusion eligibility.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from tools.benchmark.openvins_ekf2_integration import OfflineEkf2Composer
from tools.benchmark.openvins_health_contract import CovarianceProfile
from tools.benchmark.openvins_online_shadow import OnlineHealthEvidence, project_camera_health_row

DECLARATION_FIELDS = {
    "schema",
    "source_journal_sha256",
    "native_binary_sha256",
    "native_config_sha256",
    "runtime_snapshot_sha256",
    "estimator_session_id",
    "clock_session_id",
    "publisher_session_id",
    "health_profile",
    "sim_domain_qualified",
    "max_sample_age_ns",
    "expected_camera_rate_hz",
    "expected_propagated_rate_hz",
    "candidate_output",
    "fusion_rate_qualified",
}


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        raise ValueError(f"invalid {name}")
    return value


def _digest(value: object, name: str) -> str:
    digest = _identity(value, name)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"invalid {name}")
    return digest


def validate_declaration(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != DECLARATION_FIELDS:
        raise ValueError("invalid file-shadow declaration")
    result = copy.deepcopy(value)
    if (
        result["schema"] != "openvins-ekf2-file-shadow-declaration-v1"
        or result["health_profile"] != "px4-d6f12ad-gate-floor-v1"
        or result["sim_domain_qualified"] is not True
        or result["candidate_output"] != "ekf2-candidates.jsonl"
        or result["fusion_rate_qualified"] is not False
    ):
        raise ValueError("invalid file-shadow declaration profile")
    for name in (
        "source_journal_sha256",
        "native_binary_sha256",
        "native_config_sha256",
        "runtime_snapshot_sha256",
    ):
        _digest(result[name], name)
    for name in ("estimator_session_id", "clock_session_id", "publisher_session_id"):
        _identity(result[name], name)
    for name, expected in (("expected_camera_rate_hz", 10), ("expected_propagated_rate_hz", 50)):
        if type(result[name]) is not int or result[name] != expected:
            raise ValueError(f"invalid {name}")
    if type(result["max_sample_age_ns"]) is not int or not 0 < result["max_sample_age_ns"] <= 2_000_000_000:
        raise ValueError("invalid maximum sample age")
    return result


class FileOnlyEkf2ShadowEvidence(OnlineHealthEvidence):
    """Health-compatible hook used by the existing single-worker ShadowInput."""

    def __init__(self, output: Path, declaration: object):
        self.declaration = validate_declaration(declaration)
        self.output = Path(output)
        if not self.output.is_dir():
            raise ValueError("file-shadow output directory missing")
        encoded = json.dumps(self.declaration, sort_keys=True, separators=(",", ":")).encode()
        self.declaration_sha256 = hashlib.sha256(encoded).hexdigest()
        declaration_path = self.output / "ekf2-shadow-declaration.json"
        candidate_path = self.output / self.declaration["candidate_output"]
        if declaration_path.exists() or candidate_path.exists():
            raise FileExistsError("file-shadow evidence destination exists")
        declaration_path.write_text(json.dumps(self.declaration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        super().__init__(
            self.output,
            session_id=self.declaration["estimator_session_id"],
            profile=CovarianceProfile(sim_domain_qualified=True),
        )
        self.candidates = candidate_path.open("x", encoding="utf-8")
        self.composer: OfflineEkf2Composer | None = None
        self.sample_to_remote_offset_ns: int | None = None
        self.candidate_count = 0
        self.refusal_count = 0
        self.sample_times: list[int] = []

    @staticmethod
    def _healthy_source() -> dict:
        return {
            "source_healthy": True,
            "native_healthy": True,
            "source_failure": None,
            "native_failure": None,
        }

    def _ensure_composer(self, native_row: dict) -> OfflineEkf2Composer:
        if self.composer is None:
            self.sample_to_remote_offset_ns = 0
            self.composer = OfflineEkf2Composer(
                self.contract,
                clock_session_id=self.declaration["clock_session_id"],
                publisher_session_id=self.declaration["publisher_session_id"],
                sample_to_remote_offset_ns=0,
                max_age_ns=self.declaration["max_sample_age_ns"],
            )
        return self.composer

    def observe_camera(self, native_row, source_health=None):
        if self.closed:
            raise RuntimeError("file-shadow evidence already closed")
        projected = project_camera_health_row(native_row, session_id=self.contract.session_id)
        composer = self._ensure_composer(native_row)
        camera = dict(projected, imu_state16=copy.deepcopy(native_row["imu_state"]))
        clock = {
            "clock_session_id": self.declaration["clock_session_id"],
            "publisher_session_id": self.declaration["publisher_session_id"],
            "observed_remote_ns": native_row["sample_ns"]
            + native_row["acknowledged_ns"]
            - native_row["source_arrival_ns"],
        }
        result = composer.compose(camera, self._healthy_source() if source_health is None else source_health, clock)
        self.contract = composer.contract
        self.last = copy.deepcopy(result["health"])
        if result["status"] == "candidate":
            self.candidate_count += 1
            self.sample_times.append(native_row["sample_ns"])
        else:
            self.refusal_count += 1
        record = {
            "schema": "openvins-ekf2-file-shadow-record-v1",
            "declaration_sha256": self.declaration_sha256,
            "native_sequence": native_row["sequence"],
            "timing": {
                "capture_sample_ns": native_row["sample_ns"],
                "source_arrival_ns": native_row["source_arrival_ns"],
                "dispatch_ns": native_row["dispatch_ns"],
                "native_receive_ns": native_row["receive_ns"],
                "native_start_ns": native_row["start_ns"],
                "native_end_ns": native_row["end_ns"],
                "acknowledged_ns": native_row["acknowledged_ns"],
            },
            "composition": result,
            "fusion_eligible": False,
        }
        self.candidates.write(json.dumps(record, allow_nan=False, sort_keys=True) + "\n")
        self.candidates.flush()
        self._write(
            {
                "event": "camera_health_and_file_candidate",
                "native_sequence": native_row["sequence"],
                "sample_ns": native_row["sample_ns"],
                "projected": projected,
                "health": result["health"],
                "candidate_status": result["status"],
                "fusion_eligible": False,
            }
        )
        return copy.deepcopy(result["health"])

    def fail(self, reason):
        if self.closed:
            raise RuntimeError("file-shadow evidence already closed")
        if self.composer is None:
            health = self.contract.fail(reason)
        else:
            result = self.composer.fail(reason)
            health = result["health"]
            self.refusal_count += 1
        self.last = copy.deepcopy(health)
        self._write({"event": "health_failure", "reason": reason, "health": health, "fusion_eligible": False})
        return copy.deepcopy(health)

    def replace_session(self, new_session_id):
        if self.closed:
            raise RuntimeError("file-shadow evidence already closed")
        if self.composer is None:
            self.contract = self.contract.replace_session(new_session_id)
            transition = {
                "schema": "openvins-ekf2-estimator-transition-v1",
                "estimator_session_id": self.contract.session_id,
                "clock_session_id": self.declaration["clock_session_id"],
                "publisher_session_id": self.declaration["publisher_session_id"],
                "quality": 0,
                "reset_total": self.contract.reset_total,
                "reset_counter": self.contract.reset_total % 256,
                "covariance_profile": self.contract.profile.name,
                "fusion_eligible": False,
            }
        else:
            transition = self.composer.replace_estimator(new_session_id)
            self.contract = self.composer.contract
        self.session_count += 1
        self.last = copy.deepcopy(transition)
        self._write({"event": "session_replacement", "transition": transition, "fusion_eligible": False})
        return copy.deepcopy(transition)

    def _receiver_rate_qualified(self) -> bool:
        if len(self.sample_times) < 2 or len(set(self.sample_times)) != len(self.sample_times):
            return False
        expected = round(1e9 / self.declaration["expected_camera_rate_hz"])
        return all(b - a == expected for a, b in zip(self.sample_times, self.sample_times[1:], strict=True))

    def finish(self):
        if self.closed:
            raise RuntimeError("file-shadow evidence already closed")
        self.closed = True
        composer_result = self.composer.finish() if self.composer is not None else None
        self.candidates.close()
        self.records.close()
        result = {
            "schema": "openvins-ekf2-file-shadow-result-v1",
            "declaration_sha256": self.declaration_sha256,
            "session_id": self.contract.session_id,
            "session_count": self.session_count,
            "reset_total": self.contract.reset_total,
            "reset_counter": self.contract.reset_total % 256,
            "last_quality": self.last["quality"] if self.last is not None else 0,
            "candidate_count": self.candidate_count,
            "refusal_count": self.refusal_count,
            "unique_candidate_samples": len(set(self.sample_times)),
            "receiver_shadow_rate_qualified": self._receiver_rate_qualified(),
            "fusion_rate_qualified": False,
            "composer_result": composer_result,
            "network_odometry": False,
            "fusion_eligible": False,
        }
        if not all(math.isfinite(value) for value in (float(result["candidate_count"]), float(result["refusal_count"]))):
            raise ValueError("invalid file-shadow result")
        (self.output / "ekf2-shadow-result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        return result
