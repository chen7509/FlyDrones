"""ODOMETRY receiver transport only, while EV is disabled and PX4 is disarmed."""

from __future__ import annotations

from tools.benchmark.disarmed_estimate_receiver import DisarmedEstimateReceiver
from tools.benchmark.openvins_odometry_contract import convert_native


class DisarmedOdometryReceiver(DisarmedEstimateReceiver):
    ODOMETRY_TRANSPORT = True

    def __init__(self, source):
        super().__init__(source)
        self.last_odometry_ns = None
        self.selected_state = None

    def transport_summary(self):
        attempts = [row for row in self.send_events if row.get("kind") == "odometry"]
        returned = [row for row in attempts if type(row["bytes_returned"]) is int]
        full = sum(row["bytes_returned"] == len(bytes.fromhex(row["raw_hex"])) for row in returned)
        return dict(
            odometry_attempts=len(attempts),
            odometry_full_returns=full,
            odometry_short_returns=len(returned) - full,
            odometry_without_return=len(attempts) - len(returned),
            odometry_sent=bool(full),
            odometry_sent_meaning="at least one full socket send return; not delivery",
            px4_receipt_verified=False,
            fusion_verified=False,
            controller_ready=False,
        )

    def check(self, now, *, disarmed):
        super().check(now, disarmed=disarmed)
        return dict(
            receiver_only_verified=True,
            native_lifecycle_policy="fresh-monitored-generation-or-terminal-refusal",
            reset_lifecycle_known=self.selected_state is not None,
            **self.transport_summary(),
        )

    def odometry(self, codec, remote_clock, sequence, now, sim_ns, *, disarmed):
        self.check(now, disarmed=disarmed)
        state = self.source.wire_snapshot(sim_ns)
        if state is None or state["sample_ns"] == self.last_odometry_ns:
            return None
        if (
            state.get("native_profile") != "offset-reset-v2"
            or type(state.get("reset_counter")) is not int
            or state["reset_counter"] != 0
            or state.get("reset_total") != 0
            or state.get("quality") is not None
            or type(state["sample_ns"]) is not int
            or not 0 <= sim_ns - state["sample_ns"] <= 100_000_000
            or self.last_odometry_ns is not None
            and state["sample_ns"] <= self.last_odometry_ns
        ):
            raise ValueError("ODOMETRY source/reset/sample not transport eligible")
        geometry = convert_native(state["native_state13"], state["native_covariance12"])
        sample_ns = remote_clock.map_odometry_sample(state["sample_ns"])
        if not 0 < sample_ns // 1000 < 2**64:
            raise ValueError("ODOMETRY wire timestamp outside microsecond range")
        codec.check()
        encoder = codec._mav.MAVLink(None, srcSystem=254, srcComponent=191)
        encoder.seq = sequence
        message = codec._mav.MAVLink_odometry_message(
            time_usec=sample_ns // 1000,
            frame_id=20,
            child_frame_id=12,
            x=geometry["position"][0],
            y=geometry["position"][1],
            z=geometry["position"][2],
            q=geometry["q_wxyz"],
            vx=geometry["velocity_body"][0],
            vy=geometry["velocity_body"][1],
            vz=geometry["velocity_body"][2],
            rollspeed=geometry["angular_velocity_body"][0],
            pitchspeed=geometry["angular_velocity_body"][1],
            yawspeed=geometry["angular_velocity_body"][2],
            pose_covariance=geometry["pose_covariance"],
            velocity_covariance=geometry["velocity_covariance"],
            reset_counter=state["reset_counter"],
            estimator_type=3,
            quality=0,
        )  # MAVLink0 means unknown, not inferred positive health.
        raw = message.pack(encoder)
        if len(self.send_events) >= 4096:
            raise ValueError("ODOMETRY attempt capacity")
        self.last_odometry_ns = state["sample_ns"]
        self.selected_state = state
        self.send_events.append(
            dict(
                kind="odometry",
                sample_ns=state["sample_ns"],
                native_pid=state["native_pid"],
                native_session=state["native_session"],
                raw_hex=raw.hex(),
                bytes_returned=None,
            )
        )
        return raw
