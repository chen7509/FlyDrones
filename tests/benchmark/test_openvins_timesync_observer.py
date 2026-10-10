from __future__ import annotations

import pytest

from tools.benchmark.openvins_timesync_observer import SerialTimesyncObserver


def record(index=0, *, rtt=2000, estimated=None, offset=1000):
    request = 1_000_000 + index * 20_000
    remote = request + rtt // 2 + offset
    status = dict(instance=2, ordinal=index + 1, timestamp=request + rtt + 7,
                  remote_timestamp=remote, observed_offset=-offset,
                  estimated_offset=-offset if estimated is None else estimated,
                  round_trip_time=rtt, source_protocol=0)
    return request * 1000, remote * 1000, status


def reserved():
    observer = SerialTimesyncObserver("clock-a", 2)
    request, remote, status = record()
    observer.reserve_reply(request, remote, 0)
    return observer, status


def test_500_matched_statuses_converge_only_model_and_keep_authority_false():
    observer = SerialTimesyncObserver("clock-a", 2)
    for index in range(500):
        request, remote, status = record(index, offset=0)
        observer.reserve_reply(request, remote, index * 20_000_000)
        output = observer.observe_status(status, index * 20_000_000 + 100_000)
        assert output["modeled_accepted_samples"] == index + 1
        assert output["observed_model_converged"] is (index == 499)
        assert output["live_convergence_qualified"] is False
        assert output["network_authorized"] is False
        assert output["fusion_qualified"] is False
    assert not hasattr(observer, "replace_session")


def test_exact_rtt_limit_is_rejection_and_next_valid_status_can_proceed():
    observer = SerialTimesyncObserver("a", 2)
    request, remote, status = record(rtt=10_000, estimated=0)
    observer.reserve_reply(request, remote, 0)
    output = observer.observe_status(status, 1)
    assert output["accepted"] is False
    assert output["modeled_accepted_samples"] == 0
    request, remote, status = record(1)
    observer.reserve_reply(request, remote, 2)
    assert observer.observe_status(status, 3)["modeled_accepted_samples"] == 1


@pytest.mark.parametrize("key,value", [
    ("instance", 0), ("ordinal", 2), ("remote_timestamp", 1),
    ("source_protocol", 1), ("observed_offset", -999),
    ("estimated_offset", -999), ("timestamp", 1_001_999),
    ("round_trip_time", -1), ("round_trip_time", 2**32),
    ("timestamp", 2**64), ("ordinal", True), ("ordinal", 1.0),
    ("observed_offset", -(2**63)-1), ("estimated_offset", float("nan")),
])
def test_status_fault_latches_and_never_consumes_as_success(key, value):
    observer, status = reserved()
    status[key] = value
    with pytest.raises(ValueError):
        observer.observe_status(status, 1)
    with pytest.raises(ValueError, match="latched"):
        observer.observe_status(record()[2], 2)


@pytest.mark.parametrize("mutation", ["missing", "extra", "not_dict"])
def test_strict_status_schema(mutation):
    observer, status = reserved()
    if mutation == "missing":
        del status["timestamp"]
    elif mutation == "extra":
        status["live_convergence_qualified"] = True
    else:
        status = []
    with pytest.raises(ValueError):
        observer.observe_status(status, 0)


def test_second_pending_reservation_cannot_overwrite_first():
    observer, _ = reserved()
    with pytest.raises(ValueError, match="pending"):
        observer.reserve_reply(*record(1)[:2], 1)
    with pytest.raises(ValueError, match="latched"):
        observer.check(2)


def test_missing_status_fails_at_inclusive_two_second_deadline():
    observer, status = reserved()
    observer.check(1_999_999_999)
    with pytest.raises(ValueError, match="timeout"):
        observer.observe_status(status, 2_000_000_000)
    with pytest.raises(ValueError, match="latched"):
        observer.check(2_000_000_000)


def test_local_clock_regression_latches_even_without_pending_reply():
    observer = SerialTimesyncObserver("a", 2)
    observer.check(50)
    observer.check(50)
    with pytest.raises(ValueError, match="clock"):
        observer.check(49)


@pytest.mark.parametrize("now", [True, -1, 0.0, 2**64])
def test_bad_local_clock(now):
    observer = SerialTimesyncObserver("a", 2)
    with pytest.raises(ValueError):
        observer.check(now)


@pytest.mark.parametrize("request_ns,remote", [
    (True, 2_000_000), (0, 2_000_000), (1001, 2000),
    (1000, 2001), (1000, 0), (2**63, 2**63), (1.0, 2000),
])
def test_invalid_reply_identity_latches(request_ns, remote):
    observer = SerialTimesyncObserver("a", 2)
    with pytest.raises(ValueError):
        observer.reserve_reply(request_ns, remote, 0)
    with pytest.raises(ValueError, match="latched"):
        observer.check(1)


def test_unsolicited_and_duplicate_statuses_are_refused():
    observer = SerialTimesyncObserver("a", 2)
    with pytest.raises(ValueError, match="pending"):
        observer.observe_status(record()[2], 0)
    observer, status = reserved()
    observer.observe_status(status, 0)
    with pytest.raises(ValueError, match="pending"):
        observer.observe_status(status, 1)


@pytest.mark.parametrize("identity", ["request", "remote"])
def test_previous_reply_identity_cannot_be_reused(identity):
    observer, status = reserved()
    observer.observe_status(status, 0)
    request, remote, _ = record(1)
    if identity == "request":
        request = record()[0]
    else:
        remote = record()[1]
    with pytest.raises(ValueError, match="identity"):
        observer.reserve_reply(request, remote, 1)


def test_filter_clock_jump_requires_fresh_observer_and_px4_epoch():
    observer = SerialTimesyncObserver("a", 2)
    for index in range(500):
        request, remote, status = record(index, offset=0)
        observer.reserve_reply(request, remote, index * 2)
        observer.observe_status(status, index * 2 + 1)
    for index in range(500, 510):
        request, remote, status = record(index, offset=0)
        remote += 200_000_000
        status["remote_timestamp"] += 200_000
        status["observed_offset"] -= 200_000
        observer.reserve_reply(request, remote, index * 2)
        assert observer.observe_status(status, index * 2 + 1)["accepted"] is False
    request, remote, status = record(510, offset=0)
    remote += 200_000_000
    status.update(remote_timestamp=remote // 1000, observed_offset=-200000, estimated_offset=0)
    observer.reserve_reply(request, remote, 1020)
    with pytest.raises(ValueError, match="reset"):
        observer.observe_status(status, 1021)


@pytest.mark.parametrize("session,instance", [("", 2), (None, 2), ("a", True), ("a", -1), ("a", 256)])
def test_constructor_rejects_invalid_identity(session, instance):
    with pytest.raises(ValueError):
        SerialTimesyncObserver(session, instance)


def test_receive_and_publication_clock_regressions_refuse():
    observer, status = reserved()
    observer.observe_status(status, 0)
    request, remote, newer = record(1)
    observer.reserve_reply(request, remote, 1)
    newer["timestamp"] = status["timestamp"]
    with pytest.raises(ValueError, match="clock"):
        observer.observe_status(newer, 2)


def test_reconstructed_receive_clock_overflow_refuses():
    request_ns = (2**63 - 1) // 1000 * 1000
    observer = SerialTimesyncObserver("a", 2)
    observer.reserve_reply(request_ns, request_ns, 0)
    status = record()[2]
    status.update(timestamp=2**64 - 1, remote_timestamp=request_ns // 1000)
    with pytest.raises(ValueError, match="overflow"):
        observer.observe_status(status, 1)


@pytest.mark.parametrize("offset,expected", [(1.9999, 1), (-1.9999, -1), (-0.9999, 0), (0.9999, 0)])
def test_status_offset_casts_in_microseconds_without_nanosecond_floor(offset, expected):
    from tools.benchmark.openvins_ekf2_disarmed_preflight import BoundedTimesyncVerifier

    verifier = BoundedTimesyncVerifier("a")
    verifier._offset_us = offset  # Analytic representation fixture, not live state.
    assert verifier.estimated_offset_us == expected


@pytest.mark.parametrize("request_us,remote_us,expected", [
    (4503599627370498, 1, 4503599627370497),
    (1, 4503599627370499, -4503599627370497),
])
@pytest.mark.parametrize("wrong_estimate", [False, True])
def test_large_odd_numerator_uses_pinned_integer_truncation(request_us, remote_us, expected, wrong_estimate):
    observer = SerialTimesyncObserver("large-clock", 2)
    observer.reserve_reply(request_us * 1000, remote_us * 1000, 0)
    status = dict(instance=2, ordinal=1, timestamp=request_us + 1,
                  remote_timestamp=remote_us, observed_offset=expected,
                  estimated_offset=expected + ((1 if expected > 0 else -1) if wrong_estimate else 0),
                  round_trip_time=1, source_protocol=0)
    if wrong_estimate:
        with pytest.raises(ValueError, match="estimated"):
            observer.observe_status(status, 1)
    else:
        assert observer.observe_status(status, 1)["estimated_offset_us"] == expected
