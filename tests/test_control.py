import json

from flydrones.config import load_config
from flydrones.drones.udp_bridge import decode_packet, encode_packet, msp_frame, msp_set_raw_rc, rc_channels
from flydrones.motor import FlightCommand, MotorDecoder
from flydrones.safety import SafetyGovernor, Telemetry


def test_decoder_settles_then_decodes():
    cfg = load_config()
    dec = MotorDecoder(cfg)
    rest = {"DNg02_L": 35, "DNg02_R": 35, "DNp03_L": 0, "DNp03_R": 0, "DNp01_L": 0, "DNp01_R": 0}
    for _ in range(40):
        c = dec.update(rest, 0.05)
    assert abs(c.throttle) < 0.05
    for _ in range(20):
        c = dec.update({**rest, "DNg02_L": 70, "DNg02_R": 70}, 0.05)
    assert c.throttle > 0.3
    for _ in range(20):
        c = dec.update({**rest, "DNg02_R": 60, "DNg02_L": 20}, 0.05)
    assert c.yaw > 0.3


def test_escape_reflex():
    cfg = load_config()
    dec = MotorDecoder(cfg)
    rest = {"DNg02_L": 35, "DNg02_R": 35, "DNp01_L": 0, "DNp01_R": 0}
    for _ in range(40):
        dec.update(rest, 0.05)
    c = None
    for _ in range(4):
        c = dec.update({**rest, "DNp01_L": 80}, 0.05)
    assert c.escape and c.throttle > 0


def test_readout_file(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"baseline": {"A": 10}, "axes": {"throttle": {"gain": 1.0, "terms": {"A": 0.1}}}}))
    cfg = load_config(overrides={"decoder": {"readout_file": str(p), "smoothing": 1.0}})
    dec = MotorDecoder(cfg)
    c = dec.update({"A": 15}, 0.05)
    assert abs(c.throttle - 0.5) < 1e-6


def test_saccade_hold_keeps_neural_turn_direction_and_brakes():
    cfg = load_config(overrides={"decoder": {
        "settle_s": 0.0,
        "smoothing": 1.0,
        "cruise": 0.7,
        "axes": {"yaw": {"gain": 1.0, "terms": {"TURN": 1.0}}},
        "saccade_hold": {"enabled": True, "trigger": 0.2, "duration_s": 0.4,
                         "strength": 0.6, "forward_max": 0.05},
    }})
    dec = MotorDecoder(cfg)
    first = dec.update({"TURN": 0.5}, 0.05)
    reversed_input = dec.update({"TURN": -0.8}, 0.05)

    assert first.yaw >= 0.6
    assert reversed_input.yaw >= 0.6
    assert reversed_input.forward <= 0.05
    assert "saccade hold" in reversed_input.note


def test_saccade_cooldown_prevents_immediate_opposite_turn():
    cfg = load_config(overrides={"decoder": {
        "settle_s": 0.0,
        "smoothing": 1.0,
        "axes": {"yaw": {"gain": 1.0, "terms": {"TURN": 1.0}}},
        "saccade_hold": {"enabled": True, "trigger": 0.2, "duration_s": 0.1,
                         "cooldown_s": 0.3, "strength": 0.6, "forward_max": 0.05},
    }})
    dec = MotorDecoder(cfg)
    dec.update({"TURN": 0.8}, 0.05)
    dec.update({"TURN": -0.8}, 0.05)
    dec.update({"TURN": -0.8}, 0.05)
    cooling = dec.update({"TURN": -0.8}, 0.05)

    assert cooling.yaw == 0.0
    assert "saccade cooldown" in cooling.note


def test_reset_transients_applies_saccade_activation_delay():
    cfg = load_config(overrides={"decoder": {
        "settle_s": 0.0,
        "smoothing": 1.0,
        "axes": {"yaw": {"gain": 1.0, "terms": {"TURN": 1.0}}},
        "saccade_hold": {"enabled": True, "trigger": 0.2, "duration_s": 0.2,
                         "activation_delay_s": 0.15, "strength": 0.6},
    }})
    dec = MotorDecoder(cfg)
    dec.update({"TURN": 0.8}, 0.2)
    dec.reset_transients()

    delayed = dec.update({"TURN": -0.8}, 0.05)
    dec.update({"TURN": -0.8}, 0.05)
    active = dec.update({"TURN": -0.8}, 0.05)

    assert "saccade hold" not in delayed.note
    assert "saccade hold" in active.note


def test_saccade_direction_memory_reuses_side_after_cooldown():
    cfg = load_config(overrides={"decoder": {
        "settle_s": 0.0,
        "smoothing": 1.0,
        "axes": {"yaw": {"gain": 1.0, "terms": {"TURN": 1.0}}},
        "saccade_hold": {"enabled": True, "trigger": 0.2, "duration_s": 0.1,
                         "cooldown_s": 0.1, "direction_memory_s": 1.0,
                         "strength": 0.6},
    }})
    dec = MotorDecoder(cfg)
    first = dec.update({"TURN": 0.8}, 0.05)
    for _ in range(4):
        dec.update({"TURN": -0.8}, 0.05)
    repeated = dec.update({"TURN": -0.8}, 0.05)

    assert first.yaw > 0.0
    assert repeated.yaw > 0.0
    assert "saccade hold" in repeated.note


def test_safety_limits():
    cfg = load_config()
    s = SafetyGovernor(cfg)
    c = s.filter(FlightCommand(throttle=1.0, yaw=1.0), Telemetry(t=0, alt_m=1.0, flying=True), dt=10)
    assert c.throttle <= cfg["safety"]["max_throttle"] + 1e-9
    assert c.yaw <= cfg["safety"]["max_yaw"] + 1e-9
    c = s.filter(FlightCommand(throttle=0.5), Telemetry(t=1, alt_m=5.0, flying=True), dt=10)
    assert c.throttle < 0
    c = s.filter(FlightCommand(throttle=-0.5), Telemetry(t=2, alt_m=0.1, flying=True), dt=10)
    assert c.throttle > 0
    assert "floor recovery" in c.note
    s.filter(FlightCommand(), Telemetry(t=3, alt_m=1.0, battery_pct=5, flying=True), dt=0.05)
    assert s.land_requested


def test_slew_rate():
    s = SafetyGovernor(load_config())
    c = s.filter(FlightCommand(yaw=0.6), Telemetry(t=0, alt_m=1, flying=True), dt=0.05)
    assert c.yaw <= 2.5 * 0.05 + 1e-9


def test_floor_recovery_stays_active_until_above_release_margin():
    s = SafetyGovernor(load_config())
    below = s.filter(FlightCommand(throttle=-0.5), Telemetry(t=0, alt_m=0.2, flying=True), dt=1)
    near = s.filter(FlightCommand(throttle=-0.5), Telemetry(t=1, alt_m=0.31, flying=True), dt=1)
    still_recovering = s.filter(FlightCommand(throttle=-0.5), Telemetry(t=2, alt_m=0.41, flying=True), dt=1)
    recovered = s.filter(FlightCommand(throttle=-0.5), Telemetry(t=3, alt_m=0.46, flying=True), dt=1)

    assert below.throttle > 0
    assert near.throttle > 0
    assert still_recovering.throttle > 0
    assert recovered.throttle < 0


def test_floor_recovery_starts_early_when_descending_toward_minimum():
    s = SafetyGovernor(load_config())

    result = s.filter(FlightCommand(throttle=-0.5),
                      Telemetry(t=0, alt_m=0.35, vz_mps=-0.2, flying=True), dt=1)

    assert result.throttle > 0
    assert "floor recovery" in result.note


def test_floor_recovery_code_defaults_match_default_configuration():
    s = SafetyGovernor({"safety": {"min_alt_m": 0.3}})

    result = s.filter(FlightCommand(throttle=-0.5),
                      Telemetry(t=0, alt_m=0.39, vz_mps=-0.2, flying=True), dt=1)

    assert result.throttle > 0
    assert "floor recovery" in result.note


def test_brain_timeout_hovers():
    s = SafetyGovernor(load_config())
    c = s.filter(FlightCommand(throttle=0.5), Telemetry(t=0, alt_m=1, flying=True), dt=0.05, brain_age_s=2.0)
    assert c.throttle == 0 and "timeout" in c.note


def test_udp_packet_roundtrip():
    pkt = encode_packet(7, True, FlightCommand(throttle=0.25, yaw=-1.0, forward=0.5, lateral=0.0))
    d = decode_packet(pkt)
    assert d == {"seq": 7, "arm": True, "throttle": 250, "yaw": -1000, "pitch": 500, "roll": 0}
    assert decode_packet(b"garbage") is None


def test_msp_frame():
    f = msp_frame(200, bytes([1, 2]))
    assert f[:3] == b"$M<" and f[3] == 2 and f[4] == 200
    assert f[-1] == (2 ^ 200 ^ 1 ^ 2)
    ch = rc_channels(FlightCommand(throttle=1.0), arm=True)
    assert ch[2] == 1650 and ch[4] == 1800
    assert len(msp_set_raw_rc(ch)) == 3 + 2 + 16 + 1
    assert rc_channels(FlightCommand(throttle=1.0), arm=False)[2] == 1000
