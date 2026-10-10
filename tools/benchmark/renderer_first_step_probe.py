"""Isolate Gazebo's first rendered step and qualify its exact new file mappings."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import traceback
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import file_record
from tools.benchmark.owned_runtime_maps import parse_maps

CACHE_DISABLE_ENV = "MESA_SHADER_CACHE_DISABLE"
MAX_MAP_BYTES = 8 * 1024 * 1024


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json_exclusive(path, value, *, opener=open):
    encoded = json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
    stream = opener(path, "x", encoding="utf-8")
    failure = None
    try:
        if stream.write(encoded) != len(encoded):
            raise OSError("short evidence write")
        stream.flush()
    except BaseException as exc:
        failure = exc
    try:
        stream.close()
    except BaseException as exc:
        failure = failure or exc
    if failure:
        raise failure


def expected_renderer_mappings(historical_path, expected_sha256, cache_path):
    historical_path = Path(historical_path)
    if _sha256(historical_path) != expected_sha256:
        raise ValueError("historical mapping hash mismatch")
    doc = json.loads(historical_path.read_text(encoding="utf-8"))
    if (
        type(doc) is not dict
        or doc.get("phase") != "postfirststep"
        or doc.get("observed_files_covered") is not False
        or doc.get("runtime_closure_qualified") is not False
        or doc.get("mismatched") != []
        or type(doc.get("unknown")) is not list
    ):
        raise ValueError("historical mapping is not the retained first-step refusal")
    cache = str(Path(cache_path).resolve(strict=True))
    libraries, seen, cache_count = [], set(), 0
    for row in doc["unknown"]:
        if type(row) is not dict or set(row) != {"path", "device", "inode"}:
            raise ValueError("invalid historical mapping row")
        path = Path(row["path"])
        if not path.is_absolute():
            raise ValueError("historical mapping path is not absolute")
        resolved = str(path.resolve(strict=True))
        if resolved in seen:
            raise ValueError("duplicate historical mapping")
        seen.add(resolved)
        if resolved == cache:
            cache_count += 1
        else:
            if not path.is_file():
                raise ValueError("historical mapped library unavailable")
            libraries.append({"path": resolved, "device": row["device"], "inode": row["inode"]})
    if cache_count != 1 or not libraries:
        raise ValueError("one mutable Mesa cache mapping required")
    libraries.sort(key=lambda row: row["path"])
    return {
        "historical_path": str(historical_path.resolve()),
        "historical_sha256": expected_sha256,
        "cache_path": cache,
        "libraries": libraries,
        "historical_failure_retained": True,
        "runtime_closure_qualified": False,
    }


def validate_probe_environment(path, expected_sha256):
    path = Path(path)
    if _sha256(path) != expected_sha256:
        raise ValueError("probe environment declaration hash mismatch")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if type(doc) is not dict:
        raise ValueError("invalid probe environment declaration")
    materialized = doc.get("materialized")
    if (
        doc.get("schema") != "renderer-probe-environment-v1"
        or doc.get("ambient_inherited") is not False
        or not isinstance(doc.get("base_environment_sha256"), str)
        or len(doc["base_environment_sha256"]) != 64
        or type(materialized) is not dict
        or not materialized
        or any(type(key) is not str or type(value) is not str for key, value in materialized.items())
        or materialized.get(CACHE_DISABLE_ENV) != "true"
    ):
        raise ValueError("invalid probe environment declaration")
    if dict(os.environ) != materialized:
        raise ValueError("actual process environment differs from declaration")
    return doc


def _key(row):
    if type(row) is not dict or set(row) != {"path", "device", "inode"}:
        raise ValueError("invalid mapping row")
    if not row["path"].startswith("/") or type(row["device"]) is not str or type(row["inode"]) is not int:
        raise ValueError("invalid mapping identity")
    return row["path"], row["device"], row["inode"]


def _device_text(value):
    if hasattr(os, "major"):
        major, minor = os.major(value), os.minor(value)
    else:
        major, minor = value >> 8 & 0xFFF, value & 0xFF | value >> 12 & 0xFFF00
    return f"{major:02x}:{minor:02x}"


def baseline_mapping_identities(path, expected_sha256):
    path = Path(path)
    if _sha256(path) != expected_sha256:
        raise ValueError("baseline mapping declaration hash mismatch")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if type(doc) is not dict or doc.get("schema") != "declared-files-v1" or type(doc.get("files")) is not list:
        raise ValueError("invalid baseline mapping declaration")
    rows, seen = [], {}
    for item in doc["files"]:
        identity = item.get("identity") if type(item) is dict else None
        if (
            type(item.get("resolved")) is not str
            or type(identity) is not dict
            or type(identity.get("device")) is not int
            or type(identity.get("inode")) is not int
        ):
            raise ValueError("invalid baseline file identity")
        row = {"path": item["resolved"], "device": _device_text(identity["device"]), "inode": identity["inode"]}
        key = _key(row)
        previous = seen.get(row["path"])
        if previous is not None and previous != key:
            raise ValueError("conflicting baseline mapping identity")
        if previous is None:
            seen[row["path"]] = key
            rows.append(row)
    return rows


def validate_mapping_delta(before, after, expected, cache_path, baseline=()):
    before_keys = {_key(row) for row in before}
    after_keys = {_key(row) for row in after}
    expected_keys = {_key(row) for row in expected}
    baseline_keys = {_key(row) for row in baseline}
    if (len(before_keys) != len(before) or len(after_keys) != len(after)
            or len(expected_keys) != len(expected) or len(baseline_keys) != len(baseline)):
        raise ValueError("duplicate mapping identity")
    added = after_keys - before_keys
    cache_present = any(row[0] == cache_path for row in after_keys)
    if cache_present:
        raise ValueError("Mesa shader cache remained mapped")
    if not expected_keys <= added or not added <= expected_keys | baseline_keys:
        raise ValueError("first-step mapping delta differs from frozen failure")
    historical = added & expected_keys
    known = added - expected_keys
    return {
        "added": [dict(path=p, device=d, inode=i) for p, d, i in sorted(added)],
        "historical_additions": [dict(path=p, device=d, inode=i) for p, d, i in sorted(historical)],
        "baseline_additions": [dict(path=p, device=d, inode=i) for p, d, i in sorted(known)],
        "exact_delta": True,
        "cache_absent": True,
        "runtime_closure_qualified": True,
    }


def persist_then_parse_maps(raw, path, *, parser=parse_maps):
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        if stream.write(raw) != len(raw):
            raise OSError("short raw maps write")
        stream.flush()
    return parser(raw)


def read_maps_snapshot(evidence_path, *, source_path=Path("/proc/self/maps")):
    with Path(source_path).open("r", encoding="utf-8") as stream:
        raw = stream.read(MAX_MAP_BYTES + 1)
    if len(raw) > MAX_MAP_BYTES:
        raise ValueError("process maps exceed evidence limit")
    return raw, persist_then_parse_maps(raw, evidence_path)


def package_provenance(libraries, *, runner=subprocess.run):
    packages, rows = {}, []
    for mapping in libraries:
        path = mapping["path"]
        owner = runner(["/usr/bin/dpkg-query", "-S", path], capture_output=True, text=True, timeout=10)
        if owner.returncode or len([line for line in owner.stdout.splitlines() if line]) != 1:
            raise ValueError("mapped library package owner unavailable")
        package = owner.stdout.split(": ", 1)[0].split(":", 1)[0]
        meta = runner(
            ["/usr/bin/dpkg-query", "-W", "-f=${source:Package}\t${Version}\t${Architecture}\t${Status}", package],
            capture_output=True,
            text=True,
            timeout=10,
        )
        fields = meta.stdout.strip().split("\t")
        if meta.returncode or len(fields) != 4 or fields[3] != "install ok installed":
            raise ValueError("mapped library package metadata unavailable")
        copyright_path = Path("/usr/share/doc") / package / "copyright"
        package_row = {
            "package": package,
            "source": fields[0],
            "version": fields[1],
            "architecture": fields[2],
            "status": fields[3],
            "copyright": file_record(copyright_path),
        }
        previous = packages.setdefault(package, package_row)
        if previous != package_row:
            raise ValueError("inconsistent package provenance")
        rows.append({"mapping": dict(mapping), "file": file_record(path), "package": package})
    return {"libraries": rows, "packages": [packages[name] for name in sorted(packages)]}


def run_probe(output, world, historical, historical_sha256, cache_path, environment, environment_sha256,
              baseline, baseline_sha256):
    output, world = Path(output), Path(world)
    if output.exists():
        raise FileExistsError(str(output))
    environment_doc = validate_probe_environment(environment, environment_sha256)
    output.mkdir(parents=True)
    expected = expected_renderer_mappings(historical, historical_sha256, cache_path)
    baseline_identities = baseline_mapping_identities(baseline, baseline_sha256)
    result = {
        "schema": "renderer-first-step-probe-v1",
        "status": "probe_failed",
        "world": file_record(world),
        "environment": environment_doc,
        "environment_declaration": file_record(environment),
        "historical": expected,
        "baseline_declaration": file_record(baseline),
        "steps": 10,
        "physics_step_ns": 1_000_000,
        "px4_started": False,
        "openvins_started": False,
        "training_started": False,
        "force_applied": False,
        "runtime_closure_qualified": False,
        "physical_execution_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }
    try:
        import gz.math7  # noqa: F401
        from gz.msgs10.camera_info_pb2 import CameraInfo
        from gz.msgs10.image_pb2 import Image
        from gz.msgs10.imu_pb2 import IMU
        from gz.sim8 import TestFixture
        from gz.transport13 import Node

        node, callbacks = Node(), []
        topics = [
            (Image, "/benchmark/rgbd/image"),
            (Image, "/benchmark/rgbd/depth_image"),
            (CameraInfo, "/benchmark/rgbd/camera_info"),
            (IMU, "/world/fly_ego_benchmark/model/x500_benchmark_8/link/base_link/sensor/imu_sensor/imu"),
        ]
        counts = {topic: 0 for _, topic in topics}
        for message_type, topic in topics:
            def callback(_message, topic=topic):
                counts[topic] += 1

            callbacks.append(callback)
            if not node.subscribe(message_type, topic, callback):
                raise RuntimeError("subscription failed: " + topic)
        fixture = TestFixture(str(world.resolve(strict=True)))
        fixture.finalize()
        server = fixture.server()
        _raw_before, before = read_maps_snapshot(output / "maps-before.txt")
        started = time.monotonic()
        if not server.run(True, 10, False):
            raise RuntimeError("Gazebo rejected isolated first step")
        elapsed = time.monotonic() - started
        if elapsed > 30:
            raise TimeoutError("isolated first step exceeded 30 seconds")
        _raw_after, after = read_maps_snapshot(output / "maps-after.txt")
        result["mapping"] = validate_mapping_delta(
            before, after, expected["libraries"], expected["cache_path"], baseline_identities,
        )
        result["packages"] = package_provenance(result["mapping"]["added"])
        result["subscriptions"] = counts
        result["step_wall_s"] = elapsed
        result["status"] = "probe_completed"
        result["runtime_closure_qualified"] = True
    except BaseException as exc:
        result["error"] = repr(exc)
        result["traceback"] = traceback.format_exc()
    write_json_exclusive(output / "result.json", result)
    return result


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--world", required=True, type=Path)
    parser.add_argument("--historical", required=True, type=Path)
    parser.add_argument("--historical-sha256", required=True)
    parser.add_argument("--cache-path", required=True)
    parser.add_argument("--environment", required=True, type=Path)
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--baseline-sha256", required=True)
    args = parser.parse_args(argv)
    result = run_probe(
        args.output, args.world, args.historical, args.historical_sha256, args.cache_path,
        args.environment, args.environment_sha256,
        args.baseline, args.baseline_sha256,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "probe_completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
