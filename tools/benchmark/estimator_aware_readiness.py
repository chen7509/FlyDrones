"""Truth-free OpenVINS internal-state evidence composed with source readiness."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import time
from pathlib import Path

COMMON_ACK_KEYS = {
    "sequence",
    "kind",
    "sample_ns",
    "receive_ns",
    "start_ns",
    "end_ns",
    "gray_first",
    "fusion_eligible",
    "quality",
    "reset_counter",
    "acknowledged_ns",
    "source_arrival_ns",
    "dispatch_ns",
}
CAMERA_ACK_KEYS = COMMON_ACK_KEYS | {
    "internal_initialized",
    "public_initialized",
    "initializer_time_s",
    "state_time_s",
    "last_regular_update_s",
    "zupt_flag_latched",
    "has_moved_since_zupt",
    "imu_state",
}
MAX_NS = 2**63 - 1
MAX_MAGNITUDE = 1e10
MAX_SOURCE_SIM_LEAD_NS = 1_000_000


def _integer(value, name, *, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_NS:
        raise ValueError("invalid " + name)
    return value


def _number(value, name):
    if type(value) is bool or not isinstance(value, (int, float)):
        raise ValueError("invalid " + name)
    result = float(value)
    if not math.isfinite(result) or abs(result) > MAX_MAGNITUDE:
        raise ValueError("invalid " + name)
    return result


def _seconds_to_ns(value, name):
    scaled = _number(value, name) * 1e9
    rounded = round(scaled)
    if not 0 <= rounded <= MAX_NS or abs(scaled - rounded) > 1.0:
        raise ValueError("invalid " + name)
    return rounded


def _validate_common_ack(value, now):
    if type(value) is not dict or value.get("kind") not in {"I", "C"}:
        raise ValueError("invalid native acknowledgement")
    expected = CAMERA_ACK_KEYS if value["kind"] == "C" else COMMON_ACK_KEYS
    if set(value) != expected:
        raise ValueError("native acknowledgement schema")
    sequence = _integer(value["sequence"], "native sequence")
    sample = _integer(value["sample_ns"], "native sample", minimum=1)
    source = _integer(value["source_arrival_ns"], "native source arrival", minimum=1)
    dispatch = _integer(value["dispatch_ns"], "native dispatch", minimum=1)
    receive = _integer(value["receive_ns"], "native receive", minimum=1)
    start = _integer(value["start_ns"], "native start", minimum=1)
    end = _integer(value["end_ns"], "native end", minimum=1)
    acknowledged = _integer(value["acknowledged_ns"], "native acknowledgement clock", minimum=1)
    if not source <= dispatch <= receive <= start <= end <= acknowledged <= now:
        raise ValueError("native acknowledgement clock order")
    if type(value["gray_first"]) is not int or not -1 <= value["gray_first"] <= 255:
        raise ValueError("invalid native gray value")
    if value["fusion_eligible"] is not False or value["quality"] is not None or value["reset_counter"] is not None:
        raise ValueError("unexpected native health claim")
    return sequence, sample, acknowledged


def _validate_camera_ack(value, now):
    sequence, sample, acknowledged = _validate_common_ack(value, now)
    for name in ("internal_initialized", "public_initialized", "zupt_flag_latched", "has_moved_since_zupt"):
        if type(value[name]) is not bool:
            raise ValueError("invalid native " + name)
    if value["public_initialized"] and not value["internal_initialized"]:
        raise ValueError("public initialization without internal state")
    initializer = _number(value["initializer_time_s"], "initializer time")
    regular = _number(value["last_regular_update_s"], "regular update time")
    state_time = _number(value["state_time_s"], "state time")
    state = value["imu_state"]
    if value["internal_initialized"]:
        if _seconds_to_ns(state_time, "state time") != sample:
            raise ValueError("native state/sample mismatch")
        if initializer == -1 or _seconds_to_ns(initializer, "initializer time") > sample:
            raise ValueError("invalid initialized time")
        if value["public_initialized"] and regular == -1:
            raise ValueError("public state missing regular update")
        if regular != -1 and _seconds_to_ns(regular, "regular update time") > sample:
            raise ValueError("regular update after sample")
        if type(state) is not list or len(state) != 16:
            raise ValueError("invalid native IMU state")
        numbers = [_number(item, "native IMU state") for item in state]
        quaternion_norm = math.sqrt(sum(item * item for item in numbers[:4]))
        if abs(quaternion_norm - 1.0) > 1e-5:
            raise ValueError("invalid native quaternion")
    elif state is not None or state_time != -1 or initializer != -1 or regular != -1:
        raise ValueError("uninitialized acknowledgement has state")
    return sequence, sample, acknowledged


class EstimatorAwareReadiness:
    """Require a fresh internal camera state in addition to existing source proof."""

    def __init__(self, output, source_readiness, *, clock=time.monotonic_ns, stream=None):
        self.output = Path(output)
        self.source_readiness = source_readiness
        self.clock = clock
        self.lock = threading.Lock()
        self.stream = stream if stream is not None else (self.output / "estimator-readiness.jsonl").open("x")
        self._failure = None
        self.first_internal = None
        self.latest_internal = None
        self.last_sequence = None
        self.last_sample = None
        self.clock_high_water_ns = None
        self.closed = False
        self.close_errors = []

    @property
    def failure(self):
        return self._failure or self.source_readiness.failure

    def _now(self):
        now = _integer(self.clock(), "estimator readiness clock", minimum=1)
        if self.clock_high_water_ns is not None and now < self.clock_high_water_ns:
            raise ValueError("regressed estimator readiness clock")
        self.clock_high_water_ns = now
        return now

    def _fail(self, exc):
        self._failure = self._failure or repr(exc)

    def _available(self):
        if self.closed or self.failure:
            raise ValueError(self.failure or "estimator readiness closed")
        return self._now()

    def _emit(self, value):
        encoded = json.dumps(value, allow_nan=False, sort_keys=True) + "\n"
        if self.stream.write(encoded) != len(encoded):
            raise OSError("short estimator readiness write")
        self.stream.flush()

    def on_record(self, row, payload):
        return self.source_readiness.on_record(row, payload)

    def observe_ack_batch(self, acknowledgements, source_row):
        with self.lock:
            try:
                now = self._available()
                if type(acknowledgements) is not list or len(acknowledgements) > 16:
                    raise ValueError("invalid native acknowledgement batch")
                if type(source_row) is not dict:
                    raise ValueError("invalid acknowledgement source")
                source_sequence = _integer(source_row.get("source_sequence"), "source sequence")
                source_sample = _integer(source_row.get("sample_ns"), "source sample", minimum=1)
                source_arrival = _integer(source_row.get("arrival_monotonic_ns"), "source arrival", minimum=1)
                observed_sim = _integer(source_row.get("observed_sim_ns"), "observed simulation time", minimum=1)
                source_age = source_row.get("sim_age_at_callback_ns")
                if type(source_age) is not int or not -MAX_NS <= source_age <= MAX_NS:
                    raise ValueError("invalid source simulation clock")
                if source_age != observed_sim - source_sample:
                    raise ValueError("inconsistent source simulation clock")
                if source_age < -MAX_SOURCE_SIM_LEAD_NS:
                    raise ValueError("source simulation clock lead exceeded")
                if source_arrival > now:
                    raise ValueError("future acknowledgement source")
                for value in acknowledgements:
                    sequence, sample, acknowledged = _validate_common_ack(value, now)
                    if value["kind"] != "C":
                        continue
                    sequence, sample, acknowledged = _validate_camera_ack(value, now)
                    if sample > source_sample or (
                        self.last_sequence is not None
                        and (sequence <= self.last_sequence or sample <= self.last_sample)
                    ):
                        raise ValueError("duplicate/regressed estimator readiness")
                    self.last_sequence, self.last_sample = sequence, sample
                    if not value["internal_initialized"]:
                        continue
                    if now - acknowledged > 2_000_000_000:
                        raise ValueError("stale estimator acknowledgement")
                    record = {
                        "event": "estimator_internal_ready",
                        "native_sequence": sequence,
                        "sample_ns": sample,
                        "acknowledged_monotonic_ns": acknowledged,
                        "journal_ack_monotonic_ns": now,
                        "source_sequence": source_sequence,
                        "source_sha256": hashlib.sha256(
                            json.dumps(source_row, allow_nan=False, sort_keys=True).encode()
                        ).hexdigest(),
                        "source_arrival_monotonic_ns": source_arrival,
                        "observed_sim_ns": observed_sim,
                        "internal_initialized": True,
                        "public_initialized": value["public_initialized"],
                        "truth_used": False,
                        "fusion_eligible": False,
                    }
                    self._emit(record)
                    if self.first_internal is None:
                        self.first_internal = copy.deepcopy(record)
                    self.latest_internal = copy.deepcopy(record)
            except BaseException as exc:
                self._fail(exc)
                raise ValueError(self.failure) from exc

    def proof(self):
        with self.lock:
            try:
                now = self._available()
                if self.latest_internal is None:
                    return None
                if now - self.latest_internal["acknowledged_monotonic_ns"] > 2_000_000_000:
                    raise ValueError("stale estimator readiness")
                source = self.source_readiness.proof()
                if source is None:
                    return None
                return {
                    **source,
                    "estimator_internal": copy.deepcopy(self.latest_internal),
                    "first_estimator_internal": copy.deepcopy(self.first_internal),
                    "truth_used": False,
                    "scope": source["scope"] + "; causal OpenVINS internal camera acknowledgement; not accuracy or health",
                }
            except BaseException as exc:
                self._fail(exc)
                raise ValueError(self.failure) from exc

    def snapshot(self):
        with self.lock:
            return {
                "source": self.source_readiness.snapshot(),
                "first_internal": copy.deepcopy(self.first_internal),
                "latest_internal": copy.deepcopy(self.latest_internal),
                "failure": self.failure,
                "clock_high_water_ns": self.clock_high_water_ns,
                "truth_used": False,
                "fusion_eligible": False,
            }

    def finish(self):
        with self.lock:
            if self.closed:
                raise ValueError("estimator readiness already closed")
            for operation, callback in (("flush", self.stream.flush), ("close", self.stream.close)):
                try:
                    callback()
                except BaseException as exc:
                    self.close_errors.append({"operation": operation, "reason": repr(exc)})
                    self._fail(exc)
            self.closed = True
            return {
                "source": self.source_readiness.snapshot(),
                "first_internal": copy.deepcopy(self.first_internal),
                "latest_internal": copy.deepcopy(self.latest_internal),
                "failure": self.failure,
                "clock_high_water_ns": self.clock_high_water_ns,
                "close_errors": copy.deepcopy(self.close_errors),
                "truth_used": False,
                "fusion_eligible": False,
            }


from tools.benchmark.journaled_heartbeat_lane import JournaledHeartbeatFanout  # noqa: E402


class EstimatorJournaledHeartbeatFanout(JournaledHeartbeatFanout):
    """Journal heartbeat plus causal internal-state proof before source commit."""

    def _after_shadow(self, row, payload):
        del payload
        if row.get("kind") == "heartbeat":
            if self.shadow.delivery_acks:
                raise ValueError("heartbeat cannot attribute native acknowledgements")
            return
        self.observation_readiness.observe_ack_batch(self.shadow.delivery_acks, row)

    def finish(self):
        result = super().finish()
        result["profile"] = "ready-shadow-heartbeat-estimator-v1"
        return result
