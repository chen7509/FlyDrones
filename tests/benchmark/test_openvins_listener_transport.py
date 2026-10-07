import copy
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.benchmark.openvins_listener_transport import ReadOnlyListener, ReplyEnvelope, listener_command

FIX=Path(__file__).parents[1]/'fixtures/timesync'
SINGLE=(FIX/'pinned-listener-implicit.bin').read_bytes()
MULTI=(FIX/'pinned-listener-two.bin').read_bytes()
OWNER=dict(pid=321,pgrp=321,session=321,start_ticks=7,uid=1000,gid=1000,
           exe='/bin/child',exe_device=1,exe_inode=2,cwd='/tmp/run',cwd_device=1,cwd_inode=3,
           net='net:[4]',user='user:[5]')


class Connection:
    def __init__(self,payload):
        self.reads=deque(payload)
        self.writes=deque()
        self.sent=b''
        self.closed=0
        self.close_error=None

    def setblocking(self,value):
        assert value is False

    def send(self,data):
        count=self.writes.popleft() if self.writes else len(data)
        if isinstance(count,BaseException):
            raise count
        if type(count) is int and count>0:
            self.sent+=data[:count]
        return count

    def recv(self,limit):
        assert limit==4096
        if not self.reads:
            raise BlockingIOError()
        value=self.reads.popleft()
        if isinstance(value,BaseException):
            raise value
        return value

    def close(self):
        self.closed+=1
        if self.close_error:
            raise self.close_error


class Backend:
    def __init__(self,payload):
        self.now=10
        self.owner=copy.deepcopy(OWNER)
        self.connection=Connection(payload)

    def clock(self):
        return self.now

    def observe(self,process):
        return copy.deepcopy(self.owner)

    def peer(self,connection):
        assert connection is self.connection
        return {k:self.owner[k] for k in ('pid','uid','gid')}

    def connect(self,path,timeout):
        assert path=='/tmp/private/socket'
        return self.connection

    def close(self,connection):
        connection.close()


def make(payload,mode='stream',count=2,journal=None):
    backend=Backend(payload)
    obj=ReadOnlyListener(SimpleNamespace(pid=321),OWNER,'/tmp/private/socket',
                         mode,count,10,8000000010,journal or (lambda _:None),backend=backend)
    return obj,backend


def test_exact_commands_only():
    assert listener_command('snapshot',1)==b'listener timesync_status -n 1\0'
    assert listener_command('stream',500)==b'listener timesync_status -i 0 -n 500\0'
    for mode,count in [('snapshot',2),('stream',1),('stream',True),('stream',4097),('arm',1),('stream',2.0)]:
        with pytest.raises(ValueError):
            listener_command(mode,count)


def test_every_native_response_trailer_split_preserves_stdout():
    raw=MULTI+b'\0\0'
    for index in range(1,len(raw)):
        decoder=ReplyEnvelope()
        assert decoder.feed(raw[:index])+decoder.feed(raw[index:])==MULTI
        assert decoder.finish()==0
    decoder=ReplyEnvelope()
    assert b''.join(decoder.feed(bytes([x])) for x in raw)==MULTI
    assert decoder.finish()==0


@pytest.mark.parametrize('chunks', [[b''],[MULTI],[MULTI+b'\0'],[MULTI+b'\0\x01'],
    [MULTI+b'\0\0x'],[MULTI+b'\0\0',b'x'],[b'x'*4097],[bytearray(b'x')]])
def test_envelope_faults_refuse_and_latch(chunks):
    obj=ReplyEnvelope()
    with pytest.raises(ValueError):
        for chunk in chunks:
            obj.feed(chunk)
        obj.finish()
    with pytest.raises(ValueError):
        obj.feed(b'x')


def test_records_provisional_until_clean_trailer_and_eof():
    obj,backend=make([MULTI,b'\0',b'\0',b''])
    first=obj.poll()
    assert len(first['records'])==2 and first['stdout']==MULTI
    assert first['terminal'] is None and not obj.evidence['transport_complete']
    assert obj.poll()['terminal'] is None
    assert obj.poll()['terminal'] is None
    terminal=obj.poll()['terminal']
    assert terminal['records']==2
    assert obj.evidence['transport_complete'] is True
    assert backend.connection.sent==listener_command('stream',2)
    assert backend.connection.closed==1
    assert obj.evidence['network_authorized'] is False
    assert obj.evidence['fusion_qualified'] is False
    with pytest.raises(ValueError):
        obj.poll()


@pytest.mark.parametrize('payload,kind', [(SINGLE,'single'),(b'never published\n','empty')])
def test_snapshot_uses_exact_existing_decoder(payload,kind):
    obj,backend=make([payload+b'\0\0',b''],'snapshot',1)
    assert obj.poll()['terminal'] is None
    result=obj.poll()['terminal']
    assert result['kind']==kind and result['raw_hex']==payload.hex()
    assert backend.connection.sent==listener_command('snapshot',1)


def test_partial_send_would_block_then_exact_tail():
    obj,backend=make([MULTI+b'\0\0',b''])
    backend.connection.writes.extend([3,BlockingIOError(),2])
    assert obj.poll()['stdout']==b''
    assert obj.poll()['stdout']==b''
    assert obj.poll()['stdout']==b''
    assert len(obj.poll()['records'])==2
    assert obj.poll()['terminal']['records']==2
    assert backend.connection.sent==listener_command('stream',2)


@pytest.mark.parametrize('fault',[0,True,999,OSError('send failed')])
def test_send_fault_closes_without_rollback_claim(fault):
    obj,backend=make([])
    backend.connection.writes.append(fault)
    with pytest.raises(ValueError):
        obj.poll()
    assert backend.connection.closed==1 and obj.evidence['error']


@pytest.mark.parametrize('fault',[b'',MULTI[:-1]+b'\0\0',b'diagnostic\0\0',MULTI+b'\0\x07'])
def test_response_refusal_closes(fault):
    obj,backend=make([fault,b''])
    with pytest.raises(ValueError):
        obj.poll()
        obj.poll()
    assert backend.connection.closed==1


def test_silence_and_fragments_do_not_refresh_frame_deadline():
    obj,backend=make([MULTI[:4]])
    obj.poll()
    backend.now=2000000010
    with pytest.raises(ValueError,match='timeout'):
        obj.poll()
    assert backend.connection.closed==1


@pytest.mark.parametrize('mode',['late','regression','raise','owner','return'])
def test_post_journal_failure_prevents_first_send(mode):
    holder={}

    def journal(event):
        if event['kind']!='send_attempt':
            return
        backend=holder['backend']
        if mode=='late':
            backend.now=2000000010
        elif mode=='regression':
            backend.now=9
        elif mode=='raise':
            raise OSError('disk failed')
        elif mode=='owner':
            backend.owner['start_ticks']=8
        else:
            return True

    obj,backend=make([],journal=journal)
    holder['backend']=backend
    with pytest.raises(ValueError):
        obj.poll()
    assert backend.connection.sent==b'' and backend.connection.closed==1


def test_swallowed_reentry_still_refuses():
    holder={}

    def journal(event):
        if event['kind']=='send_attempt':
            try:
                holder['obj'].poll()
            except ValueError:
                pass

    obj,backend=make([],journal=journal)
    holder['obj']=obj
    with pytest.raises(ValueError):
        obj.poll()
    assert backend.connection.sent==b''


def test_close_failure_retained_and_explicit_abort_idempotent():
    obj,backend=make([b''])
    backend.connection.close_error=OSError('close failed')
    with pytest.raises(ValueError):
        obj.poll()
    assert 'close failed' in obj.evidence['close_error']
    obj.close()
    assert backend.connection.closed==1
    other,backend=make([])
    other.close()
    other.close()
    assert not other.evidence['transport_complete'] and backend.connection.closed==1


def test_interrupt_closes_and_preserves_type():
    obj,backend=make([KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        obj.poll()
    assert backend.connection.closed==1


def test_late_entry_uses_global_window_and_new_command_frame_timer():
    backend=Backend([MULTI+b'\0\0',b''])
    backend.now=3000000000
    obj=ReadOnlyListener(SimpleNamespace(pid=321),OWNER,'/tmp/private/socket',
                         'stream',2,0,8000000000,lambda _:None,backend=backend)
    assert len(obj.poll()['records'])==2
    assert obj.poll()['terminal']['records']==2


@pytest.mark.parametrize('operation',['send','recv'])
def test_returned_io_is_retained_even_if_it_crosses_deadline(operation):
    obj,backend=make([MULTI+b'\0\0'])
    original=getattr(backend.connection,operation)

    def late(value):
        result=original(value)
        backend.now=2000000010
        return result

    setattr(backend.connection,operation,late)
    with pytest.raises(ValueError,match='timeout'):
        obj.poll()
    events=[e for e in obj.evidence['events'] if e['kind']==operation+'_return']
    assert len(events)==1
    if operation=='send':
        assert events[0]['count']==len(listener_command('stream',2))
    else:
        assert events[0]['raw_hex']==(MULTI+b'\0\0').hex()
    assert backend.connection.closed==1
