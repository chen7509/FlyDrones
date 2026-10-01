"""Upstream EGO-Swarm adapter over a narrow observation/reference socket."""

from __future__ import annotations

import json
import socket
import struct
import time

import numpy as np

from .contract import Command, Decision, Observation
from .sensors import encode_observation


REFERENCE_FIELDS = {'sim_ns', 'upstream_stamp_ns', 'position_ref', 'velocity_ref', 'yaw_rate'}


def track_reference(position_ref: tuple, velocity_ref: tuple, position: tuple, yaw_rate: float, gain: float) -> Command:
    values = np.asarray((*position_ref, *velocity_ref, *position, yaw_rate, gain), dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError('reference values must be finite')
    requested = np.asarray(velocity_ref, dtype=float) + float(gain) * (
        np.asarray(position_ref, dtype=float) - np.asarray(position, dtype=float)
    )
    return Command(tuple(float(value) for value in requested), float(yaw_rate))


def validate_reference(message: dict, *, observation_sim_ns: int, max_age_ns: int) -> dict:
    if not isinstance(message, dict) or set(message) != REFERENCE_FIELDS:
        raise ValueError('unexpected EGO reference fields')
    if type(message['sim_ns']) is not int:
        raise ValueError('reference timestamp must be integer nanoseconds')
    if type(message['upstream_stamp_ns']) is not int:
        raise ValueError('upstream timestamp must be integer nanoseconds')
    age = observation_sim_ns - message['sim_ns']
    if age < 0:
        raise ValueError('future EGO reference')
    if age > max_age_ns:
        raise ValueError('stale EGO reference')
    for field in ('position_ref', 'velocity_ref'):
        if not isinstance(message[field], list) or len(message[field]) != 3:
            raise ValueError(f'invalid {field}')
    numeric = np.asarray((*message['position_ref'], *message['velocity_ref'], message['yaw_rate']), dtype=float)
    if not np.all(np.isfinite(numeric)):
        raise ValueError('reference values must be finite')
    return message


def _send_packet(stream: socket.socket, payload: bytes) -> None:
    stream.sendall(struct.pack('!I', len(payload)) + payload)


def _recv_exact(stream: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.recv(remaining)
        if not chunk:
            raise ConnectionError('EGO adapter socket closed')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _recv_packet(stream: socket.socket) -> bytes:
    size = struct.unpack('!I', _recv_exact(stream, 4))[0]
    if not 0 < size <= 8_000_000:
        raise ValueError('invalid EGO adapter packet size')
    return _recv_exact(stream, size)


class EgoController:
    def __init__(self, endpoint: str, config: dict):
        host, port = endpoint.rsplit(':', 1)
        self.address = (host, int(port))
        self.gain = float(config['ego']['tracking_gain'])
        self.timeout_s = float(config['ego'].get('response_timeout_s', 10.0))
        self.max_age_ns = int(config['ego'].get('reference_max_age_ns', 100_000_000))
        self.stream: socket.socket | None = None

    def reset(self, seed: int) -> None:
        self.close()
        self.stream = socket.create_connection(self.address, timeout=self.timeout_s)
        self.stream.settimeout(self.timeout_s)
        _send_packet(self.stream, json.dumps({'type': 'reset', 'seed': int(seed)}).encode())
        response = json.loads(_recv_packet(self.stream))
        if response != {'status': 'ready'}:
            raise RuntimeError(f'EGO adapter reset failed: {response}')

    def step(self, obs: Observation) -> Decision:
        if self.stream is None:
            raise RuntimeError('EGO controller has not been reset')
        started = time.perf_counter()
        _send_packet(self.stream, encode_observation(obs))
        message = validate_reference(
            json.loads(_recv_packet(self.stream)),
            observation_sim_ns=obs.sim_ns,
            max_age_ns=self.max_age_ns,
        )
        command = track_reference(
            tuple(message['position_ref']), tuple(message['velocity_ref']),
            obs.position, message['yaw_rate'], self.gain,
        )
        elapsed = time.perf_counter() - started
        return Decision(command, elapsed, {
            'controller': 'ego',
            'reference': message,
            'tracking_gain': self.gain,
            'response_wall_s': elapsed,
            'input_fields': [field for field in obs.__dataclass_fields__],
        })

    def close(self) -> None:
        if self.stream is not None:
            try:
                self.stream.close()
            finally:
                self.stream = None
