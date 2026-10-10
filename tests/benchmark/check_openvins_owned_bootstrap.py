"""Explicit local ordinary daemon composition fixture, never actual PX4/MAVLink."""

import argparse
import hashlib
import json
import os
import selectors
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tools.benchmark.openvins_owned_bootstrap import BootstrapRefusal, OwnedBootstrap  # noqa: E402
from tools.benchmark.owned_daemon_connection import observe_owner  # noqa: E402

CASES = ["normal500", "wrong-replay", "early-eof", "nonzero-final", "silent-mid", "journal-failure"]
EXPECTED = dict(zip(CASES, [None, "ordinal", "premature EOF", "nonzero", "timeout", "fixture intent journal failure"]))


def body(index):
    request = 100000 + index * 20000
    response = request + 1000
    raw = (
        f" timesync_status\n    timestamp: {request + 2000} (0.000001 seconds ago)\n"
        f"    remote_timestamp: {response}\n    observed_offset: 0\n"
        "    estimated_offset: 0\n    round_trip_time: 2000\n    source_protocol: 0\n\n"
    ).encode()
    return request * 1000, response * 1000, raw


def frame(index):
    return b"\x1b[2J\n\x1b[H" + f"\nTOPIC: timesync_status instance 0 #{index + 1}\n".encode() + body(index)[2]


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        raw = json.dumps(value, indent=2) + "\n"
        assert stream.write(raw) == len(raw)
        stream.flush()


def control_read():
    with selectors.DefaultSelector() as selector:
        selector.register(sys.stdin, selectors.EVENT_READ)
        if not selector.select(5):
            raise TimeoutError("fixture control timeout")
    raw = sys.stdin.buffer.readline(256)
    value = json.loads(raw)
    return value


def child(args):
    result = dict(commands=[], controls=[], output=[], eof=[], error=None)

    def control():
        value = control_read()
        result["controls"].append(dict(value=value, at_ns=time.monotonic_ns()))
        return value

    def emit(connection, data):
        connection.sendall(data)
        result["output"].append(dict(raw_hex=data.hex(), returned_ns=time.monotonic_ns()))

    def open_command(server, expected):
        connection, _ = server.accept()
        connection.settimeout(5)
        data = b""
        while not data.endswith(b"\0"):
            block = connection.recv(256)
            data += block
            if not block or len(data) > 256:
                connection.close()
                raise ValueError("fixture command missing or oversized")
        result["commands"].append(data.hex())
        assert data == expected, data
        return connection

    def finish(connection, trailer=b"\0\0"):
        emit(connection, trailer)
        connection.shutdown(socket.SHUT_WR)
        value = connection.recv(256)
        result["eof"].append(value == b"")
        assert value == b"", value

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(args.socket)
            server.listen(3)
            server.settimeout(5)
            print(json.dumps(dict(ready=True, pid=os.getpid())), flush=True)
            with open_command(server, b"listener timesync_status -n 1\0") as connection:
                emit(connection, b"never published\n")
                finish(connection)
            first = control()
            if args.case == "journal-failure":
                assert first == {"stop": True}
            else:
                assert first == {"index": 0}
                with open_command(server, b"listener timesync_status -n 1\0") as connection:
                    emit(connection, b"\nTOPIC: timesync_status\n" + body(0)[2])
                    finish(connection)
                with open_command(server, b"listener timesync_status -i 0 -n 500\0") as connection:
                    replay = frame(1 if args.case == "wrong-replay" else 0)
                    emit(connection, replay[:17])
                    time.sleep(0.001)
                    emit(connection, replay[17:])
                    stopped = False
                    for index in range(1, 500):
                        command = control()
                        if command == {"stop": True}:
                            assert args.case == "wrong-replay"
                            assert connection.recv(256) == b""
                            result["eof"].append(True)
                            stopped = True
                            break
                        assert command == {"index": index}, command
                        if args.case == "early-eof" and index == 250:
                            break
                        if args.case == "silent-mid" and index == 2:
                            assert connection.recv(256) == b""
                            result["eof"].append(True)
                            stopped = True
                            break
                        emit(connection, frame(index))
                    if not stopped:
                        finish(connection, b"\0\1" if args.case == "nonzero-final" else b"\0\0")
                    if args.case != "wrong-replay":
                        assert control() == {"stop": True}
    except BaseException as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        save(args.result, result)
    return 0 if result["error"] is None else 2


def main(args):
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    files = [
        Path(__file__),
        Path(sys.executable).resolve(),
        *[
            ROOT / "tools/benchmark" / name
            for name in (
                "openvins_owned_bootstrap.py",
                "openvins_listener_transport.py",
                "owned_daemon_connection.py",
                "owned_group_evidence.py",
                "openvins_timesync_bootstrap.py",
                "openvins_timesync_listener.py",
                "openvins_timesync_observer.py",
                "openvins_ekf2_disarmed_preflight.py",
            )
        ],
    ]

    def hashes():
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}

    before = hashes()
    save(
        output / "prospective.json",
        dict(
            producer=args.producer,
            cases=CASES,
            expected=EXPECTED,
            files=before,
            global_ns=8000000000,
            progress_ns=2000000000,
            poll_s=0.001,
            sample_count=500,
            start_basis="monotonic after ordinary fixture readiness, not actual PX4 cold launch",
            status_basis="synthetic field template; no PX4 filter execution; request us=100000+i*20000, RTT2000us",
            control_basis="fixture-only stdin pipe index after intent; not MAVLink",
            no_physical_network=True,
            scope="selected hashes; not complete OS/runtime closure",
        ),
    )
    results = []
    try:
        for case in CASES:
            process = adapter = None
            error = harness_error = None
            signals = []
            elapsed = None
            evidence = None
            sent = []
            destination = output / case
            assert not destination.exists()
            # Keep Linux scratch even on exceptional exit; never lose uncopied failure logs.
            with nullcontext(tempfile.mkdtemp(prefix="fly-bootstrap-")) as temporary:
                temp = Path(temporary)
                run = temp / "evidence"
                run.mkdir()
                save(output / (case + "-scratch.json"), dict(retained_local_dir=str(run)))
                path = str(temp / "socket")
                with (run / "stderr.txt").open("xb") as stderr, (run / "journal.jsonl").open("x") as journal_file:
                    try:
                        process = subprocess.Popen(
                            [
                                sys.executable,
                                "-I",
                                str(Path(__file__).resolve()),
                                "--child",
                                "--case",
                                case,
                                "--socket",
                                path,
                                "--result",
                                str(run / "server.json"),
                            ],
                            cwd=temp,
                            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                            start_new_session=True,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=stderr,
                        )
                        with selectors.DefaultSelector() as selector:
                            selector.register(process.stdout, selectors.EVENT_READ)
                            if not selector.select(5):
                                raise TimeoutError("fixture readiness")
                        assert json.loads(process.stdout.readline()) == dict(ready=True, pid=process.pid)
                        owner = observe_owner(process)
                        save(run / "owner.json", owner)

                        def journal(event, case=case, stream=journal_file):
                            raw = json.dumps(event) + "\n"
                            assert stream.write(raw) == len(raw)
                            stream.flush()
                            if (
                                case == "journal-failure"
                                and event["source"] == "bootstrap"
                                and event["event"]["kind"] == "reply_intent"
                            ):
                                raise OSError("fixture intent journal failure")

                        start = time.monotonic_ns()
                        adapter = OwnedBootstrap(process, owner, path, "ordinary-fixture", start, journal)
                        index = 0
                        try:
                            while True:
                                progress = adapter.poll()
                                if progress["transport_bootstrap_complete"]:
                                    break
                                if progress["phase"] in ("first_ready", "stream_ready"):
                                    intent = adapter.reserve_reply(*body(index)[:2])
                                    assert not intent["transmission_proven"]
                                    raw = (json.dumps(dict(index=index)) + "\n").encode()
                                    count = process.stdin.write(raw)
                                    process.stdin.flush()
                                    assert count == len(raw)
                                    sent.append(dict(index=index, raw_hex=raw.hex(), returned_ns=time.monotonic_ns()))
                                    index += 1
                                time.sleep(0.001)
                        except BootstrapRefusal as exc:
                            error = str(exc)
                        finally:
                            elapsed = time.monotonic_ns() - start
                            adapter.close()
                            evidence = adapter.evidence
                        assert evidence["transport_bootstrap_complete"] == (case == "normal500"), evidence["failure"]
                        if case != "normal500":
                            assert EXPECTED[case] in error, error
                        else:
                            assert evidence["modeled_accepted_samples"] == 500 and elapsed < 8000000000
                        assert not any(
                            evidence[k] for k in ("network_authorized", "fusion_qualified", "live_convergence_qualified")
                        )
                        process.stdin.write(b'{"stop":true}\n')
                        process.stdin.flush()
                        process.wait(timeout=5)
                        server = json.loads((run / "server.json").read_text())
                        assert process.returncode == 0 and server["error"] is None and all(server["eof"]), server
                        expected_commands = [b"listener timesync_status -n 1\0"]
                        if case != "journal-failure":
                            expected_commands += [expected_commands[0], b"listener timesync_status -i 0 -n 500\0"]
                        assert server["commands"] == [c.hex() for c in expected_commands]
                    except BaseException as exc:
                        harness_error = type(exc).__name__ + ": " + str(exc)
                        raise
                    finally:
                        if adapter is not None:
                            adapter.close()
                            evidence = adapter.evidence
                        if process is not None:
                            if process.poll() is None:
                                signals.append("TERM")
                                process.terminate()
                                try:
                                    process.wait(timeout=3)
                                except subprocess.TimeoutExpired:
                                    signals.append("KILL")
                                    process.kill()
                                    process.wait(timeout=3)
                            process.stdin.close()
                            process.stdout.close()
                        result = dict(
                            case=case,
                            error=error,
                            harness_error=harness_error,
                            elapsed_ns=elapsed,
                            evidence=evidence,
                            control_send=sent,
                            cleanup=dict(
                                signals=signals,
                                pid=None if process is None else process.pid,
                                exit=None if process is None else process.returncode,
                            ),
                        )
                        save(run / "result.json", result)
                        results.append(result)
                shutil.copytree(run, destination)
                assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir()} == {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir()
                }
    finally:
        after = hashes()
        save(output / "post-hashes.json", after)
        save(
            output / "summary.json",
            dict(
                results=results,
                files_stable=before == after,
                complete=len(results) == len(CASES) and all(r["harness_error"] is None for r in results),
            ),
        )
    assert before == after
    print("6 private bootstrap cases matched;500 modeled samples once; no actual PX4/MAVLink")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--socket")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--producer")
    args = parser.parse_args()
    raise SystemExit(child(args) if args.child else main(args))
