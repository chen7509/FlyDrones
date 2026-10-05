"""Opt-in heartbeat observation journal, distinct from queued estimator delivery."""

from __future__ import annotations

import copy
import json
from collections import deque

from tools.benchmark.disarmed_sensor_provenance import validate_event
from tools.benchmark.ready_shadow_fanout import ReadyShadowFanout, digest


class _ReceiptReadiness:
    def __init__(self, lane, target):
        self.lane, self.target = lane, target

    @property
    def failure(self):
        return self.target.failure

    def on_record(self, row, payload):
        if row["kind"] != "heartbeat":
            return self.target.on_record(row, payload)
        original = {
            k: v for k, v in row.items() if k not in {"source_sequence", "writer_begin_monotonic_ns", "recorded_monotonic_ns"}
        }
        pending = self.lane.observations
        if not pending or digest(original) != pending[0]["source_sha256"]:
            raise ValueError("heartbeat reconciliation identity/order")
        item = pending[0]
        self.lane._heartbeat_emit(
            dict(
                event="heartbeat_reconciled",
                observation_sequence=item["observation_sequence"],
                source_sequence=row["source_sequence"],
                source_sha256=item["source_sha256"],
                reconciled_ns=self.lane._now(),
            )
        )
        pending.popleft()
        self.lane.reconciled += 1

    def proof(self):
        proof = self.target.proof()
        if proof is not None:
            proof["scope"] = (
                "sensor fan-out commit plus independent heartbeat write/flush; "
                "heartbeat reconciliation is separate; not fsync durability"
            )
        return proof


class JournaledHeartbeatFanout(ReadyShadowFanout):
    """One existing receiver + one existing source/native owner, sharing the gate lock.

    Journal I/O can block; this is not a hard real-time guarantee. A newer heartbeat
    does not refresh sensor/native progress or change the original two-second bounds.
    """

    def __init__(self, output, readiness, shadow, *, heartbeat_stream=None, **kwargs):
        self.observations = deque()
        self.observed = self.reconciled = 0
        self.latest_arrival = self.latest_sim = None
        self.heartbeat_failure = None
        self.heartbeat_errors = []
        self.heartbeat_attempt = None
        self.observation_readiness = readiness
        super().__init__(output, _ReceiptReadiness(self, readiness), shadow, **kwargs)
        try:
            self.heartbeat_stream = (
                heartbeat_stream
                if heartbeat_stream is not None
                else (output / "heartbeat-observations.jsonl").open("x", encoding="utf8")
            )
        except BaseException:
            self.stream.close()
            raise

    def _heartbeat_emit(self, row):
        encoded = json.dumps(row, allow_nan=False) + "\n"
        if self.heartbeat_stream.write(encoded) != len(encoded):
            raise OSError("short heartbeat journal write")
        self.heartbeat_stream.flush()

    def _available(self):
        now = super()._available()
        if self.shadow.failure or self.observation_readiness.failure:
            raise ValueError("downstream consumer failed: " + str(self.shadow.failure or self.observation_readiness.failure))
        if self.observations and now - self.observations[0]["arrival_monotonic_ns"] > 2_000_000_000:
            raise TimeoutError("heartbeat source reconciliation deadline")
        return now

    def _heartbeat_fail(self, exc):
        self._fail(exc)
        self.heartbeat_failure = self.heartbeat_failure or repr(exc)

    def observe_heartbeat(self, event):
        """Journal actual receiver event before queueing the identical raw event.

        All paths latch before releasing the shared gate; consumed observations
        cannot be rolled back if subsequent queue submission or delivery fails.
        """
        with self.lock:
            self.heartbeat_attempt = self._source_identity(event, None)
            try:
                now = self._available()
                original = copy.deepcopy(event)
                valid = validate_event(original)
                if original["kind"] != "heartbeat" or valid != original:
                    raise ValueError("heartbeat lane accepts only raw heartbeat events")
                for key in ["arrival_monotonic_ns", "observed_sim_ns", "system_id", "base_mode", "custom_mode"]:
                    if type(original[key]) is not int or not 0 <= original[key] < 2**63:
                        raise ValueError("invalid heartbeat integer")
                arrival, sim = original["arrival_monotonic_ns"], original["observed_sim_ns"]
                if (
                    not 0 < arrival <= now
                    or now - arrival > 2_000_000_000
                    or original["system_id"] != 9
                    or not 0 <= original["base_mode"] < 128
                    or not 0 <= original["custom_mode"] < 2**32
                    or (self.latest_arrival is not None and arrival <= self.latest_arrival)
                    or (self.latest_sim is not None and sim < self.latest_sim)
                    or len(self.observations) >= 32
                ):
                    raise ValueError("heartbeat identity/clock/capacity refusal")
                item = dict(
                    observation_sequence=self.observed,
                    source_sha256=digest(original),
                    arrival_monotonic_ns=arrival,
                    observed_ns=now,
                    original=original,
                )
                self._heartbeat_emit(dict(item, event="heartbeat_observed"))
                after_flush = self._available()
                if after_flush - arrival > 2_000_000_000:
                    raise TimeoutError("heartbeat arrival expired during journal flush")
                recorded = dict(original, writer_begin_monotonic_ns=now, recorded_monotonic_ns=now)
                self.observation_readiness.on_record(recorded, None)
                if self.observation_readiness.failure:
                    raise ValueError(self.observation_readiness.failure)
                self.latest_arrival, self.latest_sim = arrival, sim
                self.observations.append(item)
                self.observed += 1
                self.heartbeat_attempt = dict(item, event="heartbeat_committed")
            except BaseException as exc:
                self._heartbeat_fail(exc)
                self.heartbeat_attempt.update(failure=self.failure)
                raise ValueError(self.failure) from exc

    def submit_heartbeat(self, event, writer):
        try:
            self.observe_heartbeat(event)
            writer.submit(copy.deepcopy(event))
        except BaseException as exc:
            with self.lock:
                self._heartbeat_fail(exc)
            raise ValueError(self.failure) from exc

    def finish(self):
        with self.lock:
            if self.closed:
                raise ValueError("heartbeat fan-out already closed")
            if self.observations:
                self._heartbeat_fail(ValueError("unreconciled heartbeat observations at finish"))
            for name, op in [("flush", self.heartbeat_stream.flush), ("close", self.heartbeat_stream.close)]:
                try:
                    op()
                except BaseException as exc:
                    self.heartbeat_errors.append(dict(operation=name, reason=repr(exc)))
                    self._heartbeat_fail(exc)
            out = super().finish()
            out["profile"] = "ready-shadow-heartbeat-v1"
            out["heartbeat"] = dict(
                observed=self.observed,
                reconciled=self.reconciled,
                pending=list(self.observations),
                failure=self.heartbeat_failure,
                close_errors=self.heartbeat_errors,
                last_attempt=self.heartbeat_attempt,
                scope="independent receiver observation; not estimator acknowledgement",
            )
            return out
