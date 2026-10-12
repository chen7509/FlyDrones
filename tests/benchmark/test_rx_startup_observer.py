"""Non-controlling trace with fake sockets and clocks only."""
import copy
import hashlib
import json
import struct
from types import SimpleNamespace

import pytest

from tools.benchmark import observe_kernel_rx_startup as study
from tools.benchmark.observe_kernel_rx_startup import CONDITIONS, collect_trace, decode_observation


class Harness:
    def __init__(self, *, missing=(), fault=None):
        self.now = 10_000_000
        self.real_origin = 1_800_000_000_000_000_000
        self.missing, self.fault = set(missing), fault
        self.current = None
        self.calls = []
        self.records = []
        self.checks = 0
        self.last_send_real = None
        self.stamps = SimpleNamespace(check=self.check)
        self.receiver = SimpleNamespace(recvmsg=self.recv)
        self.sender = SimpleNamespace(sendto=self.send)

    def mono(self):
        if self.fault == 'regress':
            self.now -= 1
        else:
            self.now += 1
        return self.now

    def real(self):
        if self.fault == 'after_send_clock' and self.current is not None:
            raise OSError('clock after send')
        if self.fault == 'after_recv_clock' and 'recv' in self.calls:
            raise OSError('clock after recv')
        return self.real_origin + self.now

    def sleep(self, duration):
        self.now += round(duration * 1_000_000_000)

    def check(self, _socket):
        self.checks += 1
        if self.fault == 'option' and self.checks == 3:
            raise ValueError('option changed')

    def send(self, data, _destination):
        self.current = data
        self.last_send_real = self.real_origin + self.now
        self.calls.append('send')
        if self.fault == 'send':
            raise OSError('send failed')
        return len(data) - 1 if self.fault == 'partial' else len(data)

    def recv(self, *_args):
        self.calls.append('recv')
        if self.fault == 'eagain':
            raise BlockingIOError()
        if self.fault == 'recv':
            raise OSError('recv failed')
        index = int(self.current.rsplit(b':', 1)[-1])
        sec, nsec = divmod(self.last_send_real, 1_000_000_000)
        ancillary = [] if index in self.missing else [(1, 65, struct.pack('<6q', sec, nsec, 0, 0, 0, 0))]
        return (b'wrong' if self.fault == 'payload' else self.current,
                ancillary, 32 if self.fault == 'flags' else 0,
                ('127.0.0.1', 2 if self.fault == 'peer' else 1))

    def sink(self, row):
        self.records.append(copy.deepcopy(row))
        if self.fault == 'journal':
            raise OSError('journal failed')

    def run(self):
        return collect_trace(self.receiver, self.sender, self.stamps, CONDITIONS,
            peer=('127.0.0.1', 1), destination=('127.0.0.1', 2), nonce='a'*32,
            journal=self.sink, monotonic_ns=self.mono, realtime_ns=self.real, sleep=self.sleep)


def test_first_missing_later_present_preserves_all_and_no_qualification():
    harness = Harness(missing=(0,))
    result = harness.run()
    assert result['status'] == 'observed' and len(result['packets']) == 8
    assert result['production_would_refuse_at'] == 0
    assert result['metadata_present_indices'] == list(range(1, 8))
    assert result['packets'][0]['ancillary_raw'] == []
    assert all(not result[name] for name in ('arrival_qualified', 'clock_qualified', 'source_authenticated',
                                             'fusion_qualified', 'training_eligible'))
    starts = [row['send_start_monotonic_ns'] for row in result['packets']]
    assert all(b-a >= 50_000_000 for a, b in zip(starts, starts[1:]))
    assert all(row['recv_start_monotonic_ns'] - row['send_return_monotonic_ns'] >= 20_000_000
               for row in result['packets'])
    assert result['errors'] == []


def test_all_missing_is_completed_observation_and_never_timestamp_success():
    result = Harness(missing=range(8)).run()
    assert result['status'] == 'observed' and result['metadata_present_indices'] == []
    assert result['production_would_refuse_at'] == 0
    assert all(row['metadata']['timestamp_ns'] is None for row in result['packets'])


@pytest.mark.parametrize('fault', ['send', 'partial', 'recv', 'payload', 'peer', 'flags',
                                  'eagain', 'option', 'regress', 'journal'])
def test_identity_io_clock_fault_stops_without_resend(fault):
    harness = Harness(fault=fault)
    result = harness.run()
    assert result['status'] == 'failed' and result['errors']
    assert harness.calls.count('send') <= 1
    assert not result['arrival_qualified']
    if fault == 'eagain':
        assert harness.now < 500_000_000


@pytest.mark.parametrize('fault, field', [('after_send_clock', 'send_returned'),
                                         ('after_recv_clock', 'recv_returned')])
def test_successful_syscall_survives_following_clock_exception(fault, field):
    harness = Harness(fault=fault)
    result = harness.run()
    assert result['status'] == 'failed'
    assert result['packets'][0][field] is True
    assert result['packets'][0]['payload_hex'] == harness.current.hex()
    if field == 'recv_returned':
        assert result['packets'][0]['received_payload_hex'] == harness.current.hex()
        assert result['packets'][0]['ancillary_raw']


@pytest.mark.parametrize('ancillary, flags', [([], 0), ([], True), ([(1, 64, b'a'*48)], 0),
    ([(1, 65, b'a'*16)], 0), ([(1, 65, struct.pack('<6q', 1, 0, 1, 0, 0, 0))], 0),
    ([(1, 65, struct.pack('<6q', 0, 1, 0, 0, 0, 0))], 0),
    ([(1, 65, struct.pack('<6q', 2**63-1, 0, 0, 0, 0, 0))], 0)])
def test_unknown_or_malformed_metadata_never_gets_callback_timestamp(ancillary, flags):
    result = decode_observation(ancillary, flags, 1_800_000_000_000_000_000)
    assert result['timestamp_ns'] is None and result['reason']


def test_exact_generated_metadata_still_only_observation():
    result = decode_observation([(1, 65, struct.pack('<6q', 1, 2, 0, 0, 0, 0))], 0, 1_000_000_003)
    assert result['timestamp_ns'] == 1_000_000_002 and result['reason'] is None


def test_future_metadata_retained_as_reason_not_replaced():
    result = decode_observation([(1, 65, struct.pack('<6q', 2, 2, 0, 0, 0, 0))], 0, 1_000_000_003)
    assert result['timestamp_ns'] is None and 'future' in result['reason']


def declared():
    return {**copy.deepcopy(CONDITIONS), 'sources': {
        name: hashlib.sha256((study.ROOT / name).read_bytes()).hexdigest() for name in study.SOURCES},
        'abi_sha256': study.prior.ABI_SHA, 'probe_sha256': study.prior.PROBE_SHA}


def test_declaration_binds_all_current_source_and_installed_capability_without_execution():
    raw = json.dumps(declared()).encode()
    assert study.validate_profile(raw, hashlib.sha256(raw).hexdigest()) == declared()


@pytest.mark.parametrize('field, value', [('count', 7), ('count', True), ('gap_ns', 40_000_000),
                                       ('local', ['127.0.0.1', False]), ('abi_sha256', '0'*64),
                                       ('extra', 1)])
def test_declaration_drift_refuses_before_socket_use(field, value):
    profile = declared()
    profile[field] = value
    raw = json.dumps(profile).encode()
    with pytest.raises(ValueError):
        study.validate_profile(raw, hashlib.sha256(raw).hexdigest())


def test_source_hash_and_duplicate_profile_keys_refuse():
    profile = declared()
    profile['sources'][study.SOURCES[0]] = '0'*64
    raw = json.dumps(profile).encode()
    with pytest.raises(ValueError, match='source drift'):
        study.validate_profile(raw, hashlib.sha256(raw).hexdigest())
    raw = b'{"count":8,"count":8}'
    with pytest.raises(ValueError, match='duplicate'):
        study.validate_profile(raw, hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize('mode', ['short', 'flush'])
def test_journal_incomplete_write_refuses(mode):
    writer = SimpleNamespace(write=lambda data: len(data)-1 if mode == 'short' else len(data),
                             flush=lambda: (_ for _ in ()).throw(OSError('flush failed')))
    with pytest.raises(OSError):
        study._write(writer, {'raw': 'retained'})


def test_journal_mutation_does_not_change_retained_original():
    harness = Harness(missing=(0,))
    def sink(row):
        row['payload_hex'] = '00'
        if row['metadata'] is not None:
            row['metadata']['timestamp_ns'] = 0
    harness.sink = sink
    result = harness.run()
    assert result['status'] == 'observed'
    assert result['packets'][0]['payload_hex'].startswith(b'FLYD_RX_STARTUP_V1'.hex())
    assert result['packets'][1]['metadata']['timestamp_ns'] > 0


def test_boolean_clock_and_early_sleep_refuse():
    harness = Harness()
    harness.mono = lambda: True
    assert harness.run()['status'] == 'failed'
    harness = Harness()
    harness.sleep = lambda _duration: None
    assert harness.run()['status'] == 'failed'


def test_receive_return_after_poll_deadline_retained_but_refused():
    harness = Harness()
    receive = harness.recv
    def delayed(*args):
        harness.now += 250_000_000
        return receive(*args)
    harness.receiver.recvmsg = delayed
    result = harness.run()
    assert result['status'] == 'failed'
    assert len(result['packets']) == 1 and result['packets'][0]['recv_returned']


def test_pre_send_journal_delay_cannot_fake_inter_send_pacing():
    harness = Harness()
    actual_sends = []
    send, sink = harness.send, harness.sink
    def journal(row):
        if row['index'] == 0 and row['phase'] == 'send_attempt':
            harness.now += 100_000_000
        sink(row)
    def actual(data, destination):
        actual_sends.append(harness.now)
        return send(data, destination)
    harness.sink, harness.sender.sendto = journal, actual
    result = harness.run()
    assert result['status'] == 'observed'
    assert all(b-a >= 50_000_000 for a, b in zip(actual_sends, actual_sends[1:]))


def test_pre_send_journal_timeout_prevents_any_new_send():
    harness = Harness()
    def journal(_row):
        harness.now += 6_000_000_000
    harness.sink = journal
    result = harness.run()
    assert result['status'] == 'failed' and 'send' not in harness.calls


def test_final_journal_timeout_cannot_claim_observed_completion():
    harness = Harness()
    def journal(row):
        if row['index'] == 7 and row['phase'] == 'observed':
            harness.now += 6_000_000_000
    harness.sink = journal
    result = harness.run()
    assert result['status'] == 'failed' and len(result['packets']) == 8


def test_existing_output_refuses_before_creating_any_socket(tmp_path, monkeypatch):
    profile = declared()
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(profile))
    output = tmp_path / 'capture'
    output.mkdir()
    monkeypatch.setattr(study, 'check_module_origins', lambda: {})
    def socket(*_args):
        pytest.fail('must refuse before socket creation')
    monkeypatch.setattr(study.socket, 'socket', socket)
    with pytest.raises(FileExistsError):
        study.run(profile, output, profile_path=path, profile_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def test_setup_failure_still_closes_owned_socket_and_records_failure(tmp_path, monkeypatch):
    profile = declared()
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(profile))
    closed = []
    receiver = object()
    monkeypatch.setattr(study, 'check_module_origins', lambda: {})
    monkeypatch.setattr(study.socket, 'socket', lambda *_args: receiver)
    monkeypatch.setattr(study, 'close_owned', lambda sock, rows: closed.append(sock))
    class Stamp:
        def __init__(self, *_args): pass
        def enable_before_bind(self, _sock):
            raise OSError('setup failed')
        evidence = {'failure': 'setup failed', 'enabled_before_bind': False}
    monkeypatch.setattr(study, 'KernelRXTimestamping', Stamp)
    with pytest.raises(RuntimeError, match='failed'):
        study.run(profile, tmp_path / 'capture', profile_path=path,
                  profile_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    record = json.loads((tmp_path / 'capture/result.json').read_text())
    assert closed == [receiver] and record['status'] == 'failed'
    assert any('setup failed' in error for error in record['errors'])
    assert all(record[name] is False for name in ('arrival_qualified', 'clock_qualified',
               'source_authenticated', 'fusion_qualified', 'training_eligible'))
    assert record['prepared_profile_evidence'] == Stamp.evidence


def test_sender_setup_failure_preserves_rx_and_attempts_both_closes(tmp_path, monkeypatch):
    profile = declared()
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(profile))
    closed = []
    rx = SimpleNamespace(bind=lambda _where: None, setblocking=lambda _flag: None)
    def broken_bind(_where):
        raise OSError('sender bind failed')
    tx = SimpleNamespace(bind=broken_bind)
    sockets = iter((rx, tx))
    monkeypatch.setattr(study, 'check_module_origins', lambda: {})
    monkeypatch.setattr(study.socket, 'socket', lambda *_args: next(sockets))
    monkeypatch.setattr(study, 'snapshot', lambda sock: {'fd': 7 if sock is rx else 8})
    def close(sock, rows):
        closed.append(sock)
        rows.append({'attempted': True})
        if sock is tx:
            raise OSError('first close failed')
    monkeypatch.setattr(study, 'close_owned', close)
    class Stamp:
        def __init__(self, *_args): pass
        def enable_before_bind(self, _sock): pass
        evidence = {'enabled_before_bind': True}
    monkeypatch.setattr(study, 'KernelRXTimestamping', Stamp)
    with pytest.raises(RuntimeError):
        study.run(profile, tmp_path / 'capture', profile_path=path,
                  profile_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    record = json.loads((tmp_path / 'capture/result.json').read_text())
    assert closed == [tx, rx] and record['receiver_identity'] == {'fd': 7}
    assert any('sender bind failed' in error for error in record['errors'])
    assert any('first close failed' in error for error in record['errors'])


def test_journal_close_failure_prevents_complete_result(tmp_path, monkeypatch):
    profile = declared()
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(profile))
    objects = [SimpleNamespace(bind=lambda _where: None, setblocking=lambda _flag: None,
                              settimeout=lambda _seconds: None) for _ in range(2)]
    sockets = iter(objects)
    monkeypatch.setattr(study, 'check_module_origins', lambda: {})
    monkeypatch.setattr(study.socket, 'socket', lambda *_args: next(sockets))
    monkeypatch.setattr(study, 'snapshot', lambda sock: {'fd': id(sock), 'local': ['127.0.0.1', 1]})
    monkeypatch.setattr(study, 'close_owned', lambda _sock, _rows: None)
    monkeypatch.setattr(study, 'collect_trace', lambda *_args, **_kwargs: {'status': 'observed', 'errors': []})
    class Stamp:
        def __init__(self, *_args): pass
        def enable_before_bind(self, _sock): pass
        evidence = {'enabled_before_bind': True}
    monkeypatch.setattr(study, 'KernelRXTimestamping', Stamp)
    original = study.Path.open
    def open_path(value, *args, **kwargs):
        stream = original(value, *args, **kwargs)
        if value.name == 'packets.jsonl':
            def close():
                stream.close()
                raise OSError('journal close failed')
            return SimpleNamespace(close=close)
        return stream
    monkeypatch.setattr(study.Path, 'open', open_path)
    with pytest.raises(RuntimeError):
        study.run(profile, tmp_path / 'capture', profile_path=path,
                  profile_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    record = json.loads((tmp_path / 'capture/result.json').read_text())
    assert record['status'] == 'failed' and any('journal close failed' in x for x in record['errors'])
