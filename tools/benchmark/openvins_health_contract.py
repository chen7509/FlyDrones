"""Fail-closed OpenVINS quality, reset, and covariance evidence contract.

This module is transport-neutral and never publishes ODOMETRY or grants
fusion.  Simulation-domain qualification is an explicit constructor input;
it cannot be inferred from a single camera sample.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

MAX_NS = 2**63 - 1
CAMERA_FIELDS = {
    "kind",
    "session_id",
    "sample_ns",
    "internal_initialized",
    "public_initialized",
    "state_time_s",
    "last_regular_update_s",
    "imu_covariance15",
}
SOURCE_HEALTH_FIELDS = {
    "source_healthy",
    "native_healthy",
    "source_failure",
    "native_failure",
}


def _session_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or any(character.isspace() for character in value):
        raise ValueError("invalid session identity")
    return value


def _strict_int(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_NS:
        raise ValueError(f"invalid {name}")
    return value


def _seconds_to_ns(value: object, name: str) -> int:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {name}")
    seconds = float(value)
    scaled = seconds * 1e9
    rounded = round(scaled)
    if not math.isfinite(seconds) or not 0 <= rounded <= MAX_NS or abs(scaled - rounded) > 1.0:
        raise ValueError(f"invalid {name}")
    return rounded


@dataclass(frozen=True)
class CovarianceProfile:
    """Pinned PX4 body-tangent profile with predeclared conservative floors."""

    sim_domain_qualified: bool = False
    name: str = "px4-d6f12ad-gate-floor-v1"
    position_screen_m: float = 0.25
    velocity_screen_m_s: float = 0.25
    attitude_screen_deg: float = 10.0

    def __post_init__(self) -> None:
        if type(self.sim_domain_qualified) is not bool or self.name != "px4-d6f12ad-gate-floor-v1":
            raise ValueError("invalid covariance profile")
        for value in (self.position_screen_m, self.velocity_screen_m_s, self.attitude_screen_deg):
            if type(value) is bool or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("invalid covariance profile screen")

    @property
    def position_variance_floor(self) -> float:
        return (self.position_screen_m / 3.0) ** 2

    @property
    def velocity_variance_floor(self) -> float:
        return (self.velocity_screen_m_s / 3.0) ** 2

    @property
    def attitude_variance_floor(self) -> float:
        return math.radians(self.attitude_screen_deg / 3.0) ** 2

    def bound(self, covariance: object) -> list[list[float]]:
        try:
            matrix = np.asarray(covariance, dtype=float)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("invalid covariance") from exc
        if matrix.shape != (15, 15) or not np.all(np.isfinite(matrix)):
            raise ValueError("invalid covariance")
        scale = max(1.0, float(np.max(np.abs(matrix))))
        if not np.allclose(matrix, matrix.T, rtol=0, atol=1e-10 * scale):
            raise ValueError("invalid covariance")
        symmetric = (matrix + matrix.T) * 0.5
        if float(np.linalg.eigvalsh(symmetric)[0]) < -1e-12 * scale:
            raise ValueError("invalid covariance")
        bounded = symmetric.copy()
        floors = (
            (range(0, 3), self.attitude_variance_floor),
            (range(3, 6), self.position_variance_floor),
            (range(6, 9), self.velocity_variance_floor),
        )
        for indices, floor in floors:
            for index in indices:
                bounded[index, index] = max(float(bounded[index, index]), floor)
        if float(np.linalg.eigvalsh(bounded)[0]) < -1e-12 * max(1.0, float(np.max(np.abs(bounded)))):
            raise ValueError("invalid bounded covariance")
        return bounded.tolist()


class OpenVinsHealthContract:
    """One native estimator session with explicit fail-closed transitions."""

    def __init__(
        self,
        session_id: str,
        *,
        reset_total: int = 0,
        profile: CovarianceProfile | None = None,
        _used_session_ids: frozenset[str] | None = None,
    ) -> None:
        self.session_id = _session_id(session_id)
        self.reset_total = _strict_int(reset_total, "reset total")
        self.profile = profile if profile is not None else CovarianceProfile()
        if not isinstance(self.profile, CovarianceProfile):
            raise ValueError("invalid covariance profile")
        prior = frozenset() if _used_session_ids is None else _used_session_ids
        if self.session_id in prior:
            raise ValueError("reused session identity")
        self._used_session_ids = prior | {self.session_id}
        self._last_sample_ns: int | None = None
        self._seen_public = False
        self._failure: str | None = None

    def _result(self, *, quality: int, reasons: list[str], bounded_covariance=None) -> dict:
        return {
            "schema": "openvins-health-evidence-v1",
            "session_id": self.session_id,
            "quality": quality,
            "quality_semantics": "mavlink-minimum-positive-not-a-percentage-score",
            "reset_total": self.reset_total,
            "reset_counter": self.reset_total % 256,
            "covariance_profile": self.profile.name,
            "covariance_sim_domain_qualified": self.profile.sim_domain_qualified,
            "bounded_covariance15": bounded_covariance,
            "reasons": list(reasons),
            "failed_latched": self._failure is not None,
            "fusion_eligible": False,
        }

    def fail(self, reason: str) -> dict:
        if not isinstance(reason, str) or not reason:
            raise ValueError("invalid failure reason")
        if self._failure is None:
            self._failure = reason
        return self._result(quality=-1, reasons=[self._failure])

    def replace_session(self, new_session_id: str) -> OpenVinsHealthContract:
        new_identity = _session_id(new_session_id)
        if new_identity in self._used_session_ids:
            raise ValueError("reused session identity")
        if self.reset_total == MAX_NS:
            raise ValueError("reset total overflow")
        return OpenVinsHealthContract(
            new_identity,
            reset_total=self.reset_total + 1,
            profile=self.profile,
            _used_session_ids=self._used_session_ids,
        )

    def accept_camera(self, row: object, source_health: object) -> dict:
        if self._failure is not None:
            return self._result(quality=-1, reasons=[self._failure])
        if not isinstance(source_health, dict) or set(source_health) != SOURCE_HEALTH_FIELDS:
            return self.fail("source_health_invalid")
        if type(source_health["source_healthy"]) is not bool or type(source_health["native_healthy"]) is not bool:
            return self.fail("source_health_invalid")
        for name in ("source_failure", "native_failure"):
            if source_health[name] is not None and not isinstance(source_health[name], str):
                return self.fail("source_health_invalid")
        if not source_health["source_healthy"] or source_health["source_failure"] is not None:
            return self.fail("source_failure")
        if not source_health["native_healthy"] or source_health["native_failure"] is not None:
            return self.fail("native_failure")
        if not isinstance(row, dict) or set(row) != CAMERA_FIELDS:
            return self.fail("camera_state_invalid")
        try:
            if row["kind"] != "C":
                raise ValueError
            if row["session_id"] != self.session_id:
                return self.fail("session_mismatch")
            sample_ns = _strict_int(row["sample_ns"], "sample_ns", minimum=1)
            if self._last_sample_ns is not None and sample_ns <= self._last_sample_ns:
                return self.fail("sample_time_regressed")
            internal, public = row["internal_initialized"], row["public_initialized"]
            if type(internal) is not bool or type(public) is not bool or (public and not internal):
                raise ValueError
            if self._seen_public and not public:
                return self.fail("public_state_reverted")
            if _seconds_to_ns(row["state_time_s"], "state time") != sample_ns:
                return self.fail("state_time_mismatch")
            regular_ns = _seconds_to_ns(row["last_regular_update_s"], "regular update")
            if regular_ns > sample_ns:
                return self.fail("regular_update_in_future")
        except (KeyError, TypeError, ValueError, OverflowError):
            return self.fail("camera_state_invalid")
        try:
            bounded = self.profile.bound(row["imu_covariance15"])
        except (TypeError, ValueError, OverflowError):
            return self.fail("covariance_invalid")
        self._last_sample_ns = sample_ns
        self._seen_public |= public
        reasons: list[str] = []
        if not public:
            reasons.append("public_unavailable")
        elif sample_ns - regular_ns > 200_000_000:
            reasons.append("regular_update_stale")
        if not self.profile.sim_domain_qualified:
            reasons.append("covariance_profile_unqualified")
        return self._result(quality=0 if reasons else 1, reasons=reasons, bounded_covariance=bounded)

