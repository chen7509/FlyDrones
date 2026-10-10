"""Pinned PX4 d6f12ad Mavlink::get_status_all_instances text contract."""

import pytest

from tools.benchmark.px4_mavlink_startup_status import parse_mavlink_status

NORMAL = (b"\ninstance #0:\n\tmavlink chan: #0\n\tmode: Normal\n"
          b"\ttransport protocol: UDP (18578, remote port: 14550)\n")
ONBOARD = (b"\ninstance #1:\n\tmavlink chan: #1\n\tmode: Onboard\n"
           b"\ttransport protocol: UDP (14588, remote port: 14548)\n")
PAYLOAD = (b"\ninstance #2:\n\tmavlink chan: #2\n\tmode: Onboard\n"
           b"\ttransport protocol: UDP (14288, remote port: 14038)\n")


def test_exact_source_derived_multi_instance_pair():
    proof = parse_mavlink_status(NORMAL + ONBOARD + PAYLOAD, 0)
    assert proof == {
        "phase": "ready", "instance": 1, "local_port": 14588, "remote_port": 14548,
        "authority": False, "fusion_qualified": False,
    }


def test_nonzero_empty_is_explicitly_pending_only():
    assert parse_mavlink_status(b"", 1) == {
        "phase": "pending", "reason": "no-instances", "authority": False,
        "fusion_qualified": False,
    }


@pytest.mark.parametrize("raw,exit_code", [
    (b"", 0), (b"unexpected", 1), (NORMAL, 2), (NORMAL, True),
    (NORMAL + ONBOARD + ONBOARD.replace(b"instance #1", b"instance #2"), 0),
    (NORMAL + ONBOARD.replace(b"remote port: 14548", b"remote port: 14549"), 0),
    (NORMAL + ONBOARD.replace(b"UDP (14588", b"UDP (14589"), 0),
    (NORMAL + ONBOARD.replace(b"mode: Onboard", b"mode: Normal"), 0),
    (NORMAL + ONBOARD.replace(b"instance #1", b"instance #0"), 0),
    (NORMAL + ONBOARD.replace(b"\tmode: Onboard\n", b"\tmode: Onboard\n\tmode: Onboard\n"), 0),
    (NORMAL + ONBOARD.replace(b"\ttransport protocol: UDP", b"\ttransport protocol: TCP"), 0),
    (NORMAL + ONBOARD[:-1], 0),
    (NORMAL + ONBOARD + b"\0\0", 0),
    (NORMAL + ONBOARD + b"\xff", 0),
    (b"x" * 32769, 0),
], ids=[f"case-{index}" for index in range(15)])
def test_ambiguous_or_malformed_status_never_passes(raw, exit_code):
    with pytest.raises(ValueError):
        parse_mavlink_status(raw, exit_code)


def test_other_onboard_endpoint_is_not_confused_with_selected_one():
    with pytest.raises(ValueError):
        parse_mavlink_status(NORMAL + PAYLOAD.replace(b"instance #2", b"instance #1"), 0)


def test_source_decimal_format_rejects_leading_zero_ports():
    with pytest.raises(ValueError):
        parse_mavlink_status(NORMAL.replace(b"UDP (18578", b"UDP (018578") + ONBOARD, 0)


def test_mode_and_port_from_different_sections_cannot_combine():
    deceptive = (NORMAL.replace(b"mode: Normal", b"mode: Onboard")
                 + ONBOARD.replace(b"mode: Onboard", b"mode: Normal"))
    with pytest.raises(ValueError):
        parse_mavlink_status(deceptive, 0)
