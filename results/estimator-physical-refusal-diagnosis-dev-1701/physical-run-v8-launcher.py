import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/mnt/c/Users/yuche/.codex/worktrees/FlyDrones/track-eligibility')
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from tools.benchmark.capture_disarmed_sensors import active_resources

EXPECTED_HEAD = 'ed82c4ae7e1e13cbaf3521fa85953ef6643c7aab'
EXPECTED_ARCHIVE_SHA256 = '955c914bdc55884a804e532f839d369ee41a195ec3411cbd2a272ad359b27f9b'
BASE = ROOT / 'results/estimator-physical-refusal-diagnosis-dev-1701'
STUDY = BASE / 'study-v16'
DESTINATION = STUDY / 'capture-v1'
DISPATCH = BASE / 'physical-run-v8-dispatch.json'
COMPLETION = BASE / 'physical-run-v8-completion.json'
OUTPUT = BASE / 'physical-run-v8-output.txt'
HEAD_FILE = BASE / 'current-head-for-physical-v8.txt'
PACKAGE_AUDIT = ROOT / 'results/heartbeat-sim-time-retry-preflight-dev-1701/study-v16-audit-v4-physical-boundary.json'
STARTUP_AUDIT = ROOT / 'results/heartbeat-sim-time-retry-preflight-dev-1701/study-v16-startup-audit-v1.json'
CORRECTION_AUDIT = ROOT / 'results/heartbeat-simulation-time-readiness-dev-1701/fixed-evidence-audit.json'
ARCHIVE = ROOT / 'evidence/heartbeat-simulation-time-readiness-dev-1701.zip'

def read(path):
    value=json.loads(path.read_text());
    if type(value) is not dict: raise ValueError(f'object required: {path}')
    return value

def validate():
    head=HEAD_FILE.read_text().strip()
    if head != EXPECTED_HEAD: raise ValueError(f'unexpected head: {head}')
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != EXPECTED_ARCHIVE_SHA256: raise ValueError('archive drift')
    package, startup, correction = read(PACKAGE_AUDIT), read(STARTUP_AUDIT), read(CORRECTION_AUDIT)
    if package.get('prepare_qualified') is not True or package.get('failures') != []: raise ValueError('package audit')
    if startup.get('startup_preflight_qualified') is not True or startup.get('failures') != [] or startup.get('head') != '6ff824199685e57f1be374d62eb846369256ee57': raise ValueError('startup audit')
    if correction.get('qualified') is not True or correction.get('failures') != []: raise ValueError('correction audit')
    manifest=read(STUDY/'study-manifest.json'); command=list(manifest['command']); expected=DESTINATION.as_posix()
    if manifest.get('future_destination') != expected or '--output' not in command or command[command.index('--output')+1] != expected or '--startup-preflight' in command: raise ValueError('manifest command')
    existing=[str(p) for p in (DESTINATION,DISPATCH,COMPLETION,OUTPUT) if p.exists()]
    if existing: raise FileExistsError(existing)
    resources=active_resources()
    if resources: raise RuntimeError(f'active resources: {resources!r}')
    return command, {'head':head,'destination':expected,'archive_sha256':EXPECTED_ARCHIVE_SHA256,'resources_before':resources}

def write_x(path,value):
    with path.open('x') as stream: json.dump(value,stream,indent=2,sort_keys=True); stream.write('\n')

def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument('--check-only',action='store_true'); args=parser.parse_args(argv)
    command,checked=validate()
    if args.check_only:
        print(json.dumps({'schema':'physical-run-v8-check-v1','qualified':True,**checked},indent=2)); return 0
    write_x(DISPATCH,{'schema':'estimator-physical-run-dispatch-v4','study':STUDY.as_posix(),'destination':checked['destination'],'command':command,'head':checked['head'],'package_audit':PACKAGE_AUDIT.as_posix(),'startup_audit':STARTUP_AUDIT.as_posix(),'correction_audit':CORRECTION_AUDIT.as_posix(),'archive':ARCHIVE.as_posix(),'archive_sha256':checked['archive_sha256'],'resources_before':checked['resources_before'],'single_actual_attempt':True,'physical_run':True,'started_wall_ns':time.time_ns()})
    with OUTPUT.open('xb') as stream:
        completed=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=False)
    completion={'schema':'estimator-physical-run-completion-v4','returncode':completed.returncode,'destination':checked['destination'],'destination_exists':DESTINATION.exists(),'resources_after':active_resources(),'ended_wall_ns':time.time_ns(),'physical_run':True}
    write_x(COMPLETION,completion); print(json.dumps(completion,indent=2,sort_keys=True)); return completed.returncode

if __name__=='__main__': raise SystemExit(main())