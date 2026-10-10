from pathlib import Path

import pytest

from tools.benchmark.openvins_timesync_listener import TimesyncListenerDecoder
from tools.benchmark.openvins_timesync_observer import SerialTimesyncObserver

FIXTURE = Path(__file__).parents[1] / 'fixtures/timesync/pinned-listener-two.bin'
RAW = FIXTURE.read_bytes()
PREFIX = b'\x1b[2J\n\x1b[H'
PROFILE = 'px4-d6f12ad-multi-v1'


def decoder(count=2):
    return TimesyncListenerDecoder(0, count, 0, output_profile=PROFILE)


def test_recorded_native_format_into_serial_observer():
    obj = decoder()
    rows = obj.feed(RAW, 1)
    assert [r['ordinal'] for r in rows] == [1, 2]
    observer = SerialTimesyncObserver('native-stub-fixture', 0)
    for index, row in enumerate(rows):
        observer.reserve_reply((100000 + index * 20000) * 1000,
                               (102000 + index * 20000) * 1000, 2 + 2*index)
        result = observer.observe_status(row, 3 + 2*index)
        assert result['accepted'] and not result['live_convergence_qualified']
    result = obj.finish(7, 0)
    assert result['bytes'] == len(RAW) == 484
    assert result['output_profile'] == PROFILE
    assert result['network_authorized'] is result['fusion_qualified'] is False


@pytest.mark.parametrize('split', range(1, len(RAW)))
def test_all_recorded_native_chunk_splits(split):
    obj = decoder()
    rows = obj.feed(RAW[:split], 1) + obj.feed(RAW[split:], 2)
    assert [r['ordinal'] for r in rows] == [1, 2]
    assert obj.finish(3, 0)['records'] == 2


def test_byte_fragments_and_no_record_released_by_prefix():
    obj = decoder()
    rows = []
    for now, byte in enumerate(RAW, 1):
        rows.extend(obj.feed(bytes([byte]), now))
        if now <= len(PREFIX):
            assert not rows
    assert len(rows) == 2
    assert obj.finish(1000, 0)['bytes'] == 484


@pytest.mark.parametrize('bad', [
    RAW[len(PREFIX):], RAW.replace(PREFIX, b'', 1),
    PREFIX + RAW, RAW.replace(PREFIX, b'\x1b[H\x1b[2J\n'),
    RAW.replace(b'\x1b[2J', b'\x1b[3J'), RAW.replace(PREFIX, b'\x1b[2J\r\n\x1b[H'),
    RAW.replace(b'    remote_timestamp:', PREFIX + b'    remote_timestamp:', 1),
    RAW.replace(b'#2', b'#1'), RAW + b'\x1b', RAW + PREFIX,
    b'never published\n', b'\x00' + RAW, RAW.replace(b'offset: -1000', b'offset: nan'),
])
def test_exact_native_format_refuses_mutations_and_latches(bad):
    obj = decoder()
    with pytest.raises(ValueError):
        obj.feed(bad, 1)
        obj.finish(2, 0)
    with pytest.raises(ValueError, match='latched'):
        obj.feed(RAW, 3)


@pytest.mark.parametrize('length', range(1, len(PREFIX)+1))
def test_prefix_does_not_refresh_deadline(length):
    obj = decoder()
    obj.feed(RAW[:length], 1_999_999_999)
    with pytest.raises(ValueError, match='timeout'):
        obj.feed(RAW[length:], 2_000_000_000)


@pytest.mark.parametrize('length', range(len(PREFIX)+1))
def test_prefix_eof_refused(length):
    obj = decoder()
    obj.feed(RAW[:length], 1)
    with pytest.raises(ValueError, match='truncated'):
        obj.finish(2, 0)


@pytest.mark.parametrize('profile,count', [('unknown',2), (None,2), (True,2), ([],2), (PROFILE,1)])
def test_profile_requires_exact_name_and_multirecord_count(profile, count):
    with pytest.raises(ValueError):
        TimesyncListenerDecoder(0, count, 0, output_profile=profile)


def test_plain_profile_does_not_silently_accept_native_control_bytes():
    obj = TimesyncListenerDecoder(0, 2, 0)
    with pytest.raises(ValueError, match='control'):
        obj.feed(RAW, 1)


def test_prefix_counts_against_raw_frame_budget():
    obj = decoder()
    obj.MAX_FRAME = len(PREFIX) + 2
    with pytest.raises(ValueError, match='frame byte limit'):
        obj.feed(RAW, 1)


def test_native_profile_keeps_chunk_total_and_exit_bounds():
    obj = decoder()
    with pytest.raises(ValueError, match='oversized'):
        obj.feed(b'x'*4097, 1)
    obj = decoder()
    obj.MAX_TOTAL = 483
    with pytest.raises(ValueError, match='total'):
        obj.feed(RAW, 1)
    obj = decoder()
    obj.feed(RAW, 1)
    with pytest.raises(ValueError, match='exit'):
        obj.finish(2, -15)


def test_500_synthetic_records_keep_live_authority_false():
    first = RAW[:len(RAW)//2]
    obj = decoder(500)
    observer = SerialTimesyncObserver('synthetic-chain', 0)
    for index in range(500):
        request_us = 100000 + 20000*index
        status_us = request_us + 2000
        remote_us = request_us + 1000
        frame = (first.replace(b'#1', f'#{index+1}'.encode())
                 .replace(b'    timestamp: 102000', f'    timestamp: {status_us}'.encode())
                 .replace(b'    remote_timestamp: 102000', f'    remote_timestamp: {remote_us}'.encode())
                 .replace(b'offset: -1000', b'offset: 0'))
        now = 10000000*index
        observer.reserve_reply(request_us*1000, remote_us*1000, now)
        rows = obj.feed(frame, now + 1)
        assert len(rows) == 1
        outcome = observer.observe_status(rows[0], now+1)
        assert outcome['observed_model_converged'] is (index == 499)
        assert outcome['live_convergence_qualified'] is False
    assert obj.finish(now+2, 0)['records'] == 500
