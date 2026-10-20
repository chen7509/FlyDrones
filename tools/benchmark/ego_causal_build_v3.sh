#!/usr/bin/env bash
set -Eeo pipefail

out=/out
source_dir=/ego_ws/src/ego-planner-swarm
expected_commit=23a8d5a191711dd65633df689bd00f55d4dea8f9
expected_patch=bcf739842f3868fb082efce4a9a82609a7d5eb0833dea6c39e80ed9c57433fe9

finish() {
  local status=$?
  printf '%s\n' "$status" > "$out/container-exit-code.txt"
  if [ -d /ego_ws/log ]; then
    tar -czf "$out/colcon-logs.tgz" -C /ego_ws log || true
  fi
  git -C "$source_dir" status --porcelain=v1 > "$out/source-status-after.txt" || true
  exit "$status"
}
trap finish EXIT

test "$(git -C "$source_dir" rev-parse HEAD)" = "$expected_commit"
test -z "$(git -C "$source_dir" status --porcelain=v1)"
test "$(sha256sum /patch.diff | cut -d' ' -f1)" = "$expected_patch"
git -C "$source_dir" apply --check /patch.diff
find -L /ego_ws/install/plan_env /ego_ws/install/ego_planner -type f \
  \( -name 'libplan_env.so' -o -name 'ego_planner_node' -o -name 'traj_server' \) \
  -print0 | xargs -0 -r sha256sum > "$out/binaries-before.txt"
git -C "$source_dir" apply /patch.diff
git -C "$source_dir" -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check
git -C "$source_dir" diff --binary > "$out/applied-source.diff"

source /opt/ros/humble/setup.bash
source /ego_ws/install/setup.bash
set -u
export MAKEFLAGS=-j1
export CMAKE_BUILD_PARALLEL_LEVEL=1
cd /ego_ws
timeout --signal=TERM --kill-after=10s 1200s colcon build \
  --symlink-install --executor sequential --parallel-workers 1 \
  --packages-select plan_env ego_planner \
  --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF

find -L /ego_ws/install/plan_env /ego_ws/install/ego_planner -type f \
  \( -name 'libplan_env.so' -o -name 'ego_planner_node' -o -name 'traj_server' \) \
  -print0 | xargs -0 -r sha256sum > "$out/binaries-after.txt"
test -s "$out/binaries-after.txt"
sha256sum /patch.diff "$out/applied-source.diff" > "$out/source-digests.txt"
