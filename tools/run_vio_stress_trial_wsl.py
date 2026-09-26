"""Run one isolated PX4/Gazebo visual-odometry fault trial under WSL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Mapping
from pathlib import Path

from flydrones.px4_ulog_evidence import newest_vehicle_ulog

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "results" / "vio-stress"


def git_revision(
    path: Path,
    *,
    check_output: Callable[..., str] = subprocess.check_output,
) -> str:
    command = ["git", "-C", str(path), "rev-parse", "HEAD"]
    try:
        return check_output(command, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        windows_path = check_output(["wslpath", "-w", str(path)], text=True).strip()
        return check_output(
            ["git.exe", "-C", windows_path, "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()


def campaign_run_directory(
    name: str,
    campaign_id: str | None,
    *,
    temp_root: Path = Path("/tmp"),
) -> Path:
    label = f"{campaign_id}-{name}" if campaign_id else name
    if not label.replace("-", "").replace("_", "").isalnum() or "/" in label:
        raise ValueError("campaign and trial labels must be alphanumeric")
    return temp_root / f"flydrones-vio-{label}"


def create_trial_manifest(
    *,
    name: str,
    fleet_size: int,
    profile: Path,
    model: Path,
    renderer_profile: str,
    pair_id: int | None,
    pair_position: int | None,
    campaign_id: str | None,
    output_root: Path,
    repository_revision: str,
    px4_revision: str,
    frozen_hashes: Mapping[str, str],
    software_versions: Mapping[str, str],
) -> dict:
    return {
        "schema": "flydrones-vio-stress-trial-v2",
        "name": name,
        "fleet_size": fleet_size,
        "seed": 240901,
        "profile": str(profile.resolve()),
        "policy_checkpoint": str(model.resolve()),
        "renderer": {"requested_profile": renderer_profile, "attestation": None},
        "pair": {"id": pair_id, "position": pair_position},
        "campaign_id": campaign_id,
        "output_root": str(output_root),
        "repository_revision": repository_revision,
        "px4_revision": px4_revision,
        "frozen_hashes": dict(frozen_hashes),
        "software_versions": dict(software_versions),
        "launch_exit_code": None,
        "worker_exit_code": None,
        "stop_exit_code": None,
        "evidence_accepted": False,
        "errors": [],
        "raw_artifact_sha256": {},
    }


def apply_renderer_attestation(manifest: dict, path: Path) -> None:
    if not path.is_file():
        manifest["evidence_accepted"] = False
        manifest["errors"].append("renderer attestation missing")
        return
    try:
        attestation = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        manifest["evidence_accepted"] = False
        manifest["errors"].append(f"renderer attestation unreadable: {exc}")
        return
    manifest["renderer"]["attestation"] = attestation
    if not attestation.get("accepted"):
        manifest["evidence_accepted"] = False
        manifest["errors"].append("renderer attestation rejected")


def terminate_worker_process_group(
    process_group: int,
    *,
    send_signal: Callable[[int, int], None] | None = None,
    grace_s: float = 0.0,
) -> None:
    if send_signal is None:
        if not hasattr(os, "killpg"):
            raise RuntimeError("process-group signals are unavailable on this platform")
        send_signal = os.killpg
    for signum in (signal.SIGTERM, getattr(signal, "SIGKILL", 9)):
        try:
            send_signal(process_group, signum)
        except ProcessLookupError:
            return
        if signum == signal.SIGTERM and grace_s > 0:
            time.sleep(grace_s)


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


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(bytes.fromhex(sha256(item)))
    return digest.hexdigest()


def _version(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
        return result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else "unavailable"
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _software_versions() -> dict[str, str]:
    return {
        "gazebo": _version(["gz", "sim", "--version"]),
        "gz_rendering": _version(["dpkg-query", "-W", "-f=${Version}", "libgz-rendering8"]),
        "gz_sensors": _version(["dpkg-query", "-W", "-f=${Version}", "libgz-sensors8"]),
        "mesa": _version(["dpkg-query", "-W", "-f=${Version}", "libgl1-mesa-dri"]),
        "kernel": _version(["uname", "-r"]),
        "python": sys.version.split()[0],
    }


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


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


def run_trial(
    *,
    name: str,
    profile: Path,
    fleet_size: int,
    model: Path,
    renderer_profile: str = "default",
    pair_id: int | None = None,
    pair_position: int | None = None,
    campaign_id: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict:
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
    output = output_root / name
    run_dir = campaign_run_directory(name, campaign_id)
    if output.exists() or run_dir.exists():
        raise FileExistsError(f"trial output already exists: {output} or {run_dir}")
    px4_root = Path(os.environ.get("PX4_ROOT", Path.home() / "PX4-Autopilot"))
    repository_revision = git_revision(ROOT)
    px4_revision = git_revision(px4_root)
    frozen_hashes = {
        "profile": sha256(profile),
        "policy": sha256(model),
        "controller": sha256(ROOT / "src/flydrones/distributed_px4.py"),
        "relay": sha256(ROOT / "tools/relay_gazebo_vio.py"),
        "runner": sha256(Path(__file__)),
        "launcher": sha256(ROOT / "tools/launch_px4_depth_swarm_wsl.sh"),
        "renderer_attestation": sha256(ROOT / "tools/attest_gazebo_renderer_wsl.py"),
        "renderer_profile": sha256(ROOT / "src/flydrones/gazebo_renderer.py"),
        "runtime_probe": sha256(ROOT / "tools/probe_gazebo_runtime_wsl.py"),
        "summary": sha256(ROOT / "tools/summarize_vio_stress_wsl.py"),
        "world_generator": sha256(ROOT / "tools/generate_px4_forest_world.py"),
        "camera_model": _tree_sha256(ROOT / "assets/gazebo/models/OakD-Lite-Fly"),
        "vehicle_model": _tree_sha256(ROOT / "assets/gazebo/models/x500_depth_fly"),
    }
    manifest = create_trial_manifest(
        name=name,
        fleet_size=fleet_size,
        profile=profile,
        model=model,
        renderer_profile=renderer_profile,
        pair_id=pair_id,
        pair_position=pair_position,
        campaign_id=campaign_id,
        output_root=output_root,
        repository_revision=repository_revision,
        px4_revision=px4_revision,
        frozen_hashes=frozen_hashes,
        software_versions=_software_versions(),
    )
    manifest["px4_run_dir"] = str(run_dir)
    manifest["controller_revision"] = os.environ.get("FLYDRONES_CONTROLLER_REVISION", repository_revision)
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
        "FLYDRONES_GZ_RENDER_PROFILE": renderer_profile,
        "FLYDRONES_SEED": "240901",
        "PYTHONPATH": str(ROOT / "src"),
    })
    completion_marker = output / "trial-complete.marker"
    probe_log = (output / "runtime-probe.log").open("w", encoding="utf-8")
    probe = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools/probe_gazebo_runtime_wsl.py"),
            "--run-dir", str(run_dir),
            "--output-dir", str(output),
            "--completion-marker", str(completion_marker),
            "--duration-s", "300",
        ],
        env=environment,
        stdout=probe_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    worker_process = None
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
                          "--gps-failure-mode", "fusion-off", "--gps-failure-all",
                          "--external-vision-fusion", "--allow-no-udp-blackout",
                          "--fault-marker", str(marker), "--vio-health-base-port", "16880"]
            with (output / "worker.log").open("w", encoding="utf-8") as log:
                worker_process = subprocess.Popen(
                    worker,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                try:
                    manifest["worker_exit_code"] = worker_process.wait(timeout=240)
                except subprocess.TimeoutExpired:
                    terminate_worker_process_group(worker_process.pid, grace_s=2.0)
                    manifest["worker_exit_code"] = worker_process.wait(timeout=10)
                    manifest["errors"].append("worker process group timed out and was terminated")
    except Exception as exc:
        manifest["errors"].append(f"execution: {exc}\n{traceback.format_exc()}")
    finally:
        if worker_process is not None and worker_process.poll() is None:
            try:
                terminate_worker_process_group(worker_process.pid, grace_s=2.0)
                worker_process.wait(timeout=10)
            except Exception as exc:
                manifest["errors"].append(f"worker cleanup: {exc}")
        try:
            with (output / "stop.log").open("w", encoding="utf-8") as log:
                stopped = subprocess.run(["bash", str(ROOT / "tools/stop_px4_swarm_wsl.sh")],
                                         env=environment, stdout=log, stderr=subprocess.STDOUT,
                                         check=False, timeout=30)
            manifest["stop_exit_code"] = stopped.returncode
        except Exception as exc:
            manifest["errors"].append(f"stop: {exc}")
        completion_marker.touch()
        try:
            probe_return_code = probe.wait(timeout=20)
            if probe_return_code != 0:
                manifest["errors"].append(f"runtime probe exited {probe_return_code}")
        except subprocess.TimeoutExpired:
            probe.terminate()
            try:
                probe.wait(timeout=5)
            except subprocess.TimeoutExpired:
                probe.kill()
                probe.wait(timeout=5)
            manifest["errors"].append("runtime probe did not stop after completion marker")
        probe_log.close()
        manifest["shared_px4_files_restored"] = shared_px4_files_restored(
            run_dir, px4_root
        )
        world_source = run_dir / "flydrones_forest.sdf"
        if world_source.exists():
            shutil.copy2(world_source, output / "flydrones_forest.sdf")
            manifest["frozen_hashes"]["world"] = sha256(output / "flydrones_forest.sdf")
        for source_name in (
            "vio-relay.jsonl",
            "vio-relay.stdout.log",
            "vio-relay.stderr.log",
            "renderer-attestation.json",
            "cleanup-evidence.json",
            "gazebo.stdout.log",
            "gazebo.stderr.log",
        ):
            source = run_dir / source_name
            if source.exists():
                shutil.copy2(source, output / source_name)
        relay_log = output / "vio-relay.jsonl"
        manifest["relay_closed_cleanly"] = relay_closed_cleanly(relay_log)
        if not manifest["relay_closed_cleanly"]:
            manifest["errors"].append("relay log is missing or lacks a complete stop record")
        ulog_artifacts = []
        if run_dir.exists():
            for vehicle_id in range(fleet_size):
                try:
                    source = newest_vehicle_ulog(run_dir, vehicle_id)
                    target = output / "px4-ulogs" / f"agent-{vehicle_id}.ulg"
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(source, target)
                    ulog_artifacts.append({
                        "vehicle_id": vehicle_id,
                        "path": target.relative_to(output).as_posix(),
                        "bytes": target.stat().st_size,
                        "sha256": sha256(target),
                    })
                except Exception as exc:
                    manifest["errors"].append(f"ULog vehicle {vehicle_id}: {exc}")
        manifest["ulog_artifacts"] = ulog_artifacts
        apply_renderer_attestation(manifest, output / "renderer-attestation.json")
        attestation = manifest["renderer"].get("attestation")
        manifest["evidence_accepted"] = bool(
            attestation and attestation.get("accepted")
            and manifest["relay_closed_cleanly"]
            and manifest.get("stop_exit_code") == 0
            and manifest["shared_px4_files_restored"]
            and len(ulog_artifacts) == fleet_size
        )
        raw_paths = [
            path for path in output.rglob("*")
            if path.is_file() and path.name not in {"trial-manifest.json", "trial-manifest.json.tmp"}
        ]
        manifest["raw_artifact_sha256"] = {
            path.relative_to(output).as_posix(): sha256(path)
            for path in sorted(raw_paths)
        }
        _atomic_json(output / "trial-manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--fleet-size", type=int, choices=(1, 5), required=True)
    parser.add_argument("--model", type=Path, default=ROOT / "docs/results/vio-stress/policy-checkpoint.npz")
    parser.add_argument("--renderer-profile", choices=("default", "d3d12-nvidia"), default="default")
    parser.add_argument("--pair-id", type=int)
    parser.add_argument("--pair-position", type=int, choices=(1, 2))
    parser.add_argument("--campaign-id")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    manifest = run_trial(
        name=args.name,
        profile=args.profile,
        fleet_size=args.fleet_size,
        model=args.model,
        renderer_profile=args.renderer_profile,
        pair_id=args.pair_id,
        pair_position=args.pair_position,
        campaign_id=args.campaign_id,
        output_root=args.output_root,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    try:
        from summarize_vio_stress_wsl import summarize_trial

        summary = summarize_trial(args.output_root / args.name)
        return 0 if (summary["operational_continuity_pass"]
                     or summary["fault_vehicle_gate_land_sequence_observed"] and summary["all_landed"]) else 2
    except Exception as exc:
        print(f"trial scoring failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
