"""Run one isolated PX4/Gazebo visual-odometry fault trial under WSL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

from flydrones.px4_ulog_evidence import extract_ulog_fusion_evidence, newest_vehicle_ulog

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_trial(*, name: str, profile: Path, fleet_size: int, model: Path) -> dict:
    if not name.replace("-", "").replace("_", "").isalnum() or "/" in name:
        raise ValueError("name must be an alphanumeric trial label")
    if fleet_size not in (1, 5):
        raise ValueError("fleet_size must be 1 or 5")
    processes = subprocess.check_output(["ps", "-eo", "args="], text=True)
    occupied = [line for line in processes.splitlines() if (
        "/build/px4_sitl_default/bin/px4 -i " in line
        or line.startswith("gz sim ")
        or line.startswith("python3 ") and "tools/relay_gazebo_vio.py" in line
    )]
    if occupied:
        raise RuntimeError(f"PX4/Gazebo resources are in use: {occupied}")
    output = ROOT / "results" / "vio-stress" / name
    run_dir = Path("/tmp") / f"flydrones-vio-{name}"
    if output.exists() or run_dir.exists():
        raise FileExistsError(f"trial output already exists: {output} or {run_dir}")
    manifest = {
        "schema": "flydrones-vio-stress-trial-v1",
        "name": name,
        "fleet_size": fleet_size,
        "profile": str(profile.resolve()),
        "profile_sha256": sha256(profile),
        "policy_checkpoint": str(model.resolve()),
        "policy_sha256": sha256(model),
        "px4_run_dir": str(run_dir),
        "px4_revision": subprocess.check_output(
            ["git", "-C", str(Path.home() / "PX4-Autopilot"), "rev-parse", "HEAD"], text=True
        ).strip(),
        "controller_revision": os.environ["FLYDRONES_CONTROLLER_REVISION"],
        "controller_source_sha256": sha256(ROOT / "src/flydrones/distributed_px4.py"),
        "relay_source_sha256": sha256(ROOT / "tools/relay_gazebo_vio.py"),
        "trial_runner_sha256": sha256(Path(__file__)),
        "launch_exit_code": None,
        "worker_exit_code": None,
        "evidence_accepted": False,
        "errors": [],
    }
    output.mkdir(parents=True)
    environment = os.environ.copy()
    environment.update({
        "FLYDRONES_PX4_RUN_DIR": str(run_dir),
        "FLYDRONES_VIO_FAULT_PROFILE": str(profile.resolve()),
        "FLYDRONES_VEHICLE_COUNT": str(fleet_size),
        "PYTHONPATH": str(ROOT / "src"),
    })
    try:
        with (output / "launch.log").open("w", encoding="utf-8") as log:
            launch = subprocess.run(["bash", str(ROOT / "tools/launch_px4_depth_swarm_wsl.sh")],
                                    env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
        manifest["launch_exit_code"] = launch.returncode
        if launch.returncode == 0:
            marker = run_dir / "fault-start.json"
            if fleet_size == 1:
                worker = [sys.executable, str(ROOT / "tools/px4_distributed_agent.py"),
                          "--vehicle-id", "0", "--output", str(output), "--model", str(model),
                          "--mission-timeout", "70", "--gps-failure-at", "5",
                          "--gps-failure-mode", "fusion-off", "--external-vision-fusion",
                          "--fault-marker", str(marker)]
            else:
                worker = [sys.executable, str(ROOT / "tools/run_distributed_px4_swarm.py"),
                          "--output", str(output), "--model", str(model),
                          "--mission-timeout", "70", "--process-timeout", "180",
                          "--gps-failure-vehicle", "0", "--gps-failure-at", "5",
                          "--gps-failure-mode", "fusion-off", "--external-vision-fusion",
                          "--fault-marker", str(marker)]
            with (output / "worker.log").open("w", encoding="utf-8") as log:
                result = subprocess.run(worker, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                        check=False)
            manifest["worker_exit_code"] = result.returncode
    except Exception as exc:
        manifest["errors"].append(f"execution: {exc}\n{traceback.format_exc()}")
    finally:
        with (output / "stop.log").open("w", encoding="utf-8") as log:
            subprocess.run(["bash", str(ROOT / "tools/stop_px4_swarm_wsl.sh")],
                           env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
        for source_name in ("vio-relay.jsonl", "vio-relay.stdout.log", "vio-relay.stderr.log"):
            source = run_dir / source_name
            if source.exists():
                shutil.copy2(source, output / source_name)
        if run_dir.exists():
            for vehicle_id in range(fleet_size):
                try:
                    source = newest_vehicle_ulog(run_dir, vehicle_id)
                    target = output / "px4-ulogs" / f"agent-{vehicle_id}.ulg"
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(source, target)
                    if vehicle_id == 0:
                        evidence = extract_ulog_fusion_evidence(
                            target, output_path=output / "px4-ekf-fusion-evidence.json",
                            fault_vehicle_id=0, preserve_ulog=False,
                        )
                        manifest["evidence_accepted"] = bool(evidence["accepted"])
                except Exception as exc:
                    manifest["errors"].append(f"ULog vehicle {vehicle_id}: {exc}")
        (output / "trial-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--fleet-size", type=int, choices=(1, 5), required=True)
    parser.add_argument("--model", type=Path, default=ROOT / "results/autonomous-forest-ppo-v1/autonomous-policy-numpy.npz")
    args = parser.parse_args()
    manifest = run_trial(name=args.name, profile=args.profile, fleet_size=args.fleet_size, model=args.model)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if (manifest["launch_exit_code"] == 0 and manifest["worker_exit_code"] == 0
                 and manifest["evidence_accepted"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
