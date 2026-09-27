#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="${repo_root}/native/camera_phase"
build_dir="${repo_root}/build/native-camera-phase"
run_tests=0
check_only=0
pkg_config_command="${PKG_CONFIG:-pkg-config}"

case "${1:-}" in
  --test) run_tests=1 ;;
  --check-dependencies) check_only=1 ;;
  "") ;;
  *) echo "usage: $0 [--test|--check-dependencies]" >&2; exit 64 ;;
esac

for package in gz-transport13 gz-msgs10; do
  if ! "${pkg_config_command}" --exists "${package}"; then
    echo "missing required pkg-config package: ${package}" >&2
    exit 3
  fi
done
if ! command -v cmake >/dev/null 2>&1; then
  echo "missing required command: cmake" >&2
  exit 3
fi
if [[ "${check_only}" -eq 1 ]]; then
  exit 0
fi

cmake -S "${source_dir}" -B "${build_dir}" -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON
cmake --build "${build_dir}" --parallel
if [[ "${run_tests}" -eq 1 ]]; then
  ctest --test-dir "${build_dir}" --output-on-failure
fi

executable="${build_dir}/flydrones_camera_phase_native"
if [[ ! -x "${executable}" ]]; then
  echo "native executable missing after build: ${executable}" >&2
  exit 3
fi
echo "executable=${executable}"
echo "sha256=$(sha256sum "${executable}" | awk '{print $1}')"
