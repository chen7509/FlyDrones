"""One isolated cached-library consumer study; no simulator or flight authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shlex
import subprocess
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT/'results/camera-px4-imu-dataset-producer-dev-1701/real-export-v2'
MANIFEST = ROOT/'evidence/camera-px4-imu-dataset-producer-dev-1701.sha256.json'
SOURCE = '/home/yuchen7509/flydrones-upstream/open_vins'
PIN = '69488123ed9362dd44b6f28e7f4680abbff1442b'
LIBRARY = SOURCE+'/ov_msckf/build/libov_msckf_lib.so'
LIB_SHA = 'ef649cc55d9d4471dbf9e549561a877752a48ae08d568a3433e157cb8e747b45'
MIN_MEMORY = 2*1024**3
STUDY = ROOT/'results/openvins-candidate-dataset-consumer-dev-1701'
CONFIG_SOURCE = ROOT/'results/openvins-candidate-dataset-consumer-research-dev-1701/openvins-offline-1701/config-v1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x', encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def linux(path):
    p = path.resolve()
    if p.drive.lower() != 'c:':
        raise ValueError('study requires declared C-drive path')
    return '/mnt/c/'+p.as_posix()[3:]


def wsl(*argv, check=True):
    p = subprocess.run(['wsl', '-d', 'Ubuntu', '--', *argv], capture_output=True)
    if check and p.returncode:
        raise RuntimeError(f'WSL command refused: {argv!r}, exit {p.returncode}, stderr {p.stderr.hex()}')
    return p


def heavy_process(process):
    name = (process['name'] or '').lower().removesuffix('.exe')
    command = process['cmdline']
    command = command if isinstance(command, str) else ' '.join(command or [])
    if name in {'px4', 'gz', 'gzserver', 'gzclient', 'gazebo', 'g++', 'gcc', 'c++',
                'cc1plus', 'cmake', 'make', 'ninja', 'clang', 'clang++', 'cl', 'msbuild',
                'openvins', 'open_vins'}:
        return True
    return (name not in {'git', 'ps', 'systemctl', 'sha256sum', 'readelf', 'ldd'}
            and any(x in command.lower() for x in ('openvins', 'open_vins'))
            or 'python' in name and any(x in command for x in ('-m pytest', 'run_curriculum.py', 'train_stage')))


def admission():
    script = """import pathlib,json,os
mem={a:b for a,b in (line.split(':',1) for line in pathlib.Path('/proc/meminfo').read_text().splitlines())}
rows=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit() or int(p.name) in (os.getpid(),os.getppid()):continue
 try:
  name=(p/'comm').read_text().strip(); cmd=(p/'cmdline').read_bytes().replace(b'\\0',b' ').decode(errors='replace')
  rows.append({'pid':int(p.name),'name':name,'cmdline':cmd})
 except OSError:pass
print(json.dumps({'available':int(mem['MemAvailable'].split()[0])*1024,'processes':rows}))
"""
    observed = wsl('/usr/bin/python3', '-c', script)
    data = json.loads(observed.stdout)
    own = {os.getpid(), *(p.pid for p in psutil.Process().parents())}
    windows = [{'pid': p.pid, **p.info} for p in psutil.process_iter(['name', 'cmdline']) if p.pid not in own]
    blocked = [p for p in [*data['processes'], *windows] if heavy_process(p)]
    docker = subprocess.run(['docker', 'ps', '--no-trunc', '--format', '{{json .}}'], capture_output=True)
    # Use actual argv for classification, but do not publish unrelated argv/secrets.
    def identity(p):
        command = p['cmdline'] if isinstance(p['cmdline'], str) else ' '.join(p['cmdline'] or [])
        return {'pid': p['pid'], 'name': p['name'], 'argv_sha256': hashlib.sha256(command.encode()).hexdigest()}
    facts = {'windows_available': psutil.virtual_memory().available,
             'wsl': {'available': data['available'], 'processes': [identity(p) for p in data['processes']]},
             'windows_processes': [identity(p) for p in windows], 'blocked_processes': [identity(p) for p in blocked],
             'docker_exit': docker.returncode, 'docker_running': docker.stdout.decode(errors='replace'),
             'wsl_stderr_hex': observed.stderr.hex()}
    facts['admitted'] = (facts['windows_available'] >= MIN_MEMORY and data['available'] >= MIN_MEMORY
                         and not blocked and docker.returncode == 0 and not docker.stdout.strip())
    return facts


def verify_input():
    manifest = json.loads(MANIFEST.read_text(encoding='utf8'))
    prefix = DATASET.relative_to(ROOT).as_posix()+'/'
    members = [x for x in manifest['members'] if x['path'].startswith(prefix)]
    if not members:
        raise ValueError('dataset missing from sealed manifest')
    for row in members:
        p = ROOT/row['path']
        if not p.resolve().is_relative_to(DATASET.resolve()) or p.is_symlink() or digest(p) != row['sha256']:
            raise ValueError('sealed dataset changed')
    completion = json.loads((DATASET/'completion.json').read_text(encoding='utf8'))
    if (completion['status'] != 'file-dataset-production-complete'
            or completion['candidate_imu_csv_emitted'] is not True
            or completion['ulog_bytes_bound_by_reader'] is not True):
        raise ValueError('candidate source not complete/bound')
    pin = wsl('git', '-C', SOURCE, 'rev-parse', 'HEAD').stdout.decode().strip()
    status = wsl('git', '-C', SOURCE, 'status', '--porcelain').stdout
    sha = wsl('sha256sum', LIBRARY).stdout.decode().split()[0]
    if pin != PIN or status or sha != LIB_SHA:
        raise ValueError('pinned clean source/library mismatch')
    return {'members': len(members), 'source_pin': pin, 'source_status': status.decode(),
            'library_sha256': sha, 'source_clock_calibration_teacher_training_flight_qualified': False}


def scoped(output, argv, *, label, memory, seconds, outer_seconds=None):
    output.mkdir(parents=True, exist_ok=False)
    unit = 'fly-openvins-dataset-'+label+'-'+secrets.token_hex(12)+'.scope'
    before = wsl('systemctl', '--user', 'show', unit, '--property=LoadState', '--property=ActiveState', check=False)
    if b'LoadState=not-found' not in before.stdout:
        raise ValueError('owned scope already exists or unknown')
    profile = {'unit': unit, 'output': linux(output), 'argv': argv, 'memory': memory, 'seconds': seconds}
    write(output/'profile.json', profile)
    command = ['wsl', '-d', 'Ubuntu', '--', '/usr/bin/systemd-run', '--user', '--scope',
               '--unit='+unit.removesuffix('.scope'), '--property=MemoryMax='+str(memory),
               '--property=MemorySwapMax=0', '--property=CPUQuota=100%', '--property=TasksMax=64',
               '--property=RuntimeMaxSec='+str(seconds), '--property=TimeoutStopSec=5s',
               '/usr/bin/env', 'OMP_NUM_THREADS=1', 'OPENBLAS_NUM_THREADS=1', 'MKL_NUM_THREADS=1',
               '/usr/bin/python3', linux(output.parent/'code/native_consumer_scope.py')
               if (output.parent/'code/native_consumer_scope.py').exists()
               else linux(ROOT/'tools/benchmark/native_consumer_scope.py'), linux(output/'profile.json')]
    with (output/'launcher.stdout').open('xb') as stdout, (output/'launcher.stderr').open('xb') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        write(output/'launcher.json', {'pid': process.pid, 'command': command})
        print(f'{label} launcher pid={process.pid} unit={unit}', flush=True)
        try:
            code = process.wait(timeout=outer_seconds if outer_seconds is not None else seconds+30)
        except subprocess.TimeoutExpired:
            if not (output/'inside-before.json').exists():
                write(output/'timeout-ownership-unknown.json', {'launcher_pid': process.pid,
                      'launcher_exit_observed': process.poll(), 'unit': unit, 'owned_group_released': None,
                      'reason': 'inside identity absent; residual unknown; no unowned stop'})
                finish_owned_launcher(output, process)
                raise RuntimeError('timeout ownership unknown; residual recorded') from None
            inside = json.loads((output/'inside-before.json').read_text(encoding='utf8'))
            try:
                stop_owned(output, unit, inside, 'timeout-stop.json')
                code = process.wait(timeout=15)
            except (RuntimeError, subprocess.TimeoutExpired):
                finish_owned_launcher(output, process)
                raise
    if not (output/'inside-before.json').exists():
        write(output/'launcher-completion.json', {'exit_code': code, 'unit': unit,
              'inside_observed': False, 'owned_group_released': None, 'qualification': False})
        raise RuntimeError('scope did not reach its verified command; retained launcher failure')
    inside = json.loads((output/'inside-before.json').read_text(encoding='utf8'))
    group = inside['cgroup']
    if not group.endswith('/'+unit) or '..' in group.split('/'):
        raise ValueError('cleanup cgroup identity invalid')
    def observe():
        observation = wsl('/usr/bin/python3', '-c',
            "import pathlib,json; p=pathlib.Path("+repr('/sys/fs/cgroup'+group)+"); print(json.dumps({'exists':p.exists(),'events':(p/'cgroup.events').read_text() if p.exists() else None,'pids':(p/'cgroup.procs').read_text() if p.exists() else None}))")
        return json.loads(observation.stdout)
    release = observe()
    released = not release['exists'] or (not release['pids'].strip() and 'populated 0' in release['events'])
    if not released:
        write(output/'cleanup-before-stop.json', release)
        stop_owned(output, unit, inside, 'residual-stop.json')
        release = observe()
        released = not release['exists'] or (not release['pids'].strip() and 'populated 0' in release['events'])
    result = {'exit_code': code, 'unit': unit, 'cgroup': group, 'cleanup': release,
              'owned_group_released': released, 'escaped_descendants_closure': 'unknown', 'qualification': False}
    write(output/'launcher-completion.json', result)
    if code or not released:
        raise RuntimeError('native phase failed or owned group not released')
    return result


def finish_owned_launcher(output, process):
    """Bound cleanup of this Popen only; never infer that its Linux scope stopped."""
    observation = {'pid': process.pid, 'before': process.poll(), 'scope_release': 'unknown'}
    try:
        if observation['before'] is None:
            process.terminate()
            observation['terminate_sent'] = True
        try:
            observation['exit_code'] = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            observation['kill_sent'] = True
            observation['exit_code'] = process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired) as error:
        observation['cleanup_error'] = type(error).__name__
        observation['exit_code'] = process.poll()
    write(output/'owned-launcher-timeout-cleanup.json', observation)


def stop_owned(output, unit, inside, name):
    props = wsl('systemctl', '--user', 'show', unit, '--property=InvocationID',
                '--property=ControlGroup', check=False)
    actual = dict(x.split('=', 1) for x in props.stdout.decode().splitlines() if '=' in x)
    expected = dict(x.split('=', 1) for x in inside['systemd_properties'].splitlines() if '=' in x)
    owned = (props.returncode == 0 and expected.get('InvocationID')
             and actual.get('InvocationID') == expected['InvocationID']
             and actual.get('ControlGroup') == inside['cgroup']
             and inside['cgroup'].endswith('/'+unit))
    if not owned:
        write(output/name, {'ownership_confirmed': False, 'properties': actual,
                           'owned_group_released': None, 'residual': 'unknown; no unowned stop'})
        raise RuntimeError('scope ownership unknown; residual recorded')
    stopped = wsl('systemctl', '--user', 'stop', unit, check=False)
    write(output/name, {'ownership_confirmed': True, 'invocation': expected['InvocationID'],
                       'cgroup': inside['cgroup'], 'exit': stopped.returncode,
                       'stdout_hex': stopped.stdout.hex(), 'stderr_hex': stopped.stderr.hex()})
    if stopped.returncode:
        raise RuntimeError('owned scope stop failed; residual unknown')


def execute():
    if STUDY.exists():
        raise FileExistsError('one-shot consumer study already exists')
    first = admission()
    if not first['admitted']:
        raise RuntimeError('fresh resource/process admission refused; no build dispatch')
    inputs = verify_input()
    STUDY.mkdir()
    write(STUDY/'preflight.json', {'first': first, 'input': inputs})
    code = STUDY/'code'
    code.mkdir()
    sources = [ROOT/'tools/benchmark/gpl/openvins_dataset_consumer.cpp',
               ROOT/'tools/benchmark/gpl/openvins_dataset_io.h',
               ROOT/'tools/benchmark/native_consumer_scope.py', Path(__file__)]
    for p in sources:
        (code/p.name).write_bytes(p.read_bytes())
    hashes = {p.name: {'original': digest(p), 'snapshot': digest(code/p.name)} for p in sources}
    if any(x['original'] != x['snapshot'] for x in hashes.values()):
        raise RuntimeError('source changed during snapshot')
    write(STUDY/'code-before.json', hashes)
    config = STUDY/'config'
    config.mkdir()
    for name in ('estimator_config.yaml', 'kalibr_imu_chain.yaml', 'kalibr_imucam_chain.yaml'):
        (config/name).write_bytes((CONFIG_SOURCE/name).read_bytes())
    write(STUDY/'config-before.json', {p.name: digest(p) for p in config.iterdir()})
    src = code
    flags = shlex.split(wsl('pkg-config', '--cflags', '--libs', 'opencv4').stdout.decode())
    binary = STUDY/'openvins_dataset_consumer'
    command = ['/usr/bin/g++', '-std=c++17', '-O2', '-DROS_AVAILABLE=0', '-DENABLE_ARUCO_TAGS=0',
               '-I'+linux(src), '-I'+SOURCE+'/ov_msckf/src', '-I'+SOURCE+'/ov_core/src',
               '-I'+SOURCE+'/ov_init/src', '-I/usr/include/eigen3',
               linux(src/'openvins_dataset_consumer.cpp'), '-L'+SOURCE+'/ov_msckf/build',
               '-Wl,-rpath,'+SOURCE+'/ov_msckf/build', '-lov_msckf_lib', *flags, '-o', linux(binary)]
    second = admission()
    write(STUDY/'build-admission.json', second)
    if not second['admitted']:
        raise RuntimeError('second build resource admission refused')
    scoped(STUDY/'build', command, label='build', memory=1024**3, seconds=300)
    runtime = admission()
    write(STUDY/'runtime-admission.json', runtime)
    if not runtime['admitted']:
        raise RuntimeError('fresh consumer admission refused; binary retained, no runtime dispatch')
    verify_input()
    write(STUDY/'binary-before.json', {'sha256': digest(binary)})
    scoped(STUDY/'run', [linux(binary), linux(config/'estimator_config.yaml'), linux(DATASET),
                         linux(STUDY/'states.csv')], label='consume', memory=512*1024**2, seconds=120)
    code_after = {p.name: digest(p) for p in code.iterdir()}
    config_after = {p.name: digest(p) for p in config.iterdir()}
    if (any(code_after[k] != v['snapshot'] for k, v in hashes.items())
            or config_after != json.loads((STUDY/'config-before.json').read_text(encoding='utf8'))):
        raise RuntimeError('execution snapshots changed')
    write(STUDY/'completion.json', {'status': 'offline-native-consumer-returned',
          'binary_sha256_after': digest(binary), 'input_after': verify_input(),
          'code_snapshot_after': code_after, 'original_code_after': {p.name: digest(p) for p in sources},
          'config_after': config_after,
          'source_clock_calibration_teacher_fusion_training_flight_qualified': False})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-once', action='store_true', required=True)
    parser.parse_args()
    execute()
