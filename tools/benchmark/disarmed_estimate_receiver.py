"""Receiver-only stage on the capture's existing MAVLink owner; never enables EV."""

from __future__ import annotations


class DisarmedEstimateReceiver:
    def __init__(self, source=None):
        self.source = source
        self.request_ns = self.response_ns = self.last_state_ns = None
        self.pending = False
        self.requests = 0
        self.send_events = []

    def due(self, now):
        if self.pending and now - self.request_ns >= 2_000_000_000:
            raise ValueError("EKF2_EV_CTRL read response deadline")
        return not self.pending and (self.request_ns is None or now - self.request_ns >= 1_000_000_000)

    def request(self, codec, sequence, now):
        if type(now) is not int or now < 0 or not self.due(now) or self.requests >= 300:
            raise ValueError("bounded parameter read unavailable")
        codec.check()
        # Use the same sequence owner and component as TIMESYNC/interval traffic.
        encoder = codec._mav.MAVLink(None, srcSystem=254, srcComponent=191)
        encoder.seq = sequence
        raw = codec._mav.MAVLink_param_request_read_message(9, 1, b"EKF2_EV_CTRL", -1).pack(encoder)
        self.request_ns, self.pending = now, True
        self.requests += 1
        self.send_events.append(dict(request_ns=now, raw_hex=raw.hex(), bytes_returned=None))
        return raw

    def receive(self, rows, received_ns):
        for row in rows:
            if row["type"] != "PARAM_VALUE" or row["fields"].get("param_id") != "EKF2_EV_CTRL":
                continue
            value = row["fields"]
            if (
                not self.pending
                or type(received_ns) is not int
                or not 0 <= received_ns - self.request_ns < 2_000_000_000
                or row["system"] != 9
                or row["component"] != 1
                or row["framing"] != 2
                or value.get("param_type") != 6
                or value.get("param_value") != 0.0
            ):
                raise ValueError("uncorrelated/late/nonzero EKF2_EV_CTRL response")
            self.response_ns, self.pending = received_ns, False

    def check(self, now, *, disarmed):
        if (
            type(now) is not int
            or disarmed is not True
            or self.response_ns is None
            or not 0 <= now - self.response_ns < 2_000_000_000
        ):
            raise ValueError("receiver requires fresh disabled EV and disarmed heartbeat")
        return dict(
            receiver_only_verified=True,
            fusion_verified=False,
            controller_ready=False,
            reset_lifecycle_known=False,
            odometry_sent=False,
        )

    def diagnostic(self, sim_ns):
        if self.source is None:
            raise ValueError("managed native source absent")
        state = self.source.latest_diagnostic(sim_ns)
        if state is None or state["sample_ns"] == self.last_state_ns:
            return None
        self.last_state_ns = state["sample_ns"]
        return dict(state=state, publication_blocked="native reset lifecycle unknown; calibration/fusion unqualified")

    def require_publishable(self, state):
        if state.get("reset_counter") is None:
            raise RuntimeError("native reset lifecycle unknown; ODOMETRY cannot invent zero")
        raise RuntimeError("source/calibration/fusion are not qualified in this source version")
