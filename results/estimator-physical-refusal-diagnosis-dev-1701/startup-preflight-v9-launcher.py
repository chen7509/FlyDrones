import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/mnt/c/Users/yuche/.codex/worktrees/FlyDrones/track-eligibility')
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from tools.benchmark.capture_disarmed_sensors import active_resources

EXPECTED_HEAD = '6ff824199685e57f1be374d62eb846369256ee57'
base = ROOT / 'results/estimator-physical-refusal-diagnosis-dev-1701'
study = base / 'study-v16'
destination = study / 'startup-preflight-v1'
dispatch_path = base / 'startup-preflight-v9-dispatch.json'
completion_path = base / 'startup-preflight-v9-completion.json'
output_path = base / 'startup-preflight-v9-output.txt'
head = (base / 'current-head-for-startup-v9.txt').read_text().strip()
manifest = json.loads((study / 'study-manifest.json').read_text())
prepare_audit_path = ROOT / 'results/heartbeat-sim-time-retry-preflight-dev-1701/study-v16-audit-v2-committed.json'
prepare_audit = json.loads(prepare_audit_path.read_text())
command = list(manifest['command'])
command[command.index('--output') + 1] = destination.as_posix()
command.append('--startup-preflight')
if head != EXPECTED_HEAD:
    raise SystemExit(f'unexpected committed head: {head}')
if destination.exists() or any(p.exists() for p in (dispatch_path, completion_path, output_path)):
    raise SystemExit('refusing existing startup-preflight evidence')
if prepare_audit.get('failures') or prepare_audit.get('prepare_qualified') is not True:
    raise SystemExit('prepare audit not qualified')
if manifest.get('future_destination') != (study / 'capture-v1').as_posix() or '--startup-preflight' in manifest['command']:
    raise SystemExit('physical declaration changed')
resources = active_resources()
if resources:
    raise SystemExit(f'active resources: {resources!r}')
def write_x(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True); stream.write('\n')
write_x(dispatch_path, {'schema':'capture-startup-preflight-dispatch-v1','command':command,'destination':destination.as_posix(),'head':head,'prepare_audit':prepare_audit_path.as_posix(),'resources_before':resources,'physical_run':False,'started_wall_ns':time.time_ns()})
with output_path.open('xb') as stream:
    completed = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
completion = {'schema':'capture-startup-preflight-completion-v1','returncode':completed.returncode,'destination':destination.as_posix(),'resources_after':active_resources(),'ended_wall_ns':time.time_ns(),'physical_run':False}
write_x(completion_path, completion)
print(json.dumps(completion, indent=2, sort_keys=True))
raise SystemExit(completed.returncode)