"""Synthetic POSIX native protocol and timeout checks; no estimator or simulation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    from tools.benchmark.openvins_online_shadow import NativeClient, encode_packet
    evidence = []
    now = time.monotonic_ns()
    def imu(seq, sample, extra=""):
        return f"I {seq} {sample} {now} {now} 0 0 0 0 0 -9.81{extra}\n".encode()
    def camera(seq, sample, size=57600):
        return f"C {seq} {sample} {now} {now} {size}\n".encode() + bytes([255, 0, 0]) * 19200
    normal = imu(0, 1_000_000) + imu(1, 4_000_000) + camera(2, 1_000_000)
    cases = {
        "normal": (normal, True), "nonfinite": (imu(0, 1).replace(b"-9.81", b"nan"), False),
        "extra_fields": (imu(0, 1, " truth"), False), "duplicate": (imu(0, 1)+imu(1, 1), False),
        "gap": (imu(0, 1)+imu(1, 5_000_002), False), "future_camera": (imu(0, 1)+camera(1, 1), False),
        "truncated_pixels": (normal[:-1], False), "oversize_pixels": (imu(0, 1)+imu(1, 4)+camera(2, 1, 9999999), False),
        "path_instead_of_pixels": (b"C 0 1 1 1 ../../frame.ppm\n", False),
        "huge_clock": (imu(0, 2**80), False), "huge_header": (b"I"*513+b"\n", False),
        "dispatch_regression": (f"I 0 1 {now} {now-1} 0 0 0 0 0 0\n".encode(), False),
    }
    for name, (data, valid) in cases.items():
        directory = args.output/name
        directory.mkdir()
        with (directory/"ack.jsonl").open("xb") as ack:
            completed = subprocess.run([args.binary, "--parse-only", str(directory/"states.jsonl"), str(directory/"fast.jsonl"), str(ack.fileno())], input=data, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, pass_fds=(ack.fileno(),), timeout=10)
        (directory/"log.txt").write_bytes(completed.stdout)
        (directory/"input.bin").write_bytes(data)
        assert (completed.returncode == 0) == valid, (name, completed.returncode, completed.stdout)
        if valid:
            acks = [json.loads(line) for line in (directory/"ack.jsonl").read_text().splitlines()]
            assert [a["sequence"] for a in acks] == [0, 1, 2]
            assert acks[-1]["gray_first"] == 76  # OpenCV RGB2GRAY red, not BGR.
        evidence.append(dict(case=name, exit=completed.returncode, expected_accept=valid))
    # Existing output must be refused before content changes.
    prior = args.output/"normal/states.jsonl"
    original = prior.read_bytes()
    with (args.output/"overwrite-ack.jsonl").open("xb") as ack:
        result = subprocess.run([args.binary, "--parse-only", str(prior), str(args.output/"unused.jsonl"), str(ack.fileno())], input=b"", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, pass_fds=(ack.fileno(),), timeout=10)
    assert result.returncode != 0 and prior.read_bytes() == original
    evidence.append(dict(case="overwrite", exit=result.returncode))
    # Full client verifies real cross-process clock intervals and byte delivery.
    directory = args.output/"client"
    directory.mkdir()
    client = NativeClient([args.binary, "--parse-only", str(directory/"states.jsonl"), str(directory/"fast.jsonl")], directory)
    for sample in [1_000_000, 4_000_000]:
        client.send(dict(kind="imu", sample_ns=sample, source_arrival_ns=time.monotonic_ns(), wm=[0,0,0], am=[0,0,-9.81]))
    client.send(dict(kind="camera", sample_ns=1_000_000, source_arrival_ns=time.monotonic_ns()), bytes([255,0,0])*19200)
    assert client.finish()["exit"] == 0
    evidence.append(dict(case="actual_clock_and_bytes", accepted=3))
    # Child never reads stdin: filling pipe must hit deadline, not block forever.
    directory = args.output/"blocked"
    directory.mkdir()
    blocked = NativeClient([sys.executable, "-c", "import time;time.sleep(30)"], directory, timeout_s=.25)
    started = time.monotonic()
    try:
        blocked.send(dict(kind="camera", sample_ns=1, source_arrival_ns=time.monotonic_ns()), b"\0"*57600)
        raise AssertionError("blocked native child accepted")
    except TimeoutError:
        elapsed = time.monotonic()-started
        assert elapsed < 2
    finally:
        blocked.finish()
    evidence.append(dict(case="blocked_write", refusal_wall_s=elapsed))
    (args.output/"summary.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
