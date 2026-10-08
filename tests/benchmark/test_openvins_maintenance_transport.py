"""Actual listener transport/parser, injected ordinary daemon I/O only."""
import inspect
from types import SimpleNamespace

import pytest

from tests.benchmark.test_openvins_listener_transport import OWNER, Backend
from tests.benchmark.test_openvins_timesync_continuation import START, completed, feed, kwargs, raw, take
from tools.benchmark.openvins_listener_transport import ReadOnlyListener


def make(journal=None):
    assert 'continuation' in inspect.signature(ReadOnlyListener).parameters
    continued = take(completed())
    backend = Backend([raw(499, 1)[2]])
    backend.now = START
    obj = ReadOnlyListener(SimpleNamespace(pid=321), OWNER, '/tmp/private/socket',
                           'stream', 4096, START, 300_000_000_000,
                           journal or (lambda _: None), backend=backend, continuation=continued)
    return obj, continued, backend


def consume(obj, continued, backend):
    result = obj.poll()
    if result['stdout']:
        feed(continued, result['stdout'], backend.now)
    return result


def test_maintenance_binding_continues_over8s_and_cancels_owned_socket_once():
    obj, continued, backend = make()
    consume(obj, continued, backend)
    for index in range(500, 505):
        backend.now += 999_000_000
        req, resp, packet = raw(index, index - 498)
        continued.reserve_reply(req, resp, **kwargs(backend.now))
        backend.connection.reads.append(packet)
        consume(obj, continued, backend)
    assert backend.now > START + 4_000_000_000
    assert backend.connection.sent == b'listener timesync_status -i 0 -n 4096\0'
    result = obj.cancel('capture stop')
    assert result['cancellation_requested'] and result['socket_close_returned']
    assert not result['transport_complete'] and not result['daemon_exit_proven']
    assert backend.connection.closed == 1
    assert obj.cancel('capture stop') == result
    with pytest.raises(ValueError):
        obj.poll()


@pytest.mark.parametrize('mode', ['missing-context', 'deadline', 'start', 'count', 'fake-context'])
def test_deadline_extension_requires_exact_continuation_context(mode):
    assert 'continuation' in inspect.signature(ReadOnlyListener).parameters
    continued = take(completed())
    backend = Backend([])
    backend.now = START
    context = None if mode == 'missing-context' else object() if mode == 'fake-context' else continued
    with pytest.raises(ValueError):
        ReadOnlyListener(SimpleNamespace(pid=321), OWNER, '/tmp/private/socket', 'stream',
                         500 if mode == 'count' else 4096, START + 1 if mode == 'start' else START,
                         299_000_000_000 if mode == 'deadline' else 300_000_000_000,
                         lambda _: None, backend=backend, continuation=context)
    assert backend.connection.sent == b''


def test_failed_source_refuses_next_read_and_closes_socket():
    obj, continued, backend = make()
    consume(obj, continued, backend)
    with pytest.raises(ValueError):
        feed(continued, raw(499, 1)[2], backend.now)
    with pytest.raises(ValueError):
        obj.poll()
    assert backend.connection.closed == 1
    assert obj.evidence['error']


@pytest.mark.parametrize('mode', ['partial', 'owner-change', 'close', 'journal', 'deadline'])
def test_cancel_keeps_partial_error_and_owned_close_evidence(mode):
    def journal(event):
        if mode == 'journal' and event['kind'] == 'cancellation_requested':
            raise OSError('injected cancel journal')
    obj, continued, backend = make(journal)
    consume(obj, continued, backend)
    if mode == 'partial':
        req, resp, packet = raw(500, 2)
        continued.reserve_reply(req, resp, **kwargs(backend.now))
        backend.connection.reads.append(packet[:37])
        consume(obj, continued, backend)
    if mode == 'owner-change':
        backend.owner['start_ticks'] += 1
    if mode == 'close':
        backend.connection.close_error = OSError('injected close')
    if mode == 'deadline':
        backend.now = 300_000_000_000
    result = obj.cancel('capture stop')
    assert backend.connection.closed == 1
    assert result['cancellation_requested']
    assert not result['daemon_exit_proven'] and not result['transport_complete']
    assert result['incomplete_frame_bytes'] == (37 if mode == 'partial' else 0)
    assert result['socket_close_returned'] is (mode != 'close')
    assert bool(result['error']) is (mode != 'partial')


def test_one_continuation_cannot_bind_two_listeners_before_first_record():
    obj, continued, backend = make()
    other = Backend([])
    other.now = START
    with pytest.raises(ValueError):
        ReadOnlyListener(SimpleNamespace(pid=321), OWNER, '/tmp/private/socket',
                         'stream', 4096, START, 300_000_000_000, lambda _: None,
                         backend=other, continuation=continued)
    assert other.connection.sent == b''
    assert continued.progress['failure']
    with pytest.raises(ValueError):
        obj.poll()
    assert backend.connection.closed == 1


def test_cancelled_continuation_refuses_next_transport_read():
    obj, continued, backend = make()
    consume(obj, continued, backend)
    continued.cancel('capture stop', **kwargs(backend.now))
    with pytest.raises(ValueError):
        obj.poll()
    assert backend.connection.closed == 1


def test_cancel_interruption_keeps_close_result_and_reraises():
    def journal(event):
        if event['kind'] == 'cancellation_requested':
            raise KeyboardInterrupt()
    obj, continued, backend = make(journal)
    with pytest.raises(KeyboardInterrupt):
        obj.cancel('capture stop')
    assert backend.connection.closed == 1
    result = obj.evidence
    assert result['cancellation_requested'] and result['socket_close_returned']
    assert result['error']


def test_failed_terminal_cancel_journal_never_claims_clean_result():
    def journal(event):
        if event['kind'] == 'cancellation_result':
            raise OSError('terminal write failed')
    obj, continued, backend = make(journal)
    result = obj.cancel('capture stop')
    assert backend.connection.closed == 1
    assert result['error'] and result['cancel_journal_error']
    assert result['socket_close_returned'] and not result['daemon_exit_proven']
