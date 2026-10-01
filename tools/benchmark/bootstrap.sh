#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bench_root="${FLY_EGO_BUILD_ROOT:-$HOME/fly-ego-benchmark}"
upstream="$bench_root/ego_ws/src/ego-planner-swarm"
commit=23a8d5a191711dd65633df689bd00f55d4dea8f9
mkdir -p "$bench_root/ego_ws/src" "$bench_root/logs"
if [[ ! -d "$upstream/.git" ]]; then
    git clone --branch ros2_version --single-branch \
        https://github.com/ZJU-FAST-Lab/ego-planner-swarm.git "$upstream"
fi
if [[ -n "$(git -C "$upstream" status --porcelain)" ]]; then
    echo 'Upstream checkout has modifications; refusing silent overwrite.' >&2
    exit 2
fi
git -C "$upstream" checkout --detach "$commit"
test "$(git -C "$upstream" rev-parse HEAD)" = "$commit"
docker build --progress=plain -f "$repo_root/tools/benchmark/Dockerfile.ego" \
    -t fly-ego-benchmark:humble "$bench_root/ego_ws" 2>&1 | tee "$bench_root/logs/build-ego.log"
docker image inspect fly-ego-benchmark:humble > "$bench_root/logs/image.json"
docker run --rm fly-ego-benchmark:humble | tee "$bench_root/logs/executables.txt"
