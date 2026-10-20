import base64
import copy
import io
import json
from types import SimpleNamespace

import numpy as np
import pytest

from tools.benchmark import ego_bspline_observation as bs


def payload(traj_id=1, offset=0.0):
    store = bs.typestore()
    point = store.types['geometry_msgs/msg/Point']
    stamp = store.types['builtin_interfaces/msg/Time']
    msg = store.types[bs.TYPE](0, 3, traj_id, stamp(2, 0),
        np.arange(8, dtype=np.float64) * .1,
        [point(float(i) + offset, 0., 1.) for i in range(4)],
        np.array([], dtype=np.float64), 0.)
    return bytes(store.serialize_cdr(msg, bs.TYPE))


def context():
    return {key: '1'*64 for key in bs.CONTEXT}


def journal(packets=None):
    stream = io.StringIO()
    ticks = iter(range(100, 1000))
    obs = bs.Observation(stream, run_id='original', session='s1', topic='/planning/bspline',
                         replay_context=context(), clock=lambda: next(ticks))
    for raw in [payload()] if packets is None else packets:
        obs.accept(raw)
    obs.close()
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def proof(rows):
    # Synthetic caller-owned StringIO completion, not runtime provenance.
    return {'journal_semantic_sha256': bs.completion_digest(rows), 'stream_closed': True, 'success': True}


def compare(a, b):
    return bs.compare(a, b, original_completion=proof(a), patched_completion=proof(b))


def test_actual_cdr_and_padding_preserve_both_digests():
    raw = payload()
    decoded = bs.decode(raw)
    assert decoded['trajectory']['pos_pts'][2] == [2., 0., 1.]
    padded = bs.decode(raw + b'\0\0\0')
    assert padded['canonical_sha256'] == decoded['raw_sha256']
    assert padded['raw_sha256'] != padded['canonical_sha256']
    for suffix in (b'x', b'\0'*4):
        with pytest.raises(ValueError):
            bs.decode(raw + suffix)


def test_payload_limits_and_id_range():
    for raw in (b'', b'a' * (bs.MAX_BYTES + 1), payload(traj_id=2**31), payload(traj_id=0)):
        with pytest.raises(ValueError):
            bs.decode(raw)


def test_equal_candidate_never_grants_runtime_or_teacher():
    rows = journal()
    result = compare(rows, copy.deepcopy(rows))
    assert result['coefficient_candidate_equal']
    assert not result['planner_numerical_equivalence_qualified']
    assert not result['teacher_qualified']


def test_interior_control_change_retained():
    result = compare(journal(), journal([payload(offset=.1)]))
    assert not result['coefficient_candidate_equal']
    assert result['differences'][0]['field'] == 'pos_pts'


@pytest.mark.parametrize('mutation', ['raw', 'fields', 'context', 'sequence', 'close', 'failed'])
def test_tampering_and_incomplete_refused(mutation):
    a = journal()
    b = copy.deepcopy(a)
    if mutation == 'raw':
        b[1]['raw_b64'] = base64.b64encode(b'bad').decode()
    elif mutation == 'fields':
        b[2]['decoded']['trajectory']['pos_pts'][0][0] += 1
    elif mutation == 'context':
        b[0]['replay_context']['input_schedule_sha256'] = '2'*64
    elif mutation == 'sequence':
        b[1]['sequence'] += 1
    elif mutation == 'close':
        b.pop()
    else:
        b[-1]['phase'] = 'failed'
    with pytest.raises(ValueError):
        compare(a, b)


def test_rejection_retains_raw_and_latches():
    stream = io.StringIO()
    obs = bs.Observation(stream, run_id='r', session='s', topic='/x', replay_context=context(), clock=lambda: 10)
    with pytest.raises(ValueError):
        obs.accept(b'bad')
    assert obs.failed
    assert base64.b64decode(json.loads(stream.getvalue().splitlines()[1])['raw_b64']) == b'bad'
    with pytest.raises(ValueError):
        obs.accept(payload())
    obs.close()
    assert json.loads(stream.getvalue().splitlines()[-1])['phase'] == 'failed'


def test_duplicate_id_not_silently_dropped():
    with pytest.raises(ValueError):
        journal([payload(), payload()])


def test_observation_clock_regression_refused():
    stream = io.StringIO()
    ticks = iter([10, 9])
    obs = bs.Observation(stream, run_id='r', session='s', topic='/x', replay_context=context(), clock=lambda: next(ticks))
    with pytest.raises(ValueError):
        obs.accept(payload())
    assert obs.failed


def test_boolean_redundant_numeric_metadata_refused():
    rows = journal()
    other = copy.deepcopy(rows)
    other[2]['decoded']['trajectory']['traj_id'] = True
    with pytest.raises(ValueError):
        compare(rows, other)


def test_unknown_journal_field_cannot_be_smuggled():
    rows = journal()
    rows[2]['teacher_qualified'] = True
    with pytest.raises(ValueError):
        bs.audit(rows, proof(rows))


@pytest.mark.parametrize('field', ['knots', 'yaw_pts', 'start_time', 'pos_pts'])
def test_distinct_full_trajectory_fields_are_compared(field):
    raw = payload()
    store = bs.typestore()
    msg = store.deserialize_cdr(raw, bs.TYPE)
    if field == 'knots':
        msg.knots = msg.knots.copy()
        msg.knots[4] += .01
    elif field == 'yaw_pts':
        msg.yaw_pts = np.array([.5], dtype=np.float64)
    elif field == 'start_time':
        msg.start_time.nanosec = 1
    else:
        # Interior differs while endpoints of the control polygon stay equal.
        msg.pos_pts[1].z += .1
    changed = bytes(store.serialize_cdr(msg, bs.TYPE))
    assert not compare(journal(), journal([changed]))['coefficient_candidate_equal']


@pytest.mark.parametrize('field', ['knots', 'pos_pts', 'order'])
def test_invalid_cdr_semantics_refused(field):
    store = bs.typestore()
    msg = store.deserialize_cdr(payload(), bs.TYPE)
    if field == 'knots':
        msg.knots = msg.knots.copy()
        msg.knots[1] = msg.knots[0]
    elif field == 'pos_pts':
        msg.pos_pts[0].x = float('nan')
    else:
        msg.order = 2
    with pytest.raises(ValueError):
        bs.decode(bytes(store.serialize_cdr(msg, bs.TYPE)))


@pytest.mark.parametrize('mode', ['short', 'flush'])
def test_writer_failure_latches(mode):
    class Broken(io.StringIO):
        def write(self, value):
            size = super().write(value)
            return size - 1 if mode == 'short' else size

        def flush(self):
            if mode == 'flush':
                raise OSError('disk')
            return super().flush()

    with pytest.raises((ValueError, OSError)):
        bs.Observation(Broken(), run_id='r', session='s', topic='/x',
                       replay_context=context(), clock=lambda: 1)


@pytest.mark.parametrize('failure', [None, 'empty', 'spin', 'destroy', 'shutdown'])
def test_readonly_runtime_cleanup_and_no_publisher(tmp_path, monkeypatch, failure):
    events = []
    class Node:
        def __init__(self, name):
            self.callback = None

        def create_subscription(self, msg_type, topic, callback, qos, *, raw):
            assert raw is True and topic == '/x'
            self.callback = callback
            events.append('subscribe')

        def destroy_node(self):
            events.append('destroy')
            if failure == 'destroy':
                raise OSError('destroy failure')

    class Runtime:
        spinning = True

        @staticmethod
        def init(*, args):
            events.append('init')

        @staticmethod
        def shutdown():
            events.append('shutdown')
            if failure == 'shutdown':
                raise OSError('shutdown failure')

        def ok(self):
            return self.spinning

        def spin_once(self, node, timeout_sec):
            self.spinning = False
            if failure == 'spin':
                raise ValueError('primary spin')
            if failure != 'empty':
                node.callback(payload())

    declaration = tmp_path / 'context.json'
    declaration.write_text(json.dumps(context()))
    output = tmp_path / 'rows.jsonl'
    args = SimpleNamespace(replay_context=declaration, output=output, run_id='r', session='s', topic='/x')
    clock = iter([0., 0., 0., 31., 31.])
    monkeypatch.setattr(bs.time, 'monotonic', lambda: next(clock))
    if failure:
        with pytest.raises((ValueError, RuntimeError)):
            bs.run_readonly(args, Runtime(), Node, object)
    else:
        bs.run_readonly(args, Runtime(), Node, object)
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert rows[-1]['phase'] == ('failed' if failure else 'closed')
    assert events == ['init', 'subscribe', 'destroy', 'shutdown']
    completion = json.loads(output.with_suffix('.jsonl.completion.json').read_text())['completion']
    if failure:
        with pytest.raises(ValueError):
            bs.audit(rows, completion)
    else:
        bs.audit(rows, completion)
    with pytest.raises(FileExistsError):
        bs.run_readonly(args, Runtime(), Node, object)


def test_normal_journal_without_close_proof_refused():
    rows = journal()
    with pytest.raises(ValueError):
        bs.audit(rows)
    with pytest.raises(ValueError):
        bs.compare(rows, rows)


def test_capacity_retains_bounded_refusal_not_full_oversize_payload():
    stream = io.StringIO()
    observer = bs.Observation(stream, run_id='r', session='s', topic='/x',
                              replay_context=context(), clock=lambda: 1)
    with pytest.raises(ValueError):
        observer.accept(b'x' * (bs.MAX_BYTES + 1))
    observer.close()
    terminal = json.loads(stream.getvalue().splitlines()[-1])
    assert terminal['phase'] == 'failed'
    assert terminal['refusal']['raw_bytes'] == bs.MAX_BYTES + 1
    assert terminal['refusal']['prefix_bytes'] == bs.MAX_BYTES
    assert len(stream.getvalue()) < 1000


def test_close_failure_cannot_use_previous_closed_terminal(tmp_path, monkeypatch):
    path = tmp_path / 'rows.jsonl'
    declaration = tmp_path / 'context.json'
    declaration.write_text(json.dumps(context()))
    original_open = type(path).open
    class BrokenClose:
        def __init__(self, stream):
            self.stream = stream
        def write(self, value):
            return self.stream.write(value)
        def flush(self):
            return self.stream.flush()
        def close(self):
            self.stream.close()
            raise OSError('close failed after previous terminal')
    def patched_open(self, *args, **kwargs):
        stream = original_open(self, *args, **kwargs)
        return BrokenClose(stream) if self == path and args and args[0] == 'x' else stream
    monkeypatch.setattr(type(path), 'open', patched_open)
    clock = iter([0., 0., 0., 31., 31.])
    monkeypatch.setattr(bs.time, 'monotonic', lambda: next(clock))
    class Node:
        def __init__(self, name):
            pass
        def create_subscription(self, msg, topic, callback, qos, raw):
            self.callback = callback
        def destroy_node(self):
            pass
    runtime = SimpleNamespace(init=lambda args: None, ok=lambda: True, shutdown=lambda: None,
                              spin_once=lambda node, timeout_sec: node.callback(payload()))
    args = SimpleNamespace(replay_context=declaration, output=path, run_id='r', session='s', topic='/x')
    with pytest.raises(RuntimeError, match='cleanup failed'):
        bs.run_readonly(args, runtime, Node, object)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[-1]['phase'] == 'closed'  # Raw historical terminal remains, never rewritten.
    completion = json.loads(path.with_suffix('.jsonl.completion.json').read_text())['completion']
    assert completion['stream_closed'] is False and completion['success'] is False
    with pytest.raises(ValueError):
        bs.audit(rows, completion)


def test_completion_close_failure_does_not_publish_success(tmp_path, monkeypatch):
    path = tmp_path / 'rows.jsonl'
    declaration = tmp_path / 'context.json'
    declaration.write_text(json.dumps(context()))
    original_open = type(path).open
    class BrokenProofClose:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self.stream
        def __exit__(self, *args):
            self.stream.close()
            raise OSError('completion close failed')
    def patched_open(self, *args, **kwargs):
        stream = original_open(self, *args, **kwargs)
        if self.name.endswith('.completion.pending.json') and args and args[0] == 'x':
            return BrokenProofClose(stream)
        return stream
    monkeypatch.setattr(type(path), 'open', patched_open)
    clock = iter([0., 0., 0., 31., 31.])
    monkeypatch.setattr(bs.time, 'monotonic', lambda: next(clock))
    class Node:
        def __init__(self, name):
            pass
        def create_subscription(self, msg, topic, callback, qos, raw):
            self.callback = callback
        def destroy_node(self):
            pass
    runtime = SimpleNamespace(init=lambda args: None, ok=lambda: True, shutdown=lambda: None,
                              spin_once=lambda node, timeout_sec: node.callback(payload()))
    args = SimpleNamespace(replay_context=declaration, output=path, run_id='r', session='s', topic='/x')
    with pytest.raises(RuntimeError, match='cleanup failed'):
        bs.run_readonly(args, runtime, Node, object)
    assert path.with_suffix('.jsonl.completion.pending.json').exists()
    assert not path.with_suffix('.jsonl.completion.json').exists()
