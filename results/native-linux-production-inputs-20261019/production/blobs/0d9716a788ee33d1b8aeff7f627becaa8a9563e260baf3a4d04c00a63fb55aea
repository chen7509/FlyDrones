"""Isolated simulator diagnostics; never an estimator input or flight control."""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

from flydrones.benchmark.gateway import sim_duration_ns


def _integer(v):
    if type(v) is not int or not 0 < v < 2**63:
        raise ValueError("invalid integer clock")
    return v


def _state(value):
    for key, n in [("position", 3), ("velocity_world", 3), ("accel_world", 3), ("angular_world", 3), ("quaternion_xyzw", 4)]:
        v = value[key]
        try:
            valid = len(v) == n and all(type(x) in (int, float) and math.isfinite(x) for x in v)
        except (TypeError, OverflowError):
            valid = False
        if not valid:
            raise ValueError("invalid physics " + key)
    if abs(math.hypot(*value["quaternion_xyzw"]) - 1) > 1e-6:
        raise ValueError("nonunit physics quaternion")


class SubstepTrace:
    def __init__(self, output):
        self.output = output
        self.stream = (output / "physics-substeps.jsonl").open("x")
        self.records, self.bytes_written = 0, 0
        self.max_bytes = 128 * 1024 * 1024
        self.phase, self.next_ns = "pre", 1_000_000
        self.last_wall = 0
        self.failure, self.last_attempt = None, None
        self.backend_recorded = False
        self.unavailable = 0

    def refuse(self, exc):
        self.failure = self.failure or repr(exc)
        raise ValueError(self.failure)

    def record(self, phase, ns, dt, state, wall):
        if self.failure:
            raise ValueError("trace failure latched: " + self.failure)
        self.last_attempt = dict(phase=str(phase), sim_ns_repr=repr(ns), record_index=self.records)
        try:
            if phase != self.phase or _integer(ns) != self.next_ns or _integer(dt) != 1_000_000:
                raise ValueError("trace phase/step mismatch")
            if _integer(wall) < self.last_wall or ns > 25_000_000_000 or self.records >= 50000:
                raise ValueError("trace clock/record limit")
            if state is None:
                if ns >= 100_000_000:
                    raise ValueError("physics fields unavailable after startup")
            else:
                _state(state)
            row = dict(
                phase=phase,
                sim_ns=ns,
                dt_ns=dt,
                state_time_ns=ns - dt if phase == "pre" else ns,
                state_time_basis="callback_phase_only",
                component_refresh_verified=False,
                wall_ns=wall,
                available=state is not None,
                truth_for_diagnostics_only=True,
            )
            if state is not None:
                row.update(state)
            encoded = json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n"
            if self.bytes_written + len(encoded.encode()) > self.max_bytes:
                raise ValueError("trace byte limit")
            if self.stream.write(encoded) != len(encoded):
                raise OSError("short trace write")
            self.records += 1
            self.bytes_written += len(encoded.encode())
            self.last_wall = wall
            self.unavailable += int(state is None)
            self.phase = "post" if phase == "pre" else "pre"
            if phase == "post":
                self.next_ns += dt
            if self.records % 200 == 0:
                self.stream.flush()
        except Exception as exc:
            self.refuse(exc)

    def observe(self, phase, info, link, ecm):
        try:
            if info.paused:
                raise ValueError("paused trace callback")
            pose = link.world_pose(ecm)
            vel = link.world_linear_velocity(ecm)
            accel = link.world_linear_acceleration(ecm)
            angular = link.world_angular_velocity(ecm)
            state = None
            if all(v is not None for v in [pose, vel, accel, angular]):

                def xyz(v):
                    return [v.x(), v.y(), v.z()]

                q = pose.rot()
                state = dict(
                    position=xyz(pose.pos()),
                    velocity_world=xyz(vel),
                    accel_world=xyz(accel),
                    angular_world=xyz(angular),
                    quaternion_xyzw=[q.x(), q.y(), q.z(), q.w()],
                )
            self.record(phase, sim_duration_ns(info.sim_time), sim_duration_ns(info.dt), state, time.monotonic_ns())
            if phase == "post" and state is not None and not self.backend_recorded:
                self._record_backend()
        except Exception as exc:
            self.refuse(exc)

    def _record_backend(self):
        paths = set()
        for line in Path("/proc/self/maps").read_text().splitlines():
            parts = line.split(maxsplit=5)
            if len(parts) == 6 and ("libgz-physics" in parts[-1] or "/libdart" in parts[-1]):
                paths.add(parts[-1])
        if not any("dartsim" in p for p in paths) or not any("/libdart" in p for p in paths):
            raise ValueError("expected installed dartsim backend not observed")
        entries = []
        for name in sorted(paths):
            data = Path(name).read_bytes()
            entries.append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        with (self.output / "backend-loaded.json").open("x") as f:
            json.dump(entries, f, indent=2)
        self.backend_recorded = True

    def finish(self):
        close_errors = []
        for name, op in [("flush", self.stream.flush), ("close", self.stream.close)]:
            try:
                op()
            except Exception as exc:
                self.failure = self.failure or repr(exc)
                close_errors.append(dict(operation=name, reason=repr(exc)))
        if self.records != 50000 or self.phase != "pre":
            self.failure = self.failure or "incomplete terminal physics trace"
        if not self.backend_recorded:
            self.failure = self.failure or "missing runtime backend provenance"
        return dict(
            records=self.records,
            bytes_written=self.bytes_written,
            unavailable_records=self.unavailable,
            failure=self.failure,
            last_attempt=self.last_attempt,
            close_errors=close_errors,
            complete=self.records == 50000 and self.phase == "pre" and self.failure is None,
            backend_recorded=self.backend_recorded,
            eligible_for_px4_fusion=False,
        )


def finish_capture_trace(trace, result, errors):
    result["physics_trace"] = trace.finish()
    if result["physics_trace"]["failure"]:
        errors.append("physics trace: " + result["physics_trace"]["failure"])


def phase_closures(rows, start_ns, end_ns):
    start_ns, end_ns = _integer(start_ns), _integer(end_ns)
    if not 8_000_000 <= end_ns - start_ns <= 25_000_000_000 or (end_ns - start_ns) % 1_000_000:
        raise ValueError("invalid diagnostic window")
    selected = []
    last = 0
    for row in rows:
        if row["phase"] != "post":
            continue
        ns = _integer(row["sim_ns"])
        if ns <= last:
            raise ValueError("duplicate/regressed post trace")
        last = ns
        if start_ns <= ns <= end_ns:
            if row["available"] is not True:
                raise ValueError("unavailable analysis sample")
            _state(row)
            selected.append(row)
    if [r["sim_ns"] for r in selected] != list(range(start_ns, end_ns + 1, 1_000_000)):
        raise ValueError("incomplete full-rate trace")

    def closure(samples):
        stamps = np.array([r["sim_ns"] for r in samples], dtype=np.int64)
        accel = np.array([r["accel_world"] for r in samples])
        vel = np.array([r["velocity_world"] for r in samples])
        dt = np.diff(stamps) * 1e-9
        actual = vel[-1] - vel[0]
        right = np.sum(accel[1:] * dt[:, None], axis=0)
        trap = np.sum((accel[1:] + accel[:-1]) * 0.5 * dt[:, None], axis=0)
        return dict(
            start_ns=int(stamps[0]),
            end_ns=int(stamps[-1]),
            samples=len(samples),
            endpoint_delta_velocity=actual.tolist(),
            right_integral=right.tolist(),
            trapezoid_integral=trap.tolist(),
            right_error_norm_m_s=float(np.linalg.norm(right - actual)),
            trapezoid_error_norm_m_s=float(np.linalg.norm(trap - actual)),
        )

    return dict(
        full=closure(selected),
        quarter_phases=[
            dict(phase_ns=p, **closure([r for r in selected if r["sim_ns"] % 4_000_000 == p]))
            for p in range(0, 4_000_000, 1_000_000)
        ],
        root_cause_proven=False,
        eligible_for_px4_fusion=False,
    )
