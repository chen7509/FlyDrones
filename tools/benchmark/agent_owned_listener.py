"""Bounded Agent-only UDP listener diagnosis; never starts PX4 or authorizes DDS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

from tools.benchmark.owned_group_evidence import GroupEvidence

BUNDLE_SHA256 = '4a5a104380bd320f87a3e1df1db4007287a4be4102d8ac511187ce69dd55596b'
AGENT_SHA256 = 'ded56cf545394670effaf112c642d62e8dd0e7145e53a6c9b0593014b721fcfe'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_owned_udp_listener(raw, pid, port):
    """Require exactly one IPv4 UDP socket row attributed to the owned PID."""
    if type(pid) is not int or pid <= 1 or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid listener identity')
    rows = raw.strip().splitlines()
    if len(rows) != 1:
        raise ValueError('expected exactly one UDP listener row')
    row = rows[0]
    fields = row.split()
    # `ss -H -lunp` selects UDP but omits the Netid column on this iproute2.
    if len(fields) < 6 or fields[0] != 'UNCONN':
        raise ValueError('invalid UDP listener row')
    if fields[3] not in (f'0.0.0.0:{port}', f'127.0.0.1:{port}'):
        raise ValueError('wrong IPv4 listener endpoint')
    owners = re.findall(r'pid=(\d+),fd=\d+', row)
    if owners != [str(pid)]:
        raise ValueError('UDP socket owner mismatch')
    return row


def ss(port):
    return subprocess.run(['ss', '-H', '-lunp', f'sport = :{port}'], check=True,
                          capture_output=True, text=True, timeout=2).stdout


def diagnose(bundle, output, port=18888):
    bundle, output = Path(bundle).resolve(strict=True), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    result = dict(schema='agent-owned-listener-v1', status='failed', port=port,
                  bundle_sha256=sha256(bundle), agent_sha256=None, pid=None,
                  listener_owned=False, no_listener_after=False, cleanup=None,
                  px4_started=False, xrce_client_authenticated=False,
                  typed_dds_provenance=False, fusion_qualified=False, errors=[])
    scratch = None
    worker = evidence = None
    out_stream = err_stream = group_stream = None
    try:
        if result['bundle_sha256'] != BUNDLE_SHA256:
            raise ValueError('sealed Agent bundle hash mismatch')
        if ss(port).strip():
            raise ValueError('UDP port already has a listener')
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(('0.0.0.0', port))
        scratch = Path(tempfile.mkdtemp(prefix='fly-agent-listener-'))
        with tarfile.open(bundle, 'r:gz') as archive:
            members = archive.getmembers()
            if any(name.name.startswith('/') or '..' in Path(name.name).parts for name in members):
                raise ValueError('unsafe bundle member path')
            archive.extractall(scratch, filter='data')
        binary = scratch / 'bin/MicroXRCEAgent'
        result['agent_sha256'] = sha256(binary)
        if result['agent_sha256'] != AGENT_SHA256:
            raise ValueError('sealed Agent executable hash mismatch')
        env = os.environ.copy()
        env['LD_LIBRARY_PATH'] = str(scratch / 'lib')
        out_stream = (output / 'agent.stdout').open('x')
        err_stream = (output / 'agent.stderr').open('x')
        group_stream = (output / 'group-events.jsonl').open('x')
        worker = subprocess.Popen([str(binary), 'udp4', '-p', str(port)],
                                  cwd=scratch, env=env, start_new_session=True,
                                  stdin=subprocess.DEVNULL, stdout=out_stream,
                                  stderr=err_stream)
        result['pid'] = worker.pid
        evidence = GroupEvidence(worker, group_stream)
        if evidence.owner is None or evidence.errors:
            raise RuntimeError('Agent process group identity unavailable')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            evidence.identity()
            if worker.poll() is not None:
                raise RuntimeError('Agent exited before listener proof')
            observed = ss(port)
            (output / 'listener-ss.txt').write_text(observed)
            if observed.strip():
                result['listener_row'] = parse_owned_udp_listener(observed, worker.pid, port)
                result['listener_owned'] = True
                break
            time.sleep(0.05)
        if not result['listener_owned']:
            raise TimeoutError('owned Agent listener not observed within five seconds')
    except (Exception, KeyboardInterrupt) as exc:
        result['errors'].append(repr(exc))
    finally:
        if evidence is not None:
            result['cleanup'] = evidence.terminate()
            try:
                result['worker_exit'] = worker.wait(timeout=5)
                evidence.snapshot('after_leader_reap')
            except (Exception, KeyboardInterrupt) as exc:
                result['errors'].append('reap: ' + repr(exc))
            evidence.close()
            result['cleanup'] = evidence.summary()
        for stream in (out_stream, err_stream, group_stream):
            if stream is not None and not stream.closed:
                stream.close()
        try:
            remaining = ss(port)
            (output / 'listener-after-ss.txt').write_text(remaining)
            result['no_listener_after'] = not bool(remaining.strip())
        except Exception as exc:
            result['errors'].append('post-listener: ' + repr(exc))
        if scratch is not None:
            shutil.rmtree(scratch)
        result['status'] = ('agent_only_passed' if result['listener_owned'] and result['no_listener_after']
                            and result['cleanup'] and result['cleanup']['graceful_group_cleanup_verified']
                            and not result['errors'] else 'failed')
        (output / 'result.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18888)
    args = parser.parse_args()
    return 0 if diagnose(args.bundle, args.output, args.port)['status'] == 'agent_only_passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
