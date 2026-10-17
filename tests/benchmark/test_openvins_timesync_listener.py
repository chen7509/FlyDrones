import pytest

from tools.benchmark.openvins_timesync_listener import TimesyncListenerDecoder
from tools.benchmark.openvins_timesync_observer import SerialTimesyncObserver


def frame(ordinal=1, timestamp=102000, remote=102000, offset=-1000, rtt=2000, protocol=0):
    return (f"\nTOPIC: timesync_status instance 0 #{ordinal}\n timesync_status\n"
            f"    timestamp: {timestamp} (0.000001 seconds ago)\n"
            f"    remote_timestamp: {remote}\n    observed_offset: {offset}\n"
            f"    estimated_offset: {offset}\n    round_trip_time: {rtt}\n"
            f"    source_protocol: {protocol}\n\n").encode()


def test_whole_frame_into_existing_observer():
    decoder = TimesyncListenerDecoder(0, 1, 0)
    observer = SerialTimesyncObserver("fixture", 0)
    observer.reserve_reply(100000000, 102000000, 0)
    decoded = decoder.feed(frame(), 1)
    assert len(decoded) == 1
    outcome = observer.observe_status(decoded[0], 1)
    assert outcome["accepted"] and not outcome["live_convergence_qualified"]
    completion = decoder.finish(2, 0)
    assert completion["records"] == 1
    for flag in ("live_listener_qualified", "network_authorized", "fusion_qualified"):
        assert completion[flag] is False


@pytest.mark.parametrize("split", range(1, len(frame())))
def test_each_two_chunk_split(split):
    decoder = TimesyncListenerDecoder(0, 1, 0)
    assert decoder.feed(frame()[:split], 1) == []
    assert len(decoder.feed(frame()[split:], 2)) == 1
    assert decoder.finish(3, 0)["records"] == 1


def test_byte_by_byte_and_two_complete_frames():
    decoder = TimesyncListenerDecoder(0, 2, 0)
    records = []
    for index, byte in enumerate(frame() + frame(2), 1):
        records.extend(decoder.feed(bytes([byte]), index))
    assert [r["ordinal"] for r in records] == [1, 2]
    decoder.finish(1000, 0)


@pytest.mark.parametrize("before,after", [
    (b"#1", b"#2"), (b"instance 0", b"instance 1"),
    (b"timesync_status\n", b"different_topic\n"),
    (b"    remote_timestamp: 102000\n", b""),
    (b"    remote_timestamp: 102000\n", b"    timestamp: 102000\n"),
    (b"    observed_offset: -1000\n", b"    observed_offset: NaN\n"),
    (b"    estimated_offset: -1000\n", b"    estimated_offset: 1.0\n"),
    (b"timestamp: 102000", b"timestamp: 0"),
    (b"timestamp: 102000", b"timestamp: 18446744073709551616"),
    (b"remote_timestamp: 102000", b"remote_timestamp: -1"),
    (b"observed_offset: -1000", b"observed_offset: -9223372036854775809"),
    (b"estimated_offset: -1000", b"estimated_offset: 9223372036854775808"),
    (b"round_trip_time: 2000", b"round_trip_time: 4294967296"),
    (b"source_protocol: 0", b"source_protocol: 256"),
    (b"0.000001 seconds ago", b"nan seconds ago"),
    (b"0.000001 seconds ago", b"-1.000000 seconds ago"),
    (b"102000 (", b"0102000 ("),
])
def test_malformed_field_refuses_and_latches(before, after):
    decoder = TimesyncListenerDecoder(0, 1, 0)
    with pytest.raises(ValueError):
        decoder.feed(frame().replace(before, after), 1)
    with pytest.raises(ValueError, match="latched"):
        decoder.feed(frame(), 2)


@pytest.mark.parametrize("data", [b"never published\n", b"Waited for 2.0 seconds without a message. Giving up.\n",
    b"ERROR [listener] listener callback failed (-1)\n", b"\x1b[2J\n", b"\x00", b"\xff", b"\r\n"])
def test_diagnostic_and_control_output_not_sanitized(data):
    decoder = TimesyncListenerDecoder(0, 1, 0)
    with pytest.raises(ValueError):
        decoder.feed(data, 1)


@pytest.mark.parametrize("cut", [0, 1, 30, len(frame())-1])
def test_clean_exit_does_not_hide_truncation(cut):
    decoder = TimesyncListenerDecoder(0, 1, 0)
    decoder.feed(frame()[:cut], 1)
    with pytest.raises(ValueError):
        decoder.finish(2, 0)


@pytest.mark.parametrize("exit_code", [1, -15, None, True, 0.0])
def test_exit_code_required(exit_code):
    decoder = TimesyncListenerDecoder(0, 1, 0)
    decoder.feed(frame(), 1)
    with pytest.raises(ValueError):
        decoder.finish(2, exit_code)


def test_deadline_and_partial_trickle():
    decoder = TimesyncListenerDecoder(0, 1, 0)
    decoder.feed(frame()[:1], 1_000_000_000)
    decoder.feed(frame()[1:2], 1_999_999_999)
    with pytest.raises(ValueError, match="timeout"):
        decoder.feed(frame()[2:], 2_000_000_000)


def test_complete_frame_refreshes_deadline_but_clock_must_not_regress():
    decoder = TimesyncListenerDecoder(0, 2, 0)
    decoder.feed(frame(), 1_999_999_999)
    decoder.check(3_999_999_998)
    with pytest.raises(ValueError, match="regression"):
        decoder.feed(frame(2), 3_999_999_997)


def test_silence_without_pending_bytes_times_out():
    decoder = TimesyncListenerDecoder(0, 1, 50)
    with pytest.raises(ValueError, match="timeout"):
        decoder.check(2_000_000_050)


def test_extra_frame_and_finished_stream_refused():
    decoder = TimesyncListenerDecoder(0, 1, 0)
    decoder.feed(frame(), 1)
    with pytest.raises(ValueError):
        decoder.feed(frame(2), 2)
    decoder = TimesyncListenerDecoder(0, 1, 0)
    decoder.feed(frame(), 1)
    decoder.finish(2, 0)
    with pytest.raises(ValueError):
        decoder.feed(frame(), 3)


@pytest.mark.parametrize("chunk", [b"a"*4097, b"a"*1025, bytearray(frame()), "text"])
def test_bounded_strict_byte_input(chunk):
    decoder = TimesyncListenerDecoder(0, 1, 0)
    with pytest.raises(ValueError):
        decoder.feed(chunk, 1)


@pytest.mark.parametrize("args", [(True, 1, 0), (-1,1,0), (256,1,0), (0,0,0), (0,4097,0), (0,1,-1), (0,1,True)])
def test_invalid_constructor(args):
    with pytest.raises(ValueError):
        TimesyncListenerDecoder(*args)


def test_scalar_integer_boundaries():
    decoder = TimesyncListenerDecoder(0, 1, 0)
    data = frame(timestamp=2**64-1,remote=2**64-1,offset=-(2**63),rtt=2**32-1,protocol=255)
    decoded = decoder.feed(data, 1)[0]
    assert decoded["estimated_offset"] == -(2**63)
    assert decoded["timestamp"] == 2**64-1


@pytest.mark.parametrize("same_chunk", [True, False])
def test_any_byte_after_expected_count_immediately_latches(same_chunk):
    decoder = TimesyncListenerDecoder(0, 1, 0)
    if not same_chunk:
        decoder.feed(frame(), 1)
    with pytest.raises(ValueError, match="trailing"):
        decoder.feed((frame() if same_chunk else b"") + b"CORRUPT", 2)
    with pytest.raises(ValueError, match="latched"):
        decoder.check(3)
