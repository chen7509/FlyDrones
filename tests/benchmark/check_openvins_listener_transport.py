"""Explicit private Linux wire fixture; never connects to an actual PX4 socket."""
import argparse
import hashlib
import json
import os
import selectors
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]

from tools.benchmark.openvins_listener_transport import ListenerRefusal, ReadOnlyListener, listener_command  # noqa: E402
from tools.benchmark.owned_daemon_connection import observe_owner  # noqa: E402

FIX = ROOT/'tests/fixtures/timesync'
CASES = ['snapshot-single', 'snapshot-empty', 'multi-fragmented', 'missing-trailer',
         'nonzero-trailer', 'silent-peer', 'journal-failure']
PASS = CASES[:3]
ERRORS = dict(zip(CASES[3:], ['missing trailer', 'nonzero exit', 'timeout', 'fixture journal failure']))


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        data = json.dumps(value, indent=2)+'\n'
        assert stream.write(data) == len(data)
        stream.flush()


def child(args):
    result = dict(command_hex='', writes=[], eof=False, error=None)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(args.socket)
            server.listen(1)
            server.settimeout(5)
            print(json.dumps(dict(ready=True, pid=os.getpid())), flush=True)
            connection, _ = server.accept()
            with connection:
                connection.settimeout(5)
                command = b''
                while not command.endswith(b'\0'):
                    block = connection.recv(256)
                    command += block
                    result['command_hex'] = command.hex()
                    if not block:
                        result['eof'] = True
                        break
                    if len(command) > 256:
                        raise ValueError('fixture command length')
                mode = 'snapshot' if args.case.startswith('snapshot') else 'stream'
                count = 1 if mode == 'snapshot' else 2
                expected = b'' if args.case == 'journal-failure' else listener_command(mode, count)
                assert command == expected, (command, expected)
                if args.case == 'journal-failure':
                    assert result['eof']
                else:
                    body = (FIX/'pinned-listener-implicit.bin').read_bytes() if mode == 'snapshot' else (FIX/'pinned-listener-two.bin').read_bytes()
                    if args.case == 'snapshot-empty':
                        body = b'never published\n'
                    trailer = b'' if args.case == 'missing-trailer' else b'\0\1' if args.case == 'nonzero-trailer' else b'\0\0'
                    response = body+trailer
                    if args.case != 'silent-peer':
                        sizes = [1, 2, 3, 5, 13, len(response)] if args.case == 'multi-fragmented' else [len(response)]
                        offset = 0
                        for size in sizes:
                            block = response[offset:offset+size]
                            connection.sendall(block)
                            result['writes'].append(dict(raw_hex=block.hex(), returned_ns=time.monotonic_ns()))
                            offset += len(block)
                            if args.case == 'multi-fragmented':
                                time.sleep(.002)
                        connection.shutdown(socket.SHUT_WR)
                    # Keep peer identity live through client EOF validation.
                    extra = connection.recv(256)
                    result['eof'] = extra == b''
                    assert result['eof'], extra
    except BaseException as exc:
        result['error'] = type(exc).__name__+': '+str(exc)
    finally:
        save(args.result, result)
    return 0 if result['error'] is None else 2


def main(args):
    out = args.output.absolute()
    out.mkdir(parents=True, exist_ok=False)
    files = [Path(__file__), Path(sys.executable).resolve(),
             *[ROOT/'tools/benchmark'/name for name in (
                 'openvins_listener_transport.py', 'owned_daemon_connection.py', 'owned_group_evidence.py',
                 'openvins_timesync_bootstrap.py', 'openvins_timesync_listener.py', 'openvins_timesync_observer.py')],
             FIX/'pinned-listener-implicit.bin', FIX/'pinned-listener-two.bin']

    def hashes():
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}

    before = hashes()
    save(out/'prospective.json', dict(producer=args.producer, files=before, cases=CASES,
        success=PASS, expected_errors=ERRORS, readiness_s=5, global_ns=8000000000,
        frame_ns=2000000000, poll_s=.001, fragmented_write_sizes=[1, 2, 3, 5, 13, 'rest'],
        fragmented_write_sleep_s=.002, px4_started=False, mavlink_started=False,
        provenance_scope='selected sources/fixtures/Python executable, not entire runtime closure'))
    results = []
    try:
        for case in CASES:
            folder = out/case
            folder.mkdir()
            process = adapter = None
            events, outputs, signals = [], [], []
            evidence = error = harness_error = None
            with tempfile.TemporaryDirectory(prefix='fly-listener-') as temporary:
                path = str(Path(temporary)/'socket')
                argv = [sys.executable, '-I', str(Path(__file__).resolve()), '--child', '--case', case,
                        '--socket', path, '--result', str(folder/'server.json')]
                with (folder/'stderr.txt').open('xb') as stderr:
                    try:
                        process = subprocess.Popen(argv, cwd=temporary, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                            stdout=subprocess.PIPE, stderr=stderr, start_new_session=True)
                        with selectors.DefaultSelector() as selector:
                            selector.register(process.stdout, selectors.EVENT_READ)
                            if not selector.select(5):
                                raise TimeoutError('fixture readiness')
                        assert json.loads(process.stdout.readline()) == dict(ready=True, pid=process.pid)
                        owner = observe_owner(process)
                        save(folder/'owner.json', owner)

                        def journal(event, folder=folder, events=events, case=case):
                            events.append(event)
                            save(folder/f'event-{len(events):05}.json', event)
                            if case == 'journal-failure' and event['kind'] == 'send_attempt':
                                raise OSError('fixture journal failure after retained write')

                        mode = 'snapshot' if case.startswith('snapshot') else 'stream'
                        start = time.monotonic_ns()
                        try:
                            adapter = ReadOnlyListener(process, owner, path, mode, 1 if mode == 'snapshot' else 2,
                                start, start+8000000000, journal)
                            while True:
                                row = adapter.poll()
                                if row['stdout'] or row['records'] or row['terminal'] is not None:
                                    outputs.append(dict(row, stdout=row['stdout'].hex()))
                                if row['terminal'] is not None:
                                    break
                                time.sleep(.001)
                        except ListenerRefusal as exc:
                            error, evidence = str(exc), exc.evidence
                        finally:
                            if adapter is not None:
                                adapter.close()
                                evidence = adapter.evidence
                        assert evidence['transport_complete'] == (case in PASS), evidence
                        if case not in PASS:
                            assert ERRORS[case] in error, error
                        assert not any(evidence[k] for k in ('fusion_qualified', 'network_authorized', 'live_listener_qualified'))
                        process.wait(timeout=5)
                        server = json.loads((folder/'server.json').read_text())
                        assert server['error'] is None and server['eof'] and process.returncode == 0, server
                        assert events == evidence['events']
                        if case in PASS:
                            expected_body = b'never published\n' if case == 'snapshot-empty' else (FIX/('pinned-listener-implicit.bin' if mode == 'snapshot' else 'pinned-listener-two.bin')).read_bytes()
                            assert b''.join(bytes.fromhex(row['stdout']) for row in outputs) == expected_body
                            assert outputs[-1]['terminal'] is not None
                    except BaseException as exc:
                        harness_error = type(exc).__name__+': '+str(exc)
                        raise
                    finally:
                        if adapter is not None:
                            adapter.close()
                        if process is not None:
                            if process.poll() is None:
                                signals.append('TERM')
                                process.terminate()
                                try:
                                    process.wait(timeout=3)
                                except subprocess.TimeoutExpired:
                                    signals.append('KILL')
                                    process.kill()
                                    process.wait(timeout=3)
                            process.stdout.close()
                        result = dict(case=case, error=error, harness_error=harness_error, evidence=evidence,
                            outputs=outputs, cleanup=dict(pid=None if process is None else process.pid,
                            signals=signals, exit=None if process is None else process.returncode))
                        save(folder/'result.json', result)
                        results.append(result)
    finally:
        after = hashes()
        save(out/'post-hashes.json', after)
        save(out/'summary.json', dict(results=results, files_stable=before == after,
            complete=len(results) == len(CASES) and all(r['harness_error'] is None for r in results)))
    assert before == after
    print('7 private listener cases matched;3 complete,4 expected refusals; no PX4/MAVLink')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--socket')
    parser.add_argument('--result', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--producer')
    args = parser.parse_args()
    raise SystemExit(child(args) if args.child else main(args))
