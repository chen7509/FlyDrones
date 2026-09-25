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


def _tree_fingerprint(path: Path) -> tuple | None:
    if not path.exists():
        return None
    if path.is_file():
        return ("file", sha256(path))
    return ("directory", tuple(sorted(
        (item.relative_to(path).as_posix(), sha256(item))
        for item in path.rglob("*") if item.is_file()
    )))


def shared_px4_files_restored(run_dir: Path, px4_root: Path) -> bool:
    backup = run_dir / "backups"
    if not backup.is_dir():
        return False
    pairs = (
        (backup / "world.sdf", px4_root / "Tools/simulation/gz/worlds/flydrones_forest.sdf"),
        (backup / "OakD-Lite-Fly", px4_root / "Tools/simulation/gz/models/OakD-Lite-Fly"),
        (backup / "x500_depth_fly", px4_root / "Tools/simulation/gz/models/x500_depth_fly"),
    )
    return all(_tree_fingerprint(before) == _tree_fingerprint(after) for before, after in pairs)


def relay_closed_cleanly(path: Path) -> bool:
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    if not lines:
        return False
    try:
        return json.loads(lines[-1]).get("event") == "stop"
    except json.JSONDecodeError:
        return False


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
        "controller_revision": os.environ.get("FLYDRONES_CONTROLLER_REVISION"),
        "controller_source_sha256": sha256(ROOT / "src/flydrones/distributed_px4.py"),
        "relay_source_sha256": sha256(ROOT / "tools/relay_gazebo_vio.py"),
        "trial_runner_sha256": sha256(Path(__file__)),
        "launch_exit_code": None,
        "worker_exit_code": None,
        "evidence_accepted": False,
        "errors": [],
    }
    output.mkdir(parents=True)
    profile_copy = output / "fault-profile.json"
    model_copy = output / "policy-checkpoint.npz"
    shutil.copy2(profile, profile_copy)
    shutil.copy2(model, model_copy)
    environment = os.environ.copy()
    environment.update({
        "FLYDRONES_PX4_RUN_DIR": str(run_dir),
        "FLYDRONES_VIO_FAULT_PROFILE": str(profile_copy.resolve()),
        "FLYDRONES_VEHICLE_COUNT": str(fleet_size),
        "FLYDRONES_VIO_HEALTH_BASE_PORT": "16880",
        "PYTHONPATH": str(ROOT / "src"),
    })
    try:
        with (output / "launch.log").open("w", encoding="utf-8") as log:
            launch = subprocess.run(["bash", str(ROOT / "tools/launch_px4_depth_swarm_wsl.sh")],
                                    env=environment, stdout=log, stderr=subprocess.STDOUT, check=False,
                                    timeout=120)
        manifest["launch_exit_code"] = launch.returncode
        if launch.returncode == 0:
            marker = run_dir / "fault-start.json"
            if fleet_size == 1:
                worker = [sys.executable, str(ROOT / "tools/px4_distributed_agent.py"),
                          "--vehicle-id", "0", "--output", str(output), "--model", str(model_copy),
                          "--mission-timeout", "70", "--gps-failure-at", "5",
                          "--gps-failure-mode", "fusion-off", "--external-vision-fusion",
                          "--fault-marker", str(marker), "--vio-health-port", "16880"]
            else:
                worker = [sys.executable, str(ROOT / "tools/run_distributed_px4_swarm.py"),
                          "--output", str(output), "--model", str(model_copy),
                          "--mission-timeout", "70", "--process-timeout", "180",
                          "--gps-failure-vehicle", "0", "--gps-failure-at", "5",
                          "--gps-failure-mode", "fusion-off", "--external-vision-fusion",
                          "--fault-marker", str(marker), "--vio-health-base-port", "16880"]
            with (output / "worker.log").open("w", encoding="utf-8") as log:
                result = subprocess.run(worker, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                        check=False, timeout=240)
            manifest["worker_exit_code"] = result.returncode
    except Exception as exc:
        manifest["errors"].append(f"execution: {exc}\n{traceback.format_exc()}")
    finally:
        try:
            with (output / "stop.log").open("w", encoding="utf-8") as log:
                stopped = subprocess.run(["bash", str(ROOT / "tools/stop_px4_swarm_wsl.sh")],
                                         env=environment, stdout=log, stderr=subprocess.STDOUT,
                                         check=False, timeout=30)
            manifest["stop_exit_code"] = stopped.returncode
        except Exception as exc:
            manifest["errors"].append(f"stop: {exc}")
        manifest["shared_px4_files_restored"] = shared_px4_files_restored(
            run_dir, Path(os.environ.get("PX4_ROOT", Path.home() / "PX4-Autopilot"))
        )
        world_source = run_dir / "flydrones_forest.sdf"
        if world_source.exists():
            shutil.copy2(world_source, output / "flydrones_forest.sdf")
            manifest["world_sha256"] = sha256(output / "flydrones_forest.sdf")
        for source_name in ("vio-relay.jsonl", "vio-relay.stdout.log", "vio-relay.stderr.log"):
            source = run_dir / source_name
            if source.exists():
                shutil.copy2(source, output / source_name)
        relay_log = output / "vio-relay.jsonl"
        manifest["relay_closed_cleanly"] = relay_closed_cleanly(relay_log)
        if not manifest["relay_closed_cleanly"]:
            manifest["errors"].append("relay log is missing or lacks a complete stop record")
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
    parser.add_argument("--model", type=Path, default=ROOT / "docs/results/vio-stress/policy-checkpoint.npz")
    args = parser.parse_args()
    manifest = run_trial(name=args.name, profile=args.profile, fleet_size=args.fleet_size, model=args.model)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    try:
        from summarize_vio_stress_wsl import summarize_trial

        summary = summarize_trial(ROOT / "results" / "vio-stress" / args.name)
        return 0 if (summary["operational_continuity_pass"]
                     or summary["fault_vehicle_gate_land_sequence_observed"] and summary["all_landed"]) else 2
    except Exception as exc:
        print(f"trial scoring failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
