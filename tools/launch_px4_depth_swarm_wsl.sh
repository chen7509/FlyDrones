#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
px4_root="${PX4_ROOT:-$HOME/PX4-Autopilot}"
build="$px4_root/build/px4_sitl_default"
run_dir="${FLYDRONES_PX4_RUN_DIR:-/tmp/flydrones-px4-five-depth}"
vehicle_count="${FLYDRONES_VEHICLE_COUNT:-5}"
vio_fault_profile="${FLYDRONES_VIO_FAULT_PROFILE:-}"
world_source="$repo_root/results/px4-sitl-five-depth/flydrones_forest.sdf"
world_target="$px4_root/Tools/simulation/gz/worlds/flydrones_forest.sdf"
model_root="$px4_root/Tools/simulation/gz/models"

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
if [[ -n "$vio_fault_profile" && -e "$run_dir" ]]; then
  echo "Fault-trial run directory already exists; refusing to overwrite: $run_dir" >&2
  exit 2
fi

if [[ -n "$vio_fault_profile" ]]; then
  mkdir -p "$run_dir/backups"
  touch "$run_dir/fault-mode"
  world_source="$run_dir/flydrones_forest.sdf"
  if [[ -e "$world_target" ]]; then
    cp -a "$world_target" "$run_dir/backups/world.sdf"
  fi
  for model in OakD-Lite-Fly x500_depth_fly; do
    if [[ -e "$model_root/$model" ]]; then
      cp -a "$model_root/$model" "$run_dir/backups/$model"
    fi
  done
fi
PYTHONPATH="$repo_root/src" python3 "$repo_root/tools/generate_px4_forest_world.py" --output "$world_source" --lane-spacing 2.0
cp "$world_source" "$world_target"
rm -rf "$model_root/OakD-Lite-Fly" "$model_root/x500_depth_fly"
cp -r "$repo_root/assets/gazebo/models/OakD-Lite-Fly" "$model_root/OakD-Lite-Fly"
cp -r "$repo_root/assets/gazebo/models/x500_depth_fly" "$model_root/x500_depth_fly"
if [[ -n "$vio_fault_profile" ]]; then
  python3 "$repo_root/tools/configure_gazebo_vio_model.py" "$model_root/x500_depth_fly/model.sdf"
fi

for port in 14580 14581 14582 14583 14584; do
  pids="$(ss -H -lunp "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u)"
  if [[ -n "$pids" ]]; then kill $pids 2>/dev/null || true; fi
done
pkill -9 -f "^$build/bin/px4 -i [0-4] -d $build/etc$" 2>/dev/null || true
pkill -9 -f '^px4-gz_bridge --instance [0-4] start -w flydrones_forest' 2>/dev/null || true
pkill -9 -f '^gz sim .*Tools/simulation/gz/worlds/flydrones_forest.sdf$' 2>/dev/null || true
sleep 2

if [[ -z "$vio_fault_profile" ]]; then rm -rf "$run_dir"; fi
mkdir -p "$run_dir"
if [[ -n "$vio_fault_profile" ]]; then
  nohup env PYTHONPATH="$repo_root/src" python3 "$repo_root/tools/relay_gazebo_vio.py" \
    --profile "$vio_fault_profile" --marker "$run_dir/fault-start.json" \
    --output "$run_dir/vio-relay.jsonl" --vehicle-count "$vehicle_count" \
    >"$run_dir/vio-relay.stdout.log" 2>"$run_dir/vio-relay.stderr.log" </dev/null &
  echo $! >"$run_dir/vio-relay.pid"
fi
poses=(-4.0 -2.0 0.0 2.0 4.0)
for ((instance_id=0; instance_id<vehicle_count; instance_id++)); do
  instance_dir="$run_dir/instance_$instance_id"
  mkdir -p "$instance_dir"
  ln -sf "$build/rootfs/gz_env.sh" "$instance_dir/gz_env.sh"
  extra_env=()
  if [[ "$instance_id" -gt 0 ]]; then extra_env+=(PX4_GZ_STANDALONE=1); fi
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
  if [[ "$instance_id" -eq 0 ]]; then sleep 7; else sleep 2; fi
done

for _ in $(seq 1 40); do
  running=0
  for pid_file in "$run_dir"/instance_*/pid; do
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then running=$((running + 1)); fi
  done
  depth_topics="$(gz topic -l 2>/dev/null | grep -c '/sensor/StereoOV7251/depth_image$' || true)"
  if [[ "$running" -eq "$vehicle_count" ]] && [[ "$depth_topics" -eq "$vehicle_count" ]]; then
    if [[ -n "$vio_fault_profile" ]] && ! kill -0 "$(cat "$run_dir/vio-relay.pid")" 2>/dev/null; then
      echo "VIO relay exited before PX4 startup completed" >&2
      cat "$run_dir/vio-relay.stderr.log" >&2
      exit 3
    fi
    echo "$vehicle_count PX4 x500_depth_fly instances and $vehicle_count isolated depth topics are ready."
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
