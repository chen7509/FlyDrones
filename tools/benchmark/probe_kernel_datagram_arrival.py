"""Declared opaque loopback-only receive study; never a PX4/source trial.

Run under the separately frozen GNU timeout20s wrapper. Only this process's
sockets are closed. No MAVLink packet, source daemon or simulator is started.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import secrets
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import tools.benchmark.kernel_datagram_arrival as kernel_module  # noqa: E402
import tools.benchmark.openvins_datagram_receive as receiver_module  # noqa: E402
from tools.benchmark.kernel_datagram_arrival import KernelTimestampNS  # noqa: E402
from tools.benchmark.openvins_datagram_receive import DatagramReceiver  # noqa: E402
from tools.benchmark.owned_daemon_connection import _error  # noqa: E402

SOURCES = (
    "tools/benchmark/kernel_datagram_arrival.py", "tools/benchmark/openvins_datagram_receive.py",
    "tools/benchmark/kernel_timestamp_abi.c", "tools/benchmark/probe_kernel_datagram_arrival.py",
)
ABI_PATH = "results/kernel-datagram-arrival-dev-1701/capability-v1/abi.json"
PROBE_PATH = "results/kernel-datagram-arrival-dev-1701/capability-v1/kernel_timestamp_abi"
CONDITIONS = {
    "schema": "flydrones.kernel_datagram_arrival_study.v1", "run_id": "opaque-loopback-v1",
    "count": 3, "delay_ns": 40_000_000, "minimum_queue_observation_ns": 20_000_000,
    "outer_timeout_s": 20, "outer_kill_after_s": 2,
    "abi_path": ABI_PATH, "probe_path": PROBE_PATH,
    "local": ["127.0.0.1", 14548], "peer": ["127.0.0.1", 14588],
}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate study profile key")
        result[key] = value
    return result


def read_static(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("study input must be regular and not linked")
    before = path.stat()
    if before.st_size > 1_000_000:
        raise ValueError("study input exceeds narrow static-file bound")
    with path.open("rb") as stream:
        data = stream.read(1_000_001)
    if len(data) > 1_000_000:
        raise ValueError("study input exceeds narrow static-file bound")
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("study input changed during read")
    return data


def validate_profile(raw: bytes, digest: str, root: Path = ROOT) -> dict:
    if type(raw) is not bytes or not 1 <= len(raw) <= 16_384 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("study profile digest/size invalid")
    profile = json.loads(raw, object_pairs_hook=_pairs,
                         parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("profile constant")))
    if type(profile) is not dict or profile.keys() != CONDITIONS.keys() | {"abi_sha256", "probe_sha256", "sources"}:
        raise ValueError("study profile schema invalid")
    for key, expected in CONDITIONS.items():
        if type(profile[key]) is not type(expected) or profile[key] != expected:
            raise ValueError("frozen study condition drift: " + key)
    if type(profile["sources"]) is not dict or profile["sources"].keys() != set(SOURCES):
        raise ValueError("study source inventory invalid")
    for name, expected in profile["sources"].items():
        if type(expected) is not str or hashlib.sha256(read_static(root / name)).hexdigest() != expected:
            raise ValueError("study source changed: " + name)
    for path_key, hash_key in (("abi_path", "abi_sha256"), ("probe_path", "probe_sha256")):
        if type(profile[hash_key]) is not str or hashlib.sha256(read_static(root / profile[path_key])).hexdigest() != profile[hash_key]:
            raise ValueError("study selected capability changed")
    KernelTimestampNS(read_static(root / profile["abi_path"]), profile["abi_sha256"])
    return profile


def snapshot(sock):
    value = os.fstat(sock.fileno())
    return {"fd": sock.fileno(), "device": value.st_dev, "inode": value.st_ino,
            "net": os.readlink("/proc/self/ns/net"), "local": list(sock.getsockname())}


def close_owned(sock, observations):
    fd = sock.fileno()
    observed = {"fd": fd, "fileno_after": None, "fstat_errno": None, "close_error": None}
    observations.append(observed)
    try:
        sock.close()
    except BaseException as exc:
        observed["close_error"] = _error(exc)
        raise
    finally:
        observed["fileno_after"] = sock.fileno()
    try:
        os.fstat(fd)
    except OSError as exc:
        observed["fstat_errno"] = exc.errno
    if observed["fileno_after"] != -1 or observed["fstat_errno"] != errno.EBADF:
        raise RuntimeError("owned socket closure not observed")
    return observed


def run(profile: dict, output: Path, *, profile_path: Path, profile_sha256: str):
    if validate_profile(read_static(profile_path), profile_sha256, ROOT) != profile:
        raise ValueError("supplied study profile differs from frozen input")
    output.mkdir()
    abi = read_static(ROOT / profile["abi_path"])
    result = {"run_id": profile["run_id"], "pid": os.getpid(), "status": "running",
              "case": None, "normal": {}, "option_drift": {}, "owned_close": [], "errors": [],
              "px4_ros_physics_or_training_started": False, "source_authenticated": False,
              "clock_mapping_qualified": False, "fusion_qualified": False, "training_eligible": False}
    nonce = secrets.token_hex(16)
    payloads = [f"FLYD_OPAQUE_KERNEL_TS_V1:{nonce}:{index}".encode() for index in range(3)]
    (output / "intent.json").write_text(json.dumps({"profile": profile, "nonce": nonce,
                                                   "payload_hex": [data.hex() for data in payloads]}, indent=2))
    live = []
    retained_receivers = {}
    retained_profiles = {}
    started = time.monotonic_ns()
    try:
        result["case"] = "queue-delay-v1"
        receiver_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        live.append(receiver_sock)
        timestamps = KernelTimestampNS(abi, profile["abi_sha256"])
        retained_profiles["normal"] = timestamps
        prebind_ns = time.monotonic_ns()
        timestamps.enable_before_bind(receiver_sock)
        enabled_ns = time.monotonic_ns()
        receiver_sock.bind(tuple(profile["local"]))
        receiver_sock.setblocking(False)
        bound_ns = time.monotonic_ns()
        original = snapshot(receiver_sock)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        live.append(sender)
        sender.bind(tuple(profile["peer"]))
        sender.settimeout(0.1)
        sender_identity = snapshot(sender)
        events = []

        def guard():
            if snapshot(receiver_sock) != original:
                raise ValueError("owned study receiver identity changed")

        result["normal"] = {"prebind_ns": prebind_ns, "enabled_ns": enabled_ns, "bound_ns": bound_ns,
                            "receiver_identity": original, "sender_identity": sender_identity,
                            "sent": [], "received": [], "events": events}
        receiver = DatagramReceiver(receiver_sock, guard, time.monotonic_ns, time.monotonic_ns(),
                                    lambda event: events.append(event), kernel_timestamps=timestamps)
        retained_receivers["normal"] = receiver
        for data in payloads:
            before_mono, before_real = time.monotonic_ns(), time.time_ns()
            count = sender.sendto(data, tuple(profile["local"]))
            after_real, after_mono = time.time_ns(), time.monotonic_ns()
            if count != len(data):
                raise RuntimeError("opaque datagram short send")
            result["normal"]["sent"].append({"payload_hex": data.hex(), "bytes": count,
                                             "before_monotonic_ns": before_mono, "after_monotonic_ns": after_mono,
                                             "before_realtime_ns": before_real, "after_realtime_ns": after_real})
        delay_start = time.monotonic_ns()
        time.sleep(profile["delay_ns"] / 1e9)
        delay_end = time.monotonic_ns()
        result["normal"].update(delay_start_ns=delay_start, delay_end_ns=delay_end)
        for index, expected in enumerate(payloads):
            before_real = time.time_ns()
            packet = receiver.poll()
            if packet is None or packet.data != expected or packet.peer != tuple(profile["peer"]):
                raise RuntimeError("owned opaque payload/peer missing or mismatched")
            timestamp = packet.kernel_received_realtime_ns
            if timestamp is None or not result["normal"]["sent"][index]["before_realtime_ns"] <= timestamp <= before_real:
                raise RuntimeError("kernel timestamp outside owned send/read observations")
            difference = before_real - timestamp
            if difference < profile["minimum_queue_observation_ns"]:
                raise RuntimeError("kernel timestamp did not preserve declared queued interval")
            result["normal"]["received"].append({"data_hex": packet.data.hex(), "peer": list(packet.peer),
                                                 "received_monotonic_ns": packet.received_ns,
                                                 "kernel_received_realtime_ns": timestamp,
                                                 "read_before_realtime_ns": before_real,
                                                 "realtime_queue_observation_ns": difference})
        result["normal"]["receiver_evidence"] = receiver.evidence
        for sock in list(reversed(live)):
            close_owned(sock, result["owned_close"])
            live.remove(sock)

        result["case"] = "option-drift-v1"
        drift_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        live.append(drift_sock)
        drift_timestamps = KernelTimestampNS(abi, profile["abi_sha256"])
        retained_profiles["option_drift"] = drift_timestamps
        drift_timestamps.enable_before_bind(drift_sock)
        drift_sock.bind(tuple(profile["local"]))
        drift_sock.setblocking(False)
        drift_events = []
        result["option_drift"] = {"identity": snapshot(drift_sock), "events": drift_events, "refused": False}
        drift_receiver = DatagramReceiver(drift_sock, lambda: None, time.monotonic_ns, time.monotonic_ns(),
                                          lambda event: drift_events.append(event), kernel_timestamps=drift_timestamps)
        retained_receivers["option_drift"] = drift_receiver
        drift_sock.setsockopt(1, 64, 0)  # Values validated from this study's installed ABI.
        try:
            drift_receiver.poll()
        except ValueError as exc:
            if "timestamp option changed" not in str(exc) or drift_receiver.evidence["datagram_returns"] != 0:
                raise
            result["option_drift"].update(refused=True, reason=str(exc))
        else:
            raise RuntimeError("native option drift accepted")
        if time.monotonic_ns() - started >= profile["outer_timeout_s"] * 1_000_000_000:
            raise RuntimeError("study elapsed budget exceeded")
        result["status"] = "cases_complete"
    except BaseException as exc:
        result["status"] = "failed"
        result["errors"].append(_error(exc))
    finally:
        for name, item in retained_profiles.items():
            try:
                result[name]["timestamp_profile_evidence"] = item.evidence
            except BaseException as exc:
                result["status"] = "failed"
                result["errors"].append("profile evidence: " + _error(exc))
        for name, item in retained_receivers.items():
            try:
                result[name]["receiver_evidence"] = item.evidence
            except BaseException as exc:
                result["status"] = "failed"
                result["errors"].append("evidence: " + _error(exc))
        for sock in list(reversed(live)):
            try:
                close_owned(sock, result["owned_close"])
            except BaseException as exc:
                result["status"] = "failed"
                result["errors"].append("close: " + _error(exc))
        result["profile_post_verified"] = False
        try:
            validate_profile(read_static(profile_path), profile_sha256, ROOT)
            result["profile_post_verified"] = True
        except BaseException as exc:
            result["status"] = "failed"
            result["errors"].append("post profile: " + _error(exc))
        if result["status"] == "cases_complete" and result["profile_post_verified"]:
            result["status"] = "passed"
        result["elapsed_wall_ns"] = time.monotonic_ns() - started
        with (output / "result.json").open("x") as handle:
            json.dump(result, handle, indent=2, allow_nan=False)
        if result["status"] != "passed":
            raise RuntimeError("declared local study failed; retain this attempt")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if (Path(kernel_module.__file__).resolve() != ROOT / "tools/benchmark/kernel_datagram_arrival.py"
            or Path(receiver_module.__file__).resolve() != ROOT / "tools/benchmark/openvins_datagram_receive.py"):
        raise RuntimeError("unexpected imported receiver modules")
    raw = read_static(args.profile)
    profile = validate_profile(raw, args.profile_sha256)
    result = run(profile, args.output, profile_path=args.profile, profile_sha256=args.profile_sha256)
    print(json.dumps({"status": result["status"], "elapsed_wall_ns": result["elapsed_wall_ns"],
                      "observed_queue_ns": [row["realtime_queue_observation_ns"] for row in result["normal"]["received"]],
                      "option_drift_refused": result["option_drift"]["refused"], "owned_sockets_closed": len(result["owned_close"])}))


if __name__ == "__main__":
    main()
