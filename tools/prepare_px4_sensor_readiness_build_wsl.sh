#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config="${1:-$repo_root/configs/px4_sensor_readiness.json}"
px4_root="${PX4_ROOT:-$HOME/PX4-Autopilot}"

readarray -t contract < <(python3 - "$config" "$repo_root" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1]).resolve()
repo_root = Path(sys.argv[2]).resolve()
value = json.loads(config_path.read_text(encoding="utf-8"))
patch = (repo_root / value["px4_patch"]).resolve()
try:
    patch.relative_to(repo_root)
except ValueError as exc:
    raise SystemExit("PX4 patch must remain inside the FlyDrones repository") from exc
for item in (
    value["px4_revision"],
    str(patch),
    value["px4_patch_sha256"],
    value["px4_vehicle_imu_sha256"],
    value["px4_build_name"],
):
    print(item)
PY
)
expected_revision="${contract[0]}"
patch_path="${contract[1]}"
expected_patch_sha256="${contract[2]}"
expected_vehicle_imu_sha256="${contract[3]}"
build_name="${contract[4]}"
vehicle_imu="$px4_root/src/modules/sensors/vehicle_imu/VehicleIMU.cpp"
build="$px4_root/build/$build_name"
attestation="$build/.flydrones-sensor-readiness-build.json"

if [[ "$build_name" != "px4_sitl_nolockstep" ]]; then
  echo "sensor-readiness requires px4_sitl_nolockstep" >&2
  exit 2
fi
if [[ "$(git -C "$px4_root" rev-parse HEAD)" != "$expected_revision" ]]; then
  echo "PX4 revision differs from the frozen sensor-readiness contract" >&2
  exit 2
fi
if [[ "$(sha256sum "$patch_path" | awk '{print $1}')" != "$expected_patch_sha256" ]]; then
  echo "PX4 patch hash differs from the frozen sensor-readiness contract" >&2
  exit 2
fi

if git -C "$px4_root" apply --check "$patch_path" 2>/dev/null; then
  git -C "$px4_root" apply "$patch_path"
elif ! git -C "$px4_root" apply --reverse --check "$patch_path" 2>/dev/null; then
  echo "PX4 source is neither unpatched nor the expected patched state" >&2
  exit 2
fi
if [[ "$(sha256sum "$vehicle_imu" | awk '{print $1}')" != "$expected_vehicle_imu_sha256" ]]; then
  echo "VehicleIMU.cpp hash differs from the frozen patched source" >&2
  exit 2
fi

make -C "$px4_root" "$build_name"
if ! grep -Fxq '#define CONFIG_BOARD_NOLOCKSTEP 1' "$build/px4_boardconfig.h"; then
  echo "PX4 build does not prove CONFIG_BOARD_NOLOCKSTEP" >&2
  exit 2
fi

python3 - "$attestation" "$build_name" "$expected_revision" "$expected_patch_sha256" \
  "$expected_vehicle_imu_sha256" "$build/bin/px4" "$build/px4_boardconfig.h" <<'PY'
import hashlib
import json
import sys
import tempfile
from pathlib import Path

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

target = Path(sys.argv[1])
payload = {
    "schema": "flydrones-px4-build-attestation-v1",
    "build_name": sys.argv[2],
    "px4_revision": sys.argv[3],
    "px4_patch_sha256": sys.argv[4],
    "vehicle_imu_sha256": sys.argv[5],
    "binary_sha256": sha256(Path(sys.argv[6])),
    "boardconfig_sha256": sha256(Path(sys.argv[7])),
    "nolockstep": True,
}
target.parent.mkdir(parents=True, exist_ok=True)
with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
    temporary = Path(handle.name)
temporary.replace(target)
PY

cat "$attestation"
