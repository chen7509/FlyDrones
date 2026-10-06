"""Truth-free journal fan-out; callbacks may consume partially and cannot roll back."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time

from tools.benchmark.disarmed_sensor_provenance import audit_event_records


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class ReadyShadowFanout:
    def __init__(self, output, readiness, shadow, *, clock=time.monotonic_ns, stream=None):
        self.output, self.readiness, self.shadow, self.clock = output, readiness, shadow, clock
        self.stream = stream if stream is not None else (output / "source-fanout.jsonl").open("x")
        self.lock = threading.RLock()
        self.delivery = threading.Lock()
        self.owner = None
        self.failure = self.failure_ns = None
        self.pending = None
        self.sequence = self.committed = self.skipped = 0
        self.last_sample, self.last_arrival = {}, {}
        self.last_recorded = self.high_water = 0
        self.last_disposition = None
        self.closed = False
        self.close_errors = []
        self.refusals = []

    def _now(self):
        now = self.clock()
        if type(now) is not int or not 0 < now < 2**63 or now < self.high_water:
            raise ValueError("invalid/regressed fan-out clock")
        self.high_water = now
        return now

    def _fail(self, exc):
        # Caller holds gate lock, which also serializes complete pre-step callbacks.
        if self.failure is None:
            self.failure = repr(exc)
            try:
                self.failure_ns = self._now()
            except Exception:
                self.failure_ns = None

    def _emit(self, event):
        encoded = json.dumps(event, allow_nan=False) + "\n"
        if self.stream.write(encoded) != len(encoded):
            raise OSError("short fan-out journal write")
        self.stream.flush()

    def _available(self):
        if self.failure or self.closed:
            raise ValueError(self.failure or "fan-out closed")
        now = self._now()
        if self.pending is not None and now - self.pending > 2_000_000_000:
            raise TimeoutError("fan-out per-source delivery deadline")
        return now

    def _file(self, relative):
        path = self.output / relative
        root = self.output.resolve()
        if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("fan-out payload path escapes source root")
        return path.read_bytes()

    def _validate(self, row, payload, now):
        if type(row.get("source_sequence")) is not int or row["source_sequence"] != self.sequence:
            raise ValueError("fan-out source sequence gap/duplicate/type")
        base = {k: v for k, v in row.items() if k != "source_sequence"}
        audit_event_records([base], required_kinds=[])
        kind = row["kind"]
        arrival, prepared = row["arrival_monotonic_ns"], row["recorded_monotonic_ns"]
        if not (self.last_arrival.get(kind, 0) < arrival <= row["writer_begin_monotonic_ns"] <= prepared <= now):
            raise ValueError("fan-out receipt clock")
        if row["writer_begin_monotonic_ns"] < self.last_recorded:
            raise ValueError("fan-out writer clock regressed")
        if "sample_ns" in row and row["sample_ns"] <= self.last_sample.get(kind, 0):
            raise ValueError("fan-out duplicate/regressed sample")
        if kind == "rgb":
            if type(payload) is not bytes or len(payload) != 57600:
                raise ValueError("fan-out RGB bytes")
            data = self._file("rgb-frames/" + str(row["sample_ns"]) + ".ppm")
            if data != b"P6\n160 120\n255\n" + payload:
                raise ValueError("fan-out RGB file not complete/equal")
        elif kind == "info":
            if type(payload) is not bytes or not payload or self._file(row["payload_path"]) != payload:
                raise ValueError("fan-out CameraInfo bytes")
            if hashlib.sha256(payload).hexdigest() != row["payload_sha256"]:
                raise ValueError("fan-out CameraInfo hash")
        elif payload is not None:
            raise ValueError("unexpected fan-out payload")
        return base

    def _source_identity(self, row, payload):
        record = dict(
            event="source_delivery",
            sequence_repr=repr(row.get("source_sequence")) if isinstance(row, dict) else None,
            dispositions=dict(shadow="not_attempted", readiness="not_attempted"),
        )
        try:
            record["source_sha256"] = digest(row)
        except Exception as exc:
            record["source_sha256"] = None
            record["identity_error"] = repr(exc)
        record["payload_sha256"] = hashlib.sha256(payload).hexdigest() if type(payload) is bytes else None
        return record

    def _retain_refusal(self, record):
        record.update(event="source_refusal", failure=self.failure, failure_latched_ns=self.failure_ns)
        self.refusals.append(copy.deepcopy(record))
        try:
            self._emit(record)
        except Exception as exc:
            self.close_errors.append(dict(operation="refusal_journal", reason=repr(exc)))

    def _after_shadow(self, row, payload):
        """Opt-in subclasses may commit causal evidence before readiness."""

    def on_record(self, row, payload):
        record = self._source_identity(row, payload)
        if not self.delivery.acquire(blocking=False):
            with self.lock:
                self._fail(ValueError("concurrent/reentrant fan-out writer"))
                self._retain_refusal(record)
            return
        try:
            with self.lock:
                if self.failure or self.closed:
                    self.skipped += 1
                    self._retain_refusal(record)
                    return
                now = self._available()
                ident = threading.get_ident()
                if self.owner is None:
                    self.owner = ident
                if self.owner != ident:
                    raise ValueError("fan-out writer thread changed")
                self._validate(row, payload, now)
                record.update(
                    source_sequence=self.sequence,
                    source_sha256=digest(row),
                    payload_sha256=hashlib.sha256(payload).hexdigest() if payload is not None else None,
                    begin_ns=now,
                    consumers={},
                )
                self._emit(dict(record, event="source_intent"))
                self.pending = now
            # Native transport owns its bounded channel, never the gate lock.
            independent = copy.deepcopy(row)
            record["dispositions"]["shadow"] = "attempted"
            self.shadow.on_record(independent, payload)
            with self.lock:
                try:
                    self._available()
                    if self.shadow.failure or digest(independent) != record["source_sha256"]:
                        raise ValueError("shadow failed or mutated source: " + str(self.shadow.failure))
                    self._after_shadow(independent, payload)
                    record["dispositions"]["shadow"] = "returned"
                    record["consumers"]["shadow"] = dict(start_ns=now, returned_ns=self._now())
                    # The readiness callback, checks, receipt and commit are one gate transaction.
                    # A native consumption cannot be rolled back if this second route fails.
                    independent = copy.deepcopy(row)
                    start = self._now()
                    record["dispositions"]["readiness"] = "attempted"
                    self.readiness.on_record(independent, payload)
                    if self.readiness.failure or digest(independent) != record["source_sha256"]:
                        raise ValueError("readiness failed or mutated source: " + str(self.readiness.failure))
                    self._available()
                    record["dispositions"]["readiness"] = "returned"
                    record["consumers"]["readiness"] = dict(start_ns=start, returned_ns=self._now())
                    record["end_ns"] = self._now()
                    self._emit(record)
                    self.last_disposition = copy.deepcopy(record)
                    self.sequence += 1
                    self.committed += 1
                    kind = row["kind"]
                    self.last_arrival[kind] = row["arrival_monotonic_ns"]
                    self.last_recorded = row["recorded_monotonic_ns"]
                    if "sample_ns" in row:
                        self.last_sample[kind] = row["sample_ns"]
                    self.pending = None
                except BaseException as exc:
                    self._fail(exc)
                    raise
        except BaseException as exc:
            with self.lock:
                self._fail(exc)
                record.update(failure=self.failure, failure_latched_ns=self.failure_ns)
                self.last_disposition = copy.deepcopy(record)
                try:
                    self._emit(record)
                except Exception as journal_exc:
                    self.close_errors.append(dict(operation="failure_journal", reason=repr(journal_exc)))
                self.pending = None
        finally:
            self.delivery.release()

    def proof(self):
        with self.lock:
            try:
                self._available()
                return self.readiness.proof()
            except Exception as exc:
                self._fail(exc)
                raise ValueError(self.failure) from exc

    def pre_step(self, action, health):
        """Stop callbacks after a latched refusal; do not claim to undo in-flight steps."""
        with self.lock:
            try:
                self._available()
                health()
                action()
                return True
            except Exception as exc:
                self._fail(exc)
                return False

    def finish(self):
        with self.lock:
            if self.closed:
                raise ValueError("fan-out already closed")
            self.closed = True
            if self.pending is not None:
                self._fail(ValueError("fan-out finish while delivery pending"))
            for name, op in (("flush", self.stream.flush), ("close", self.stream.close)):
                try:
                    op()
                except Exception as exc:
                    self.close_errors.append(dict(operation=name, reason=repr(exc)))
                    self._fail(exc)
            return dict(
                profile="ready-shadow-v1",
                committed=self.committed,
                skipped=self.skipped,
                failure=self.failure,
                failure_latched_ns=self.failure_ns,
                last_disposition=self.last_disposition,
                close_errors=self.close_errors,
                refusals=self.refusals,
                fusion_eligible=False,
                quality=None,
                reset_counter=None,
                stop_scope="subsequent gated pre-steps after failure latch; not retroactive cancellation",
            )
