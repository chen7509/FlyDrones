"""Pure prepare-only contracts for a future disarmed PX4 receiver study.

This module deliberately has no socket or process surface.  It mirrors the
relevant pinned PX4 time-sync rules and models parameter transactions so they
can be fault tested before the first network/PX4 mutation stage.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class ReceiverProfile:
    target_system: int
    target_component: int
    sender_system: int
    sender_component: int
    px4_udp_port: int
    companion_udp_port: int
    px4_instance: int
    model: str
    network_enabled: bool = False


def frozen_receiver_profile() -> ReceiverProfile:
    """Return the endpoint observed in the retained instance-eight PX4 logs."""

    return ReceiverProfile(
        target_system=9,
        target_component=1,
        sender_system=254,
        sender_component=191,
        px4_udp_port=14588,
        companion_udp_port=14548,
        px4_instance=8,
        model="gz_x500_benchmark",
    )


@dataclass(frozen=True)
class TimesyncExchange:
    px4_request_ns: int
    remote_response_ns: int
    px4_receive_ns: int


class RemoteMonotonicClock:
    """One slope-one simulation-to-remote clock shared with ODOMETRY.

    Repeated or regressed simulation time latches the session.  A caller must
    replace the clock session after a pause, jump or process restart.
    """

    def __init__(self, session_id: str, *, sim_origin_ns: int, remote_origin_ns: int):
        self._configure(session_id, sim_origin_ns, remote_origin_ns)

    @staticmethod
    def _valid_ns(value: int) -> bool:
        return not isinstance(value, bool) and isinstance(value, int) and value >= 0

    def _configure(self, session_id: str, sim_origin_ns: int, remote_origin_ns: int) -> None:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("invalid clock session")
        if not self._valid_ns(sim_origin_ns) or not self._valid_ns(remote_origin_ns):
            raise ValueError("invalid clock origin")
        self.session_id = session_id
        self.sim_origin_ns = sim_origin_ns
        self.remote_origin_ns = remote_origin_ns
        self._last_sim_ns: dict[str, int] = {}
        self._fault: str | None = None

    def replace_session(self, session_id: str, *, sim_origin_ns: int, remote_origin_ns: int) -> None:
        if session_id == self.session_id:
            raise ValueError("clock session replacement must change identity")
        self._configure(session_id, sim_origin_ns, remote_origin_ns)

    def _map(self, sim_ns: int, lane: str) -> int:
        if self._fault is not None:
            raise ValueError("clock session replacement required: " + self._fault)
        if not self._valid_ns(sim_ns) or sim_ns < self.sim_origin_ns:
            self._fault = "simulation_time_invalid"
            raise ValueError("clock simulation time invalid")
        if lane in self._last_sim_ns and sim_ns <= self._last_sim_ns[lane]:
            self._fault = "simulation_time_not_strictly_monotonic"
            raise ValueError("clock simulation time paused or regressed")
        self._last_sim_ns[lane] = sim_ns
        return self.remote_origin_ns + sim_ns - self.sim_origin_ns

    def map_odometry_sample(self, sample_sim_ns: int) -> int:
        return self._map(sample_sim_ns, "odometry")

    def respond_to_px4_request(self, *, tc1_ns: int, ts1_ns: int, observed_sim_ns: int) -> dict:
        if tc1_ns != 0 or isinstance(ts1_ns, bool) or not isinstance(ts1_ns, int) or ts1_ns <= 0:
            raise ValueError("invalid PX4 TIMESYNC request")
        return {
            "tc1_ns": self._map(observed_sim_ns, "timesync"),
            "ts1_ns": ts1_ns,
            "clock_session_id": self.session_id,
        }


class BoundedTimesyncVerifier:
    """Mirror the pinned PX4 double-exponential TIMESYNC acceptance filter.

    The verifier consumes a complete request/response/receive triple.  It does
    not claim that a future packet was delivered; Task 5 must compare this
    prediction with the retained PX4 ``timesync_status`` stream.
    """

    CONVERGENCE_WINDOW = 500
    MAX_RTT_NS = 10_000_000
    MAX_DEVIATION_NS = 100_000_000
    MAX_CONSECUTIVE_HIGH_DEVIATION = 10
    ALPHA_INITIAL = 0.05
    BETA_INITIAL = 0.05
    ALPHA_FINAL = 0.003
    BETA_FINAL = 0.003

    def __init__(self, session_id: str):
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("invalid clock session")
        self.session_id = session_id
        self._last_px4_receive_ns: int | None = None
        self._last_remote_response_ns: int | None = None
        self._session_fault: str | None = None
        self._reset_filter()

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def converged(self) -> bool:
        return self._sequence >= self.CONVERGENCE_WINDOW

    @property
    def offset_ns(self) -> int:
        return int(self._offset_us * 1_000.0)

    def _reset_filter(self) -> None:
        self._sequence = 0
        self._offset_us = 0.0
        self._skew_us = 0.0
        self._alpha = self.ALPHA_INITIAL
        self._beta = self.BETA_INITIAL
        self._high_deviation_count = 0
        self._high_rtt_count = 0

    def replace_session(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id or session_id == self.session_id:
            raise ValueError("clock session must change")
        self.session_id = session_id
        self._last_px4_receive_ns = None
        self._last_remote_response_ns = None
        self._session_fault = None
        self._reset_filter()

    def _validate_exchange(self, exchange: TimesyncExchange) -> None:
        if self._session_fault is not None:
            raise ValueError("clock session replacement required: " + self._session_fault)
        values = (exchange.px4_request_ns, exchange.remote_response_ns, exchange.px4_receive_ns)
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
            raise ValueError("invalid clock sample")
        if exchange.px4_receive_ns < exchange.px4_request_ns:
            raise ValueError("negative round trip")
        if self._last_px4_receive_ns is not None and exchange.px4_receive_ns <= self._last_px4_receive_ns:
            raise ValueError("clock regression")
        if self._last_remote_response_ns is not None and exchange.remote_response_ns <= self._last_remote_response_ns:
            raise ValueError("clock regression")
        self._last_px4_receive_ns = exchange.px4_receive_ns
        self._last_remote_response_ns = exchange.remote_response_ns

    def observe(self, exchange: TimesyncExchange) -> dict:
        self._validate_exchange(exchange)
        rtt_ns = exchange.px4_receive_ns - exchange.px4_request_ns
        numerator_us = (
            exchange.px4_request_ns // 1_000
            + exchange.px4_receive_ns // 1_000
            - 2 * (exchange.remote_response_ns // 1_000)
        )
        observed_offset_us = int(numerator_us / 2)
        deviation_ns = abs(int(self._offset_us) - observed_offset_us) * 1_000
        reset = False
        accepted = False
        reason = None

        if rtt_ns < self.MAX_RTT_NS:
            if self.converged and deviation_ns > self.MAX_DEVIATION_NS:
                self._high_deviation_count += 1
                reason = "high_deviation"
                if self._high_deviation_count > self.MAX_CONSECUTIVE_HIGH_DEVIATION:
                    self._reset_filter()
                    reset = True
                    reason = "clock_jump_reset"
                    self._session_fault = reason
            else:
                if not self.converged:
                    progress = self._sequence / self.CONVERGENCE_WINDOW
                    p = 1.0 - math.exp(0.5 * (1.0 - 1.0 / (1.0 - progress)))
                    self._alpha = p * self.ALPHA_FINAL + (1.0 - p) * self.ALPHA_INITIAL
                    self._beta = p * self.BETA_FINAL + (1.0 - p) * self.BETA_INITIAL
                else:
                    self._alpha = self.ALPHA_FINAL
                    self._beta = self.BETA_FINAL
                previous = self._offset_us
                if self._sequence == 0:
                    self._offset_us = float(observed_offset_us)
                else:
                    self._offset_us = self._alpha * observed_offset_us + (1.0 - self._alpha) * (
                        self._offset_us + self._skew_us
                    )
                    self._skew_us = self._beta * (self._offset_us - previous) + (1.0 - self._beta) * self._skew_us
                self._sequence += 1
                self._high_deviation_count = 0
                self._high_rtt_count = 0
                accepted = True
        else:
            self._high_rtt_count += 1
            reason = "high_rtt"

        return {
            "accepted": accepted,
            "reason": reason,
            "reset": reset,
            "sequence": self._sequence,
            "converged": self.converged,
            "offset_ns": self.offset_ns,
            "round_trip_ns": rtt_ns,
            "session_id": self.session_id,
            "requires_session_replacement": self._session_fault is not None,
        }


_REQUIRED_PARAMETERS = (
    "EKF2_EV_CTRL",
    "EKF2_EV_NOISE_MD",
    "EKF2_EV_QMIN",
    "EKF2_EV_DELAY",
    "EKF2_EV_POS_X",
    "EKF2_EV_POS_Y",
    "EKF2_EV_POS_Z",
    "EKF2_IMU_POS_X",
    "EKF2_IMU_POS_Y",
    "EKF2_IMU_POS_Z",
    "EKF2_HGT_REF",
    "EKF2_GPS_CTRL",
    "EKF2_OF_CTRL",
    "EKF2_BARO_CTRL",
    "EKF2_RNG_CTRL",
    "EKF2_MAG_TYPE",
    "EKF2_EVA_NOISE",
    "EKF2_EVP_GATE",
    "EKF2_EVP_NOISE",
    "EKF2_EVV_GATE",
    "EKF2_EVV_NOISE",
)


def required_parameter_names() -> tuple[str, ...]:
    return _REQUIRED_PARAMETERS


def receiver_only_parameter_profile() -> dict[str, int]:
    """The only Task-5 mutation predeclared by Task 4."""

    return {"EKF2_EV_CTRL": 0}


class ParameterTransport(Protocol):
    def read(self, name: str) -> list[int | float]: ...

    def write(self, name: str, value: int | float) -> bool: ...


class ParameterTransaction:
    """Fail-closed apply/verify/restore model for a later live transport."""

    def __init__(self, transport: ParameterTransport):
        self._transport = transport

    def _read_one(self, name: str) -> int | float:
        values = self._transport.read(name)
        if len(values) != 1:
            kind = "missing" if not values else "ambiguous"
            raise ValueError(f"{kind} parameter {name}")
        value = values[0]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"invalid parameter {name}")
        return value

    def snapshot(self) -> dict[str, int | float]:
        return {name: self._read_one(name) for name in _REQUIRED_PARAMETERS}

    @staticmethod
    def _equal(left: int | float, right: int | float) -> bool:
        return type(left) is type(right) and left == right

    def apply_verify_restore(self, desired: dict[str, int | float]) -> dict:
        unknown = sorted(set(desired) - set(_REQUIRED_PARAMETERS))
        if unknown:
            raise ValueError("unknown parameters: " + ",".join(unknown))
        if desired.get("EKF2_EV_CTRL") != 0:
            raise ValueError("receiver-only study requires EKF2_EV_CTRL=0")
        baseline = self.snapshot()
        changed: list[str] = []
        events: list[dict] = []
        primary_failure: str | None = None

        for name, value in desired.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"invalid desired parameter {name}")
            if self._equal(baseline[name], value):
                events.append({"phase": "apply", "parameter": name, "status": "unchanged"})
                continue
            try:
                acknowledged = self._transport.write(name, value)
            except Exception as exc:
                primary_failure = f"write_exception:{name}:{type(exc).__name__}"
                events.append({"phase": "apply", "parameter": name, "status": "write_exception"})
                break
            if not acknowledged:
                primary_failure = "write_failed:" + name
                events.append({"phase": "apply", "parameter": name, "status": "write_failed"})
                break
            changed.append(name)
            try:
                observed = self._read_one(name)
            except Exception as exc:
                primary_failure = f"verify_read_failed:{name}:{type(exc).__name__}"
                events.append({"phase": "apply", "parameter": name, "status": "verify_read_failed"})
                break
            if not self._equal(observed, value):
                primary_failure = "verify_failed:" + name
                events.append({"phase": "apply", "parameter": name, "status": "verify_failed"})
                break
            events.append({"phase": "apply", "parameter": name, "status": "verified"})

        rollback_failures: list[str] = []
        for name in reversed(changed):
            expected = baseline[name]
            try:
                acknowledged = self._transport.write(name, expected)
            except Exception as exc:
                rollback_failures.append(f"restore_write_exception:{name}:{type(exc).__name__}")
                events.append({"phase": "restore", "parameter": name, "status": "write_exception"})
                continue
            if not acknowledged:
                rollback_failures.append("restore_write_failed:" + name)
                events.append({"phase": "restore", "parameter": name, "status": "write_failed"})
                continue
            try:
                observed = self._read_one(name)
            except Exception as exc:  # the concrete failure is retained below
                rollback_failures.append(f"restore_read_failed:{name}:{type(exc).__name__}")
                events.append({"phase": "restore", "parameter": name, "status": "read_failed"})
                continue
            if not self._equal(observed, expected):
                rollback_failures.append("restore_verify_failed:" + name)
                events.append({"phase": "restore", "parameter": name, "status": "verify_failed"})
            else:
                events.append({"phase": "restore", "parameter": name, "status": "verified"})

        return {
            "baseline": baseline,
            "desired": dict(desired),
            "events": events,
            "primary_failure": primary_failure,
            "rollback_attempted": True,
            "rollback_failures": rollback_failures,
            "qualified": primary_failure is None and not rollback_failures,
            "network_parameter_access": False,
        }


def ulog_acceptance_profile() -> dict:
    return {
        "schema": "openvins-ekf2-receiver-only-ulog-profile-v1",
        "required_topics": [
            "vehicle_visual_odometry",
            "timesync_status",
            "vehicle_status",
            "estimator_status",
            "estimator_status_flags",
            "estimator_aid_src_ev_pos",
            "estimator_aid_src_ev_vel",
            "estimator_aid_src_ev_hgt",
        ],
        "require_unarmed": True,
        "require_ev_fusion_false": True,
        "require_arrival_and_sample_time": True,
        "require_parameter_restore": True,
        "network_odometry": False,
        "ekf2_fusion": False,
    }


def preflight_declaration() -> dict:
    return {
        "schema": "openvins-ekf2-disarmed-preflight-v1",
        "endpoint": asdict(frozen_receiver_profile()),
        "required_parameters": list(required_parameter_names()),
        "receiver_only_parameters": receiver_only_parameter_profile(),
        "timesync": {
            "convergence_samples": BoundedTimesyncVerifier.CONVERGENCE_WINDOW,
            "max_round_trip_ns_exclusive": BoundedTimesyncVerifier.MAX_RTT_NS,
            "max_deviation_ns": BoundedTimesyncVerifier.MAX_DEVIATION_NS,
            "reset_after_consecutive_high_deviation": BoundedTimesyncVerifier.MAX_CONSECUTIVE_HIGH_DEVIATION + 1,
            "clock_mapping": "remote_ns=remote_origin_ns+(sim_ns-sim_origin_ns)",
            "sample_and_timesync_clock_shared": True,
            "arrival_time_fallback_allowed": False,
            "session_replacement_on_pause_jump_restart": True,
        },
        "ulog": ulog_acceptance_profile(),
        "network_odometry": False,
        "px4_parameter_access": False,
        "physical_destination_present": False,
        "ekf2_fusion": False,
        "arming": False,
    }


_RESOURCE_SELECTORS = {
    "px4_binary": ("runtime-root:px4", "/build/px4_sitl_default/bin/px4"),
    "rootfs_environment": ("runtime:px4-startup", "/build/px4_sitl_default/rootfs/gz_env.sh"),
    "startup_script": ("runtime:px4-startup", "/build/px4_sitl_default/etc/init.d-posix/rcS"),
    "vehicle_model": ("declared:resources", "/assets/gazebo/models/x500_benchmark/model.sdf"),
    "world_sdf": ("generated:world.sdf", "/world.sdf"),
}


def _resource_record(files: list[dict], name: str, role: str, suffix: str) -> dict:
    matches = [
        record
        for record in files
        if record.get("role") == role and str(record.get("requested", "")).replace("\\", "/").endswith(suffix)
    ]
    if len(matches) != 1:
        raise ValueError(f"{name} resource count {len(matches)}")
    record = matches[0]
    digest = record.get("sha256")
    size = record.get("bytes")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
        raise ValueError(f"invalid {name} sha256")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError(f"invalid {name} size")
    return {
        "role": role,
        "requested": record["requested"],
        "resolved": record.get("resolved"),
        "bytes": size,
        "sha256": digest.lower(),
    }


def build_preflight_evidence(runtime_binding: dict, parameter_baseline: dict) -> dict:
    """Bind a retained runtime snapshot and ULog parameter baseline.

    This is a prepare-only operation: the records are inspected in memory and
    no parameter transport or MAVLink destination is constructed.
    """

    if runtime_binding.get("schema") != "declared-files-v1" or not isinstance(runtime_binding.get("files"), list):
        raise ValueError("invalid runtime binding")
    if parameter_baseline.get("schema") != "px4-ulog-parameter-baseline-v1":
        raise ValueError("invalid parameter baseline")
    parameters = parameter_baseline.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("invalid parameters")
    for name in ("MAV_SYS_ID", *_REQUIRED_PARAMETERS):
        if name not in parameters:
            raise ValueError("missing parameter " + name)
        value = parameters[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError("invalid parameter " + name)
    endpoint = frozen_receiver_profile()
    if parameters["MAV_SYS_ID"] != endpoint.target_system:
        raise ValueError("MAV_SYS_ID does not match frozen endpoint")
    ev_reference = tuple(parameters[f"EKF2_EV_POS_{axis}"] for axis in "XYZ")
    imu_reference = tuple(parameters[f"EKF2_IMU_POS_{axis}"] for axis in "XYZ")
    if ev_reference != imu_reference:
        raise ValueError("EV and IMU reference points differ")
    ulog = parameter_baseline.get("source_ulog")
    if not isinstance(ulog, dict):
        raise ValueError("missing source ULog")
    if (
        not isinstance(ulog.get("path"), str)
        or isinstance(ulog.get("bytes"), bool)
        or not isinstance(ulog.get("bytes"), int)
        or ulog["bytes"] <= 0
        or not isinstance(ulog.get("sha256"), str)
        or len(ulog["sha256"]) != 64
    ):
        raise ValueError("invalid source ULog")

    resources = {
        name: _resource_record(runtime_binding["files"], name, role, suffix)
        for name, (role, suffix) in _RESOURCE_SELECTORS.items()
    }
    declaration = preflight_declaration()
    return {
        **declaration,
        "schema": "openvins-ekf2-disarmed-preflight-evidence-v1",
        "baseline": {name: parameters[name] for name in ("MAV_SYS_ID", *_REQUIRED_PARAMETERS)},
        "source_ulog": dict(ulog),
        "resources": resources,
        "ev_reference_body_frd_m": list(ev_reference),
        "imu_reference_body_frd_m": list(imu_reference),
        "ev_and_imu_reference_equal": True,
        "runtime_binding_schema": runtime_binding["schema"],
        "runtime_closure_qualified": False,
    }
