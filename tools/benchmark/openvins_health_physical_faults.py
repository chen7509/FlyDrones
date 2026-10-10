"""Predeclared shadow-only OpenVINS physical health fault adapters.

The adapter never publishes odometry or changes the simulator.  Raw capture
continues in ``CaptureWriter`` before these estimator-side faults are applied.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from tools.benchmark.openvins_online_shadow import OnlineHealthEvidence, ShadowInput

PROFILES = {
    "imu-source-loss-after-8s-v1": {
        "name": "imu-source-loss-after-8s-v1",
        "trigger_sample_ns": 8_000_000_000,
        "source_kind": "imu",
        "source_loss_wall_timeout_ns": 2_000_000_000,
    },
    "native-restart-after-8s-v1": {
        "name": "native-restart-after-8s-v1",
        "trigger_sample_ns": 8_000_000_000,
        "source_kind": None,
        "source_loss_wall_timeout_ns": None,
    },
    "imu-source-loss-after-8s-immediate-v2": {
        "name": "imu-source-loss-after-8s-immediate-v2",
        "trigger_sample_ns": 8_000_000_000,
        "source_kind": "imu",
        "source_loss_wall_timeout_ns": 0,
        "detection_mode": "first_dropped_sample",
    },
    "native-restart-after-8s-failclosed-v2": {
        "name": "native-restart-after-8s-failclosed-v2",
        "trigger_sample_ns": 8_000_000_000,
        "source_kind": None,
        "source_loss_wall_timeout_ns": None,
        "expected_terminal_behavior": "readiness_loss_capture_failure",
    },
}


def fault_profile(name: str) -> dict:
    if name not in PROFILES:
        raise ValueError("unknown health fault profile")
    return copy.deepcopy(PROFILES[name])


class ManagedHealthShadow:
    """Own sequential native sessions and apply one immutable fault once."""

    def __init__(
        self,
        output,
        *,
        profile,
        health,
        client_factory,
        client_finisher=None,
        now=time.monotonic_ns,
    ):
        self.output = Path(output)
        self.profile = fault_profile(profile)
        if not isinstance(health, OnlineHealthEvidence):
            raise ValueError("managed shadow requires health evidence")
        if not callable(client_factory) or not callable(now):
            raise ValueError("invalid managed shadow dependency")
        if client_finisher is not None and not callable(client_finisher):
            raise ValueError("invalid managed shadow client finisher")
        self.health, self.client_factory, self.now = health, client_factory, now
        self.client_finisher = client_finisher or (lambda client: client.finish())
        self.session_replacement_callback = None
        self.events = (self.output / "health-fault-events.jsonl").open("x", encoding="utf-8")
        self.sessions = []
        self.active = None
        self.client = None
        self.session_index = -1
        self.restart_count = 0
        self.dropped_source_records = 0
        self.triggered_wall_ns = None
        self.failure = None
        self.delivery_acks = []
        self.closed = False
        self._spawn_initial()

    @property
    def current_session_id(self):
        return f"fault-session-{self.session_index}"

    @property
    def process(self):
        return getattr(self.client, "process", None)

    def _emit(self, value):
        value = {**value, "profile": self.profile["name"], "fusion_eligible": False}
        encoded = json.dumps(value, allow_nan=False, sort_keys=True) + "\n"
        if self.events.write(encoded) != len(encoded):
            raise OSError("short health fault event write")
        self.events.flush()

    def _spawn_initial(self):
        self.session_index = 0
        session_dir = self.output / "session-0"
        session_dir.mkdir()
        self.client = self.client_factory(0, self.current_session_id)
        self.active = ShadowInput(
            self.client,
            session_dir,
            session_id=self.current_session_id,
            now=self.now,
            health=self.health,
        )

    def _close_active(self):
        if self.active is None:
            return
        shadow_result = self.active.finish()
        native_result = self.client_finisher(self.client)
        self.sessions.append(
            {
                "index": self.session_index,
                "session_id": self.current_session_id,
                "shadow": shadow_result,
                "native": native_result,
                "fusion_eligible": False,
            }
        )
        self.active = None
        self.client = None
        if shadow_result["failure"] and self.failure is None:
            self.failure = shadow_result["failure"]
        if (native_result.get("failure") or native_result.get("exit") != 0) and self.failure is None:
            self.failure = "native_session_close:" + repr(native_result)

    def _restart(self, row, wall_ns):
        old_session = self.current_session_id
        self._close_active()
        if self.failure is not None:
            self.health.fail("native_restart_failed")
            return
        next_index = self.session_index + 1
        next_session = f"fault-session-{next_index}"
        session_dir = self.output / f"session-{next_index}"
        session_dir.mkdir()
        try:
            client = self.client_factory(next_index, next_session)
            transition = self.health.replace_session(next_session)
            if self.session_replacement_callback is not None:
                self.session_replacement_callback(next_session, transition["reset_total"])
            active = ShadowInput(client, session_dir, session_id=next_session, now=self.now, health=self.health)
        except Exception as exc:
            if "client" in locals():
                try:
                    self.client_finisher(client)
                except Exception:
                    pass
            self.failure = "native_restart_failed:" + repr(exc)
            self.health.fail("native_restart_failed")
            self._emit(
                {
                    "event": "native_restart_failed",
                    "sample_ns": row["sample_ns"],
                    "wall_monotonic_ns": wall_ns,
                    "previous_session_id": old_session,
                    "reason": repr(exc),
                }
            )
            return
        self.session_index = next_index
        self.client = client
        self.active = active
        self.restart_count += 1
        self._emit(
            {
                "event": "native_session_replaced",
                "sample_ns": row["sample_ns"],
                "wall_monotonic_ns": wall_ns,
                "previous_session_id": old_session,
                "session_id": next_session,
                "transition": transition,
            }
        )

    def set_session_replacement_callback(self, callback):
        if self.closed or self.restart_count or self.session_replacement_callback is not None or not callable(callback):
            raise ValueError("invalid session replacement callback")
        self.session_replacement_callback = callback

    def send(self, action, pixels=None):
        if self.failure or self.client is None:
            raise RuntimeError("managed native unavailable: " + str(self.failure))
        return self.client.send(action, pixels)

    def send_motion_intent(self, action):
        if self.failure or self.client is None:
            raise RuntimeError("managed native unavailable: " + str(self.failure))
        return self.client.send_motion_intent(action)

    def on_record(self, row, payload):
        self.delivery_acks = []
        if self.closed or self.failure:
            return
        wall_ns = self.now()
        if self.profile["name"].startswith("native-restart-"):
            if self.restart_count == 0 and row.get("sample_ns", 0) >= self.profile["trigger_sample_ns"]:
                self._restart(row, wall_ns)
                if self.failure:
                    return
        else:
            target = self.profile["source_kind"]
            if row.get("sample_ns", 0) >= self.profile["trigger_sample_ns"] and row.get("kind") == target:
                if self.triggered_wall_ns is None:
                    self.triggered_wall_ns = wall_ns
                    self._emit(
                        {
                            "event": "source_loss_started",
                            "sample_ns": row["sample_ns"],
                            "wall_monotonic_ns": wall_ns,
                            "source_kind": target,
                        }
                    )
                self.dropped_source_records += 1
                if self.profile.get("detection_mode") == "first_dropped_sample":
                    self.failure = "source_loss:" + target
                    self.health.fail("source_failure")
                    self._emit(
                        {
                            "event": "source_loss_detected",
                            "sample_ns": row["sample_ns"],
                            "wall_monotonic_ns": wall_ns,
                            "source_kind": target,
                            "elapsed_wall_ns": 0,
                        }
                    )
                return
            if (
                self.triggered_wall_ns is not None
                and wall_ns - self.triggered_wall_ns > self.profile["source_loss_wall_timeout_ns"]
            ):
                self.failure = "source_loss:" + target
                self.health.fail("source_failure")
                self._emit(
                    {
                        "event": "source_loss_detected",
                        "sample_ns": row.get("sample_ns"),
                        "wall_monotonic_ns": wall_ns,
                        "source_kind": target,
                        "elapsed_wall_ns": wall_ns - self.triggered_wall_ns,
                    }
                )
                return
        self.active.on_record(row, payload)
        self.delivery_acks = copy.deepcopy(self.active.delivery_acks)
        if self.active.failure:
            self.failure = self.active.failure

    def tick_idle(self, wall_monotonic_ns):
        if self.closed or self.failure or self.active is None:
            return False
        return self.active.tick_idle(wall_monotonic_ns)

    def finish(self):
        if self.closed:
            raise RuntimeError("managed shadow already closed")
        self.closed = True
        self._close_active()
        self.events.close()
        result = {
            "schema": "openvins-health-physical-fault-result-v1",
            "profile": self.profile,
            "failure": self.failure,
            "restart_count": self.restart_count,
            "dropped_source_records": self.dropped_source_records,
            "sessions": self.sessions,
            "health_last": copy.deepcopy(self.health.last),
            "fusion_eligible": False,
        }
        with (self.output / "health-fault-result.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        return result
