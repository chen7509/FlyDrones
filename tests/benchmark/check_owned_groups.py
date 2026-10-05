"""Bounded real Linux subprocess experiments; no simulator, estimator or training."""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from tools.benchmark.disarmed_sensor_provenance import supervise_worker  # noqa: E402
from tools.benchmark.owned_group_evidence import parse_stat  # noqa: E402


def put(path, data):
    with path.open("x") as f:
        json.dump(data, f, indent=2)


def child(mode, output):
    def term(sig, frame):
        put(output / "child-term.json", dict(pid=os.getpid(), signal=sig, monotonic_ns=time.monotonic_ns()))
        if mode != "stubborn":
            raise SystemExit(0)

    signal.signal(signal.SIGTERM, term)
    put(output / "child-ready.json", parse_stat(Path(f"/proc/{os.getpid()}/stat").read_text()))
    time.sleep(30)  # outer supervisor bounds are far shorter


def leader(mode, output):
    output.mkdir(parents=True, exist_ok=False)
    if mode != "normal":
        p = subprocess.Popen([sys.executable, __file__, "--child", mode, "--output", str(output)])
        deadline = time.monotonic() + 5
        while not (output / "child-ready.json").exists():
            if p.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("harness child not ready")
            time.sleep(0.01)
    put(output / "result.json", dict(status="capture_completed", scope="subprocess harness only", estimator_run=False))
    if mode == "timeout":
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--leader", choices=["normal", "graceful", "stubborn", "timeout"])
    parser.add_argument("--child", choices=["graceful", "stubborn", "timeout"])
    parser.add_argument("--producer")
    a = parser.parse_args()
    if a.child:
        child(a.child, a.output)
        return
    if a.leader:
        leader(a.leader, a.output)
        return
    if not a.producer:
        parser.error("frozen producer required")
    a.output.mkdir(parents=True, exist_ok=False)
    files = [
        ROOT / x
        for x in [
            "tools/benchmark/owned_group_evidence.py",
            "tools/benchmark/disarmed_sensor_provenance.py",
            "tests/benchmark/check_owned_groups.py",
        ]
    ]
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    put(
        a.output / "freeze.json",
        dict(producer=a.producer, hashes=before, cases=["normal", "graceful", "stubborn", "timeout"], no_physics=True),
    )
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    sentinel_identity = parse_stat(Path(f"/proc/{sentinel.pid}/stat").read_text())
    results = []
    try:
        for mode in ["normal", "graceful", "stubborn", "timeout"]:
            output = a.output / mode
            started = time.monotonic()
            result = supervise_worker(
                [sys.executable, __file__, "--leader", mode, "--output", str(output)],
                output,
                timeout_s=2 if mode == "timeout" else 10,
            )
            elapsed = time.monotonic() - started
            c = result["cleanup"]
            assert not result["errors"] and not c["errors"] and c["no_executing_members"], result
            assert c["sigkill_dispatched"] is (mode == "stubborn")
            assert c["graceful_group_cleanup_verified"] is (mode != "stubborn")
            assert result["status"] == ("supervisor_timeout" if mode == "timeout" else "worker_exited")
            assert result["worker_exit"] == (-15 if mode == "timeout" else 0)
            assert elapsed < 15
            assert sentinel.poll() is None
            current = parse_stat(Path(f"/proc/{sentinel.pid}/stat").read_text())
            assert all(current[k] == sentinel_identity[k] for k in ["pid", "pgrp", "session", "start_ticks"])
            if mode != "normal":
                identity = json.loads((output / "child-ready.json").read_text())
                assert identity["pgrp"] == identity["session"] == result["worker_pid"]
                assert json.loads((output / "child-term.json").read_text())["signal"] == 15
                path = Path(f"/proc/{identity['pid']}/stat")
                state = parse_stat(path.read_text()) if path.exists() else None
                assert state is None or state["start_ticks"] != identity["start_ticks"] or state["state"] in {"Z", "X", "x"}
            results.append(dict(mode=mode, elapsed_s=elapsed, supervisor=result, sentinel_unchanged=True))
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=5)
        put(a.output / "sentinel-cleanup.json", dict(identity=sentinel_identity, returncode=sentinel.returncode))
    after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    assert before == after
    put(a.output / "check.json", dict(results=results, unchanged=True, escaped_descendants_tested=False, physical_capture=False))
    print(
        json.dumps(
            [
                dict(
                    mode=r["mode"],
                    elapsed_s=r["elapsed_s"],
                    no_executing=r["supervisor"]["cleanup"]["no_executing_members"],
                    sigkill=r["supervisor"]["cleanup"]["sigkill_dispatched"],
                )
                for r in results
            ]
        )
    )


if __name__ == "__main__":
    main()
