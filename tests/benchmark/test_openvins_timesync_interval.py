import pytest

from tools.benchmark.openvins_timesync_interval import (
    TimesyncIntervalTransaction,
    restorable_interval,
)


class Transport:
    def __init__(self, interval=100000):
        self.interval = interval
        self.calls = []
        self.read_faults = {}
        self.set_faults = {}
        self.reads = 0
        self.sets = 0

    def read_interval(self, message_id):
        self.calls.append(("read", message_id))
        self.reads += 1
        outcome = self.read_faults.get(self.reads)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome is not None:
            return outcome
        return [{"message_id": message_id, "interval_us": self.interval}]

    def set_interval(self, message_id, interval_us):
        self.calls.append(("set", message_id, interval_us))
        self.sets += 1
        self.interval = interval_us  # lost ACK can follow an actual write
        outcome = self.set_faults.get(self.sets, True)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_apply_body_restore():
    transport = Transport()
    def body():
        assert transport.interval == 10000
        transport.calls.append(("body",))
        return True
    result = TimesyncIntervalTransaction(transport).run(body)
    assert result["modeled_transaction_pass"]
    assert result["baseline_us"] == result["final_us"] == 100000
    assert transport.calls == [
        ("read", 111), ("set", 111, 10000), ("read", 111), ("body",),
        ("set", 111, 100000), ("read", 111), ("read", 111),
    ]
    assert result["mutation_attempted"] and result["restore_attempted"]
    for flag in ("network_authorized", "live_rate_qualified", "fusion_qualified"):
        assert result[flag] is False


@pytest.mark.parametrize("value", [-1, 0, -2, True, 100000.0, None, "100000", 2**31, 2**31-1, 49, 61, 16777217])
def test_unrestorable_baseline_refused_before_write(value):
    transport = Transport(value)
    result = TimesyncIntervalTransaction(transport).run(lambda: pytest.fail("body"))
    assert not result["modeled_transaction_pass"]
    assert not result["mutation_attempted"]
    assert transport.calls == [("read", 111)]


@pytest.mark.parametrize("rows", [[], [{"message_id": 111, "interval_us": 100000}]*2,
    [{"message_id": 110, "interval_us": 100000}],
    [{"message_id": 111, "interval_us": 100000, "extra": 0}],
    [{"message_id": True, "interval_us": 100000}], [100000], "invalid"])
def test_invalid_readback_shape(rows):
    transport = Transport()
    transport.read_faults[1] = rows
    result = TimesyncIntervalTransaction(transport).run(lambda: pytest.fail("body"))
    assert result["primary_failure"]
    assert transport.sets == 0


@pytest.mark.parametrize("value", [1, 10000, 100000, 1000000])
def test_known_restorable_intervals(value):
    assert restorable_interval(value) == value


@pytest.mark.parametrize("fault", [False, 1, TimeoutError("lost"), RuntimeError("lost")])
def test_apply_failure_after_write_still_restores(fault):
    transport = Transport()
    transport.set_faults[1] = fault
    result = TimesyncIntervalTransaction(transport).run(lambda: pytest.fail("body"))
    assert not result["modeled_transaction_pass"]
    assert result["primary_failure"]
    assert result["restore_failures"] == []
    assert transport.interval == 100000 and transport.sets == 2


def test_apply_readback_mismatch_still_restores():
    transport = Transport()
    transport.read_faults[2] = [{"message_id": 111, "interval_us": 20000}]
    result = TimesyncIntervalTransaction(transport).run(lambda: pytest.fail("body"))
    assert result["primary_failure"]
    assert transport.interval == 100000


@pytest.mark.parametrize("outcome", [False, None, 1, RuntimeError("body")])
def test_body_failure_restores(outcome):
    transport = Transport()
    def body():
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    result = TimesyncIntervalTransaction(transport).run(body)
    assert not result["modeled_transaction_pass"]
    assert transport.interval == 100000


@pytest.mark.parametrize("place", ["apply", "body", "restore", "verify"])
def test_interrupt_cleanup_and_last_result(place):
    transport = Transport()
    def body():
        if place == "body":
            raise KeyboardInterrupt()
        return True
    if place == "apply":
        transport.set_faults[1] = KeyboardInterrupt()
    if place == "restore":
        transport.set_faults[2] = KeyboardInterrupt()
    if place == "verify":
        transport.read_faults[2] = KeyboardInterrupt()
    transaction = TimesyncIntervalTransaction(transport)
    with pytest.raises(KeyboardInterrupt):
        transaction.run(body)
    assert transaction.last_result is not None
    assert not transaction.last_result["modeled_transaction_pass"]
    assert transport.interval == 100000
    assert transport.calls[-1] == ("read", 111)


@pytest.mark.parametrize("fault", [False, TimeoutError("lost restore")])
def test_restore_ack_not_replaced_by_matching_readback(fault):
    transport = Transport()
    transport.set_faults[2] = fault
    result = TimesyncIntervalTransaction(transport).run(lambda: True)
    assert result["primary_failure"] is None
    assert result["restore_failures"]
    assert result["final_us"] == 100000
    assert not result["modeled_transaction_pass"]


@pytest.mark.parametrize("read_number", [3, 4])
@pytest.mark.parametrize("fault", [[], TimeoutError(), [{"message_id": 111, "interval_us": 20000}]])
def test_restore_and_final_read_failures(read_number, fault):
    transport = Transport()
    transport.read_faults[read_number] = fault
    result = TimesyncIntervalTransaction(transport).run(lambda: True)
    assert result["restore_failures"]
    assert not result["modeled_transaction_pass"]
    assert transport.reads == 4


@pytest.mark.parametrize("drift", [False, True])
def test_already_candidate_no_unowned_writes(drift):
    transport = Transport(10000)
    def body():
        if drift:
            transport.interval = 20000
        return True
    result = TimesyncIntervalTransaction(transport).run(body)
    assert result["modeled_transaction_pass"] is (not drift)
    assert not result["mutation_attempted"] and not result["restore_attempted"]
    assert transport.sets == 0


def test_single_use_and_reentrant_refusal():
    transport = Transport()
    transaction = TimesyncIntervalTransaction(transport)
    def body():
        count = len(transport.calls)
        with pytest.raises(ValueError, match="single-use"):
            transaction.run(lambda: True)
        assert len(transport.calls) == count
        return True
    assert transaction.run(body)["modeled_transaction_pass"]
    with pytest.raises(ValueError, match="single-use"):
        transaction.run(body)


class BrokenError(Exception):
    def __str__(self):
        raise RuntimeError("exception rendering failed")


@pytest.mark.parametrize("place", ["apply", "body", "restore", "readback"])
def test_error_rendering_cannot_bypass_restoration(place):
    transport = Transport()
    def body():
        if place == "body":
            raise BrokenError()
        return True
    if place == "apply":
        transport.set_faults[1] = BrokenError()
    if place == "restore":
        transport.set_faults[2] = BrokenError()
    if place == "readback":
        transport.read_faults[3] = BrokenError()
    transaction = TimesyncIntervalTransaction(transport)
    result = transaction.run(body)
    assert not result["modeled_transaction_pass"]
    assert transport.interval == 100000
    assert transaction.last_result is result
    assert result["events"][-1]["phase"] == "final"
    assert "BrokenError" in str(result)
