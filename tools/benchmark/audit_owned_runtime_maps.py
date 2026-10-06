"""Run bounded non-Gazebo owned-process mapping checks on Linux."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import snapshot
from tools.benchmark.owned_runtime_maps import OwnedRuntimeMaps


def ldd_paths(text):
    paths = []
    for line in text.splitlines():
        fields = line.strip().split()
        candidates = [item for item in fields if item.startswith("/")]
        if candidates:
            path = candidates[0].split("(", 1)[0]
            if path not in paths:
                paths.append(path)
        elif "not found" in line:
            raise ValueError("ldd dependency missing")
    return paths


def write_json(path, value):
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False)
    with path.open("x", encoding="utf-8") as stream:
        if stream.write(text) != len(text):
            raise OSError("short audit write")
        stream.flush()


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    executable = Path("/usr/bin/sleep").resolve(strict=True)
    ldd = subprocess.run(["/usr/bin/ldd", str(executable)], check=True, capture_output=True, text=True, timeout=10)
    declared = [str(executable), *ldd_paths(ldd.stdout)]
    inventory = {"owned-harness": declared}
    before = snapshot(inventory)
    write_json(output / "declared-files-pre.json", before)
    (output / "ldd.txt").write_text(ldd.stdout, encoding="utf-8")
    known = {row["resolved"]: row["identity"] for row in before["files"]}

    child_env = dict(os.environ, LC_ALL="C", LANG="C")
    write_json(output / "child-environment.json", {"LC_ALL": "C", "LANG": "C"})
    normal = subprocess.Popen([str(executable), "30"], env=child_env)
    observer = OwnedRuntimeMaps(output / "normal", known, max_maps_bytes=8 * 1024 * 1024, max_observations=2)
    (output / "normal").mkdir()
    try:
        observer.register("harness", normal, str(executable))
        observer.observe("harness", "ready")
        observer.observe("harness", "prestop")
    finally:
        normal.terminate()
        normal.wait(timeout=5)

    fault_dir = output / "fault-disappeared"
    fault_dir.mkdir()
    fault = subprocess.Popen([str(executable), "30"], env=child_env)
    fault_observer = OwnedRuntimeMaps(fault_dir, known, max_maps_bytes=8 * 1024 * 1024, max_observations=1)
    fault_observer.register("harness", fault, str(executable))
    fault.terminate()
    fault.wait(timeout=5)
    refusal = None
    try:
        fault_observer.observe("harness", "after-exit")
    except ValueError as exc:
        refusal = repr(exc)
    if refusal is None:
        raise RuntimeError("disappeared process was not refused")

    after = snapshot(inventory)
    write_json(output / "declared-files-post.json", after)
    stable = before["files"] == after["files"]
    result = dict(
        schema="owned-runtime-maps-audit-v1",
        executable=str(executable),
        python=sys.version,
        declaration_sha256=hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
        normal_observations=["ready", "prestop"],
        disappeared_refusal=refusal,
        declared_files_stable=stable,
        runtime_mapping_coverage_verified=stable,
        runtime_closure_qualified=False,
        physics_qualified=False,
        estimator_qualified=False,
        fusion_eligible=False,
    )
    write_json(output / "audit.json", result)
    if not stable:
        raise RuntimeError("declared harness files drifted")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    print(json.dumps(run(parser.parse_args().output), indent=2))


if __name__ == "__main__":
    main()
