"""Broker-free UDP peer telemetry for independent swarm agents."""

from __future__ import annotations

import heapq
import math
import random
import socket
import struct
import time
from dataclasses import dataclass

_MAGIC = b"FDP1"
_VERSION = 1
_PACKET = struct.Struct("!4sBHI d 6f")


@dataclass(frozen=True)
class PeerDatagram:
    sender_id: int
    sequence: int
    sent_at: float
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]


@dataclass(frozen=True)
class PeerTrack:
    sender_id: int
    sequence: int
    sent_at: float
    received_at: float
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]


@dataclass(frozen=True)
class PeerUdpConfig:
    range_m: float = 8.0
    latency_s: float = 0.12
    jitter_s: float = 0.04
    packet_loss: float = 0.15
    track_ttl_s: float = 0.65
    blackout_windows_s: tuple[tuple[float, float], ...] = ()
    seed: int = 20260921

    def __post_init__(self) -> None:
        if self.range_m <= 0.0 or self.track_ttl_s <= 0.0:
            raise ValueError("range and track TTL must be positive")
        if self.latency_s < 0.0 or self.jitter_s < 0.0:
            raise ValueError("latency and jitter cannot be negative")
        if not 0.0 <= self.packet_loss <= 1.0:
            raise ValueError("packet loss must be between zero and one")
        if any(start < 0.0 or end < start for start, end in self.blackout_windows_s):
            raise ValueError("invalid blackout window")


def _finite_vector(values: tuple[float, float, float]) -> bool:
    return len(values) == 3 and all(math.isfinite(float(value)) for value in values)


def encode_peer_datagram(packet: PeerDatagram) -> bytes:
    if not 0 <= int(packet.sender_id) <= 0xFFFF:
        raise ValueError("sender id is outside the wire range")
    if not 0 <= int(packet.sequence) <= 0xFFFFFFFF:
        raise ValueError("sequence is outside the wire range")
    if not math.isfinite(float(packet.sent_at)) or not _finite_vector(packet.position) or not _finite_vector(packet.velocity):
        raise ValueError("peer packet contains a non-finite value")
    return _PACKET.pack(
        _MAGIC,
        _VERSION,
        int(packet.sender_id),
        int(packet.sequence),
        float(packet.sent_at),
        *(float(value) for value in (*packet.position, *packet.velocity)),
    )


def decode_peer_datagram(payload: bytes) -> PeerDatagram:
    if len(payload) != _PACKET.size:
        raise ValueError("invalid peer packet length")
    magic, version, sender_id, sequence, sent_at, *values = _PACKET.unpack(payload)
    if magic != _MAGIC or version != _VERSION:
        raise ValueError("invalid peer packet header")
    packet = PeerDatagram(
        sender_id=int(sender_id),
        sequence=int(sequence),
        sent_at=float(sent_at),
        position=tuple(float(value) for value in values[:3]),
        velocity=tuple(float(value) for value in values[3:]),
    )
    if not math.isfinite(packet.sent_at) or not _finite_vector(packet.position) or not _finite_vector(packet.velocity):
        raise ValueError("peer packet contains a non-finite value")
    return packet


class UdpPeerNode:
    """One vehicle's UDP endpoint and receiver-local peer track cache."""

    def __init__(
        self,
        vehicle_id: int,
        peer_ids: list[int] | tuple[int, ...],
        *,
        base_port: int,
        config: PeerUdpConfig | None = None,
        bind_host: str = "127.0.0.1",
        peer_host: str = "127.0.0.1",
        clock=time.monotonic,
        socket_factory=socket.socket,
    ) -> None:
        ids = tuple(sorted(set(int(peer_id) for peer_id in peer_ids)))
        if vehicle_id not in ids:
            raise ValueError("vehicle id must be included in peer ids")
        if not 0 < base_port <= 65535 or base_port + max(ids) > 65535:
            raise ValueError("peer UDP port range is invalid")
        self.vehicle_id = int(vehicle_id)
        self.peer_ids = ids
        self.base_port = int(base_port)
        self.config = config or PeerUdpConfig()
        self.peer_host = peer_host
        self._clock = clock
        self._random = random.Random(self.config.seed + self.vehicle_id * 1009)
        self._socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((bind_host, self.base_port + self.vehicle_id))
        self._socket.setblocking(False)
        self._sequence = 0
        self._pending: list[tuple[float, int, int, bytes]] = []
        self._tracks: dict[int, PeerTrack] = {}
        self.metrics = {
            "attempted_packets": 0,
            "sent_packets": 0,
            "random_dropped_packets": 0,
            "blackout_dropped_packets": 0,
            "received_packets": 0,
            "malformed_packets": 0,
            "out_of_range_packets": 0,
            "stale_tracks_expired": 0,
            "out_of_order_packets": 0,
        }

    def _in_blackout(self, mission_elapsed_s: float) -> bool:
        return any(start <= mission_elapsed_s <= end for start, end in self.config.blackout_windows_s)

    def broadcast(
        self,
        position: tuple[float, float, float],
        velocity: tuple[float, float, float],
        *,
        mission_elapsed_s: float,
    ) -> None:
        now = float(self._clock())
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        payload = encode_peer_datagram(PeerDatagram(self.vehicle_id, self._sequence, now, tuple(position), tuple(velocity)))
        blackout = self._in_blackout(float(mission_elapsed_s))
        for peer_id in self.peer_ids:
            if peer_id == self.vehicle_id:
                continue
            self.metrics["attempted_packets"] += 1
            if blackout:
                self.metrics["blackout_dropped_packets"] += 1
                continue
            if self._random.random() < self.config.packet_loss:
                self.metrics["random_dropped_packets"] += 1
                continue
            jitter = self._random.uniform(-self.config.jitter_s, self.config.jitter_s)
            due_at = now + max(0.0, self.config.latency_s + jitter)
            heapq.heappush(self._pending, (due_at, peer_id, self._sequence, payload))
        self._flush(now)

    def _flush(self, now: float) -> None:
        while self._pending and self._pending[0][0] <= now:
            _due_at, peer_id, _sequence, payload = heapq.heappop(self._pending)
            self._socket.sendto(payload, (self.peer_host, self.base_port + peer_id))
            self.metrics["sent_packets"] += 1

    def poll(self, own_position: tuple[float, float, float], *, now: float | None = None) -> list[PeerTrack]:
        timestamp = float(self._clock() if now is None else now)
        self._flush(timestamp)
        while True:
            try:
                payload, _address = self._socket.recvfrom(max(2048, _PACKET.size))
            except BlockingIOError:
                break
            try:
                packet = decode_peer_datagram(payload)
            except ValueError:
                self.metrics["malformed_packets"] += 1
                continue
            if packet.sender_id == self.vehicle_id or packet.sender_id not in self.peer_ids:
                self.metrics["malformed_packets"] += 1
                continue
            if math.dist(tuple(float(value) for value in own_position), packet.position) > self.config.range_m:
                self.metrics["out_of_range_packets"] += 1
                continue
            previous = self._tracks.get(packet.sender_id)
            if previous is not None and packet.sequence <= previous.sequence:
                self.metrics["out_of_order_packets"] += 1
                continue
            self._tracks[packet.sender_id] = PeerTrack(
                sender_id=packet.sender_id,
                sequence=packet.sequence,
                sent_at=packet.sent_at,
                received_at=timestamp,
                position=packet.position,
                velocity=packet.velocity,
            )
            self.metrics["received_packets"] += 1
        expired = [
            sender_id
            for sender_id, track in self._tracks.items()
            if timestamp - track.received_at > self.config.track_ttl_s
        ]
        for sender_id in expired:
            del self._tracks[sender_id]
            self.metrics["stale_tracks_expired"] += 1
        return self.neighbors()

    def neighbors(self) -> list[PeerTrack]:
        return [self._tracks[sender_id] for sender_id in sorted(self._tracks)]

    def close(self) -> None:
        self._socket.close()
