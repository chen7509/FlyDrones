"""One declared, non-controlling per-socket RX startup observation.

Missing metadata is retained here; it never recovers a production receiver.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import re
import secrets
import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.benchmark import probe_kernel_rx_timestamping as prior  # noqa: E402
from tools.benchmark.kernel_rx_timestamping import KernelRXTimestamping  # noqa: E402
from tools.benchmark.probe_kernel_datagram_arrival import close_owned, read_static, snapshot  # noqa: E402

SOURCES = ('tools/benchmark/observe_kernel_rx_startup.py', *prior.SOURCES)
CONDITIONS = {
    'schema': 'flydrones.rx_startup_observer.v1', 'run_id': 'opaque-rx-startup-observer-v1',
    'count': 8, 'gap_ns': 50_000_000, 'hold_ns': 20_000_000, 'poll_ns': 200_000_000,
    'inner_ns': 5_000_000_000, 'outer_timeout_s': 20, 'outer_kill_after_s': 2,
    'local': ['127.0.0.1', 0], 'peer': ['127.0.0.1', 0],
    'abi_path': prior.ABI_PATH, 'probe_path': prior.PROBE_PATH,
}
MAX_NS = 2**63 - 1


def _exact(value, expected):
    return (type(value) is type(expected) and (len(value) == len(expected)
        and all(_exact(a, b) for a, b in zip(value, expected))
        if type(expected) is list else value == expected))


def check_module_origins():
    origins = {}
    for name in SOURCES:
        if not name.endswith('.py'):
            continue
        module = sys.modules[__name__] if name == SOURCES[0] else importlib.import_module(name[:-3].replace('/', '.'))
        path = Path(module.__file__).resolve()
        if path != (ROOT / name).resolve():
            raise ValueError('observer module outside frozen root: ' + name)
        origins[name] = str(path)
    return origins


def validate_profile(raw, digest, root=ROOT):
    if type(raw) is not bytes or not 1 <= len(raw) <= 16_384 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('observer profile identity/size')
    profile = json.loads(raw, object_pairs_hook=prior._pairs,
        parse_constant=lambda _x: (_ for _ in ()).throw(ValueError('profile constant')))
    if (type(profile) is not dict or profile.keys() != CONDITIONS.keys() | {'sources', 'abi_sha256', 'probe_sha256'}
            or any(not _exact(profile[key], value) for key, value in CONDITIONS.items())):
        raise ValueError('observer frozen conditions drift')
    if (profile['abi_sha256'] != prior.ABI_SHA or profile['probe_sha256'] != prior.PROBE_SHA
            or type(profile['sources']) is not dict or profile['sources'].keys() != set(SOURCES)):
        raise ValueError('observer capability/source declaration drift')
    for name, digest in profile['sources'].items():
        if type(digest) is not str or hashlib.sha256(read_static(Path(root) / name)).hexdigest() != digest:
            raise ValueError('observer source drift: ' + name)
    for name, digest in ((prior.ABI_PATH, prior.ABI_SHA), (prior.PROBE_PATH, prior.PROBE_SHA)):
        if hashlib.sha256(read_static(Path(root) / name)).hexdigest() != digest:
            raise ValueError('observer selected capability drift')
    KernelRXTimestamping(read_static(Path(root) / prior.ABI_PATH), prior.ABI_SHA)
    return profile


def decode_observation(ancillary, flags, after_ns):
    """Stateless exact ABI observation, deliberately no receiver authority."""
    result = {'timestamp_ns': None, 'reason': None}
    if (type(flags) is not int or flags != 0 or type(ancillary) is not list or len(ancillary) != 1
            or type(ancillary[0]) is not tuple or len(ancillary[0]) != 3):
        return dict(result, reason='missing_duplicate_or_invalid_flags')
    level, kind, data = ancillary[0]
    if (type(level) is not int or level != 1 or type(kind) is not int or kind != 65
            or type(data) is not bytes or len(data) != 48):
        return dict(result, reason='ancillary_type_or_length')
    sec, ns, *other = struct.unpack('<6q', data)
    if sec <= 0 or not 0 <= ns < 1_000_000_000 or any(other):
        return dict(result, reason='nonsoftware_or_invalid_value')
    value = sec * 1_000_000_000 + ns
    if (value > MAX_NS or type(after_ns) is not int or not 0 < after_ns <= MAX_NS
            or value > after_ns):
        return dict(result, reason='future_overflow_or_invalid_realtime')
    return dict(result, timestamp_ns=value)


def collect_trace(receiver, sender, stamps, profile, *, peer, destination, nonce, journal,
                  monotonic_ns=time.monotonic_ns, realtime_ns=time.time_ns, sleep=time.sleep,
                  guard=lambda: None):
    """Only raw observations; a failed syscall/identity/clock stops new sends."""
    result = {'status': 'running', 'packets': [], 'errors': [], 'metadata_present_indices': [],
              'production_would_refuse_at': None, 'arrival_qualified': False, 'clock_qualified': False,
              'source_authenticated': False, 'fusion_qualified': False, 'training_eligible': False}
    last_mono = last_real = last_stamp = previous_send = None
    try:
        if (type(profile) is not dict or any(not _exact(profile.get(k), v) for k, v in CONDITIONS.items())
                or type(nonce) is not str or re.fullmatch('[0-9a-f]{32}', nonce) is None):
            raise ValueError('observer trace conditions/nonce invalid')
        start = monotonic_ns()
        if type(start) is not int or not 0 < start <= MAX_NS:
            raise ValueError('invalid observer start clock')
        last_mono = start

        def mono():
            nonlocal last_mono
            value = monotonic_ns()
            if type(value) is not int or not last_mono <= value <= MAX_NS:
                raise ValueError('observer monotonic clock regressed/invalid')
            last_mono = value
            if value - start >= profile['inner_ns']:
                raise TimeoutError('observer inner bound')
            return value

        def real():
            nonlocal last_real
            value = realtime_ns()
            if (type(value) is not int or not 0 < value <= MAX_NS
                    or last_real is not None and value < last_real):
                raise ValueError('observer realtime clock regressed/invalid')
            last_real = value
            return value

        def emit(row):
            if journal(copy.deepcopy(row)) is not None:
                raise ValueError('observer journal completion must be None')
            mono()  # Include synchronous journal time, even the final record.

        def check():
            if guard() is not None:
                raise ValueError('observer guard completion must be None')
            stamps.check(receiver)

        def until(deadline):
            now = mono()
            if now < deadline:
                sleep((deadline-now)/1_000_000_000)
            if mono() < deadline:
                raise ValueError('observer pacing sleep returned early')

        for index in range(profile['count']):
            if previous_send is not None:
                until(previous_send + profile['gap_ns'])
            check()
            payload = f'FLYD_RX_STARTUP_V1:{nonce}:{index}'.encode()
            row = {'index': index, 'payload_hex': payload.hex(), 'send_returned': False,
                   'recv_returned': False, 'metadata': None, 'phase': 'send_attempt'}
            result['packets'].append(row)
            row['attempt_monotonic_ns'], row['attempt_realtime_ns'] = mono(), real()
            emit(row)
            check()
            row['send_start_realtime_ns'], row['send_start_monotonic_ns'] = real(), mono()
            previous_send = row['send_start_monotonic_ns']
            size = sender.sendto(payload, destination)
            row.update(send_returned=True, sent_bytes=size, phase='send_return')
            emit(row)  # Preserve syscall success before invoking another clock.
            row['send_return_monotonic_ns'], row['send_return_realtime_ns'] = mono(), real()
            if type(size) is not int or size != len(payload):
                raise ValueError('observer send incomplete')
            check()
            until(row['send_return_monotonic_ns'] + profile['hold_ns'])
            row['recv_start_monotonic_ns'], row['recv_start_realtime_ns'] = mono(), real()
            deadline = row['recv_start_monotonic_ns'] + profile['poll_ns']
            while True:
                check()
                if mono() >= deadline:
                    raise TimeoutError('observer receive bound')
                try:
                    data, ancillary, flags, address = receiver.recvmsg(4096, 64, 64)
                    break
                except BlockingIOError:
                    sleep(.001)
            row.update(recv_returned=True, received_payload_hex=data.hex(), flags=flags,
                       received_peer=list(address), phase='recv_return',
                       ancillary_raw=[{'level': level, 'type': kind, 'data_hex': raw.hex()}
                                      for level, kind, raw in ancillary])
            emit(row)
            row['recv_return_monotonic_ns'], row['recv_return_realtime_ns'] = mono(), real()
            if row['recv_return_monotonic_ns'] >= deadline:
                raise TimeoutError('observer receive return exceeded poll bound')
            check()
            if data != payload or address != peer or type(flags) is not int or flags != 0:
                raise ValueError('observer payload/peer/flags mismatch')
            row['metadata'] = decode_observation(ancillary, flags, row['recv_return_realtime_ns'])
            value = row['metadata']['timestamp_ns']
            row['timestamp_order_valid'] = value is None or last_stamp is None or value >= last_stamp
            if value is not None:
                result['metadata_present_indices'].append(index)
                row['send_receive_bracket_valid'] = row['send_start_realtime_ns'] <= value <= row['recv_return_realtime_ns']
                row['generated_before_read'] = value <= row['recv_start_realtime_ns']
                row['realtime_queue_lower_ns'] = row['recv_start_realtime_ns'] - value if row['generated_before_read'] else None
                last_stamp = value
            if (value is None or not row['timestamp_order_valid']) and result['production_would_refuse_at'] is None:
                result['production_would_refuse_at'] = index
            row['phase'] = 'observed'
            emit(row)
        result['status'] = 'observed'
    except BaseException as error:
        result['status'] = 'failed'
        result['errors'].append(repr(error))
    return result


def _write(stream, value):
    raw = json.dumps(value, allow_nan=False, sort_keys=True) + '\n'
    if stream.write(raw) != len(raw):
        raise OSError('observer journal short write')
    if stream.flush() is not None:
        raise OSError('observer journal flush completion invalid')


def run(profile, output, *, profile_path, profile_sha256):
    origins = check_module_origins()
    if validate_profile(read_static(profile_path), profile_sha256) != profile:
        raise ValueError('observer profile differs from file')
    output = Path(output)
    output.mkdir(exist_ok=False)
    result = {'status': 'failed', 'errors': [], 'owned_close': [], 'module_origins': origins,
              'profile_sha256': profile_sha256, 'pid': os.getpid(), 'production_parser_used': False,
              'arrival_qualified': False, 'clock_qualified': False, 'source_authenticated': False,
              'fusion_qualified': False, 'training_eligible': False}
    live = []
    journal = None
    stamps = None
    try:
        journal = (output / 'packets.jsonl').open('x', encoding='utf-8')
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        live.append(receiver)
        stamps = KernelRXTimestamping(read_static(ROOT / prior.ABI_PATH), prior.ABI_SHA)
        result['enable_started_ns'] = time.monotonic_ns()
        stamps.enable_before_bind(receiver)
        result['enable_return_ns'] = time.monotonic_ns()
        receiver.bind(tuple(profile['local']))
        receiver.setblocking(False)
        rx_identity = snapshot(receiver)
        result['receiver_identity'] = rx_identity
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        live.append(sender)
        sender.bind(tuple(profile['peer']))
        sender.settimeout(.1)
        tx_identity = snapshot(sender)
        result.update(sender_identity=tx_identity, nonce=secrets.token_hex(16))

        def guard():
            if snapshot(receiver) != rx_identity or snapshot(sender) != tx_identity:
                raise ValueError('owned observer socket identity changed')

        result.update(collect_trace(receiver, sender, stamps, profile,
            peer=tuple(tx_identity['local']), destination=tuple(rx_identity['local']), nonce=result['nonce'],
            journal=lambda row: _write(journal, row), guard=guard))
        result['prepared_profile_evidence'] = stamps.evidence
    except BaseException as error:
        result['status'] = 'failed'
        result['errors'].append(repr(error))
    finally:
        if stamps is not None:
            try:
                result['prepared_profile_evidence'] = stamps.evidence
            except BaseException as error:
                result['status'] = 'failed'
                result['errors'].append(repr(error))
        for sock in reversed(live):
            try:
                close_owned(sock, result['owned_close'])
            except BaseException as error:
                result['status'] = 'failed'
                result['errors'].append(repr(error))
        if journal is not None:
            try:
                journal.close()
            except BaseException as error:
                result['status'] = 'failed'
                result['errors'].append(repr(error))
        try:
            result['profile_post_verified'] = validate_profile(read_static(profile_path), profile_sha256) == profile
        except BaseException as error:
            result['status'] = 'failed'
            result['errors'].append(repr(error))
        with (output / 'result.json').open('x', encoding='utf-8') as stream:
            _write(stream, result)
    if result['status'] != 'observed':
        raise RuntimeError('observer failed; no retry')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    profile = validate_profile(read_static(args.profile), args.profile_sha256)
    run(profile, args.output, profile_path=args.profile, profile_sha256=args.profile_sha256)


if __name__ == '__main__':
    main()
