"""Read-only EGO Bspline byte observation; coefficient equality is not attestation."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import time
from importlib.metadata import version
from pathlib import Path
from zipfile import ZipFile

TYPE = 'traj_utils/msg/Bspline'
DEFINITION_SHA = '6a81d3687daf49f3152f514ed5639e55374be32dd438a4f1c90900503f8e3f85'
DEFINITION_MEMBER = 'results/ego-causal-provenance-dev-1701/source/Bspline.msg'
MAX_BYTES, MAX_POINTS, MAX_RECORDS = 512 * 1024, 4096, 4096
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_NS = 2**63 - 1
CONTEXT = frozenset({'input_schedule_sha256', 'parameters_sha256', 'clock_schedule_sha256'})
NUMERIC = ('knots', 'pos_pts', 'yaw_pts', 'yaw_dt')
TOLERANCE = 1e-9


def typestore():
    if version('rosbags') != '0.11.5':
        raise ValueError('pinned rosbags0.11.5 required')
    from rosbags.typesys import Stores, get_types_from_msg, get_typestore
    archive = Path(__file__).resolve().parents[2] / 'evidence/ego-causal-provenance-dev-1701.zip'
    with ZipFile(archive) as zipped:
        definition = zipped.read(DEFINITION_MEMBER)
    if hashlib.sha256(definition).hexdigest() != DEFINITION_SHA:
        raise ValueError('pinned Bspline definition mismatch')
    store = get_typestore(Stores.ROS2_HUMBLE)
    store.register(get_types_from_msg(definition.decode('utf-8'), TYPE))
    return store


def _int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('integer out of declared range')
    return value


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('invalid digest')
    return value


def _context(value):
    if type(value) is not dict or set(value) != CONTEXT:
        raise ValueError('exact replay context required')
    return {key: _sha(item) for key, item in value.items()}


def decode(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('bounded nonempty raw CDR required')
    store = typestore()
    try:
        msg = store.deserialize_cdr(raw, TYPE)
        canonical = bytes(store.serialize_cdr(msg, TYPE))
        extra = raw[len(canonical):]
        if not raw.startswith(canonical) or len(extra) > 3 or any(extra):
            raise ValueError('noncanonical CDR')
        _int(msg.drone_id, 0, 2**31 - 1)
        _int(msg.traj_id, 1, 2**31 - 1)
        _int(msg.order, 3, 3)
        sec = _int(msg.start_time.sec, 0, 2**31 - 1)
        ns = _int(msg.start_time.nanosec, 0, 999_999_999)
        start = _int(sec * 1_000_000_000 + ns, 0, MAX_NS)
        if not 4 <= len(msg.pos_pts) <= MAX_POINTS or len(msg.knots) != len(msg.pos_pts) + 4:
            raise ValueError('cubic trajectory shape mismatch')
        if len(msg.yaw_pts) > MAX_POINTS:
            raise ValueError('yaw capacity')
        points = [[float(p.x), float(p.y), float(p.z)] for p in msg.pos_pts]
        knots = [float(v) for v in msg.knots]
        yaw = [float(v) for v in msg.yaw_pts]
        dt = float(msg.yaw_dt)
        if (not all(math.isfinite(v) for p in points for v in p)
                or not all(math.isfinite(v) for v in [*knots, *yaw, dt])
                or any(b <= a for a, b in zip(knots, knots[1:]))
                or knots[len(points)] <= knots[3] or dt < 0):
            raise ValueError('trajectory finite/domain fields refused')
    except Exception as exc:
        raise ValueError('Bspline decode/semantics refused') from exc
    return {'raw_sha256': hashlib.sha256(raw).hexdigest(), 'raw_bytes': len(raw),
            'canonical_sha256': hashlib.sha256(canonical).hexdigest(),
            'alignment_suffix_bytes': len(extra),
            'trajectory': {'drone_id': msg.drone_id, 'order': msg.order, 'traj_id': msg.traj_id,
                           'start_ns': start, 'knots': knots, 'pos_pts': points,
                           'yaw_pts': yaw, 'yaw_dt': dt}}


class Observation:
    """Single-threaded observer journal; publisher identity remains unattested."""

    def __init__(self, stream, *, run_id, session, topic, replay_context, clock=time.monotonic_ns):
        if (any(type(v) is not str or not v for v in (run_id, session, topic))
                or not topic.startswith('/') or not callable(clock)):
            raise ValueError('explicit observer identity/topic/clock required')
        self.stream, self.clock = stream, clock
        self.identity = {'run_id': run_id, 'session': session, 'topic': topic}
        self.context = _context(replay_context)
        self.sequence, self.last, self.count, self.total_bytes = 0, -1, 0, 0
        self.failed, self.closed = False, False
        self.refusal = None
        self.ids = set()
        self._append('open', replay_context=self.context, definition_sha256=DEFINITION_SHA,
                     source_attested=False)

    def _append(self, phase, **fields):
        try:
            now = _int(self.clock(), 0, MAX_NS)
            if now < self.last:
                raise ValueError('observer clock regressed')
            self.last = now
            row = {'schema': 'flydrones-ego-bspline-observer-v1', **self.identity,
                   'sequence': self.sequence, 'phase': phase, 'callback_monotonic_ns': now, **fields}
            line = json.dumps(row, allow_nan=False, separators=(',', ':')) + '\n'
            if self.stream.write(line) != len(line):
                raise ValueError('observer short write')
            self.stream.flush()
            self.sequence += 1
        except BaseException:
            self.failed = True
            raise

    def accept(self, raw):
        if self.failed or self.closed:
            raise ValueError('observer failed or closed')
        try:
            if (type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES or self.count >= MAX_RECORDS
                    or self.total_bytes + len(raw) > MAX_TOTAL_BYTES):
                self.refusal = {'reason': 'observer payload/count capacity',
                                'raw_bytes': len(raw) if type(raw) is bytes else None,
                                'prefix_bytes': min(len(raw), MAX_BYTES) if type(raw) is bytes else None,
                                'prefix_sha256': hashlib.sha256(raw[:MAX_BYTES]).hexdigest() if type(raw) is bytes else None}
                raise ValueError('observer payload/count capacity')
            self.total_bytes += len(raw)
            self._append('raw', raw_b64=base64.b64encode(raw).decode('ascii'),
                         raw_sha256=hashlib.sha256(raw).hexdigest(), raw_bytes=len(raw))
            decoded = decode(raw)
            identity = (decoded['trajectory']['drone_id'], decoded['trajectory']['traj_id'])
            if identity in self.ids:
                raise ValueError('duplicate trajectory identity')
            self._append('decoded', decoded=decoded)
            self.ids.add(identity)
            self.count += 1
        except BaseException:
            self.failed = True
            raise

    def close(self):
        if self.closed:
            return
        try:
            extra = {'refusal': self.refusal} if self.refusal is not None else {}
            self._append('failed' if self.failed or not self.count else 'closed', count=self.count, **extra)
        finally:
            self.closed = True
            # Caller owns stream; the standalone process also closes it on failure.


def completion_digest(rows):
    """Semantic journal binding; raw-file SHA is separately retained by CLI."""
    return hashlib.sha256(json.dumps(rows, allow_nan=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def audit(rows, completion=None):
    if (type(completion) is not dict or set(completion) != {'journal_semantic_sha256', 'stream_closed', 'success'}
            or completion['stream_closed'] is not True or completion['success'] is not True
            or completion['journal_semantic_sha256'] != completion_digest(rows)):
        raise ValueError('separately bound successful stream close required')
    if type(rows) is not list or not 4 <= len(rows) <= 2 * MAX_RECORDS + 2:
        raise ValueError('incomplete/capacity journal')
    first, terminal = rows[0], rows[-1]
    if type(first) is not dict or first.get('phase') != 'open' or type(terminal) is not dict:
        raise ValueError('missing journal boundary')
    context = _context(first.get('replay_context'))
    identity = {key: first.get(key) for key in ('run_id', 'session', 'topic')}
    if (any(type(v) is not str or not v for v in identity.values()) or not identity['topic'].startswith('/')
            or first.get('definition_sha256') != DEFINITION_SHA or first.get('source_attested') is not False
            or terminal.get('phase') != 'closed'):
        raise ValueError('unqualified/malformed journal boundary')
    core = {'schema', 'run_id', 'session', 'topic', 'sequence', 'phase', 'callback_monotonic_ns'}
    additions = {'open': {'replay_context', 'definition_sha256', 'source_attested'},
                 'raw': {'raw_b64', 'raw_sha256', 'raw_bytes'}, 'decoded': {'decoded'}, 'closed': {'count'}}
    last, plans, ids, pending, total = -1, [], set(), None, 0
    for index, row in enumerate(rows):
        if (type(row) is not dict or row.get('schema') != 'flydrones-ego-bspline-observer-v1'
                or row.get('sequence') != index or type(row.get('sequence')) is not int
                or any(row.get(k) != v for k, v in identity.items())
                or row.get('phase') not in additions or set(row) != core | additions[row['phase']]):
            raise ValueError('journal framing/identity mismatch')
        now = _int(row.get('callback_monotonic_ns'), 0, MAX_NS)
        if now < last:
            raise ValueError('journal clock regression')
        last = now
        if index in (0, len(rows) - 1):
            continue
        if row.get('phase') == 'raw' and pending is None:
            if type(row['raw_b64']) is not str or len(row['raw_b64']) > 4 * ((MAX_BYTES + 2) // 3):
                raise ValueError('journal CDR encoding capacity')
            try:
                raw = base64.b64decode(row['raw_b64'], validate=True)
            except Exception as exc:
                raise ValueError('journal CDR encoding') from exc
            pending = decode(raw)
            total += len(raw)
            if total > MAX_TOTAL_BYTES:
                raise ValueError('journal aggregate capacity')
            if (row['raw_b64'] != base64.b64encode(raw).decode('ascii')
                    or row.get('raw_sha256') != pending['raw_sha256']
                    or type(row.get('raw_bytes')) is not int or row['raw_bytes'] != len(raw)):
                raise ValueError('journal CDR integrity')
        elif row.get('phase') == 'decoded' and pending is not None:
            if json.dumps(row.get('decoded'), allow_nan=False, sort_keys=True) != json.dumps(pending, sort_keys=True):
                raise ValueError('journal decoded fields mismatch')
            plan = pending['trajectory']
            key = (plan['drone_id'], plan['traj_id'])
            if key in ids:
                raise ValueError('duplicate trajectory identity')
            ids.add(key)
            plans.append(plan)
            pending = None
        else:
            raise ValueError('partial/misordered journal')
    if (pending is not None or not plans or type(terminal.get('count')) is not int
            or terminal['count'] != len(plans)):
        raise ValueError('incomplete observer output')
    return identity, context, plans


def _flatten(value):
    if type(value) is list:
        return [v for item in value for v in _flatten(item)]
    return [value]


def compare(original, patched, *, original_completion=None, patched_completion=None):
    a_id, a_context, a = audit(original, original_completion)
    b_id, b_context, b = audit(patched, patched_completion)
    if a_context != b_context or a_id['topic'] != b_id['topic']:
        raise ValueError('declared replay context differs')
    differences = []
    if len(a) != len(b):
        differences.append({'field': 'plan_count', 'original': len(a), 'patched': len(b)})
    for index, (left, right) in enumerate(zip(a, b)):
        for field in ('drone_id', 'traj_id', 'order', 'start_ns', *NUMERIC):
            if field in NUMERIC:
                x, y = _flatten(left[field]), _flatten(right[field])
                if len(x) != len(y) or any(not math.isclose(p, q, rel_tol=0., abs_tol=TOLERANCE)
                                          for p, q in zip(x, y)):
                    differences.append({'plan_index': index, 'field': field, 'original': left[field], 'patched': right[field]})
            elif left[field] != right[field]:
                differences.append({'plan_index': index, 'field': field, 'original': left[field], 'patched': right[field]})
    return {'coefficient_candidate_equal': not differences, 'differences': differences,
            'plan_counts': [len(a), len(b)], 'absolute_tolerance': TOLERANCE,
            'planner_numerical_equivalence_qualified': False, 'command_yaw_timing_qualified': False,
            'replay_consumption_qualified': False, 'source_attested': False,
            'teacher_qualified': False, 'fusion_qualified': False}


def run_readonly(args, rclpy, node_type, message_type):
    """Observe DDS only; retain the first exception and every cleanup error."""
    primary, cleanup = None, []
    stream_closed, stop_reason, started = False, 'startup_failure', None
    stream, observer, node, initialized = None, None, None, False
    try:
        context = _context(json.loads(args.replay_context.read_text(encoding='utf-8')))
        typestore()
        stream = args.output.open('x', encoding='utf-8', newline='\n')
        observer = Observation(stream, run_id=args.run_id, session=args.session,
                               topic=args.topic, replay_context=context)
        rclpy.init(args=[])
        initialized = True
        node = node_type('flydrones_bspline_observer')
        node.create_subscription(message_type, args.topic, observer.accept, 100, raw=True)
        started = time.monotonic()
        deadline = started + 30.
        while time.monotonic() < deadline:
            if not rclpy.ok():
                stop_reason = 'context_ended_early'
                raise ValueError('ROS context ended before observation deadline')
            rclpy.spin_once(node, timeout_sec=min(.1, max(0., deadline - time.monotonic())))
        stop_reason = 'deadline_observed'
        if not observer.count:
            raise ValueError('no trajectory observed')
    except BaseException as exc:
        primary = exc
    finally:
        for action in ([node.destroy_node] if node is not None else []) + ([rclpy.shutdown] if initialized else []):
            try:
                action()
            except BaseException as exc:
                cleanup.append(exc)
        if observer is not None:
            observer.failed = observer.failed or primary is not None or bool(cleanup)
            try:
                observer.close()
            except BaseException as exc:
                cleanup.append(exc)
        if stream is not None:
            try:
                stream.close()
                stream_closed = True
            except BaseException as exc:
                cleanup.append(exc)
                if observer is not None:
                    observer.failed = True
        if stream is not None:
            try:
                raw = args.output.read_bytes()
                rows = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
                proof = {'journal_semantic_sha256': completion_digest(rows), 'stream_closed': stream_closed,
                         'success': primary is None and not cleanup and observer is not None and not observer.failed}
                record = {'completion': proof, 'journal_file_sha256': hashlib.sha256(raw).hexdigest(),
                          'stop_reason': stop_reason, 'window_started_monotonic': started,
                          'window_returned_monotonic': time.monotonic(),
                          'primary_error': None if primary is None else repr(primary),
                          'cleanup_errors': [repr(e) for e in cleanup]}
                final_path = args.output.with_suffix(args.output.suffix + '.completion.json')
                pending_path = args.output.with_suffix(args.output.suffix + '.completion.pending.json')
                with pending_path.open('x', encoding='utf-8') as final:
                    json.dump(record, final, allow_nan=False, indent=2)
                # A closed pending file is published without replacing any prior artifact.
                # Keep pending evidence even on failure; it is not a completion proof.
                os.link(pending_path, final_path)
            except BaseException as exc:
                cleanup.append(exc)
    if primary is not None:
        for exc in cleanup:
            if hasattr(primary, 'add_note'):
                primary.add_note(f'observer cleanup error: {type(exc).__name__}: {exc}')
        raise primary
    if cleanup:
        raise RuntimeError(f'observer cleanup failed: {cleanup!r}') from cleanup[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topic', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--replay-context', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # ROS imports are opt-in; offline audit never starts DDS or a node.
    import rclpy
    from rclpy.node import Node
    from traj_utils.msg import Bspline
    run_readonly(args, rclpy, Node, Bspline)


if __name__ == '__main__':
    main()
