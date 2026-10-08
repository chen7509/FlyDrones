"""Explicit ordinary-process byte/owned-listener integration, never actual PX4."""

import argparse
import hashlib
import json
import os
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from pymavlink.dialects.v20 import common as mav  # noqa: E402

from tests.benchmark import check_openvins_owned_bootstrap as legacy  # noqa: E402
from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock  # noqa: E402
from tools.benchmark.openvins_timesync_wire import PinnedCodec  # noqa: E402
from tools.benchmark.openvins_wire_bootstrap import OwnedWireBootstrap  # noqa: E402
from tools.benchmark.owned_daemon_connection import _error, observe_owner  # noqa: E402

CASES = ["normal500", "wrong-replay", "sink-short", "journal-failure"]
EXPECTED = {"normal500": None, "wrong-replay": "ordinal", "sink-short": "send count",
            "journal-failure": "fixture composite journal failure"}


def save(path, value):
    with path.open("x") as stream:
        raw = json.dumps(value, indent=2) + "\n"
        assert stream.write(raw) == len(raw)
        stream.flush()


def child(args):
    evidence = dict(reads=[], replies=[], stop=False)
    codec = PinnedCodec()

    def read(count):
        raw = b""
        deadline = time.monotonic() + 5
        with selectors.DefaultSelector() as sel:
            sel.register(sys.stdin.fileno(), selectors.EVENT_READ)
            while len(raw) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not sel.select(remaining):
                    raise TimeoutError("fixture reply wait")
                part = os.read(sys.stdin.fileno(), count - len(raw))
                evidence["reads"].append(dict(raw_hex=part.hex(), returned_ns=time.monotonic_ns()))
                if not part:
                    raise EOFError("fixture reply incomplete")
                raw += part
        return raw

    def control():
        first = read(1)
        if first == b"{":
            raw = first
            while not raw.endswith(b"\n") and len(raw) < 256:
                raw += read(1)
            assert raw == b'{"stop":true}\n'
            evidence["stop"] = True
            return dict(stop=True)
        assert first == b"\xfd", first.hex()
        header = first + read(9)
        raw = header + read(header[1] + 2)
        messages = codec.decode_datagram(raw)
        index = len(evidence["replies"])
        request, response, _ = legacy.body(index)
        assert len(messages) == 1
        msg = messages[0]
        assert (msg["type"], msg["system"], msg["component"], msg["sequence"]) == ("TIMESYNC", 254, 191, index % 256)
        assert msg["fields"] == dict(mavpackettype="TIMESYNC", tc1=response, ts1=request)
        evidence["replies"].append(dict(index=index, raw_hex=raw.hex(), parsed=msg, at_ns=time.monotonic_ns()))
        return dict(index=index)

    legacy.control_read = control
    try:
        return legacy.child(args)
    finally:
        save(args.result.parent / "wire-received.json", evidence)


def main(args):
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    files = [Path(__file__), Path(legacy.__file__), Path(sys.executable).resolve(), Path(mav.__file__)]
    files += [ROOT / "tools/benchmark" / name for name in (
        "openvins_wire_bootstrap.py", "openvins_timesync_wire.py", "openvins_owned_bootstrap.py",
        "openvins_listener_transport.py", "owned_daemon_connection.py", "owned_group_evidence.py",
        "openvins_timesync_bootstrap.py", "openvins_timesync_listener.py", "openvins_timesync_observer.py",
        "openvins_ekf2_disarmed_preflight.py")]

    def hashes():
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}

    before = hashes()
    save(output / "prospective.json", dict(producer=args.producer, cases=CASES, expected=EXPECTED,
        source_hashes=before, global_ns=8000000000, progress_ns=2000000000, sample_count=500,
        input="parent synthetic requests and supplied peer/sim time; no UDP receive",
        reply="actual raw MAVLink bytes through direct-owned stdin pipe; os.write count",
        status="legacy fixed synthetic fields and2ms RTT; not PX4 filter or actual timing",
        start="after ordinary child ready, not PX4 cold launch", poll_seconds=.001,
        actual_px4=False, network_authorized=False, fusion_qualified=False))
    results = []
    try:
        for case in CASES:
            temporary = Path(tempfile.mkdtemp(prefix="fly-wire-bootstrap-"))
            run = temporary / "evidence"
            run.mkdir()
            save(output / (case + "-scratch.json"), dict(retained_local_dir=str(run)))
            process = adapter = None
            error = harness_error = None
            signals, sent, requests = [], [], []
            start = elapsed = None
            with (run / "journal.jsonl").open("x") as journal_file, (run / "stderr.txt").open("xb") as stderr:
                try:
                    legacy_case = "normal500" if case == "sink-short" else case
                    process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--child",
                        "--case", legacy_case, "--socket", str(temporary / "socket"), "--result", str(run / "server.json")],
                        cwd=temporary, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, start_new_session=True,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
                    with selectors.DefaultSelector() as sel:
                        sel.register(process.stdout, selectors.EVENT_READ)
                        if not sel.select(5):
                            raise TimeoutError("fixture readiness")
                    assert json.loads(process.stdout.readline()) == dict(ready=True, pid=process.pid)
                    owner = observe_owner(process)
                    save(run / "owner.json", owner)
                    os.set_blocking(process.stdin.fileno(), False)

                    def journal(event, case=case, journal_file=journal_file):
                        raw = json.dumps(event) + "\n"
                        assert journal_file.write(raw) == len(raw)
                        journal_file.flush()
                        if case == "journal-failure" and event["source"] == "wire" and event["event"]["kind"] == "reserved":
                            raise OSError("fixture composite journal failure")

                    def sink(raw, peer, case=case, sent=sent, process=process):
                        assert peer == ("127.0.0.1", 14588)
                        actual = raw[:-1] if case == "sink-short" and len(sent) == 2 else raw
                        count = os.write(process.stdin.fileno(), actual)
                        sent.append(dict(at_ns=time.monotonic_ns(), offered_hex=raw.hex(), actual_hex=actual.hex(), returned=count))
                        return count

                    start = time.monotonic_ns()
                    remote = RemoteMonotonicClock("ordinary-wire", sim_origin_ns=0, remote_origin_ns=1000000)
                    adapter = OwnedWireBootstrap(process, owner, str(temporary / "socket"), remote, start, journal, sink)
                    index = 0
                    try:
                        while True:
                            progress = adapter.poll()
                            if progress["wire_bootstrap_complete"]:
                                break
                            if progress["phase"] in ("first_ready", "stream_ready"):
                                request = legacy.body(index)[0]
                                encoder = mav.MAVLink(None, srcSystem=9, srcComponent=1)
                                encoder.seq = index % 256
                                raw = mav.MAVLink_timesync_message(0, request).pack(encoder)
                                supplied_ns = time.monotonic_ns()
                                requests.append(dict(raw_hex=raw.hex(), supplied_ns=supplied_ns, supplied_sim_ns=request))
                                adapter.receive(raw, ("127.0.0.1", 14588), supplied_ns, request)
                                index += 1
                            time.sleep(.001)
                    except ValueError as exc:
                        error = _error(exc)
                    finally:
                        elapsed = time.monotonic_ns() - start
                        adapter.close()
                    evidence = adapter.evidence
                    assert not any(evidence[key] for key in ("network_authorized", "delivery_proven", "live_convergence_qualified", "fusion_qualified"))
                    assert evidence["wire_bootstrap_complete"] == (case == "normal500"), evidence["failure"]
                    if case == "normal500":
                        assert evidence["completed_reply_attempts"] == evidence["modeled_accepted_samples"] == 500
                        assert elapsed < 8000000000
                    else:
                        assert EXPECTED[case] in error, error
                    if case != "sink-short":
                        assert os.write(process.stdin.fileno(), b'{"stop":true}\n') == 14
                    process.stdin.close()
                    process.wait(timeout=5)
                    server = json.loads((run / "server.json").read_text())
                    wire = json.loads((run / "wire-received.json").read_text())
                    expected_count = {"normal500": 500, "wrong-replay": 1, "sink-short": 2, "journal-failure": 0}[case]
                    assert len(wire["replies"]) == expected_count
                    for index, reply in enumerate(wire["replies"]):
                        assert reply["raw_hex"] == sent[index]["actual_hex"] == sent[index]["offered_hex"]
                    if case == "sink-short":
                        assert process.returncode == 2 and "fixture reply incomplete" in server["error"], server
                        assert len(sent) == 3 and sent[-1]["returned"] == len(bytes.fromhex(sent[-1]["offered_hex"])) - 1
                    else:
                        assert process.returncode == 0 and server["error"] is None and all(server["eof"]), server
                    expected_commands = [b"listener timesync_status -n 1\0"]
                    if case != "journal-failure":
                        expected_commands += [expected_commands[0], b"listener timesync_status -i 0 -n 500\0"]
                    assert server["commands"] == [c.hex() for c in expected_commands]
                except BaseException as exc:
                    harness_error = _error(exc)
                    raise
                finally:
                    if adapter is not None:
                        adapter.close()
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
                    result = dict(case=case, error=error, harness_error=harness_error, elapsed_ns=elapsed,
                                  evidence=None if adapter is None else adapter.evidence, sent=sent, requests=requests,
                                  cleanup=dict(signals=signals, pid=None if process is None else process.pid,
                                               exit=None if process is None else process.returncode))
                    save(run / "result.json", result)
                    results.append(result)
            entries = [json.loads(line) for line in (run / "journal.jsonl").read_text().splitlines()]
            for source in ("wire", "owned"):
                assert [event["event"] for event in entries if event["source"] == source] == result["evidence"][source]["events"]
            destination = output / case
            shutil.copytree(run, destination)
            assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir()} == {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir()}
    finally:
        after = hashes()
        save(output / "post-hashes.json", after)
        save(output / "summary.json", dict(results=results, source_stable=before == after,
             complete=len(results) == len(CASES) and all(r["harness_error"] is None for r in results)))
    assert before == after
    print("4 private wire/listener cases matched;500 pipe replies decoded; no actual PX4/UDP")


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
