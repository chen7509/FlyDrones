"""No partial/corrupt stream may be accepted as complete receiver evidence."""
import json
import struct
import sys
from types import SimpleNamespace

import pytest
from receiver_ulog_fixture import receiver_log, record
from test_openvins_receiver_parity import fixture, ulog

from tools.benchmark import audit_openvins_receiver_parity as cli
from tools.benchmark import openvins_receiver_parity as parity


def log_parts():
    return receiver_log([fixture()[1]])


def test_complete_raw_receiver_count_is_retained():
    definitions, subscription, data = log_parts()
    result = parity.validate_ulog_stream(definitions + subscription + data[0])
    assert result['receiver_data_count'] == 1
    assert result['message_count'] == 4


@pytest.mark.parametrize('fault', [
    'short_header', 'short_payload', 'reused_id', 'reused_topic', 'data_without_subscription',
    'header', 'version', 'appended', 'unknown_incompat', 'late_flags', 'missing_flags',
    'short_flags', 'remove_subscription', 'duplicate_format', 'unknown_record',
    'dropout', 'short_subscription', 'short_data',
])
def test_whole_stream_faults_are_rejected_before_decoder(fault):
    definitions, subscription, data = log_parts()
    normal = definitions + subscription + data[0]
    variants = {
        'short_header': normal+b'\x04',
        'short_payload': normal+b'\x04\x00Iab',
        'reused_id': normal+subscription+data[0],
        'reused_topic': normal+record('A', b'\x00\x01\x00vehicle_visual_odometry'),
        'data_without_subscription': definitions+data[0],
        'header': b'X'+normal[1:], 'version': normal[:7]+b'\x02'+normal[8:],
        'appended': normal[:35]+b'\x01'+normal[36:],
        'unknown_incompat': normal[:28]+b'\x01'+normal[29:],
        'late_flags': normal+record('B', bytes(40)),
        'missing_flags': definitions[:16]+definitions[59:]+subscription+data[0],
        'short_flags': normal[:16]+record('B', bytes(39)),
        'remove_subscription': normal+record('R', b'\x00\x00'),
        'duplicate_format': definitions+definitions[59:]+subscription+data[0],
        'unknown_record': normal+record('X', b'skipped'),
        'dropout': normal+record('O', b'\x01\x00'),
        'short_subscription': definitions+record('A', b'\x00\x00'),
        'short_data': definitions+subscription+record('D', b'\x00'),
    }
    with pytest.raises(ValueError):
        parity.validate_ulog_stream(variants[fault])


def fake_pyulog(monkeypatch, factory):
    # Only the external decoder is replaced; raw framing and row checks stay real.
    monkeypatch.setattr(parity.importlib.metadata, 'version', lambda _: '1.2.4')
    monkeypatch.setitem(sys.modules, 'pyulog', SimpleNamespace(ULog=factory))


def test_raw_count_cannot_be_hidden_by_decoder(monkeypatch, tmp_path):
    definitions, subscription, data = log_parts()
    path = tmp_path/'log.ulg'
    path.write_bytes(definitions+subscription+data[0]+data[0])
    def parser(stream, **kwargs):
        stream.read()
        stream.read(3)  # Normal pinned-parser EOF; exposes only one of two rows.
        return ulog()
    fake_pyulog(monkeypatch, parser)
    with pytest.raises(ValueError, match='count'):
        parity.read_receiver_log(path)


@pytest.mark.parametrize('error', [struct.error('short definition'), NotImplementedError('incompat'),
                                 RecursionError('recursive format')])
def test_parser_errors_leave_cli_refusal_artifact(monkeypatch, tmp_path, error):
    definitions, subscription, data = log_parts()
    log = tmp_path/'log.ulg'
    log.write_bytes(definitions+subscription+data[0])
    packets = tmp_path/'packets.json'
    packets.write_text('[]')
    clock = tmp_path/'clock.json'
    clock.write_text('{"schema":"px4-receiver-parity-clock-v1","px4_minus_remote_us":10000}')
    output = tmp_path/'audit.json'
    def broken_parser(*args, **kwargs):
        raise error
    fake_pyulog(monkeypatch, broken_parser)
    monkeypatch.setattr(cli, 'decode_sent_packets', lambda _: [fixture()[0]])
    rc = cli.main(['--packets',str(packets),'--clock',str(clock),'--ulog',str(log),'--output',str(output)])
    assert rc == 2
    result = json.loads(output.read_text())
    assert result['field_parity_pass'] is False
    assert result['failures']
    assert result['receiver_stage_qualified'] is False


def test_same_validated_bytes_are_passed_to_decoder(monkeypatch, tmp_path):
    definitions, subscription, data = log_parts()
    raw = definitions+subscription+data[0]
    path = tmp_path/'log.ulg'
    path.write_bytes(raw)
    seen = []
    def parser(stream, **kwargs):
        seen.append(stream.read())
        stream.read(3)
        path.write_bytes(b'changed after read')
        return ulog()
    fake_pyulog(monkeypatch, parser)
    rows, _ = parity.read_receiver_log(path)
    assert seen == [raw]
    assert rows == [fixture()[1]]


def test_swallowed_parser_error_at_end_cannot_look_like_normal_eof(monkeypatch, tmp_path):
    definitions, subscription, data = log_parts()
    path = tmp_path/'log.ulg'
    path.write_bytes(definitions+subscription+data[0]+record('L', b''))
    def stopped_parser(stream, **kwargs):
        stream.read()  # Full payload consumed but internal error prevented next header read.
        return ulog()
    fake_pyulog(monkeypatch, stopped_parser)
    with pytest.raises(ValueError, match='normal EOF'):
        parity.read_receiver_log(path)
