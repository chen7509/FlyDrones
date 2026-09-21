from __future__ import annotations

import hashlib
import json
import socket
import struct
import time

import pytest

from flydrones.task_udp import (
    MissionTaskStation,
    TaskMessage,
    TaskUdpConfig,
    TaskUdpNode,
    decode_task_message,
    encode_task_message,
    task_overlay_peers,
)

MISSION_ID = "m1"
DIGEST = "a" * 64
HEADER = struct.Struct("!4sBHIH32s")


def free_base_port(count: int) -> int:
    for base in range(33000, 58000, count + 1):
        sockets: list[socket.socket] = []
        try:
            for offset in range(count + 1):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind(("127.0.0.1", base + offset))
                sockets.append(sock)
            return base
        except OSError:
            pass
        finally:
            for sock in sockets:
                sock.close()
    raise RuntimeError("no free UDP port range")


def task_message(**overrides: object) -> TaskMessage:
    values: dict[str, object] = {
        "kind": "bid",
        "mission_id": MISSION_ID,
        "mission_digest": DIGEST,
        "sender_id": 0,
        "sequence": 1,
        "sent_at": 1.0,
        "payload": {"task_id": "search-0000"},
    }
    values.update(overrides)
    return TaskMessage(**values)  # type: ignore[arg-type]


def raw_datagram(payload: bytes, *, sender_id: int = 0, sequence: int = 1) -> bytes:
    return HEADER.pack(
        b"FDT1",
        1,
        sender_id,
        sequence,
        len(payload),
        hashlib.sha256(payload).digest(),
    ) + payload


def make_nodes(count: int, *, rate: float = 10.0) -> tuple[list[TaskUdpNode], TaskUdpConfig]:
    config = TaskUdpConfig(
        base_port=free_base_port(count),
        max_messages_per_second=rate,
    )
    members = tuple(range(count))
    nodes = [TaskUdpNode(index, members, MISSION_ID, DIGEST, config=config) for index in members]
    return nodes, config


def wait_for_messages(node: TaskUdpNode, count: int) -> list[TaskMessage]:
    deadline = time.monotonic() + 0.7
    messages: list[TaskMessage] = []
    while time.monotonic() < deadline and len(messages) < count:
        messages.extend(node.poll())
        if len(messages) < count:
            time.sleep(0.005)
    return messages


def test_task_message_round_trip_and_strict_validation() -> None:
    message = task_message()
    assert decode_task_message(
        encode_task_message(message),
        expected_mission_id=MISSION_ID,
        expected_digest=DIGEST,
    ) == message
    with pytest.raises(ValueError, match="1200"):
        encode_task_message(task_message(payload={"award": "x" * 1400}))
    with pytest.raises(ValueError, match="mission"):
        decode_task_message(
            encode_task_message(message),
            expected_mission_id="other",
            expected_digest=DIGEST,
        )

    duplicate = raw_datagram(
        b'{"kind":"bid","kind":"award","mission_id":"m1",'
        b'"mission_digest":"' + DIGEST.encode() + b'","sent_at":1,"payload":{}}'
    )
    with pytest.raises(ValueError, match="duplicate"):
        decode_task_message(
            duplicate,
            expected_mission_id=MISSION_ID,
            expected_digest=DIGEST,
        )


def test_checksum_nonfinite_and_exact_top_level_keys_are_rejected() -> None:
    encoded = bytearray(encode_task_message(task_message()))
    encoded[-1] ^= 1
    with pytest.raises(ValueError, match="checksum"):
        decode_task_message(bytes(encoded), MISSION_ID, DIGEST)

    nonfinite = raw_datagram(
        b'{"kind":"bid","mission_id":"m1","mission_digest":"'
        + DIGEST.encode()
        + b'","sent_at":NaN,"payload":{}}'
    )
    with pytest.raises(ValueError, match="non-finite"):
        decode_task_message(nonfinite, MISSION_ID, DIGEST)

    extra = json.loads(encode_task_message(task_message())[HEADER.size :])
    extra["extra"] = True
    payload = json.dumps(extra, separators=(",", ":"), sort_keys=True).encode()
    with pytest.raises(ValueError, match="keys"):
        decode_task_message(raw_datagram(payload), MISSION_ID, DIGEST)


def test_overlay_peers_are_deterministic_and_bounded() -> None:
    assert task_overlay_peers(0, tuple(range(100))) == (1, 3, 7, 13, 87, 93, 97, 99)
    assert task_overlay_peers(2, (0, 1, 2, 3, 4)) == (0, 1, 3, 4)
    assert 50 not in task_overlay_peers(50, tuple(range(100)))


def test_two_task_nodes_exchange_on_real_loopback_and_rate_limit_sender() -> None:
    nodes, _config = make_nodes(2, rate=2.0)
    first, second = nodes
    try:
        assert first.send("bid", {"task_id": "search-0000"}, now=1.0) == 1
        assert first.send("lease", {"task_id": "search-0000"}, now=1.1) == 1
        assert first.send("progress", {"done": 0}, now=1.2) == 0
        messages = wait_for_messages(second, count=2)
        assert [message.kind for message in messages] == ["bid", "lease"]
        assert first.metrics["rate_limited_messages"] == 1
        assert first.metrics["sent_datagrams"] == 2
    finally:
        for node in nodes:
            node.close()


def test_rate_budget_counts_each_overlay_datagram() -> None:
    nodes, _config = make_nodes(9, rate=10.0)
    sender = nodes[0]
    try:
        assert sender.send("bid", {"task_id": "search-0000"}, now=1.0) == 8
        assert sender.send("lease", {"task_id": "search-0000"}, now=1.0) == 0
        assert sender.metrics["sent_datagrams"] == 8
        assert sender.metrics["rate_limited_messages"] == 1
    finally:
        for node in nodes:
            node.close()


def test_poll_rejects_out_of_order_and_accepts_sequence_wrap() -> None:
    nodes, config = make_nodes(2)
    receiver = nodes[1]
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        address = ("127.0.0.1", config.base_port + 1)
        for sequence in (0xFFFFFFFF, 0, 0xFFFFFFFF):
            sender.sendto(
                encode_task_message(task_message(sequence=sequence, sent_at=float(sequence))),
                address,
            )
        messages = wait_for_messages(receiver, count=2)
        assert [message.sequence for message in messages] == [0, 0xFFFFFFFF]
        assert receiver.metrics["out_of_order_messages"] == 1
    finally:
        sender.close()
        for node in nodes:
            node.close()


def test_wrong_sender_partition_filter_and_wrong_mission_are_counted() -> None:
    count = 2
    config = TaskUdpConfig(base_port=free_base_port(count))
    node = TaskUdpNode(
        0,
        tuple(range(count)),
        MISSION_ID,
        DIGEST,
        config=config,
        partition_filter=lambda _source, _target: False,
    )
    raw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        assert node.send("bid", {}, now=1.0) == 0
        assert node.metrics["partition_drops"] == 1
        raw.sendto(
            encode_task_message(task_message(sender_id=7)),
            ("127.0.0.1", config.base_port),
        )
        raw.sendto(
            encode_task_message(task_message(mission_id="other", sequence=2)),
            ("127.0.0.1", config.base_port),
        )
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline and sum(node.metrics.values()) < 3:
            node.poll()
            time.sleep(0.005)
        assert node.metrics["wrong_sender_messages"] == 1
        assert node.metrics["wrong_mission_messages"] == 1
    finally:
        raw.close()
        node.close()


def test_poll_tolerates_windows_connection_reset() -> None:
    class ResettingSocket:
        def __init__(self, *_args: object) -> None:
            self.calls = 0

        def setsockopt(self, *_args: object) -> None:
            pass

        def bind(self, *_args: object) -> None:
            pass

        def setblocking(self, *_args: object) -> None:
            pass

        def recvfrom(self, *_args: object) -> tuple[bytes, tuple[str, int]]:
            self.calls += 1
            if self.calls == 1:
                raise ConnectionResetError(10054, "peer exited")
            raise BlockingIOError

        def close(self) -> None:
            pass

    node = TaskUdpNode(
        0,
        (0, 1),
        MISSION_ID,
        DIGEST,
        config=TaskUdpConfig(base_port=25000),
        socket_factory=ResettingSocket,
    )
    assert node.poll() == []
    assert node.metrics["connection_resets"] == 1
    node.close()


def test_station_offers_contract_and_observes_every_real_agent_acceptance() -> None:
    nodes, config = make_nodes(3)
    station = MissionTaskStation(MISSION_ID, DIGEST, (0, 1, 2), config=config)
    contract = {"schema_version": 1, "mission_id": MISSION_ID}
    try:
        assert station.offer(contract, now=1.0) == 3
        for node in nodes:
            offers = wait_for_messages(node, count=1)
            assert len(offers) == 1
            assert offers[0].kind == "mission_offer"
            assert offers[0].payload["contract"] == contract
            assert node.send_to_station(
                "mission_accept",
                {"mission_digest": DIGEST},
                now=1.1,
            ) == 1

        deadline = time.monotonic() + 0.7
        accepted: set[int] = set()
        while time.monotonic() < deadline and len(accepted) < len(nodes):
            accepted |= station.poll_accepts()
            time.sleep(0.005)
        assert accepted == {0, 1, 2}
    finally:
        station.close()
        for node in nodes:
            node.close()
