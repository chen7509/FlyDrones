"""Strict owned opaque generated-RX trial. Never a PX4/source trial."""
from __future__ import annotations

import argparse
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
from tools.benchmark.kernel_rx_timestamping import KernelRXTimestamping  # noqa: E402
from tools.benchmark.openvins_datagram_receive import DatagramReceiver  # noqa: E402
from tools.benchmark.owned_daemon_connection import _error  # noqa: E402
from tools.benchmark.probe_kernel_datagram_arrival import (  # noqa: E402
    _pairs,
    close_owned,
    read_static,
    snapshot,
)

SOURCES = (
    "tools/benchmark/probe_kernel_rx_timestamping.py", "tools/benchmark/kernel_rx_timestamping.py",
    "tools/benchmark/kernel_datagram_arrival.py", "tools/benchmark/openvins_datagram_receive.py",
    "tools/benchmark/probe_kernel_datagram_arrival.py", "tools/benchmark/openvins_segmented_journal.py",
    "tools/benchmark/openvins_timesync_interval.py", "tools/benchmark/owned_daemon_connection.py",
    "tools/benchmark/owned_group_evidence.py", "tools/benchmark/kernel_rx_timestamping_abi.c",
)
ABI_PATH = "results/kernel-rx-timestamping-dev-1701/capability-completion-v1/abi.json"
PROBE_PATH = "results/kernel-rx-timestamping-dev-1701/capability-v1/kernel_rx_timestamping_abi"
ABI_SHA = "6e466d6b0b5d43a5086e1bb509c9932d715c7aba6ebc32ba665d90aa81f72366"
PROBE_SHA = "2833ebd4ba6a51df6d5db76f59dee3b44247f2c621e2403eb237775feff5aa01"
CONDITIONS = {
    "schema": "flydrones.kernel_generated_rx_queue_study.v1", "run_id": "opaque-generated-rx-v1",
    "count": 3, "delay_ns": 40_000_000, "minimum_queue_observation_ns": 20_000_000,
    "outer_timeout_s": 20, "outer_kill_after_s": 2, "abi_path": ABI_PATH, "probe_path": PROBE_PATH,
    "local": ["127.0.0.1", 14548], "peer": ["127.0.0.1", 14588],
}


def check_module_origins():
    origins = {}
    for name in SOURCES:
        if not name.endswith(".py"):
            continue
        module_name = name[:-3].replace("/", ".")
        module = sys.modules[__name__] if name == SOURCES[0] else sys.modules.get(module_name)
        if module is None or Path(module.__file__).resolve() != (ROOT / name).resolve():
            raise ValueError("unexpected generated RX study module origin: " + name)
        origins[name] = str(Path(module.__file__).resolve())
    return origins


def validate_profile(raw: bytes, digest: str, root=None):
    root = ROOT if root is None else root
    if type(raw) is not bytes or not 1 <= len(raw) <= 16_384 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("study profile digest/size invalid")
    profile = json.loads(raw, object_pairs_hook=_pairs,
                         parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("profile constant")))
    if type(profile) is not dict or profile.keys() != CONDITIONS.keys() | {"abi_sha256", "probe_sha256", "sources"}:
        raise ValueError("generated study profile schema invalid")
    for name, expected in CONDITIONS.items():
        if type(profile[name]) is not type(expected) or profile[name] != expected:
            raise ValueError("frozen condition drift: " + name)
    if profile["abi_sha256"] != ABI_SHA or profile["probe_sha256"] != PROBE_SHA:
        raise ValueError("pinned RX capability substitution")
    if type(profile["sources"]) is not dict or profile["sources"].keys() != set(SOURCES):
        raise ValueError("study source inventory invalid")
    for name, expected in profile["sources"].items():
        if type(expected) is not str or hashlib.sha256(read_static(root / name)).hexdigest() != expected:
            raise ValueError("study source hash drift: " + name)
    for name, expected in ((ABI_PATH, ABI_SHA), (PROBE_PATH, PROBE_SHA)):
        if hashlib.sha256(read_static(root / name)).hexdigest() != expected:
            raise ValueError("pinned capability bytes drift")
    KernelRXTimestamping(read_static(root / ABI_PATH), ABI_SHA)
    return profile


def run(profile, output, *, profile_path, profile_sha256):
    origins = check_module_origins()
    if validate_profile(read_static(profile_path), profile_sha256, ROOT) != profile:
        raise ValueError("supplied profile differs from declared input")
    output.mkdir()
    result = {"run_id": profile["run_id"], "status": "running", "case": "queue-delay",
              "normal": {"events": [], "sent": [], "received": []},
              "option_drift": {"executed": False, "events": [], "refused": False},
              "owned_close": [], "errors": [], "pid": os.getpid(), "module_origins": origins,
              "source_authenticated": False, "kernel_receive_instant_qualified": False,
              "clock_mapping_qualified": False, "fusion_qualified": False, "training_eligible": False,
              "px4_ros_physics_or_training_started": False}
    nonce = secrets.token_hex(16)
    payloads = [f"FLYD_OPAQUE_RX_TS_V1:{nonce}:{index}".encode() for index in range(profile["count"])]
    with (output / "intent.json").open("x") as handle:
        json.dump({"profile": profile, "nonce": nonce, "payload_hex": [item.hex() for item in payloads]}, handle)
    profiles, receivers, live = {}, {}, []
    started = time.monotonic_ns()
    try:
        abi = read_static(ROOT / ABI_PATH)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        live.append(sock)
        stamps = KernelRXTimestamping(abi, ABI_SHA)
        profiles["normal"] = stamps
        result["normal"]["prebind_ns"] = time.monotonic_ns()
        stamps.enable_before_bind(sock)
        result["normal"]["enabled_ns"] = time.monotonic_ns()
        sock.bind(tuple(profile["local"]))
        sock.setblocking(False)
        result["normal"]["bound_ns"] = time.monotonic_ns()
        identity = snapshot(sock)
        result["normal"]["receiver_identity"] = identity
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        live.append(sender)
        sender.bind(tuple(profile["peer"]))
        sender.settimeout(0.1)
        result["normal"]["sender_identity"] = snapshot(sender)

        def guard():
            if snapshot(sock) != identity:
                raise ValueError("owned generated receiver identity changed")

        receiver = DatagramReceiver(sock, guard, time.monotonic_ns, time.monotonic_ns(),
                                    result["normal"]["events"].append, kernel_timestamps=stamps)
        receivers["normal"] = receiver
        for data in payloads:
            before_mono, before_real = time.monotonic_ns(), time.time_ns()
            sent = {"payload_hex": data.hex(), "bytes": None, "send_returned": False,
                    "before_monotonic_ns": before_mono, "before_realtime_ns": before_real,
                    "after_realtime_ns": None, "after_monotonic_ns": None}
            result["normal"]["sent"].append(sent)
            count = sender.sendto(data, tuple(profile["local"]))
            sent.update(bytes=count, send_returned=True)
            sent["after_realtime_ns"] = time.time_ns()
            sent["after_monotonic_ns"] = time.monotonic_ns()
            if count != len(data):
                raise RuntimeError("opaque generated packet short send")
        result["normal"]["delay_start_ns"] = time.monotonic_ns()
        time.sleep(profile["delay_ns"] / 1e9)
        result["normal"]["delay_end_ns"] = time.monotonic_ns()
        for index, expected in enumerate(payloads):
            before_real = time.time_ns()
            packet = receiver.poll()
            actual = {"packet_returned": packet is not None, "read_before_realtime_ns": before_real}
            result["normal"]["received"].append(actual)
            if packet is None:
                raise RuntimeError("owned generated packet unavailable")
            actual.update(data_hex=packet.data.hex(), peer=list(packet.peer), received_monotonic_ns=packet.received_ns,
                          kernel_received_realtime_ns=packet.kernel_received_realtime_ns)
            if packet.data != expected or packet.peer != tuple(profile["peer"]):
                raise RuntimeError("owned generated payload/peer mismatch")
            stamp = packet.kernel_received_realtime_ns
            if stamp is None or not result["normal"]["sent"][index]["before_realtime_ns"] <= stamp <= before_real:
                raise RuntimeError("generated timestamp outside owned send/read observations")
            actual["realtime_queue_observation_ns"] = before_real - stamp
            if actual["realtime_queue_observation_ns"] < profile["minimum_queue_observation_ns"]:
                raise RuntimeError("generated timestamp did not preserve declared queue interval")
        for item in list(reversed(live)):
            close_owned(item, result["owned_close"])
            live.remove(item)
        result["case"] = "option-drift"
        case = result["option_drift"]
        case["executed"] = True
        drift_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        live.append(drift_sock)
        drift_profile = KernelRXTimestamping(abi, ABI_SHA)
        profiles["option_drift"] = drift_profile
        drift_profile.enable_before_bind(drift_sock)
        drift_sock.bind(tuple(profile["local"]))
        drift_sock.setblocking(False)
        drift_identity = snapshot(drift_sock)
        case["identity"] = drift_identity

        def drift_guard():
            if snapshot(drift_sock) != drift_identity:
                raise ValueError("owned generated drift receiver changed")

        drift = DatagramReceiver(drift_sock, drift_guard, time.monotonic_ns, time.monotonic_ns(),
                                 case["events"].append, kernel_timestamps=drift_profile)
        receivers["option_drift"] = drift
        selected = drift_profile.evidence["abi"]
        drift_sock.setsockopt(selected["sol_socket"], selected["so_timestamping_new"], 0)
        case["disabled_option"] = selected["so_timestamping_new"]
        try:
            drift.poll()
        except ValueError as exc:
            case["reason"] = str(exc)
            if "timestamp option changed" not in str(exc) or drift.evidence["datagram_returns"] != 0:
                raise
            case["refused"] = True
        else:
            raise RuntimeError("generated option drift accepted")
        if time.monotonic_ns() - started >= profile["outer_timeout_s"] * 1_000_000_000:
            raise RuntimeError("study budget exceeded")
        result["status"] = "cases_complete"
    except BaseException as exc:
        result["status"] = "failed"
        result["errors"].append(_error(exc))
    finally:
        for label, pool, name in (("profile", profiles, "timestamp_profile_evidence"),
                                  ("receiver", receivers, "receiver_evidence")):
            for case_name, item in pool.items():
                try:
                    result[case_name][name] = item.evidence
                except BaseException as exc:
                    result["status"] = "failed"
                    result["errors"].append(label + ": " + _error(exc))
        for item in reversed(live):
            try:
                close_owned(item, result["owned_close"])
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
        raise RuntimeError("generated local study failed; retain this attempt")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = validate_profile(read_static(args.profile), args.profile_sha256)
    result = run(profile, args.output, profile_path=args.profile, profile_sha256=args.profile_sha256)
    print(json.dumps({"status": result["status"], "queue_observations_ns": [
        item["realtime_queue_observation_ns"] for item in result["normal"]["received"]],
        "option_drift_refused": result["option_drift"]["refused"], "owned_sockets_closed": len(result["owned_close"])}))


if __name__ == "__main__":
    main()
