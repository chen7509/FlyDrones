#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
px4_root="${PX4_ROOT:-$HOME/PX4-Autopilot}"
build="$px4_root/build/px4_sitl_default"
run_dir="${FLYDRONES_PX4_RUN_DIR:-/tmp/flydrones-px4-five-depth}"
vehicle_count="${FLYDRONES_VEHICLE_COUNT:-5}"
vio_fault_profile="${FLYDRONES_VIO_FAULT_PROFILE:-}"
vio_health_base_port="${FLYDRONES_VIO_HEALTH_BASE_PORT:-}"
renderer_profile="${FLYDRONES_GZ_RENDER_PROFILE:-default}"
camera_schedule_mode="${FLYDRONES_CAMERA_SCHEDULE_MODE:-simultaneous}"
camera_aux_timeout_s="${FLYDRONES_CAMERA_AUX_TIMEOUT_S:-45}"
camera_phase_ready_marker="${FLYDRONES_CAMERA_PHASE_READY_MARKER:-}"
capacity_mode="${FLYDRONES_CAPACITY_MODE:-0}"
capacity_ready_marker="${FLYDRONES_CAPACITY_READY_MARKER:-}"
capacity_observer_pid_file="${FLYDRONES_CAPACITY_OBSERVER_PID_FILE:-}"
capacity_subscriber_count="${FLYDRONES_CAPACITY_SUBSCRIBER_COUNT:-}"
world_source="$repo_root/results/px4-sitl-five-depth/flydrones_forest.sdf"
world_target="$px4_root/Tools/simulation/gz/worlds/flydrones_forest.sdf"
model_root="$px4_root/Tools/simulation/gz/models"
registry="$run_dir/owned-processes.json"
renderer_env=()

case "$renderer_profile" in
  default) ;;
  d3d12-nvidia)
    renderer_env=(GALLIUM_DRIVER=d3d12 MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA)
    ;;
  *)
    echo "unsupported Gazebo renderer profile: $renderer_profile" >&2
    exit 2
    ;;
esac
case "$camera_schedule_mode" in
  simultaneous|phased) ;;
  *)
    echo "unsupported camera schedule mode: $camera_schedule_mode" >&2
    exit 2
    ;;
esac

if [[ ! -x "$build/bin/px4" ]]; then
  echo "PX4 SITL binary is missing: $build/bin/px4" >&2
  exit 2
fi
if [[ "$vehicle_count" != 1 && "$vehicle_count" != 5 ]]; then
  echo "FLYDRONES_VEHICLE_COUNT must be 1 or 5" >&2
  exit 2
fi
if [[ -n "$vio_fault_profile" && ! -f "$vio_fault_profile" ]]; then
  echo "VIO fault profile is missing: $vio_fault_profile" >&2
  exit 2
fi
if [[ -z "$camera_phase_ready_marker" ]]; then
  echo "FLYDRONES_CAMERA_PHASE_READY_MARKER is required" >&2
  exit 2
fi
if [[ "$capacity_mode" != 0 && "$capacity_mode" != 1 ]]; then
  echo "FLYDRONES_CAPACITY_MODE must be 0 or 1" >&2
  exit 2
fi
if [[ "$capacity_mode" == 1 ]]; then
  if [[ -z "$capacity_ready_marker" || -z "$capacity_observer_pid_file" ]]; then
    echo "capacity readiness marker and observer PID file are required" >&2
    exit 2
  fi
  if [[ "$capacity_subscriber_count" != 0 && "$capacity_subscriber_count" != 1 \
      && "$capacity_subscriber_count" != 5 ]]; then
    echo "FLYDRONES_CAPACITY_SUBSCRIBER_COUNT must be 0, 1, or 5" >&2
    exit 2
  fi
fi
if [[ -e "$run_dir" ]]; then
  echo "PX4 run directory already exists; refusing to overwrite: $run_dir" >&2
  exit 2
fi

for port in 14580 14581 14582 14583 14584; do
  if ss -H -lunp "sport = :$port" 2>/dev/null | grep -q .; then
    echo "PX4/Gazebo resource is in use: UDP port $port" >&2
    exit 4
  fi
done
if pgrep -x px4 >/dev/null 2>&1 || pgrep -x px4-gz_bridge >/dev/null 2>&1 \
    || pgrep -f '^gz sim .*flydrones_forest.sdf$' >/dev/null 2>&1; then
  echo "PX4/Gazebo resources are already in use; refusing to terminate them" >&2
  exit 4
fi

mkdir -p "$run_dir/backups"
touch "$run_dir/fault-mode"
cleanup_on_error() {
  status=$?
  trap - ERR INT TERM
  FLYDRONES_PX4_RUN_DIR="$run_dir" bash "$repo_root/tools/stop_px4_swarm_wsl.sh" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup_on_error ERR INT TERM

if [[ -e "$world_target" ]]; then
  cp -a "$world_target" "$run_dir/backups/world.sdf"
fi
for model in OakD-Lite-Fly x500_depth_fly; do
  if [[ -e "$model_root/$model" ]]; then
    cp -a "$model_root/$model" "$run_dir/backups/$model"
  fi
done

if [[ -n "$vio_fault_profile" ]]; then
  world_source="$run_dir/flydrones_forest.sdf"
fi
PYTHONPATH="$repo_root/src" python3 "$repo_root/tools/generate_px4_forest_world.py" --output "$world_source" --lane-spacing 2.0
cp "$world_source" "$world_target"
rm -rf "$model_root/OakD-Lite-Fly" "$model_root/x500_depth_fly"
cp -r "$repo_root/assets/gazebo/models/OakD-Lite-Fly" "$model_root/OakD-Lite-Fly"
cp -r "$repo_root/assets/gazebo/models/x500_depth_fly" "$model_root/x500_depth_fly"
PYTHONPATH="$repo_root/src" python3 "$repo_root/tools/configure_gazebo_camera_phase.py" \
  "$repo_root/assets/gazebo/models/OakD-Lite-Fly/model.sdf" \
  "$model_root/OakD-Lite-Fly/model.sdf" \
  --mode "$camera_schedule_mode" --evidence "$run_dir/camera-model-evidence.json"
cp "$model_root/OakD-Lite-Fly/model.sdf" "$run_dir/camera-model-configured.sdf"
if [[ -n "$vio_fault_profile" ]]; then
  python3 "$repo_root/tools/configure_gazebo_vio_model.py" "$model_root/x500_depth_fly/model.sdf"
fi

record_process() {
  PYTHONPATH="$repo_root/src" python3 - "$registry" "$1" "$2" <<'PY'
import sys
from pathlib import Path

from flydrones.process_ownership import append_process_identity

append_process_identity(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3])
PY
}

if [[ -n "$vio_fault_profile" ]]; then
  relay_health_args=()
  if [[ -n "$vio_health_base_port" ]]; then
    relay_health_args=(--health-base-port "$vio_health_base_port")
  fi
  nohup env PYTHONPATH="$repo_root/src" python3 "$repo_root/tools/relay_gazebo_vio.py" \
    --profile "$vio_fault_profile" --marker "$run_dir/fault-start.json" \
    --output "$run_dir/vio-relay.jsonl" --vehicle-count "$vehicle_count" \
    "${relay_health_args[@]}" \
    >"$run_dir/vio-relay.stdout.log" 2>"$run_dir/vio-relay.stderr.log" </dev/null &
  echo $! >"$run_dir/vio-relay.pid"
  record_process "$(cat "$run_dir/vio-relay.pid")" "vio-relay"
fi

export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:-}"
export GZ_SIM_SYSTEM_PLUGIN_PATH="${GZ_SIM_SYSTEM_PLUGIN_PATH:-}"
set +u
source "$build/rootfs/gz_env.sh"
set -u
(
  exec env -u GALLIUM_DRIVER -u MESA_D3D12_DEFAULT_ADAPTER_NAME "${renderer_env[@]}" \
    gz sim --headless-rendering -r -s "$world_target"
) >"$run_dir/gazebo.stdout.log" 2>"$run_dir/gazebo.stderr.log" </dev/null &
gazebo_pid=$!
echo "$gazebo_pid" >"$run_dir/gazebo.pid"
gazebo_argv_stable=0
for _ in $(seq 1 100); do
  if ! kill -0 "$gazebo_pid" 2>/dev/null; then
    echo "Gazebo exited before process identity stabilized" >&2
    exit 3
  fi
  gazebo_argv="$(tr '\0' ' ' <"/proc/$gazebo_pid/cmdline")"
  if [[ "$gazebo_argv" == "gz sim "* ]]; then
    gazebo_argv_stable=1
    break
  fi
  sleep 0.02
done
if [[ "$gazebo_argv_stable" -ne 1 ]]; then
  echo "Gazebo launcher did not reach stable gz sim argv" >&2
  exit 3
fi
record_process "$gazebo_pid" "gazebo-server"

base_ready="$run_dir/gazebo-base-ready.json"
aux_started="$run_dir/camera-aux-started.marker"
for _ in $(seq 1 40); do
  if ! kill -0 "$gazebo_pid" 2>/dev/null; then
    echo "Gazebo exited before base readiness" >&2
    tail -50 "$run_dir/gazebo.stderr.log" >&2 || true
    exit 3
  fi
  if [[ -n "$vio_fault_profile" ]] && ! kill -0 "$(cat "$run_dir/vio-relay.pid")" 2>/dev/null; then
    echo "VIO relay exited before Gazebo base readiness" >&2
    exit 3
  fi
  if gz topic -l 2>/dev/null | grep -Fxq '/clock'; then
    python3 - "$base_ready" "$gazebo_pid" "$camera_schedule_mode" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

target = Path(sys.argv[1])
payload = {
    "schema": "flydrones-gazebo-base-ready-v1",
    "gazebo_pid": int(sys.argv[2]),
    "camera_schedule_mode": sys.argv[3],
}
with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
    json.dump(payload, handle, indent=2)
    handle.write("\n")
    temporary = Path(handle.name)
temporary.replace(target)
PY
    break
  fi
  sleep 1
done
if [[ ! -f "$base_ready" ]]; then
  echo "Gazebo /clock base readiness timed out" >&2
  exit 3
fi

aux_deadline=$((SECONDS + camera_aux_timeout_s))
while [[ ! -f "$aux_started" ]]; do
  if ! kill -0 "$gazebo_pid" 2>/dev/null; then
    echo "Gazebo exited while waiting for camera auxiliaries" >&2
    exit 3
  fi
  if [[ -n "$vio_fault_profile" ]] && ! kill -0 "$(cat "$run_dir/vio-relay.pid")" 2>/dev/null; then
    echo "VIO relay exited while waiting for camera auxiliaries" >&2
    exit 3
  fi
  if (( SECONDS >= aux_deadline )); then
    echo "camera auxiliary startup handshake timed out" >&2
    exit 3
  fi
  sleep 0.05
done

poses=(-4.0 -2.0 0.0 2.0 4.0)
for ((instance_id=0; instance_id<vehicle_count; instance_id++)); do
  instance_dir="$run_dir/instance_$instance_id"
  mkdir -p "$instance_dir"
  ln -sf "$build/rootfs/gz_env.sh" "$instance_dir/gz_env.sh"
  extra_env=(PX4_GZ_STANDALONE=1)
  # Register EKF external-vision aid topics before logger startup. A late
  # MAVLink parameter change can enable fusion without logging those topics.
  if [[ -n "$vio_fault_profile" ]]; then extra_env+=(PX4_PARAM_EKF2_EV_CTRL=5); fi
  (
    cd "$instance_dir"
    nohup env HEADLESS=1 "${extra_env[@]}" PX4_SYS_AUTOSTART=4001 PX4_GZ_WORLD=flydrones_forest \
      PX4_SIM_MODEL=gz_x500_depth_fly PX4_GZ_MODEL_POSE="0,${poses[$instance_id]},0,0,0,0" \
      "$build/bin/px4" -i "$instance_id" -d "$build/etc" \
      >"$instance_dir/out.log" 2>"$instance_dir/err.log" </dev/null &
    echo $! >"$instance_dir/pid"
  )
  record_process "$(cat "$instance_dir/pid")" "px4-$instance_id"
  sleep 2
done

for _ in $(seq 1 40); do
  running=0
  bridge_ready=0
  for ((instance_id=0; instance_id<vehicle_count; instance_id++)); do
    pid_file="$run_dir/instance_$instance_id/pid"
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then running=$((running + 1)); fi
    if grep -Fq "[gz_bridge] world: flydrones_forest, model: x500_depth_fly_$instance_id" \
        "$run_dir/instance_$instance_id/out.log" 2>/dev/null; then
      bridge_ready=$((bridge_ready + 1))
    fi
  done
  depth_topics="$(gz topic -l 2>/dev/null | grep -c '/sensor/StereoOV7251/depth_image$' || true)"
  bridge_pids=()
  while read -r bridge_pid; do
    [[ -n "$bridge_pid" ]] || continue
    bridge_args="$(tr '\0' ' ' <"/proc/$bridge_pid/cmdline" 2>/dev/null || true)"
    if [[ "$bridge_args" == *"px4-gz_bridge --instance "*" start -w flydrones_forest"* ]]; then
      bridge_pids+=("$bridge_pid")
    fi
  done < <(pgrep -x px4-gz_bridge 2>/dev/null || true)
  if [[ "$running" -eq "$vehicle_count" ]] && [[ "$depth_topics" -eq "$vehicle_count" ]] \
      && [[ "$bridge_ready" -eq "$vehicle_count" ]]; then
    if [[ -n "$vio_fault_profile" ]] && ! kill -0 "$(cat "$run_dir/vio-relay.pid")" 2>/dev/null; then
      echo "VIO relay exited before PX4 startup completed" >&2
      cat "$run_dir/vio-relay.stderr.log" >&2
      exit 3
    fi
    # Recent PX4 builds run gz_bridge inside each owned PX4 process. Older
    # builds may still expose a separate process; record it when present, but
    # prove per-instance bridge readiness from each PX4 console either way.
    for bridge_pid in "${bridge_pids[@]}"; do
      bridge_args="$(tr '\0' ' ' <"/proc/$bridge_pid/cmdline")"
      bridge_instance="$(sed -n 's/.*--instance \([0-9][0-9]*\).*/\1/p' <<<"$bridge_args")"
      record_process "$bridge_pid" "px4-gz-bridge-$bridge_instance"
    done
    phase_ready=0
    for _ in $(seq 1 $((camera_aux_timeout_s * 10))); do
      if [[ -f "$camera_phase_ready_marker" ]]; then
        phase_ready=1
        break
      fi
      if ! kill -0 "$gazebo_pid" 2>/dev/null; then
        echo "Gazebo exited before camera phase evidence was ready" >&2
        exit 3
      fi
      sleep 0.1
    done
    if [[ "$phase_ready" -ne 1 ]]; then
      echo "camera phase evidence readiness timed out" >&2
      exit 3
    fi
    if ! env -u GALLIUM_DRIVER -u MESA_D3D12_DEFAULT_ADAPTER_NAME "${renderer_env[@]}" \
      PYTHONPATH="$repo_root/src" python3 "$repo_root/tools/attest_gazebo_renderer_wsl.py" \
      --profile "$renderer_profile" --gazebo-pid "$gazebo_pid" \
      --expected-depth-topics "$vehicle_count" \
      --phase-ready-marker "$camera_phase_ready_marker" \
      --output "$run_dir/renderer-attestation.json"; then
      echo "Gazebo renderer attestation failed" >&2
      exit 3
    fi
    if [[ "$capacity_mode" == 1 ]]; then
      PYTHONPATH="$repo_root/src:$repo_root" python3 - \
        "$capacity_ready_marker" "$run_dir" "$capacity_observer_pid_file" \
        "$capacity_subscriber_count" "$vehicle_count" "$camera_aux_timeout_s" <<'PY'
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from flydrones.drones.mavlink import MavlinkDrone
from tools.run_camera_render_capacity_trial_wsl import (
    _depth_topic,
    capacity_telemetry_ready,
    validate_depth_topic_connections,
)

ready_path = Path(sys.argv[1])
run_dir = Path(sys.argv[2])
observer_pid_file = Path(sys.argv[3])
subscriber_count = int(sys.argv[4])
vehicle_count = int(sys.argv[5])
observer_timeout_s = float(sys.argv[6])
deadline = time.monotonic() + observer_timeout_s
while not observer_pid_file.is_file() and time.monotonic() < deadline:
    time.sleep(0.05)
if not observer_pid_file.is_file():
    raise SystemExit("capacity observer PID file is missing after handoff")
observer_pid = int(observer_pid_file.read_text(encoding="utf-8").strip())
try:
    os.kill(observer_pid, 0)
except OSError as exc:
    raise SystemExit("capacity observer is not alive") from exc

raw = {}
for vehicle_id in range(vehicle_count):
    result = subprocess.run(
        ["gz", "topic", "-i", "-t", _depth_topic(vehicle_id)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"depth topic introspection failed for vehicle {vehicle_id}")
    raw[vehicle_id] = result.stdout
connections = validate_depth_topic_connections(raw, subscriber_count=subscriber_count)
connections["stage"] = "launcher-after-attestation"
connections["observer_pid"] = observer_pid
connections["raw"] = {str(key): value for key, value in raw.items()}
(run_dir / "depth-topic-connections-launcher.json").write_text(
    json.dumps(connections, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
if not connections["accepted"]:
    raise SystemExit("capacity depth subscriber topology rejected")

def sample(vehicle_id: int) -> dict:
    drone = MavlinkDrone(
        connection=f"udpin:0.0.0.0:{14540 + vehicle_id}",
        autopilot="px4",
    )
    drone.connect()
    deadline = time.monotonic() + 10.0
    telemetry = drone.telemetry()
    while time.monotonic() < deadline:
        telemetry = drone.telemetry()
        if capacity_telemetry_ready(telemetry):
            break
        time.sleep(0.05)
    if drone.m is not None:
        drone.m.close()
    return {
        "vehicle_id": vehicle_id,
        "estimator_healthy": telemetry.estimator_healthy,
        "armed": telemetry.armed,
        "landed": telemetry.landed,
    }

with concurrent.futures.ThreadPoolExecutor(max_workers=vehicle_count) as executor:
    states = list(executor.map(sample, range(vehicle_count)))
payload = {
    "schema": "flydrones-camera-capacity-ready-v1",
    "observer_pid": observer_pid,
    "subscriber_count": subscriber_count,
    "renderer_attestation_accepted": True,
    "px4_vehicle_count": len(states),
    "px4_all_healthy": all(item["estimator_healthy"] is True for item in states),
    "px4_all_disarmed": all(item["armed"] is False for item in states),
    "px4_all_landed": all(item["landed"] is True for item in states),
    "px4_states": states,
}
ready_path.parent.mkdir(parents=True, exist_ok=True)
with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=ready_path.parent, delete=False) as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
    temporary = Path(handle.name)
temporary.replace(ready_path)
if not (
    payload["px4_all_healthy"]
    and payload["px4_all_disarmed"]
    and payload["px4_all_landed"]
):
    raise SystemExit("PX4 capacity health/disarmed/landed gate failed")
PY
    fi
    trap - ERR INT TERM
    echo "$vehicle_count PX4 x500_depth_fly instances and $vehicle_count isolated depth topics are ready."
    echo "Gazebo renderer profile: $renderer_profile"
    echo "MAVLink ports start at 14540"
    echo "Logs: $run_dir"
    exit 0
  fi
  sleep 1
done

echo "PX4/Gazebo depth-camera startup timed out" >&2
gz topic -l 2>/dev/null | grep -E 'depth|x500_depth_fly' >&2 || true
for ((instance_id=0; instance_id<vehicle_count; instance_id++)); do
  tail -30 "$run_dir/instance_$instance_id/out.log" >&2 || true
  tail -30 "$run_dir/instance_$instance_id/err.log" >&2 || true
done
exit 3
