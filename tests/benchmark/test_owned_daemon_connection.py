import copy
from types import SimpleNamespace

import pytest

from tools.benchmark.owned_daemon_connection import ConnectionRefusal, connect_owned_daemon, validate_owner

OWNER = dict(pid=321, pgrp=321, session=321, start_ticks=77, uid=1000, gid=1000,
             exe='/usr/bin/child', exe_device=8, exe_inode=11,
             cwd='/tmp/run', cwd_device=8, cwd_inode=12, net='net:[100]', user='user:[101]')


class Backend:
    def __init__(self):
        self.now = 10
        self.owner = copy.deepcopy(OWNER)
        self.peer_value = dict(pid=321, uid=1000, gid=1000)
        self.connection = object()
        self.connected = self.closed = 0
        self.connect_error = self.peer_error = self.close_error = None

    def clock(self):
        return self.now

    def observe(self, process):
        return copy.deepcopy(self.owner)

    def connect(self, path, timeout):
        self.connected += 1
        assert path == '/tmp/private/socket' and 0 < timeout <= 2
        if self.connect_error:
            raise self.connect_error
        return self.connection

    def peer(self, connection):
        assert connection is self.connection
        if self.peer_error:
            raise self.peer_error
        return copy.deepcopy(self.peer_value)

    def close(self, connection):
        assert connection is self.connection
        self.closed += 1
        if self.close_error:
            raise self.close_error


def run(backend=None, journal=None, expected=None, path='/tmp/private/socket', deadline=2000000010):
    backend = backend or Backend()
    return connect_owned_daemon(SimpleNamespace(pid=321), OWNER if expected is None else expected,
                                path, deadline_ns=deadline, journal=journal or (lambda _: None), backend=backend)


def test_same_connection_returned_only_after_journal_and_final_checks():
    backend = Backend()
    events = []
    connection, evidence = run(backend, events.append)
    assert connection is backend.connection and backend.closed == 0
    assert evidence['connection_peer_matched'] is True
    assert evidence['network_authorized'] is False and evidence['fusion_qualified'] is False
    assert [e['kind'] for e in events] == ['connect_attempt', 'peer_observed']
    events[0].clear()
    assert evidence['events'][0]['kind'] == 'connect_attempt'


@pytest.mark.parametrize('field,value', [('pid',322),('uid',0),('gid',0),('pid',True)])
def test_peer_mismatch_closes_same_descriptor(field, value):
    backend = Backend()
    backend.peer_value[field] = value
    with pytest.raises(ConnectionRefusal, match='peer') as caught:
        run(backend)
    assert backend.closed == 1 and not caught.value.evidence['connection_peer_matched']


@pytest.mark.parametrize('field,value', [('start_ticks',78),('exe','/usr/bin/other'),
    ('exe_inode',99),('cwd','/tmp/other'),('net','net:[102]'),('user','user:[103]')])
def test_registered_owner_drift_blocks_connect(field,value):
    backend=Backend()
    backend.owner[field]=value
    with pytest.raises(ConnectionRefusal,match='owner'):
        run(backend)
    assert backend.connected==0


@pytest.mark.parametrize('phase', ['connect_attempt','peer_observed'])
@pytest.mark.parametrize('mode', ['raise','late','regress','owner-drift','peer-drift','non-none'])
def test_journal_cannot_hide_failure_or_drift(phase,mode):
    backend=Backend()

    def journal(event):
        if event['kind']!=phase:
            return None
        if mode=='raise':
            raise OSError('disk failure')
        if mode=='late':
            backend.now=2000000010
        elif mode=='regress':
            backend.now=9
        elif mode=='owner-drift':
            backend.owner['start_ticks']=88
        elif mode=='peer-drift':
            backend.peer_value['pid']=322
        elif mode=='non-none':
            return True

    with pytest.raises(ConnectionRefusal):
        run(backend,journal)
    assert backend.closed==backend.connected


@pytest.mark.parametrize('kind', ['connect','peer','close'])
def test_transport_and_cleanup_failures_retained(kind):
    backend=Backend()
    if kind=='connect':
        backend.connect_error=TimeoutError('connect timeout')
    else:
        backend.peer_error=OSError('credentials failed')
    if kind=='close':
        backend.close_error=OSError('close failed')
    with pytest.raises(ConnectionRefusal) as caught:
        run(backend)
    assert caught.value.evidence['connection_peer_matched'] is False
    assert bool(caught.value.evidence['close_error'])==(kind=='close')
    assert backend.closed==(0 if kind=='connect' else 1)


@pytest.mark.parametrize('path', ['relative','\0abstract','/tmp/'+('x'*110),'/tmp/../other'])
def test_bad_paths_never_connect(path):
    backend=Backend()
    with pytest.raises(ConnectionRefusal):
        run(backend,path=path)
    assert backend.connected==0


@pytest.mark.parametrize('deadline', [True,0,10,2000000011,1.5,2**64])
def test_invalid_deadline_refuses(deadline):
    with pytest.raises(ConnectionRefusal):
        run(deadline=deadline)


@pytest.mark.parametrize('field,value', [('pid',True),('start_ticks',-1),('uid',2**32),
    ('cwd','relative'),('exe_inode',0),('net','bad')])
def test_owner_schema_strict(field,value):
    owner=copy.deepcopy(OWNER)
    owner[field]=value
    with pytest.raises(ValueError):
        validate_owner(owner)


def test_interruption_closes_then_propagates():
    backend=Backend()

    def journal(event):
        if event['kind']=='peer_observed':
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run(backend,journal)
    assert backend.closed==1
