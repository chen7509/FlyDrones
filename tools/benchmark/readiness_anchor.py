"""Journal-acknowledged startup; no estimator or physical-state feedback."""

from __future__ import annotations

import copy
import json
import math
import threading
import time

from tools.benchmark.supported_excitation import MASSES, SupportedPolicy, supported_profile


def integer(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError("invalid readiness integer clock")
    return value


class JournaledReadiness:
    def __init__(self, *, clock=time.monotonic_ns):
        self.clock = clock
        self.lock = threading.Lock()
        self.records = {}
        self.failure = None

    def on_record(self, row, payload):
        if row["kind"] not in ("imu", "rgb", "info", "heartbeat"):
            return
        with self.lock:
            try:
                if self.failure:
                    raise ValueError(self.failure)
                now = integer(self.clock())
                arrival = integer(row["arrival_monotonic_ns"])
                prepared = integer(row["recorded_monotonic_ns"])
                if not arrival <= prepared <= now:
                    raise ValueError("future/reversed readiness receipt")
                if row["kind"] == "heartbeat" and (
                    type(row["system_id"]) is not int
                    or row["system_id"] != 9
                    or type(row["base_mode"]) is not int
                    or not 0 <= row["base_mode"] < 128
                ):
                    raise ValueError("invalid/armed heartbeat readiness")
                old = self.records.get(row["kind"])
                if old and arrival <= old["arrival_monotonic_ns"]:
                    raise ValueError("repeated/regressed readiness receipt")
                self.records[row["kind"]] = dict(copy.deepcopy(row), journal_ack_monotonic_ns=now)
            except Exception as exc:
                self.failure = self.failure or repr(exc)
                raise ValueError(self.failure) from exc

    def proof(self):
        with self.lock:
            if self.failure:
                raise ValueError(self.failure)
            now = integer(self.clock())
            if any(now < r["journal_ack_monotonic_ns"] for r in self.records.values()):
                self.failure = "regressed readiness clock"
                raise ValueError(self.failure)
            if len(self.records) != 4 or any(now - r["arrival_monotonic_ns"] > 2_000_000_000 for r in self.records.values()):
                return None
            return dict(
                checked_wall_ns=now, records=copy.deepcopy(self.records), scope="successful write and flush; not fsync durability"
            )

    def snapshot(self):
        with self.lock:
            return dict(records=copy.deepcopy(self.records), failure=self.failure)


def anchored_profile():
    p = supported_profile()
    for k in ("start_ns", "stop_ns", "expected_active_steps", "lift_start_s", "lift_end_s"):
        p.pop(k)
    p.update(
        name="supported-ready-v1",
        startup_deadline_ns=8_000_000_000,
        anchor_delay_ns=200_000_000,
        lift_duration_ns=2_000_000_000,
        lateral_start_after_anchor_ns=3_000_000_000,
        lateral_end_after_anchor_ns=4_600_000_000,
        total_duration_ns=25_000_000_000,
    )
    return p


def persist_anchor(output, row):
    with (output / "readiness-anchor.json").open("x") as stream:
        encoded = json.dumps(row, allow_nan=False, indent=2)
        if stream.write(encoded) != len(encoded):
            raise OSError("short anchor write")
        stream.flush()


class AnchoredPolicy(SupportedPolicy):
    def __init__(self, readiness, persist):
        super().__init__()
        self.readiness = readiness
        self.persist = persist
        self.anchor_ns = None

    def step(self, ns, dt_ns, *, unarmed_wall_ns, wall_ns):
        self._available()
        try:
            integer(ns)
            integer(dt_ns)
            if (
                dt_ns != 1_000_000
                or ns > 25_000_000_000
                or (self.last_ns is None and ns != 1_000_000)
                or (self.last_ns is not None and ns - self.last_ns != 1_000_000)
            ):
                raise ValueError("invalid anchored simulation sequence")
            self.last_ns = ns
            proof = self.readiness()
            if self.anchor_ns is None:
                if ns >= 8_000_000_000:
                    raise ValueError("readiness startup deadline")
                if proof is None:
                    return [0.0, 0.0, 0.0]
                anchor = ns + 200_000_000
                self.persist(
                    dict(
                        anchor_ns=anchor,
                        selected_sim_ns=ns,
                        proof=proof,
                        profile=anchored_profile(),
                        eligible_for_px4_fusion=False,
                    )
                )
                self.anchor_ns = anchor
            elif proof is None:
                raise ValueError("readiness lost after anchor")
            rel = ns - self.anchor_ns
            if rel < 0:
                return [0.0, 0.0, 0.0]
            lateral = 0.0
            if 3_000_000_000 <= rel < 4_600_000_000:
                phase = (rel - 3_000_000_000) % 800_000_000
                lateral = -26.0 if 200_000_000 <= phase < 600_000_000 else 26.0
                self.active_steps += 1
                self.signed_sum += lateral
                self.absolute_sum += abs(lateral)
            u = rel / 2_000_000_000
            a = 0.1 * (60 * u - 180 * u * u + 120 * u * u * u) if u < 1 else 0.0
            force = [0.0, lateral, sum(MASSES.values()) * (9.81 + a)]
            if not all(math.isfinite(v) for v in force) or math.hypot(*force) > 40:
                raise ValueError("force bound exceeded")
            self.support_steps += 1
            return force
        except Exception as exc:
            self.refuse(repr(exc))

    def check_clearance(self, ns, clearance):
        self._available()
        if type(clearance) not in (int, float) or not math.isfinite(clearance):
            self.refuse("invalid geometric clearance")
        if self.anchor_ns is not None and ns >= self.anchor_ns + 2_000_000_000 and clearance < 0.1:
            self.refuse("geometric ground clearance bound exceeded")

    def finish(self):
        out = super().finish()
        expected = None if self.anchor_ns is None else (25_000_000_000 - self.anchor_ns) // 1_000_000 + 1
        out.update(
            anchor_ns=self.anchor_ns,
            expected_support_steps=expected,
            full_profile_requested=self.failure is None
            and self.anchor_ns is not None
            and self.last_ns == 25_000_000_000
            and self.support_steps == expected
            and self.active_steps == 1600,
        )
        return out
