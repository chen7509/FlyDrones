"""Exercise receiver state separately from transport acknowledgement state."""

from __future__ import annotations

import sys

import pytest

from tools.benchmark.openvins_ekf2_disarmed_preflight import (
    ParameterTransaction,
    required_parameter_names,
)


class AppliedThenLost:
    def __init__(self, fault, *, restore_fault=None):
        self.values = dict.fromkeys(required_parameter_names(), 0)
        self.baseline = dict(self.values)
        self.fault = fault
        self.restore_fault = restore_fault
        self.writes = []
        self.reads = []

    def read(self, name):
        self.reads.append((name, self.values[name]))
        return [self.values[name]]

    def write(self, name, value):
        self.writes.append((name, value))
        self.values[name] = value  # Receiver already committed before response loss.
        if name == "EKF2_EV_DELAY" and value == 1:
            if self.fault == "false":
                return False
            if self.fault == "exception":
                raise TimeoutError("ack lost after remote commit")
            if self.fault == "interrupt":
                raise KeyboardInterrupt("cancel after remote commit")
            if self.fault == "truthy":
                return "ack"
        if value == 0 and self.restore_fault == name:
            return False
        return True


@pytest.mark.parametrize("fault", ["false", "exception"])
def test_unacknowledged_remote_commit_is_restored_in_reverse_attempt_order(fault):
    transport = AppliedThenLost(fault)
    result = ParameterTransaction(transport).apply_verify_restore(
        {"EKF2_EV_CTRL": 0, "EKF2_EV_QMIN": 1, "EKF2_EV_DELAY": 1}
    )
    assert transport.values == transport.baseline
    assert transport.writes == [
        ("EKF2_EV_QMIN", 1), ("EKF2_EV_DELAY", 1),
        ("EKF2_EV_DELAY", 0), ("EKF2_EV_QMIN", 0),
    ]
    assert result["primary_failure"].startswith("write_")
    assert result["qualified"] is False
    assert result["rollback_failures"] == []


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), True, "1"])
def test_all_desired_values_are_validated_before_any_transport_action(invalid):
    transport = AppliedThenLost("none")
    with pytest.raises(ValueError, match="invalid desired parameter"):
        ParameterTransaction(transport).apply_verify_restore(
            {"EKF2_EV_CTRL": 0, "EKF2_EV_QMIN": 1, "EKF2_EV_DELAY": invalid}
        )
    assert transport.writes == []
    assert transport.reads == []
    assert transport.values == transport.baseline


def test_restore_ack_loss_is_reported_even_when_readback_proves_value_restored():
    transport = AppliedThenLost("exception", restore_fault="EKF2_EV_DELAY")
    result = ParameterTransaction(transport).apply_verify_restore(
        {"EKF2_EV_CTRL": 0, "EKF2_EV_QMIN": 1, "EKF2_EV_DELAY": 1}
    )
    assert transport.values == transport.baseline
    assert result["primary_failure"].startswith("write_exception:EKF2_EV_DELAY")
    assert "restore_write_failed:EKF2_EV_DELAY" in result["rollback_failures"]
    assert ("EKF2_EV_DELAY", 0) in transport.reads
    assert result["qualified"] is False


def test_cancellation_restores_every_attempted_parameter_before_propagating():
    transport = AppliedThenLost("interrupt")
    transaction = ParameterTransaction(transport)
    with pytest.raises(KeyboardInterrupt, match="cancel after remote commit"):
        transaction.apply_verify_restore(
            {"EKF2_EV_CTRL": 0, "EKF2_EV_QMIN": 1, "EKF2_EV_DELAY": 1}
        )
    assert transport.values == transport.baseline
    assert transport.writes[-2:] == [("EKF2_EV_DELAY", 0), ("EKF2_EV_QMIN", 0)]
    assert transaction.last_result["qualified"] is False
    assert transaction.last_result["final_values"] == transport.baseline


def test_interrupt_after_write_returns_still_restores_before_reraising():
    transport = AppliedThenLost("none")
    transaction = ParameterTransaction(transport)
    previous_trace = sys.gettrace()
    injected = False

    def interrupt(frame, event, arg):
        nonlocal injected
        if (
            not injected
            and event == "line"
            and frame.f_code is ParameterTransaction.apply_verify_restore.__code__
            and transport.writes == [("EKF2_EV_QMIN", 1)]
        ):
            injected = True
            raise KeyboardInterrupt("between write and verification")
        return interrupt

    try:
        sys.settrace(interrupt)
        with pytest.raises(KeyboardInterrupt, match="between write and verification"):
            transaction.apply_verify_restore({"EKF2_EV_CTRL": 0, "EKF2_EV_QMIN": 1})
    finally:
        sys.settrace(previous_trace)
    assert injected
    assert transport.values == transport.baseline
    assert transaction.last_result["qualified"] is False
    assert transaction.last_result["final_values"] == transport.baseline


def test_non_boolean_ack_is_not_accepted_as_verified():
    transport = AppliedThenLost("truthy")
    result = ParameterTransaction(transport).apply_verify_restore(
        {"EKF2_EV_CTRL": 0, "EKF2_EV_DELAY": 1}
    )
    assert result["qualified"] is False
    assert result["primary_failure"] == "write_failed:EKF2_EV_DELAY"
    assert transport.values == transport.baseline


def test_unwritten_parameter_drift_fails_full_baseline_verification():
    transport = AppliedThenLost("none")
    original_write = transport.write

    def write_with_unrelated_drift(name, value):
        result = original_write(name, value)
        transport.values["EKF2_GPS_CTRL"] = 7
        return result

    transport.write = write_with_unrelated_drift
    result = ParameterTransaction(transport).apply_verify_restore(
        {"EKF2_EV_CTRL": 0, "EKF2_EV_QMIN": 1}
    )
    assert result["qualified"] is False
    assert "final_verify_failed:EKF2_GPS_CTRL" in result["rollback_failures"]
    # Never overwrite an unowned change while trying to conceal evidence drift.
    assert transport.values["EKF2_GPS_CTRL"] == 7

