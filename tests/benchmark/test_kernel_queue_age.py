"""Conditional integer clock model and fake receiver; no live socket."""

import copy
import hashlib
import inspect
import json
import socket
import struct
import threading

import pytest

from tools.benchmark.kernel_queue_age import KernelQueueAge, modeled_age, offset_bracket
from tools.benchmark.kernel_rx_timestamping import RX_ABI, KernelRXTimestamping
from tools.benchmark.openvins_datagram_receive import DatagramReceiver

RAW = json.dumps(RX_ABI).encode()
SHA = hashlib.sha256(RAW).hexdigest()
SECOND = 1_000_000_000


class Clock:
    def __init__(self):
        self.now, self.offset = 100_000_000, SECOND * 1_800_000_000
        self.hook = None

    def mono(self):
        return self.now

    def real(self):
        if self.hook:
            self.hook()
        return self.now + self.offset


class Sock:
    family, type, proto = socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP

    def __init__(self):
        self.local, self.options, self.calls = ("0.0.0.0", 0), {}, []
        self.result = BlockingIOError()

    def fileno(self):
        return 19

    def getsockname(self):
        return self.local

    def gettimeout(self):
        return 0.0

    def setsockopt(self, level, key, value):
        self.options[level, key] = value

    def getsockopt(self, level, key):
        return self.options.get((level, key), 0)

    def recvmsg(self, *args):
        self.calls.append(args)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@pytest.fixture(autouse=True)
def linux_flag(monkeypatch):
    monkeypatch.setattr(socket, "MSG_DONTWAIT", 64, raising=False)


class Rig:
    def __init__(self, journal=None):
        self.clock, self.sock, self.events = Clock(), Sock(), []
        self.now = self.clock.mono  # One exact callable used by both scopes.
        self.kernel = KernelRXTimestamping(RAW, SHA, realtime_ns=self.clock.real)
        self.kernel.enable_before_bind(self.sock)
        self.age = KernelQueueAge(self.kernel, self.now, self.clock.now, "source-session-1")
        self.sock.local = DatagramReceiver.LOCAL
        kwargs = {"kernel_timestamps": self.kernel}
        if "kernel_queue_age" in inspect.signature(DatagramReceiver).parameters:
            kwargs["kernel_queue_age"] = self.age
        self.receiver = DatagramReceiver(
            self.sock,
            lambda: None,
            self.now,
            self.clock.now,
            journal or (lambda row: self.events.append(copy.deepcopy(row))),
            **kwargs,
        )

    def packet(self, age_ns):
        stamp = self.clock.real() - age_ns
        sec, nsec = divmod(stamp, SECOND)
        self.sock.result = (b"opaque", [(1, 65, struct.pack("<6q", sec, nsec, 0, 0, 0, 0))], 0, DatagramReceiver.PEER)
        return stamp


def test_integer_interval_no_midpoint_and_unqualified_result():
    assert offset_bracket(100, 1100, 110) == (990, 1000)
    value = modeled_age(1110, 200, 990, 1000)
    assert value["monotonic_lower_ns"] == 110 and value["monotonic_upper_ns"] == 120
    assert value["modeled_age_lower_ns"] == 80 and value["modeled_age_upper_ns"] == 90
    assert value["clock_mapping_qualified"] is False


@pytest.mark.parametrize("values", [(True, 100, 10), (0, 0, 1), (2, 10, 1), (0, 10, SECOND * 2), (0, 10, 2**63), (0, 10.0, 0)])
def test_invalid_or_too_uncertain_bracket_refuses(values):
    with pytest.raises(ValueError):
        offset_bracket(*values)


@pytest.mark.parametrize("stamp,now,lo,hi", [(0, 1, 0, 0), (1, 0, 0, 0), (1, 2, 2, 1), (1, 2, -(2**63), 0), (2**63, 2, 0, 0)])
def test_invalid_projection_never_grants_age(stamp, now, lo, hi):
    with pytest.raises(ValueError):
        modeled_age(stamp, now, lo, hi)


def test_exact_two_second_boundary_and_future_refuse():
    with pytest.raises(ValueError, match="age"):
        modeled_age(1, SECOND * 2 + 1, 0, 0)
    with pytest.raises(ValueError, match="future"):
        modeled_age(100, 99, 0, 0)
    assert modeled_age(1, SECOND * 2, 0, 0)["modeled_age_upper_ns"] == SECOND * 2 - 1


def test_fresh_packet_keeps_original_clocks_and_model_only():
    rig = Rig()
    rig.clock.now += 50_000_000
    stamp = rig.packet(20_000_000)
    packet = rig.receiver.poll()
    assert packet.received_ns == rig.clock.now and packet.kernel_received_realtime_ns == stamp
    assert packet.modeled_kernel_age_upper_ns == 20_000_000
    assert not rig.receiver.evidence["kernel_queue_age"]["clock_mapping_qualified"]
    assert not rig.receiver.progress["network_authorized"]


def test_stale_first_packet_refused_despite_fresh_decode():
    rig = Rig()
    rig.clock.now += SECOND * 3
    rig.packet(SECOND * 2 + 1)
    with pytest.raises(ValueError, match="age"):
        rig.receiver.poll()
    assert rig.receiver.evidence["datagram_returns"] == 1
    assert any(row["kind"] == "receive_return" and row["data_hex"] == b"opaque".hex() for row in rig.events)
    with pytest.raises(ValueError, match="latched"):
        rig.receiver.poll()


def test_increasing_backlog_cannot_renew_age_from_fresh_receipt():
    rig = Rig()
    rig.clock.now += 100_000_000
    first = rig.packet(50_000_000)
    rig.receiver.poll()
    rig.clock.now += SECOND * 2
    age = rig.clock.real() - (first + 1_000_000)
    rig.packet(age)
    with pytest.raises(ValueError, match="age"):
        rig.receiver.poll()
    assert rig.receiver.evidence["datagram_returns"] == 2


def test_journal_delay_counted_before_packet_return():
    holder = {}

    def journal(row):
        if row["kind"] == "kernel_timestamp_observed":
            holder["rig"].clock.now += SECOND * 2

    rig = Rig(journal)
    holder["rig"] = rig
    rig.clock.now += 100_000_000
    rig.packet(10_000_000)
    with pytest.raises(ValueError, match="age"):
        rig.receiver.poll()


@pytest.mark.parametrize("step", [100_000_000, -100_000_000])
def test_offset_step_latches_even_without_realtime_regression(step):
    rig = Rig()
    rig.clock.now += SECOND
    rig.clock.offset += step
    rig.packet(1)
    with pytest.raises(ValueError, match="offset"):
        rig.receiver.poll()
    assert rig.age.evidence["failure"]


def test_before_session_timestamp_never_retrospectively_bound():
    rig = Rig()
    rig.packet(1)
    with pytest.raises(ValueError, match="session"):
        rig.receiver.poll()


def test_already_bound_socket_cannot_add_age_anchor():
    clock, sock = Clock(), Sock()
    kernel = KernelRXTimestamping(RAW, SHA, realtime_ns=clock.real)
    kernel.enable_before_bind(sock)
    sock.local = DatagramReceiver.LOCAL
    with pytest.raises(ValueError, match="before bind"):
        KernelQueueAge(kernel, clock.mono, clock.now, "x")


def test_sampler_cannot_be_shared_or_change_clock_identity():
    rig = Rig()
    with pytest.raises(ValueError, match="bound"):
        rig.age._bind(object(), rig.sock, rig.kernel, rig.now, 100_000_000)


def test_sampler_reentry_refuses_and_preserves_raw_return():
    rig = Rig()
    rig.clock.now += 100_000_000
    rig.packet(1)
    called = [False]

    def hook():
        if rig.sock.calls and not called[0]:
            called[0] = True
            rig.age._sample(rig.receiver)

    rig.clock.hook = hook
    with pytest.raises(ValueError, match="concurrent"):
        rig.receiver.poll()
    assert rig.age.evidence["failure"]
    assert rig.receiver.evidence["datagram_returns"] == 1
    assert any(row["kind"] == "receive_return" and row["data_hex"] == b"opaque".hex() for row in rig.events)


def test_empty_read_still_samples_and_does_not_issue_age():
    rig = Rig()
    assert rig.receiver.poll() is None
    assert len(rig.age.evidence["anchors"]) >= 3
    assert rig.receiver.evidence["datagram_returns"] == 0


def test_nonconsuming_check_revalidates_last_issued_packet_age():
    rig = Rig()
    rig.clock.now += 100_000_000
    rig.packet(1)
    packet = rig.receiver.poll()
    rig.clock.now += SECOND * 2
    with pytest.raises(ValueError, match="age"):
        rig.receiver.check(packet)


def test_bound_guard_requires_exact_issued_packet_and_refuses_old_copy():
    rig = Rig()
    rig.clock.now += 100_000_000
    rig.packet(1)
    first = rig.receiver.poll()
    rig.receiver.check(first)
    rig.clock.now += 1_000_000
    rig.packet(1)
    second = rig.receiver.poll()
    with pytest.raises(ValueError, match="packet"):
        rig.receiver.check(first)
    assert first is not second


def test_bound_guard_without_packet_cannot_certify_an_unspecified_cache():
    rig = Rig()
    rig.clock.now += 100_000_000
    rig.packet(1)
    rig.receiver.poll()
    with pytest.raises(ValueError, match="packet"):
        rig.receiver.check()


def test_sampler_rebind_refusal_latches_original_model():
    rig = Rig()
    with pytest.raises(ValueError, match="bound"):
        rig.age._bind(object(), rig.sock, rig.kernel, rig.now, 100_000_000)
    assert rig.age.evidence["failure"]


def test_evidence_mutation_does_not_change_model_or_clock_anchor():
    rig = Rig()
    exported = rig.age.evidence
    exported["anchors"][0]["realtime_ns"] = 0
    exported["failure"] = "fake"
    assert rig.age.evidence["anchors"][0]["realtime_ns"] > 0
    assert rig.age.evidence["failure"] is None


def test_missing_metadata_and_descriptor_drift_remain_refused():
    rig = Rig()
    rig.clock.now += 100_000_000
    rig.packet(1)
    rig.sock.result = (b"opaque", [], 0, DatagramReceiver.PEER)
    with pytest.raises(ValueError, match="ancillary"):
        rig.receiver.poll()
    rig = Rig()
    rig.sock.fileno = lambda: 20
    with pytest.raises(ValueError, match="descriptor"):
        rig.receiver.poll()
    assert not rig.sock.calls


def test_clock_identity_mismatch_refuses_binding():
    clock, sock = Clock(), Sock()
    first_now = clock.mono
    kernel = KernelRXTimestamping(RAW, SHA, realtime_ns=clock.real)
    kernel.enable_before_bind(sock)
    age = KernelQueueAge(kernel, first_now, clock.now, "x")
    sock.local = DatagramReceiver.LOCAL
    with pytest.raises(ValueError, match="binding"):
        DatagramReceiver(
            sock, lambda: None, lambda: clock.now, clock.now, lambda _row: None, kernel_timestamps=kernel, kernel_queue_age=age
        )
    assert age.evidence["failure"]


def test_subclass_cannot_replace_exact_clock_profile():
    class Replacement(KernelRXTimestamping):
        pass

    kernel = Replacement(RAW, SHA)
    with pytest.raises(ValueError, match="exact"):
        KernelQueueAge(kernel, lambda: 0, 0, "x")


def test_ns_profile_cannot_gain_generated_age_semantics():
    from tests.benchmark.test_kernel_datagram_arrival import RAW as NS_RAW
    from tests.benchmark.test_kernel_datagram_arrival import SHA as NS_SHA
    from tools.benchmark.kernel_datagram_arrival import KernelTimestampNS

    kernel = KernelTimestampNS(NS_RAW, NS_SHA)
    with pytest.raises(ValueError, match="exact"):
        KernelQueueAge(kernel, lambda: 0, 0, "x")


def test_anchor_capacity_refuses_without_another_clock_call():
    rig = Rig()
    for _ in range(rig.age.MAX_ANCHORS - 1):
        rig.age._sample(rig.receiver)
    calls = []
    rig.clock.hook = lambda: calls.append("real")
    with pytest.raises(ValueError, match="capacity"):
        rig.age._sample(rig.receiver)
    assert calls == [] and len(rig.age.evidence["anchors"]) == 32768


def test_new_poll_can_read_fresh_packet_after_idle_without_reissuing_old_one():
    rig = Rig()
    rig.clock.now += 100_000_000
    rig.packet(1)
    first = rig.receiver.poll()
    rig.clock.now += SECOND * 2 + 1
    rig.packet(1)
    second = rig.receiver.poll()
    assert second.received_ns > first.received_ns
    assert second.modeled_kernel_age_upper_ns == 1


def test_final_assessment_cannot_ignore_caught_receiver_refusal():
    rig = Rig()
    rig.clock.now += 100_000_000
    rig.packet(1)

    def hook():
        if len(rig.age.evidence["anchors"]) == 4:
            try:
                rig.receiver.check()
            except ValueError:
                pass

    rig.clock.hook = hook
    with pytest.raises(ValueError, match="latched"):
        rig.receiver.poll()
    assert rig.receiver.progress["failure"] and rig.receiver.evidence["datagram_returns"] == 1


def test_final_check_cannot_ignore_caught_receiver_refusal():
    rig = Rig()
    rig.clock.now += 100_000_000
    rig.packet(1)
    packet = rig.receiver.poll()

    def hook():
        try:
            rig.receiver.check(packet)
        except ValueError:
            pass

    rig.clock.hook = hook
    with pytest.raises(ValueError, match="latched"):
        rig.receiver.check(packet)


def test_clock_callback_binding_socket_invalidates_initial_anchor():
    clock, sock = Clock(), Sock()
    kernel = KernelRXTimestamping(RAW, SHA, realtime_ns=clock.real)
    kernel.enable_before_bind(sock)

    def mono():
        sock.local = DatagramReceiver.LOCAL
        return clock.now

    with pytest.raises(ValueError, match="before bind"):
        KernelQueueAge(kernel, mono, clock.now, "x")


def test_concurrent_refusal_latches_without_waiting_for_blocked_clock():
    rig = Rig()
    entered, release, second_done = threading.Event(), threading.Event(), threading.Event()
    outcomes = []

    def clock():
        entered.set()
        assert release.wait(2)

    rig.clock.hook = clock

    def sample(label):
        try:
            rig.age._sample(rig.receiver)
            outcomes.append((label, "returned"))
        except ValueError:
            outcomes.append((label, "refused"))
        finally:
            if label == "second":
                second_done.set()

    first = threading.Thread(target=sample, args=("first",))
    second = threading.Thread(target=sample, args=("second",))
    first.start()
    try:
        assert entered.wait(1)
        second.start()
        assert second_done.wait(0.2)
    finally:
        release.set()
        first.join(1)
        if second.ident is not None:
            second.join(1)
    assert not first.is_alive() and not second.is_alive()
    assert sorted(outcomes) == [("first", "refused"), ("second", "refused")]


def test_final_assessment_cannot_cross_receiver_absolute_deadline():
    rig = Rig()
    rig.clock.now += 7_900_000_000
    rig.packet(1)

    def hook():
        if len(rig.age.evidence["anchors"]) == 4:
            rig.clock.now += 100_000_000

    rig.clock.hook = hook
    with pytest.raises(ValueError, match="deadline"):
        rig.receiver.poll()


def test_final_check_assessment_cannot_cross_receiver_deadline():
    rig = Rig()
    rig.clock.now += 7_900_000_000
    rig.packet(1)
    packet = rig.receiver.poll()

    def hook():
        rig.clock.now += 100_000_000

    rig.clock.hook = hook
    with pytest.raises(ValueError, match="deadline"):
        rig.receiver.check(packet)


def test_sampler_cannot_regress_behind_receiver_clock_observation():
    rig = Rig()
    rig.receiver._accept_clock(rig.clock.now + 1)
    with pytest.raises(ValueError, match="monotonic"):
        rig.age._sample(rig.receiver)
