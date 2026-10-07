import copy
from pathlib import Path

import pytest

from tools.benchmark.openvins_timesync_bootstrap import ColdTimesyncBootstrap, parse_snapshot

PREFIX = b'\x1b[2J\n\x1b[H'
EPOCH = 'prospective-px4-a'
LISTENER = 'listener-a'
NATIVE_SINGLE = Path(__file__).parents[1] / 'fixtures/timesync/pinned-listener-implicit.bin'


def body(index=0, rtt=2000):
    request = 100000 + index*20000
    remote = request + rtt//2
    raw = (f' timesync_status\n    timestamp: {request+rtt} (0.000001 seconds ago)\n'
           f'    remote_timestamp: {remote}\n    observed_offset: 0\n'
           f'    estimated_offset: 0\n    round_trip_time: {rtt}\n'
           '    source_protocol: 0\n\n').encode()
    return request*1000, remote*1000, raw


def single(index=0, rtt=2000):
    return b'\nTOPIC: timesync_status\n' + body(index, rtt)[2]


def frame(index=0, rtt=2000):
    return PREFIX + f'\nTOPIC: timesync_status instance 0 #{index+1}\n'.encode() + body(index, rtt)[2]


def kwargs(now):
    return dict(now_ns=now, epoch_token=EPOCH)


def ready(count=500, journal=None):
    obj = ColdTimesyncBootstrap('session-a', EPOCH, 0, journal or (lambda _: None), stream_records=count)
    obj.confirm_empty(b'never published\n', 0, **kwargs(1))
    obj.reserve_reply(*body()[:2], **kwargs(2))
    obj.confirm_first(single(), 0, **kwargs(3))
    obj.begin_stream(LISTENER, **kwargs(4))
    obj.feed_stream(frame(), LISTENER, **kwargs(5))
    return obj


def test_empty_and_retained_native_snapshot_are_strictly_distinguished():
    assert parse_snapshot(b'never published\n', 0)['kind'] == 'empty'
    result = parse_snapshot(NATIVE_SINGLE.read_bytes(), 0)
    assert result['kind'] == 'single'
    assert result['status']['instance'] == 0
    assert result['status']['ordinal'] == 1
    assert result['raw_bytes'] == 220
    assert result['instance_basis'] == 'pinned default subscription, not MAVLink channel'


@pytest.mark.parametrize('raw', [b'',b'never published', b'never published\r\n', b'never published\n\n',
    b'\nTOPIC: timesync_status 2 instances\n', single()+b'x', single().replace(b': 0\n',b': NaN\n',1),
    PREFIX+single(), b'x'*1025, bytearray(single()), 'text'])
def test_snapshot_unknown_ambiguous_malformed_refuses(raw):
    with pytest.raises(ValueError):
        parse_snapshot(raw, 0)


@pytest.mark.parametrize('code', [1, -15, None, True, 0.0])
def test_snapshot_needs_clean_literal_exit(code):
    with pytest.raises(ValueError):
        parse_snapshot(single(), code)


def test_full_chain_counts_first_replay_once_and_keeps_authority_false():
    journal = []
    obj = ready(journal=journal.append)
    assert obj.progress['modeled_accepted_samples'] == 1
    assert obj.progress['stream_records_seen'] == 1
    assert not obj.progress['modeled_bootstrap_ready']
    for index in range(1,500):
        now = index*10_000_000
        intent = obj.reserve_reply(*body(index)[:2], **kwargs(now))
        assert intent['transmission_proven'] is False
        obj.feed_stream(frame(index), LISTENER, **kwargs(now+1))
    result = obj.finish_stream(0, LISTENER, **kwargs(now+2))
    assert result['modeled_bootstrap_ready'] is True
    assert result['modeled_accepted_samples'] == 500
    for flag in ('live_convergence_qualified','network_authorized','fusion_qualified'):
        assert result[flag] is False
    replays = [e for e in journal if e['kind']=='latest_replay']
    assert len(replays)==1 and replays[0]['counts_as_new_sample'] is False
    saved = obj.events
    saved.clear()
    assert obj.events
    result['modeled_bootstrap_ready'] = False
    assert obj.progress['modeled_bootstrap_ready'] is True


@pytest.mark.parametrize('count,passes', [(500,False),(501,True)])
def test_later_high_rtt_is_retained_and_count_threshold_not_relaxed(count, passes):
    obj=ready(count)
    for index in range(1,count):
        rtt=10000 if index==1 else 2000
        now=index*10_000_000
        obj.reserve_reply(*body(index,rtt)[:2],**kwargs(now))
        obj.feed_stream(frame(index,rtt),LISTENER,**kwargs(now+1))
    if passes:
        assert obj.finish_stream(0,LISTENER,**kwargs(now+2))['modeled_accepted_samples']==500
    else:
        with pytest.raises(ValueError,match='500'):
            obj.finish_stream(0,LISTENER,**kwargs(now+2))
    assert any(e.get('observer',{}).get('reason')=='high_rtt' for e in obj.events)


@pytest.mark.parametrize('phase', ['before-empty','before-first','before-replay','pending-twice'])
def test_out_of_order_reply_refuses_and_latches(phase):
    obj=ColdTimesyncBootstrap('s',EPOCH,0,lambda _:None)
    if phase!='before-empty':
        obj.confirm_empty(b'never published\n',0,**kwargs(1))
        obj.reserve_reply(*body()[:2],**kwargs(2))
    if phase=='before-replay':
        obj.confirm_first(single(),0,**kwargs(3))
        obj.begin_stream(LISTENER,**kwargs(4))
    with pytest.raises(ValueError):
        obj.reserve_reply(*body(1)[:2],**kwargs(6))
    with pytest.raises(ValueError,match='latched'):
        obj.check(**kwargs(7))


@pytest.mark.parametrize('bad', [single(),b'never published\n\n',b'ERROR\n'])
def test_nonempty_pre_reply_snapshot_refused(bad):
    obj=ColdTimesyncBootstrap('s',EPOCH,0,lambda _:None)
    with pytest.raises(ValueError):
        obj.confirm_empty(bad,0,**kwargs(1))


@pytest.mark.parametrize('bad', [b'never published\n',single(1),single(rtt=10000),
    single().replace(b'estimated_offset: 0',b'estimated_offset: 1'),
    single().replace(b'source_protocol: 0',b'source_protocol: 1')])
def test_first_must_be_accepted_cold_match(bad):
    obj=ColdTimesyncBootstrap('s',EPOCH,0,lambda _:None)
    obj.confirm_empty(b'never published\n',0,**kwargs(1))
    obj.reserve_reply(*body()[:2],**kwargs(2))
    with pytest.raises(ValueError):
        obj.confirm_first(bad,0,**kwargs(3))


@pytest.mark.parametrize('bad', [frame(1),frame().replace(b'timestamp: 102000',b'timestamp: 102001'),
    frame().replace(b'instance 0',b'instance 1'),frame()+frame(1)])
def test_handoff_requires_exact_latest_replay_and_no_unsolicited_rows(bad):
    obj=ColdTimesyncBootstrap('s',EPOCH,0,lambda _:None)
    obj.confirm_empty(b'never published\n',0,**kwargs(1))
    obj.reserve_reply(*body()[:2],**kwargs(2))
    obj.confirm_first(single(),0,**kwargs(3))
    obj.begin_stream(LISTENER,**kwargs(4))
    with pytest.raises(ValueError):
        obj.feed_stream(bad,LISTENER,**kwargs(5))


def test_replay_fragment_and_idle_do_not_refresh_two_second_progress_deadline():
    obj=ColdTimesyncBootstrap('s',EPOCH,0,lambda _:None)
    obj.confirm_empty(b'never published\n',0,**kwargs(1))
    obj.reserve_reply(*body()[:2],**kwargs(2))
    obj.confirm_first(single(),0,**kwargs(3))
    obj.begin_stream(LISTENER,**kwargs(4))
    obj.feed_stream(frame()[:2],LISTENER,**kwargs(2_000_000_003))
    with pytest.raises(ValueError,match='timeout'):
        obj.feed_stream(frame()[2:],LISTENER,**kwargs(2_000_000_004))


def test_global_eight_second_window_is_not_reset_by_regular_progress():
    obj=ready()
    for index in range(1,8):
        obj.reserve_reply(*body(index)[:2],**kwargs(index*1_000_000_000))
        obj.feed_stream(frame(index),LISTENER,**kwargs(index*1_000_000_000+1))
    with pytest.raises(ValueError,match='readiness'):
        obj.check(**kwargs(8_000_000_000))


def test_new_reply_does_not_refresh_silent_listener_complete_frame_deadline():
    obj=ready()
    obj.reserve_reply(*body(1)[:2],**kwargs(1_900_000_000))
    with pytest.raises(ValueError,match='complete-frame timeout'):
        obj.check(**kwargs(2_000_000_005))


@pytest.mark.parametrize('change', ['epoch','listener','clock','bool-clock','restart','early-exit','bad-exit'])
def test_session_clock_and_exit_failures(change):
    obj=ready()
    with pytest.raises(ValueError):
        if change=='epoch':
            obj.check(now_ns=6,epoch_token='new-epoch')
        elif change=='listener':
            obj.feed_stream(b'', 'new-listener',**kwargs(6))
        elif change=='clock':
            obj.check(**kwargs(4))
        elif change=='bool-clock':
            obj.check(**kwargs(True))
        elif change=='restart':
            obj.begin_stream('new-listener',**kwargs(6))
        elif change=='early-exit':
            obj.finish_stream(0,LISTENER,**kwargs(6))
        else:
            obj.finish_stream(-15,LISTENER,**kwargs(6))


@pytest.mark.parametrize('kind', ['reply_intent','first_status','stream_start','raw_chunk','latest_replay'])
def test_journal_failure_latches_before_any_further_reply(kind):
    def journal(event):
        if event['kind']==kind:
            raise OSError('simulated journal failure')
    obj=None
    with pytest.raises(OSError):
        obj=ColdTimesyncBootstrap('s',EPOCH,0,journal)
        obj.confirm_empty(b'never published\n',0,**kwargs(1))
        obj.reserve_reply(*body()[:2],**kwargs(2))
        obj.confirm_first(single(),0,**kwargs(3))
        obj.begin_stream(LISTENER,**kwargs(4))
        obj.feed_stream(frame(),LISTENER,**kwargs(5))
    with pytest.raises(ValueError,match='latched'):
        obj.reserve_reply(*body(1)[:2],**kwargs(6))


def test_mutating_journal_argument_cannot_change_first_replay_identity():
    log=[]
    def journal(event):
        log.append(copy.deepcopy(event))
        event.clear()
    obj=ready(journal=journal)
    assert obj.progress['modeled_accepted_samples']==1
    assert obj.events==log


def test_swallowed_reentry_error_still_latches_outer_transition():
    obj=None
    def journal(event):
        if event['kind']=='reply_intent':
            with pytest.raises(ValueError,match='concurrent'):
                obj.check(**kwargs(2))
    obj=ColdTimesyncBootstrap('s',EPOCH,0,journal)
    obj.confirm_empty(b'never published\n',0,**kwargs(1))
    with pytest.raises(ValueError,match='latched'):
        obj.reserve_reply(*body()[:2],**kwargs(2))


def test_partial_unsolicited_status_cannot_arrive_before_next_reply_reservation():
    obj=ready()
    with pytest.raises(ValueError,match='unsolicited'):
        obj.feed_stream(frame(1)[:3],LISTENER,**kwargs(6))


def test_partial_next_frame_in_same_chunk_cannot_cross_reply_gate():
    obj=ready()
    obj.reserve_reply(*body(1)[:2],**kwargs(6))
    with pytest.raises(ValueError,match='reserved record'):
        obj.feed_stream(frame(1)+PREFIX[:3],LISTENER,**kwargs(7))


def test_event_limit_and_journal_non_none_return_refuse():
    obj=ColdTimesyncBootstrap('s',EPOCH,0,lambda _:None)
    obj.MAX_EVENTS=1
    obj.confirm_empty(b'never published\n',0,**kwargs(1))
    with pytest.raises(ValueError,match='event limit'):
        obj.reserve_reply(*body()[:2],**kwargs(2))
    obj=ColdTimesyncBootstrap('s',EPOCH,0,lambda _:True)
    with pytest.raises(ValueError,match='return None'):
        obj.confirm_empty(b'never published\n',0,**kwargs(1))


@pytest.mark.parametrize('args', [('',EPOCH,0,500),('s','',0,500),('s',EPOCH,True,500),
    ('s',EPOCH,0,499),('s',EPOCH,0,4097),('s',EPOCH,0,True)])
def test_constructor_requires_frozen_bounded_inputs(args):
    session,epoch,start,count=args
    with pytest.raises(ValueError):
        ColdTimesyncBootstrap(session,epoch,start,lambda _:None,stream_records=count)
