from __future__ import annotations

import math
import socket
import time

import pytest

from flydrones.peer_udp import (
    PeerDatagram,
    PeerUdpConfig,
    UdpPeerNode,
    decode_peer_datagram,
    encode_peer_datagram,
)


def _free_base_port() -> int:
    for base in range(22000, 32000, 2):
        sockets = []
        try:
            for port in (base, base + 1):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind(("127.0.0.1", port))
                sockets.append(sock)
            return base
        except OSError:
            pass
        finally:
            for sock in sockets:
                sock.close()
    raise RuntimeError("no two-port UDP range available")


def test_peer_datagram_round_trip_and_validation():
    packet = PeerDatagram(
        sender_id=7,
        sequence=42,
        sent_at=12.5,
        position=(1.0, -2.0, 3.0),
        velocity=(0.5, 0.0, -0.25),
    )

    decoded = decode_peer_datagram(encode_peer_datagram(packet))

    assert decoded == packet
    with pytest.raises(ValueError):
        decode_peer_datagram(b"not-a-flydrones-packet")
    with pytest.raises(ValueError):
        encode_peer_datagram(PeerDatagram(1, 1, 0.0, (math.nan, 0.0, 0.0), (0.0, 0.0, 0.0)))


def test_two_udp_nodes_exchange_only_receiver_local_tracks():
    base_port = _free_base_port()
    config = PeerUdpConfig(latency_s=0.0, jitter_s=0.0, packet_loss=0.0, range_m=5.0, track_ttl_s=0.5)
    first = UdpPeerNode(0, [0, 1], base_port=base_port, config=config)
    second = UdpPeerNode(1, [0, 1], base_port=base_port, config=config)
    try:
        first.broadcast((0.0, 0.0, 1.8), (0.2, 0.0, 0.0), mission_elapsed_s=0.0)
        deadline = time.monotonic() + 0.5
        tracks = []
        while time.monotonic() < deadline and not tracks:
            first.poll((0.0, 0.0, 1.8))
            tracks = second.poll((1.0, 0.0, 1.8))
            time.sleep(0.005)

        assert len(tracks) == 1
        assert tracks[0].sender_id == 0
        assert tracks[0].position == pytest.approx((0.0, 0.0, 1.8))
        assert first.neighbors() == []
        assert second.metrics["received_packets"] == 1
    finally:
        first.close()
        second.close()


def test_udp_node_applies_range_blackout_loss_and_stale_expiry():
    base_port = _free_base_port()
    clock_value = [100.0]

    def clock():
        return clock_value[0]
    receiver = UdpPeerNode(
        1,
        [0, 1],
        base_port=base_port,
        config=PeerUdpConfig(range_m=0.5, latency_s=0.0, jitter_s=0.0, packet_loss=0.0, track_ttl_s=0.2),
        clock=clock,
    )
    sender = UdpPeerNode(
        0,
        [0, 1],
        base_port=base_port,
        config=PeerUdpConfig(range_m=5.0, latency_s=0.0, jitter_s=0.0, packet_loss=0.0, track_ttl_s=0.2),
        clock=clock,
    )
    try:
        sender.broadcast((0.0, 0.0, 1.8), (0.0, 0.0, 0.0), mission_elapsed_s=0.0)
        sender.poll((0.0, 0.0, 1.8))
        assert receiver.poll((2.0, 0.0, 1.8)) == []
        assert receiver.metrics["out_of_range_packets"] == 1
    finally:
        sender.close()
        receiver.close()

    blackout = UdpPeerNode(
        0,
        [0, 1],
        base_port=_free_base_port(),
        config=PeerUdpConfig(packet_loss=0.0, blackout_windows_s=((1.0, 2.0),)),
        clock=clock,
    )
    try:
        blackout.broadcast((0.0, 0.0, 1.8), (0.0, 0.0, 0.0), mission_elapsed_s=1.5)
        assert blackout.metrics["blackout_dropped_packets"] == 1
    finally:
        blackout.close()

    lossy = UdpPeerNode(
        0,
        [0, 1],
        base_port=_free_base_port(),
        config=PeerUdpConfig(packet_loss=1.0),
        clock=clock,
    )
    try:
        lossy.broadcast((0.0, 0.0, 1.8), (0.0, 0.0, 0.0), mission_elapsed_s=0.0)
        assert lossy.metrics["random_dropped_packets"] == 1
    finally:
        lossy.close()


def test_udp_track_expires_from_the_receivers_cache():
    base_port = _free_base_port()
    clock_value = [50.0]

    def clock():
        return clock_value[0]
    config = PeerUdpConfig(latency_s=0.0, jitter_s=0.0, packet_loss=0.0, range_m=5.0, track_ttl_s=0.2)
    first = UdpPeerNode(0, [0, 1], base_port=base_port, config=config, clock=clock)
    second = UdpPeerNode(1, [0, 1], base_port=base_port, config=config, clock=clock)
    try:
        first.broadcast((0.0, 0.0, 1.8), (0.0, 0.0, 0.0), mission_elapsed_s=0.0)
        first.poll((0.0, 0.0, 1.8))
        assert len(second.poll((1.0, 0.0, 1.8))) == 1

        clock_value[0] += 0.21

        assert second.poll((1.0, 0.0, 1.8)) == []
        assert second.metrics["stale_tracks_expired"] == 1
    finally:
        first.close()
        second.close()


def test_udp_poll_survives_windows_connection_reset_from_an_exited_peer():
    class ResettingSocket:
        def __init__(self, *_args):
            self.calls = 0

        def setsockopt(self, *_args):
            pass

        def bind(self, *_args):
            pass

        def setblocking(self, *_args):
            pass

        def recvfrom(self, *_args):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionResetError(10054, "peer exited")
            raise BlockingIOError

        def close(self):
            pass

    node = UdpPeerNode(0, [0, 1], base_port=25000, socket_factory=ResettingSocket)

    assert node.poll((0.0, 0.0, 0.0)) == []
    assert node.metrics["connection_reset_packets"] == 1
