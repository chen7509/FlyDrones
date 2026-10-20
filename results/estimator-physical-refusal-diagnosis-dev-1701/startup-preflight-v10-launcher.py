import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/mnt/c/Users/yuche/.codex/worktrees/FlyDrones/track-eligibility")
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tools.benchmark.capture_disarmed_sensors import active_resources

EXPECTED_HEAD = "bddefaf505edff403fae8c12fa99a034e36b4f40"
base = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701"
study = base / "study-v18"
destination = study / "startup-preflight-v1"
dispatch_path = base / "startup-preflight-v10-dispatch.json"
completion_path = base / "startup-preflight-v10-completion.json"
output_path = base / "startup-preflight-v10-output.txt"
head = (base / "current-head-for-startup-v10.txt").read_text().strip()
manifest = json.loads((study / "study-manifest.json").read_text())
prepare_audit_path = ROOT / "results/causal-pair-sim-time-retry-preflight-dev-1701/study-v18-audit-v2-committed.json"
prepare_audit = json.loads(prepare_audit_path.read_text())
command = list(manifest["command"])
command[command.index("--output") + 1] = destination.as_posix()
command.append("--startup-preflight")

if head != EXPECTED_HEAD:
    raise SystemExit(f"unexpected committed head: {head}")
if destination.exists() or any(path.exists() for path in (dispatch_path, completion_path, output_path)):
    raise SystemExit("refusing existing startup-preflight evidence")
if prepare_audit.get("failures") or prepare_audit.get("prepare_qualified") is not True:
    raise SystemExit("prepare audit not qualified")
if manifest.get("future_destination") != (study / "capture-v1").as_posix() or "--startup-preflight" in manifest["command"]:
    raise SystemExit("physical declaration changed")
resources = active_resources()
if resources:
    raise SystemExit(f"active resources: {resources!r}")


def write_x(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


write_x(
    dispatch_path,
    {
        "schema": "capture-startup-preflight-dispatch-v1",
        "command": command,
        "destination": destination.as_posix(),
        "head": head,
        "prepare_audit": prepare_audit_path.as_posix(),
        "resources_before": resources,
        "physical_run": False,
        "started_wall_ns": time.time_ns(),
    },
)
with output_path.open("xb") as stream:
    completed = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
completion = {
    "schema": "capture-startup-preflight-completion-v1",
    "returncode": completed.returncode,
    "destination": destination.as_posix(),
    "resources_after": active_resources(),
    "ended_wall_ns": time.time_ns(),
    "physical_run": False,
}
write_x(completion_path, completion)
print(json.dumps(completion, indent=2, sort_keys=True))
raise SystemExit(completed.returncode)
