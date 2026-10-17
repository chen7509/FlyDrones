"""Exact-file declaration for an optional, unarmed PX4 XRCE Agent capture."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import time
from pathlib import Path

from tools.benchmark.agent_owned_listener import parse_owned_udp_listener, ss
from tools.benchmark.capture_contract import read_declaration
from tools.benchmark.owned_group_evidence import GroupEvidence


class AgentListenerPending(ValueError):
    """No UDP endpoint yet; other malformed or conflicting rows are terminal."""

BUNDLE_SHA256 = '4a5a104380bd320f87a3e1df1db4007287a4be4102d8ac511187ce69dd55596b'
AGENT_SHA256 = 'ded56cf545394670effaf112c642d62e8dd0e7145e53a6c9b0593014b721fcfe'
LIBRARY_SHA256 = {
    'libfastcdr.so': '5f63f565828bd5d03073200047f72da4ef1e9ca7a009d52a32f684accc47fdab',
    'libfastcdr.so.2.2.8': '5f63f565828bd5d03073200047f72da4ef1e9ca7a009d52a32f684accc47fdab',
    'libfastrtps.so': 'a98ac4c05241aaa89bc16ddb43666de1b46d033256b9ee4d7f12800be7661888',
    'libfastrtps.so.2.14.7': 'a98ac4c05241aaa89bc16ddb43666de1b46d033256b9ee4d7f12800be7661888',
    'libmicrocdr.so': '560e1a87b7160da5d63c2e5fa03374ea7041a7eeeb448eaac2750b7b6143a6d8',
    'libmicrocdr.so.2.0': '560e1a87b7160da5d63c2e5fa03374ea7041a7eeeb448eaac2750b7b6143a6d8',
    'libmicrocdr.so.2.0.1': '560e1a87b7160da5d63c2e5fa03374ea7041a7eeeb448eaac2750b7b6143a6d8',
    'libmicroxrcedds_agent.so': '37b1fb3ffb0c769998e0df00b9cd238309eecc3d237956b7e831979571019341',
    'libmicroxrcedds_agent.so.2.4': '37b1fb3ffb0c769998e0df00b9cd238309eecc3d237956b7e831979571019341',
    'libmicroxrcedds_agent.so.2.4.3': '37b1fb3ffb0c769998e0df00b9cd238309eecc3d237956b7e831979571019341',
    'libmicroxrcedds_client.so': '84bd36a21c427e10939a547b7a43dee53d45d68349664daebbe744cd52abc9c2',
    'libmicroxrcedds_client.so.2.4': '84bd36a21c427e10939a547b7a43dee53d45d68349664daebbe744cd52abc9c2',
    'libmicroxrcedds_client.so.2.4.3': '84bd36a21c427e10939a547b7a43dee53d45d68349664daebbe744cd52abc9c2',
}


def _stable_file(path, expected, label):
    path = Path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(label + ' must be a regular file')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if any(getattr(before, name) != getattr(after, name) for name in fields):
        raise ValueError(label + ' changed during hash')
    if digest != expected:
        raise ValueError(label + ' fixed SHA256 mismatch')
    return dict(path=str(path), resolved=str(path.resolve(strict=True)), bytes=after.st_size,
                sha256=digest, device=after.st_dev, inode=after.st_ino)


def agent_runtime_record(path):
    """Return selected files, or reject any ambiguity before a capture launches."""
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError('absolute regular Agent declaration required')
    before = path.stat()
    payload = path.read_bytes()
    document = read_declaration(path)
    if payload != path.read_bytes():
        raise ValueError('Agent declaration bytes changed during validation')
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('Agent declaration changed during read')
    if (type(document) is not dict
            or document.keys() != {'schema', 'bundle', 'binary', 'lib_dir', 'port'}
            or document['schema'] != 'capture-agent-runtime-v1'
            or type(document['port']) is not int or document['port'] != 18888):
        raise ValueError('Agent declaration schema or port mismatch')
    selected = [str(path)]
    records = []
    for key, expected in (('bundle', BUNDLE_SHA256), ('binary', AGENT_SHA256)):
        value = document[key]
        if type(value) is not str or not Path(value).is_absolute() or '..' in Path(value).parts:
            raise ValueError('Agent ' + key + ' path invalid')
        entry = _stable_file(value, expected, key)
        selected.append(value)
        records.append(entry)
    binary = Path(document['binary'])
    lib_dir = document['lib_dir']
    if (type(lib_dir) is not str or not Path(lib_dir).is_absolute()
            or '..' in Path(lib_dir).parts or not Path(lib_dir).is_dir()
            or not binary.is_file() or not re.fullmatch('[0-9a-f]{64}', AGENT_SHA256)):
        raise ValueError('Agent library directory invalid')
    directory = Path(lib_dir).resolve(strict=True)
    if {item.name for item in Path(lib_dir).iterdir()} != set(LIBRARY_SHA256):
        raise ValueError('Agent library file set mismatch')
    for name, expected in sorted(LIBRARY_SHA256.items()):
        item = Path(lib_dir) / name
        if item.resolve(strict=True).parent != directory:
            raise ValueError('Agent library escapes declared directory: ' + name)
        records.append(_stable_file(item, expected, name))
        selected.append(str(item))
    return dict(schema='capture-agent-runtime-record-v1', declaration=str(path),
                declaration_sha256=hashlib.sha256(payload).hexdigest(),
                configuration=document, selected_paths=selected, files=records,
                authority=False, typed_dds_provenance=False, fusion_qualified=False)


class OwnedCaptureAgent:
    """Own an Agent listener in the unarmed capture; no DDS source grant."""

    def __init__(self, process, record, output, stdout, stderr, events, *, socket_query=ss,
                 clock=time.monotonic, sleep=time.sleep, group_factory=GroupEvidence):
        self.process, self.record, self.output = process, record, Path(output)
        self.stdout, self.stderr, self.events = stdout, stderr, events
        self.socket_query, self.clock, self.sleep = socket_query, clock, sleep
        self.group = group_factory(process, events)
        self.failure = None
        self.proof = None
        self.last_socket_check = None
        self.socket_checks = 0
        self.closed = False

    def check(self, *, force=False):
        if self.closed or self.failure is not None:
            raise ValueError('Agent session failed or closed')
        try:
            self.group.identity()
            if self.process.poll() is not None:
                raise RuntimeError('owned Agent exited during capture')
            now = self.clock()
            if force or self.last_socket_check is None or now - self.last_socket_check >= 0.5:
                if self.socket_checks >= 1024:
                    raise RuntimeError('Agent socket journal capacity exceeded')
                raw = self.socket_query(self.record['configuration']['port'])
                if not raw.strip():
                    raise AgentListenerPending('Agent listener has not appeared')
                row = parse_owned_udp_listener(raw, self.process.pid, self.record['configuration']['port'])
                with (self.output / 'agent-socket.jsonl').open('a', encoding='utf-8') as stream:
                    encoded = json.dumps(dict(monotonic_s=now, pid=self.process.pid, row=row)) + '\n'
                    if stream.write(encoded) != len(encoded):
                        raise OSError('short Agent socket journal write')
                    stream.flush()
                self.socket_checks += 1
                self.last_socket_check = now
                self.proof = row
        except AgentListenerPending:
            raise
        except Exception as exc:
            self.failure = repr(exc)
            raise
        return True

    def await_listener(self, *, timeout_s=5):
        deadline = self.clock() + timeout_s
        while True:
            try:
                return self.check(force=True)
            except AgentListenerPending:
                pass
            if self.clock() >= deadline:
                self.failure = 'owned Agent listener startup timeout'
                raise TimeoutError(self.failure)
            self.sleep(0.05)

    def stop(self):
        if self.closed:
            raise ValueError('Agent already closed')
        self.closed = True
        errors = []
        live_at_stop = self.process.poll() is None
        if not live_at_stop and self.failure is None:
            errors.append('Agent exited before capture cleanup')
        try:
            self.group.terminate()
        except Exception as exc:
            errors.append('group cleanup: ' + repr(exc))
        if self.group.errors and self.process.poll() is None:
            # The registered Popen still names this one child even if group
            # inspection failed; this cannot certify escaped descendants.
            try:
                self.process.terminate()
            except Exception as exc:
                errors.append('leader fallback TERM: ' + repr(exc))
        try:
            code = self.process.wait(timeout=5)
        except Exception as exc:
            errors.append('reap: ' + repr(exc))
            try:
                self.process.kill()
                code = self.process.wait(timeout=5)
                errors.append('leader fallback SIGKILL required')
            except Exception as final_exc:
                errors.append('leader fallback failed: ' + repr(final_exc))
                code = self.process.poll()
        try:
            self.group.snapshot('after_leader_reap')
        except Exception as exc:
            errors.append('post-reap group scan: ' + repr(exc))
        self.group.close()
        for stream in (self.stdout, self.stderr, self.events):
            if not stream.closed:
                stream.close()
        try:
            remaining = self.socket_query(self.record['configuration']['port'])
            (self.output / 'agent-after-ss.txt').write_text(remaining)
            port_released = not bool(remaining.strip())
        except Exception as exc:
            errors.append('post-listener: ' + repr(exc))
            port_released = False
        cleanup = self.group.summary()
        result = dict(pid=self.process.pid, exit_code=code, live_at_stop=live_at_stop,
                      listener_row=self.proof,
                      socket_checks=self.socket_checks, source_failure=self.failure,
                      cleanup=cleanup, port_released=port_released, errors=errors,
                      xrce_client_authenticated=False, typed_dds_provenance=False,
                      fusion_qualified=False)
        with (self.output / 'agent-result.json').open('x') as stream:
            json.dump(result, stream, indent=2)
        return result


def launch_capture_agent(record, journal, output, *, on_stop=None, before_stop=None,
                         spawn=subprocess.Popen,
                         socket_query=ss, clock=time.monotonic, sleep=time.sleep,
                         group_factory=GroupEvidence):
    """Register owned cleanup immediately after spawn, before listener wait."""
    if os.name != 'posix':
        raise RuntimeError('owned Agent requires POSIX process identity')
    if agent_runtime_record(record['declaration']) != record:
        raise ValueError('Agent files or declaration changed after preflight')
    if socket_query(18888).strip():
        raise ValueError('Agent port already occupied')
    output = Path(output)
    stdout = (output / 'agent.stdout').open('x')
    stderr = (output / 'agent.stderr').open('x')
    events = (output / 'agent-group-events.jsonl').open('x')
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = record['configuration']['lib_dir']
    try:
        process = spawn([record['configuration']['binary'], 'udp4', '-p', '18888'],
                        env=env, stdin=subprocess.DEVNULL, stdout=stdout,
                        stderr=stderr, start_new_session=True)
    except BaseException:
        for stream in (stdout, stderr, events):
            stream.close()
        raise
    try:
        agent = OwnedCaptureAgent(process, record, output, stdout, stderr, events,
                                  socket_query=socket_query, clock=clock, sleep=sleep,
                                  group_factory=group_factory)
    except BaseException:
        # Ownership failed before journal registration. Address the exact Popen
        # child immediately; this does not certify any escaped descendants.
        try:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        finally:
            for stream in (stdout, stderr, events):
                stream.close()
        raise

    def close_agent():
        before_error = None
        if before_stop is not None:
            try:
                before_stop(agent)
            except Exception as exc:
                before_error = exc
        summary = agent.stop()
        if on_stop is not None:
            on_stop(summary)
        if before_error is not None:
            raise before_error
        if not summary['cleanup']['graceful_group_cleanup_verified'] or not summary['port_released']:
            raise RuntimeError('owned Agent cleanup unqualified')

    journal.cleanup('owned Agent', close_agent, priority=30)
    agent.await_listener()
    return agent
