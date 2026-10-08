import copy
from collections import deque
from types import SimpleNamespace

import pytest

from tools.benchmark.openvins_owned_bootstrap import OwnedBootstrap

OWNER = dict(
    pid=321,
    pgrp=321,
    session=321,
    start_ticks=7,
    uid=1000,
    gid=1000,
    exe="/bin/fixture",
    exe_device=1,
    exe_inode=2,
    cwd="/tmp/run",
    cwd_device=1,
    cwd_inode=3,
    net="net:[4]",
    user="user:[5]",
)


def body(index=0):
    request = 100000 + index * 20000
    response = request + 1000
    raw = (
        f" timesync_status\n    timestamp: {request + 2000} (0.000001 seconds ago)\n"
        f"    remote_timestamp: {response}\n    observed_offset: 0\n"
        "    estimated_offset: 0\n    round_trip_time: 2000\n    source_protocol: 0\n\n"
    ).encode()
    return request * 1000, response * 1000, raw


def single():
    return b"\nTOPIC: timesync_status\n" + body()[2]


def frame(index=0):
    return b"\x1b[2J\n\x1b[H" + f"\nTOPIC: timesync_status instance 0 #{index + 1}\n".encode() + body(index)[2]


class Connection:
    def __init__(self, reads=()):
        self.reads = deque(reads)
        self.sent = b""
        self.closed = 0

    def setblocking(self, value):
        assert value is False

    def send(self, data):
        self.sent += data
        return len(data)

    def recv(self, limit):
        assert limit == 4096
        if not self.reads:
            raise BlockingIOError()
        value = self.reads.popleft()
        if isinstance(value, BaseException):
            raise value
        return value


class Backend:
    def __init__(self):
        self.now = 10
        self.owner = copy.deepcopy(OWNER)
        self.connections = [
            Connection([b"never published\n\0\0", b""]),
            Connection([single() + b"\0\0", b""]),
            Connection([frame()]),
        ]
        self.used = []

    def clock(self):
        return self.now

    def observe(self, process):
        return copy.deepcopy(self.owner)

    def peer(self, connection):
        return {key: self.owner[key] for key in ("pid", "uid", "gid")}

    def connect(self, path, timeout):
        assert path == "/tmp/private/socket"
        connection = self.connections[len(self.used)]
        self.used.append(connection)
        return connection

    def close(self, connection):
        connection.closed += 1


def make(journal=None):
    backend = Backend()
    obj = OwnedBootstrap(
        SimpleNamespace(pid=321), OWNER, "/tmp/private/socket", "session-a", 10, journal or (lambda _: None), backend=backend
    )
    return obj, backend


def first_ready(obj):
    obj.poll()
    assert obj.poll()["phase"] == "first_ready"


def stream_ready(obj):
    first_ready(obj)
    intent = obj.reserve_reply(*body()[:2])
    assert intent["transmission_proven"] is False
    obj.poll()
    assert obj.poll()["phase"] == "first_confirmed"
    assert obj.poll()["phase"] == "stream_ready"


def test_entire_owned_chain_requires_three_clean_commands_and500_counted_once():
    events = []
    obj, backend = make(events.append)
    assert not backend.used
    stream_ready(obj)
    assert obj.progress["modeled_accepted_samples"] == 1
    for index in range(1, 500):
        backend.now += 1000000
        obj.reserve_reply(*body(index)[:2])
        backend.connections[2].reads.append(frame(index))
        obj.poll()
    assert not obj.progress["transport_bootstrap_complete"]
    backend.connections[2].reads.extend([b"\0\0", b""])
    obj.poll()
    result = obj.poll()
    assert result["transport_bootstrap_complete"] and result["modeled_accepted_samples"] == 500
    assert not any(result[k] for k in ("network_authorized", "fusion_qualified", "live_convergence_qualified"))
    assert [c.sent for c in backend.used] == [b"listener timesync_status -n 1\0"] * 2 + [
        b"listener timesync_status -i 0 -n 500\0"
    ]
    assert [c.closed for c in backend.used] == [1, 1, 1]
    evidence = obj.evidence
    assert events == evidence["events"]
    assert len(evidence["transports"]) == 3
    assert all(t["transport_complete"] for t in evidence["transports"])
    assert len([e for e in evidence["bootstrap_events"] if e["kind"] == "latest_replay"]) == 1
    events.clear()
    assert obj.evidence["events"]


@pytest.mark.parametrize("change", ["owner", "clock", "bool-clock"])
def test_change_between_commands_refuses_before_another_connect(change):
    obj, backend = make()
    first_ready(obj)
    if change == "owner":
        backend.owner["start_ticks"] += 1
    else:
        backend.now = True if change == "bool-clock" else 9
    with pytest.raises(ValueError):
        obj.reserve_reply(*body()[:2])
    assert len(backend.used) == 1
    assert obj.progress["failure"] and not obj.progress["transport_bootstrap_complete"]


def test_original_global_deadline_survives_progress():
    obj, backend = make()
    stream_ready(obj)
    for index in range(1, 8):
        backend.now = 10 + index * 1000000000
        obj.reserve_reply(*body(index)[:2])
        backend.connections[2].reads.append(frame(index))
        obj.poll()
    backend.now = 8000000010
    with pytest.raises(ValueError, match="deadline|readiness"):
        obj.poll()


def test_two_second_silence_still_refuses():
    obj, backend = make()
    stream_ready(obj)
    obj.reserve_reply(*body(1)[:2])
    backend.now = 2000000010
    with pytest.raises(ValueError, match="timeout"):
        obj.poll()
    assert backend.connections[2].closed == 1


@pytest.mark.parametrize("raw", [frame(1), frame() + frame(1), b"\0\0", frame() + b"\0\1"])
def test_wrong_replay_unsolicited_early_eof_nonzero_refuse(raw):
    obj, backend = make()
    first_ready(obj)
    obj.reserve_reply(*body()[:2])
    obj.poll()
    obj.poll()
    backend.connections[2].reads = deque([raw, b""])
    with pytest.raises(ValueError):
        obj.poll()
        obj.poll()
    assert not obj.progress["transport_bootstrap_complete"]


def test_pending_intent_cannot_be_replaced():
    obj, backend = make()
    first_ready(obj)
    obj.reserve_reply(*body()[:2])
    with pytest.raises(ValueError):
        obj.reserve_reply(*body(1)[:2])
    with pytest.raises(ValueError):
        obj.poll()
    assert len(backend.used) == 1


def test_construction_refusal_evidence_is_retained():
    def journal(event):
        if event["source"] == "transport" and event["event"]["kind"] == "connection":
            raise OSError("construction journal failure")

    obj, backend = make(journal)
    with pytest.raises(ValueError, match="journal"):
        obj.poll()
    assert obj.evidence["construction_refusal"] is not None
    assert len(backend.used) == 0


@pytest.mark.parametrize("failure", ["raise", "late", "reenter"])
def test_bootstrap_journal_fault_is_immediate_and_blocks_next_command(failure):
    holder = {}

    def journal(event):
        if event["source"] == "bootstrap" and event["event"]["kind"] == "reply_intent":
            if failure == "raise":
                raise OSError("intent journal failed")
            if failure == "late":
                holder["backend"].now = 8000000010
            if failure == "reenter":
                with pytest.raises(ValueError):
                    holder["obj"].poll()

    obj, backend = make(journal)
    holder.update(obj=obj, backend=backend)
    first_ready(obj)
    with pytest.raises(ValueError):
        obj.reserve_reply(*body()[:2])
    with pytest.raises(ValueError):
        obj.poll()
    assert len(backend.used) == 1


def test_journal_argument_mutation_does_not_change_evidence():
    def journal(event):
        event.clear()

    obj, _ = make(journal)
    stream_ready(obj)
    assert all("source" in event for event in obj.evidence["events"])


def test_abort_is_idempotent_and_cannot_resume():
    obj, backend = make()
    obj.poll()
    obj.close()
    obj.close()
    with pytest.raises(ValueError):
        obj.poll()
    assert backend.used[0].closed == 1
    assert not obj.progress["transport_bootstrap_complete"]


def test_late_final_journal_never_exposes_readiness():
    holder = {}

    def journal(event):
        if event["source"] == "coordinator" and event["event"] == dict(kind="command_finished", role="stream"):
            holder["backend"].now = 8000000010

    obj, backend = make(journal)
    holder["backend"] = backend
    stream_ready(obj)
    for index in range(1, 500):
        obj.reserve_reply(*body(index)[:2])
        backend.connections[2].reads.append(frame(index))
        obj.poll()
    backend.connections[2].reads.extend([b"\0\0", b""])
    obj.poll()
    with pytest.raises(ValueError, match="deadline"):
        obj.poll()
    assert obj.evidence["bootstrap_progress"]["modeled_bootstrap_ready"]
    assert not obj.progress["modeled_bootstrap_ready"]
    assert not obj.progress["transport_bootstrap_complete"]


@pytest.mark.parametrize(
    "path,start,count",
    [
        ("/tmp/a/../b", 10, 500),
        ("relative", 10, 500),
        ("/tmp/a", True, 500),
        ("/tmp/a", 2**64 - 1, 500),
        ("/tmp/a", 10, 499),
        ("/tmp/a", 10, True),
    ],
)
def test_invalid_configuration_never_connects(path, start, count):
    backend = Backend()
    with pytest.raises(ValueError):
        OwnedBootstrap(
            SimpleNamespace(pid=321), OWNER, path, "session-a", start, lambda _: None, stream_records=count, backend=backend
        )
    assert backend.used == []
