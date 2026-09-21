"""Bounded UDP gossip transport for autonomous swarm task records."""

from __future__ import annotations

import hashlib
import json
import math
import re
import socket
import struct
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

TaskKind = Literal[
    "mission_offer",
    "mission_accept",
    "bid",
    "award",
    "lease",
    "progress",
    "evidence",
    "health",
]

_MAGIC = b"FDT1"
_VERSION = 1
_HEADER = struct.Struct("!4sBHIH32s")
_MAX_DATAGRAM_BYTES = 1200
_STATION_ID = 0xFFFF
_KINDS = {
    "mission_offer",
    "mission_accept",
    "bid",
    "award",
    "lease",
    "progress",
    "evidence",
    "health",
}
_TOP_LEVEL_KEYS = {"kind", "mission_id", "mission_digest", "sent_at", "payload"}
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")


class _WrongMission(ValueError):
    pass


def _finite(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{where} must be a finite number")
    return number


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _is_newer_sequence(new: int, previous: int) -> bool:
    difference = (new - previous) & 0xFFFFFFFF
    return 0 < difference < 2**31


@dataclass(frozen=True)
class TaskMessage:
    kind: TaskKind
    mission_id: str
    mission_digest: str
    sender_id: int
    sequence: int
    sent_at: float
    payload: dict[str, object]


@dataclass(frozen=True)
class TaskUdpConfig:
    base_port: int
    max_messages_per_second: float = 10.0
    bind_host: str = "127.0.0.1"
    peer_host: str = "127.0.0.1"

    def __post_init__(self) -> None:
        if isinstance(self.base_port, bool) or not isinstance(self.base_port, int):
            raise ValueError("base_port must be an integer")
        if not 0 < self.base_port <= 65535:
            raise ValueError("base_port is outside the UDP port range")
        rate = _finite(self.max_messages_per_second, "max_messages_per_second")
        if rate <= 0.0 or rate > 1000.0:
            raise ValueError("max_messages_per_second must be positive and bounded")


def _validate_message(message: TaskMessage) -> None:
    if not isinstance(message, TaskMessage):
        raise ValueError("task message must be a TaskMessage")
    if message.kind not in _KINDS:
        raise ValueError(f"unsupported task message kind: {message.kind}")
    if not isinstance(message.mission_id, str) or not message.mission_id:
        raise ValueError("mission_id must be a non-empty string")
    if (
        not isinstance(message.mission_digest, str)
        or _DIGEST_PATTERN.fullmatch(message.mission_digest) is None
    ):
        raise ValueError("mission_digest must be a lowercase SHA-256 digest")
    if (
        isinstance(message.sender_id, bool)
        or not isinstance(message.sender_id, int)
        or not 0 <= message.sender_id <= 0xFFFF
    ):
        raise ValueError("sender_id is outside the wire range")
    if message.sender_id == _STATION_ID and message.kind != "mission_offer":
        raise ValueError("station sender ID is reserved for mission_offer")
    if (
        isinstance(message.sequence, bool)
        or not isinstance(message.sequence, int)
        or not 0 <= message.sequence <= 0xFFFFFFFF
    ):
        raise ValueError("sequence is outside the wire range")
    _finite(message.sent_at, "sent_at")
    if not isinstance(message.payload, dict):
        raise ValueError("payload must be a JSON object")


def encode_task_message(message: TaskMessage) -> bytes:
    _validate_message(message)
    envelope = {
        "kind": message.kind,
        "mission_id": message.mission_id,
        "mission_digest": message.mission_digest,
        "sent_at": message.sent_at,
        "payload": message.payload,
    }
    try:
        payload = json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(f"task payload is not canonical JSON: {error}") from error
    datagram = _HEADER.pack(
        _MAGIC,
        _VERSION,
        message.sender_id,
        message.sequence,
        len(payload),
        hashlib.sha256(payload).digest(),
    ) + payload
    if len(datagram) > _MAX_DATAGRAM_BYTES:
        raise ValueError("task datagram exceeds 1200 bytes")
    return datagram


def decode_task_message(
    datagram: bytes,
    expected_mission_id: str,
    expected_digest: str,
) -> TaskMessage:
    if len(datagram) > _MAX_DATAGRAM_BYTES:
        raise ValueError("task datagram exceeds 1200 bytes")
    if len(datagram) < _HEADER.size:
        raise ValueError("task datagram is shorter than its header")
    magic, version, sender_id, sequence, payload_length, checksum = _HEADER.unpack(
        datagram[: _HEADER.size]
    )
    payload = datagram[_HEADER.size :]
    if magic != _MAGIC or version != _VERSION:
        raise ValueError("invalid task datagram header")
    if payload_length != len(payload):
        raise ValueError("task datagram payload length mismatch")
    if hashlib.sha256(payload).digest() != checksum:
        raise ValueError("task datagram checksum mismatch")
    try:
        decoded = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid task JSON: {error}") from error
    if not isinstance(decoded, Mapping):
        raise ValueError("task JSON must be an object")
    if set(decoded) != _TOP_LEVEL_KEYS:
        raise ValueError("task JSON keys do not match the wire schema")
    if decoded["mission_id"] != expected_mission_id or decoded["mission_digest"] != expected_digest:
        raise _WrongMission("mission ID or mission digest mismatch")
    message = TaskMessage(
        kind=decoded["kind"],  # type: ignore[arg-type]
        mission_id=decoded["mission_id"],  # type: ignore[arg-type]
        mission_digest=decoded["mission_digest"],  # type: ignore[arg-type]
        sender_id=sender_id,
        sequence=sequence,
        sent_at=decoded["sent_at"],  # type: ignore[arg-type]
        payload=decoded["payload"],  # type: ignore[arg-type]
    )
    _validate_message(message)
    return message


def task_overlay_peers(vehicle_id: int, member_ids: Iterable[int]) -> tuple[int, ...]:
    members = tuple(sorted(set(member_ids)))
    if vehicle_id not in members:
        raise ValueError("vehicle_id must be included in member_ids")
    if len(members) < 9:
        return tuple(member for member in members if member != vehicle_id)
    own_index = members.index(vehicle_id)
    peers = {
        members[(own_index + offset) % len(members)]
        for offset in (-13, -7, -3, -1, 1, 3, 7, 13)
    }
    peers.discard(vehicle_id)
    return tuple(sorted(peers))


class TaskUdpNode:
    """One agent's real nonblocking UDP task endpoint."""

    def __init__(
        self,
        vehicle_id: int,
        member_ids: Iterable[int],
        mission_id: str,
        mission_digest: str,
        *,
        config: TaskUdpConfig,
        partition_filter: Callable[[int, int], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        socket_factory: Callable[..., socket.socket] = socket.socket,
    ) -> None:
        self.member_ids = tuple(sorted(set(member_ids)))
        if self.member_ids != tuple(range(len(self.member_ids))):
            raise ValueError("member IDs must be contiguous from zero")
        if vehicle_id not in self.member_ids:
            raise ValueError("vehicle_id must be included in member_ids")
        if config.base_port + len(self.member_ids) > 65535:
            raise ValueError("task UDP port range is invalid")
        if not mission_id:
            raise ValueError("mission_id cannot be empty")
        if _DIGEST_PATTERN.fullmatch(mission_digest) is None:
            raise ValueError("mission_digest must be a lowercase SHA-256 digest")
        self.vehicle_id = vehicle_id
        self.mission_id = mission_id
        self.mission_digest = mission_digest
        self.config = config
        self.overlay_peers = task_overlay_peers(vehicle_id, self.member_ids)
        self._partition_filter = partition_filter or (lambda _source, _target: True)
        self._clock = clock
        self._socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((config.bind_host, config.base_port + vehicle_id))
        self._socket.setblocking(False)
        self._sequence = 0
        self._latest_sequences: dict[int, int] = {}
        self._tokens = float(config.max_messages_per_second)
        self._last_token_at: float | None = None
        self._peer_cursor = 0
        self.metrics = {
            "sent_datagrams": 0,
            "received_messages": 0,
            "rate_limited_messages": 0,
            "malformed_messages": 0,
            "wrong_mission_messages": 0,
            "wrong_sender_messages": 0,
            "out_of_order_messages": 0,
            "partition_drops": 0,
            "connection_resets": 0,
        }

    def _take_tokens(self, maximum: int, now: float) -> int:
        timestamp = _finite(now, "now")
        if maximum <= 0:
            return 0
        if self._last_token_at is None:
            self._last_token_at = timestamp
        else:
            elapsed = max(0.0, timestamp - self._last_token_at)
            self._tokens = min(
                float(self.config.max_messages_per_second),
                self._tokens + elapsed * self.config.max_messages_per_second,
            )
            self._last_token_at = timestamp
        count = min(maximum, int(self._tokens))
        if count == 0:
            self.metrics["rate_limited_messages"] += 1
            return 0
        self._tokens -= count
        return count

    def _next_datagram(self, kind: TaskKind, payload: dict[str, object], now: float) -> bytes:
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        return encode_task_message(
            TaskMessage(
                kind,
                self.mission_id,
                self.mission_digest,
                self.vehicle_id,
                self._sequence,
                now,
                payload,
            )
        )

    def send(
        self,
        kind: TaskKind,
        payload: dict[str, object],
        *,
        now: float | None = None,
        target_peer_id: int | None = None,
    ) -> int:
        timestamp = self._clock() if now is None else now
        if kind in {"mission_offer", "mission_accept"}:
            raise ValueError("mission handshake messages do not use peer gossip")
        if target_peer_id is not None and target_peer_id not in self.overlay_peers:
            raise ValueError("target_peer_id must be an overlay peer")
        targets: list[int] = []
        candidate_peers = self.overlay_peers if target_peer_id is None else (target_peer_id,)
        for peer_id in candidate_peers:
            if self._partition_filter(self.vehicle_id, peer_id):
                targets.append(peer_id)
            else:
                self.metrics["partition_drops"] += 1
        count = self._take_tokens(len(targets), timestamp)
        if count == 0:
            return 0
        start = self._peer_cursor % len(targets)
        ordered_targets = targets[start:] + targets[:start]
        selected_targets = ordered_targets[:count]
        self._peer_cursor = (start + count) % len(targets)
        datagram = self._next_datagram(kind, payload, timestamp)
        sent = 0
        for peer_id in selected_targets:
            self._socket.sendto(
                datagram,
                (self.config.peer_host, self.config.base_port + peer_id),
            )
            self.metrics["sent_datagrams"] += 1
            sent += 1
        return sent

    def send_to_station(
        self,
        kind: TaskKind,
        payload: dict[str, object],
        *,
        now: float | None = None,
    ) -> int:
        if kind != "mission_accept":
            raise ValueError("only mission_accept may be sent to the task station")
        timestamp = self._clock() if now is None else now
        if self._take_tokens(1, timestamp) != 1:
            return 0
        datagram = self._next_datagram(kind, payload, timestamp)
        self._socket.sendto(
            datagram,
            (self.config.peer_host, self.config.base_port + len(self.member_ids)),
        )
        self.metrics["sent_datagrams"] += 1
        return 1

    def poll(self) -> list[TaskMessage]:
        messages: list[TaskMessage] = []
        while True:
            try:
                datagram, _address = self._socket.recvfrom(_MAX_DATAGRAM_BYTES + 1)
            except BlockingIOError:
                break
            except ConnectionResetError:
                self.metrics["connection_resets"] += 1
                continue
            try:
                message = decode_task_message(datagram, self.mission_id, self.mission_digest)
            except _WrongMission:
                self.metrics["wrong_mission_messages"] += 1
                continue
            except ValueError:
                self.metrics["malformed_messages"] += 1
                continue
            valid_station_offer = message.sender_id == _STATION_ID and message.kind == "mission_offer"
            if message.sender_id == self.vehicle_id or (
                message.sender_id not in self.member_ids and not valid_station_offer
            ):
                self.metrics["wrong_sender_messages"] += 1
                continue
            previous = self._latest_sequences.get(message.sender_id)
            if previous is not None and not _is_newer_sequence(message.sequence, previous):
                self.metrics["out_of_order_messages"] += 1
                continue
            self._latest_sequences[message.sender_id] = message.sequence
            self.metrics["received_messages"] += 1
            messages.append(message)
        return sorted(messages, key=lambda item: (item.sent_at, item.sender_id, item.sequence))

    def close(self) -> None:
        self._socket.close()


class MissionTaskStation:
    """Pre-start task publisher; close it before mission execution begins."""

    def __init__(
        self,
        mission_id: str,
        mission_digest: str,
        member_ids: Iterable[int],
        *,
        config: TaskUdpConfig,
        socket_factory: Callable[..., socket.socket] = socket.socket,
    ) -> None:
        self.member_ids = tuple(sorted(set(member_ids)))
        if self.member_ids != tuple(range(len(self.member_ids))):
            raise ValueError("member IDs must be contiguous from zero")
        if config.base_port + len(self.member_ids) > 65535:
            raise ValueError("task UDP port range is invalid")
        self.mission_id = mission_id
        self.mission_digest = mission_digest
        self.config = config
        self._sequence = 0
        self._latest_sequences: dict[int, int] = {}
        self._accepted: set[int] = set()
        self._socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((config.bind_host, config.base_port + len(self.member_ids)))
        self._socket.setblocking(False)

    def offer(self, contract: dict[str, object], *, now: float | None = None) -> int:
        timestamp = time.monotonic() if now is None else _finite(now, "now")
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        datagram = encode_task_message(
            TaskMessage(
                "mission_offer",
                self.mission_id,
                self.mission_digest,
                _STATION_ID,
                self._sequence,
                timestamp,
                {"contract": contract},
            )
        )
        for member_id in self.member_ids:
            self._socket.sendto(
                datagram,
                (self.config.peer_host, self.config.base_port + member_id),
            )
        return len(self.member_ids)

    def poll_accepts(self) -> set[int]:
        while True:
            try:
                datagram, _address = self._socket.recvfrom(_MAX_DATAGRAM_BYTES + 1)
            except (BlockingIOError, ConnectionResetError):
                break
            try:
                message = decode_task_message(datagram, self.mission_id, self.mission_digest)
            except ValueError:
                continue
            if message.sender_id not in self.member_ids or message.kind != "mission_accept":
                continue
            if message.payload.get("mission_digest") != self.mission_digest:
                continue
            previous = self._latest_sequences.get(message.sender_id)
            if previous is not None and not _is_newer_sequence(message.sequence, previous):
                continue
            self._latest_sequences[message.sender_id] = message.sequence
            self._accepted.add(message.sender_id)
        return set(self._accepted)

    def close(self) -> None:
        self._socket.close()
