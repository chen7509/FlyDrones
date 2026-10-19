"""Truth-free evidence gate for applying an estimator motion-intent latch."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from pathlib import Path

ESTIMATOR_FIELDS = {
    "kind",
    "native_sequence",
    "sample_ns",
    "acknowledged_ns",
    "internal_initialized",
    "has_moved_since_zupt",
    "reset_counter",
}
COMMAND_FIELDS = {
    "session_id",
    "clock_id",
    "command_sequence",
    "effective_sim_ns",
    "issued_monotonic_ns",
    "unarmed",
    "safety_authorized",
    "velocity_setpoint_frd_m_s",
    "yaw_rate_setpoint_rad_s",
    "source",
}
ACK_FIELDS = {
    "kind",
    "native_sequence",
    "sample_ns",
    "intent_sha256",
    "estimator_session_sha256",
    "clock_id_sha256",
    "command_sequence",
    "receive_ns",
    "start_ns",
    "end_ns",
    "acknowledged_ns",
    "internal_initialized",
    "has_moved_since_zupt",
    "motion_intent_applied",
    "try_zupt",
    "zupt_only_at_beginning",
    "reset_counter",
}


def _integer(value, name, *, minimum=0):
    if type(value) is not int or not minimum <= value < 2**63:
        raise ValueError("invalid " + name)
    return value


def _reset(value):
    if value is not None and (type(value) is not int or not 0 <= value < 2**31):
        raise ValueError("invalid reset counter")
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class MotionIntentGate:
    """Require a native movement latch before the first commanded-motion step."""

    def __init__(
        self,
        *,
        session_id,
        clock_id,
        output=None,
        stream=None,
        clock=time.monotonic_ns,
        native_adapter_integrated=False,
    ):
        if not isinstance(session_id, str) or not session_id.strip() or not isinstance(clock_id, str) or not clock_id.strip():
            raise ValueError("explicit session and clock identifiers required")
        if (output is None) == (stream is None):
            raise ValueError("provide exactly one journal destination")
        self.session_id, self.clock_id, self.clock = session_id, clock_id, clock
        if type(native_adapter_integrated) is not bool:
            raise ValueError("invalid native-adapter integration flag")
        self.native_adapter_integrated = native_adapter_integrated
        self._owns_stream = stream is None
        self.stream = Path(output, "motion-intent.jsonl").open("x", encoding="utf8") if stream is None else stream
        self.failure = None
        self.high_water_ns = 0
        self.estimator = None
        self.intent = None
        self.action = None
        self.ack = None
        self.closed = False

    def _now(self):
        now = _integer(self.clock(), "motion-intent clock", minimum=1)
        if now < self.high_water_ns:
            raise ValueError("regressed motion-intent clock")
        self.high_water_ns = now
        return now

    def _emit(self, event):
        encoded = json.dumps(event, sort_keys=True, allow_nan=False) + "\n"
        if self.stream.write(encoded) != len(encoded):
            raise OSError("short motion-intent journal write")
        self.stream.flush()

    def _available(self):
        if self.closed or self.failure:
            raise ValueError(self.failure or "motion-intent gate closed")
        return self._now()

    def _fail(self, exc):
        self.failure = self.failure or repr(exc)
        try:
            self._emit({"event": "motion_intent_refusal", "failure": self.failure, "truth_used": False})
        except Exception:
            pass

    def observe_estimator(self, row):
        try:
            now = self._available()
            if not isinstance(row, dict) or set(row) != ESTIMATOR_FIELDS:
                raise ValueError("invalid estimator-state schema")
            sequence = _integer(row["native_sequence"], "native sequence")
            sample = _integer(row["sample_ns"], "estimator sample", minimum=1)
            acknowledged = _integer(row["acknowledged_ns"], "estimator acknowledgement", minimum=1)
            reset = _reset(row["reset_counter"])
            if acknowledged > now or row["kind"] != "C" or type(row["internal_initialized"]) is not bool:
                raise ValueError("invalid estimator-state identity/clock")
            if not row["internal_initialized"] or type(row["has_moved_since_zupt"]) is not bool:
                raise ValueError("motion intent requires internal initialization")
            if self.estimator is not None:
                if sequence <= self.estimator["native_sequence"] or sample <= self.estimator["sample_ns"]:
                    raise ValueError("duplicate/regressed estimator state")
                if reset != self.estimator["reset_counter"]:
                    raise ValueError("estimator reset requires a new motion-intent session")
            self.estimator = copy.deepcopy(row)
            self._emit({"event": "estimator_state_observed", **row, "truth_used": False})
        except BaseException as exc:
            self._fail(exc)
            raise ValueError(self.failure) from exc

    def request(self, command):
        try:
            now = self._available()
            if self.estimator is None:
                raise ValueError("motion intent requires internal initialization")
            if self.intent is not None:
                raise ValueError("motion intent already exists")
            if not isinstance(command, dict) or set(command) != COMMAND_FIELDS:
                raise ValueError("invalid motion-intent command schema")
            if command["session_id"] != self.session_id or command["clock_id"] != self.clock_id:
                raise ValueError("motion-intent session/clock changed")
            sequence = _integer(command["command_sequence"], "command sequence")
            if sequence != 0:
                raise ValueError("first session command sequence must be zero")
            effective = _integer(command["effective_sim_ns"], "effective simulation time", minimum=1)
            issued = _integer(command["issued_monotonic_ns"], "command issue clock", minimum=1)
            if not issued <= now or now - issued > 2_000_000_000:
                raise ValueError("future/stale motion-intent command")
            if effective < self.estimator["sample_ns"]:
                raise ValueError("motion intent precedes initialized estimator sample")
            if command["unarmed"] is not True or command["safety_authorized"] is not True:
                raise ValueError("motion intent lacks unarmed safety authorization")
            vector = command["velocity_setpoint_frd_m_s"]
            yaw = command["yaw_rate_setpoint_rad_s"]
            if (
                not isinstance(vector, list)
                or len(vector) != 3
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in vector)
                or type(yaw) not in (int, float)
                or not math.isfinite(yaw)
                or math.sqrt(sum(float(value) ** 2 for value in vector) + float(yaw) ** 2) <= 0
            ):
                raise ValueError("motion intent must contain a finite nonzero setpoint")
            if command["source"] != "px4-safe-setpoint-supervisor":
                raise ValueError("untrusted motion-intent source")
            intent = copy.deepcopy(command)
            digest = _digest(intent)
            action = {
                "kind": "motion_intent",
                "sample_ns": effective,
                "source_arrival_ns": issued,
                "session_id": self.session_id,
                "clock_id": self.clock_id,
                "command_sequence": sequence,
                "intent_sha256": digest,
            }
            self.intent, self.action = intent, action
            self._emit({"event": "motion_intent_requested", "command": intent, "action": action, "truth_used": False})
            return copy.deepcopy(action)
        except BaseException as exc:
            self._fail(exc)
            raise ValueError(self.failure) from exc

    def acknowledge(self, row):
        try:
            now = self._available()
            if self.action is None or self.ack is not None:
                raise ValueError("no pending unique motion intent")
            if not isinstance(row, dict) or set(row) != ACK_FIELDS:
                raise ValueError("invalid native motion-intent acknowledgement schema")
            if row["kind"] != "M" or row["sample_ns"] != self.action["sample_ns"]:
                raise ValueError("native motion-intent identity mismatch")
            if row["intent_sha256"] != self.action["intent_sha256"]:
                raise ValueError("native motion-intent hash mismatch")
            expected_session = hashlib.sha256(self.session_id.encode()).hexdigest()
            expected_clock = hashlib.sha256(self.clock_id.encode()).hexdigest()
            if (
                row["estimator_session_sha256"] != expected_session
                or row["clock_id_sha256"] != expected_clock
                or row["command_sequence"] != self.action["command_sequence"]
            ):
                raise ValueError("native motion-intent session/clock mismatch")
            sequence = _integer(row["native_sequence"], "native sequence")
            clocks = [_integer(row[key], key, minimum=1) for key in ("receive_ns", "start_ns", "end_ns", "acknowledged_ns")]
            if sequence <= self.estimator["native_sequence"] or not (
                self.intent["issued_monotonic_ns"] <= clocks[0] <= clocks[1] <= clocks[2] <= clocks[3] <= now
            ):
                raise ValueError("native motion-intent sequence/clock mismatch")
            if clocks[3] - self.intent["issued_monotonic_ns"] > 2_000_000_000:
                raise ValueError("native motion-intent acknowledgement deadline")
            if _reset(row["reset_counter"]) != self.estimator["reset_counter"]:
                raise ValueError("native reset changed during motion intent")
            if any(
                row[key] is not True
                for key in (
                    "internal_initialized",
                    "has_moved_since_zupt",
                    "motion_intent_applied",
                    "try_zupt",
                    "zupt_only_at_beginning",
                )
            ):
                raise ValueError("native motion intent was not applied to initialized estimator")
            self.ack = copy.deepcopy(row)
            self._emit({"event": "motion_intent_applied", **row, "truth_used": False})
        except BaseException as exc:
            self._fail(exc)
            raise ValueError(self.failure) from exc

    def authorize_step(self, simulation_ns):
        try:
            self._available()
            simulation_ns = _integer(simulation_ns, "actuation simulation time")
            if self.action is None or simulation_ns < self.action["sample_ns"]:
                return False
            if self.ack is None:
                raise ValueError("actuation reached effective time before native motion-intent acknowledgement")
            return True
        except BaseException as exc:
            self._fail(exc)
            return False

    def finish(self):
        if self.closed:
            raise ValueError("motion-intent gate already closed")
        qualified = self.failure is None and self.intent is not None and self.ack is not None
        result = {
            "schema": "motion-intent-gate-v1",
            "session_id": self.session_id,
            "clock_id": self.clock_id,
            "intent": copy.deepcopy(self.intent),
            "action": copy.deepcopy(self.action),
            "ack": copy.deepcopy(self.ack),
            "failure": self.failure,
            "qualified": qualified,
            "truth_used": False,
            "native_adapter_integrated": self.native_adapter_integrated,
            "physical_validation": False,
            "fusion_eligible": False,
        }
        try:
            self._emit({"event": "motion_intent_finish", **result})
        finally:
            self.closed = True
            if self._owns_stream:
                self.stream.close()
        return result
