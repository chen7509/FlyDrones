"""One build-free, unqualified upstream consumer of the sealed recorded dataset."""

from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from pathlib import Path

from tools.benchmark import run_openvins_dataset_consumer as execution

ROOT = execution.ROOT
STUDY = ROOT / 'results/openvins-cached-candidate-consumer-dev-1701'
ARCHIVE = ROOT / 'evidence/openvins-offline-1701.zip'
ARCHIVE_SHA = '29fee032d5400108053cdfa5f010c90519a878ce3e5c46a1c549f29085dd0bb7'
DATASET_MANIFEST_SHA = '1f7ab4c651e505a51a2317e477ff019128523976a6e8ccd22f01568986fb1e3f'
MIN_MEMORY = 1024**3
IMU_HEADER = ['#timestamp [ns]', 'w_RS_S_x [rad s^-1]', 'w_RS_S_y [rad s^-1]',
              'w_RS_S_z [rad s^-1]', 'a_RS_S_x [m s^-2]', 'a_RS_S_y [m s^-2]', 'a_RS_S_z [m s^-2]']
RAW_NAMES = [*(f'gyro_rad[{i}]' for i in range(3)),
             *(f'accelerometer_m_s2[{i}]' for i in range(3))]


def microsecond_stamp(text):
    if not re.fullmatch(r'[1-9][0-9]*', text):
        raise ValueError('noncanonical timestamp')
    value = int(text)
    if value > 2**63 - 1 or value % 1000:
        raise ValueError('timestamp cannot be losslessly represented in microseconds')
    return value // 1000


def frame_partition(frames, imu):
    if not frames or not imu or any(b <= a for a, b in zip(frames, frames[1:])) or any(
        b <= a for a, b in zip(imu, imu[1:])
    ):
        raise ValueError('nonempty strictly increasing source streams required')
    return [{'source_index': i, 'frame_ns': stamp,
             'status': 'native_requested' if imu[0] <= stamp <= imu[-1] else 'imu_range_refused'}
            for i, stamp in enumerate(frames)]


def native_counts(stdout, frames, imu):
    found = re.findall(r'^frames=(\d+) imu_fed=(\d+) initialized_frames=(\d+)$', stdout, re.M)
    if len(found) != 1:
        raise ValueError('one actual native count record required')
    actual_frames, fed, initialized = map(int, found[0])
    if actual_frames != frames or not 0 <= fed <= imu or not 0 <= initialized <= frames:
        raise ValueError('native counts disagree with requested source')
    return {'native_frames': actual_frames, 'native_imu_fed': fed,
            'public_initialized_frames': initialized,
            'imu_unconsumed_tail_indices': list(range(fed, imu)), 'teacher_qualified': False}


def cached_admission():
    facts = execution.admission()
    return {'original_compiled_profile_observation': facts, 'minimum_available_bytes': MIN_MEMORY,
            'admitted': facts['windows_available'] >= MIN_MEMORY
            and facts['wsl']['available'] >= MIN_MEMORY and not facts['blocked_processes']
            and facts['docker_exit'] == 0 and not facts['docker_running'].strip()}


def rows(path, header):
    with path.open(encoding='utf8', newline='') as stream:
        reader = csv.reader(stream)
        if next(reader, None) != header:
            raise ValueError('source CSV header mismatch')
        result = list(reader)
    if any(len(row) != len(header) for row in result):
        raise ValueError('source CSV row width mismatch')
    return result


def prepare(output):
    if execution.digest(execution.MANIFEST) != DATASET_MANIFEST_SHA:
        raise ValueError('sealed manifest changed')
    verified = execution.verify_input()
    dataset = execution.DATASET
    metadata = json.loads((dataset / 'dataset.json').read_text(encoding='utf8'))
    cameras = rows(dataset / 'cam0/data.csv', ['#timestamp [ns]', 'filename'])
    imu = rows(dataset / 'imu0/data.csv', IMU_HEADER)
    camera_journal = [json.loads(x) for x in (dataset / 'camera-source.jsonl').read_text(encoding='utf8').splitlines()]
    journal = [json.loads(x) for x in (dataset / 'imu-source.jsonl').read_text(encoding='utf8').splitlines()]
    if (len(cameras) != len(camera_journal) or len(imu) != len(journal)
            or len(cameras) != metadata['camera_frames'] or len(imu) != metadata['imu_rows']):
        raise ValueError('sealed stream cardinality mismatch')
    timestamps = []
    for i, (row, raw) in enumerate(zip(imu, journal)):
        stamp = microsecond_stamp(row[0])
        if (raw['index'] != i or raw['reasons'] or raw['gyro_sample_ns'] != stamp * 1000
                or raw['accel_sample_ns'] != stamp * 1000
                or raw['source_identity'] != metadata['source_identity']
                or [float(x) for x in row[1:]] != [raw['raw'][name] for name in RAW_NAMES]):
            raise ValueError('candidate IMU differs from raw journal')
        timestamps.append(stamp * 1000)
    frame_times = []
    for i, (row, raw) in enumerate(zip(cameras, camera_journal)):
        stamp = microsecond_stamp(row[0]) * 1000
        name = f'rgb-frames/{stamp}.ppm'
        if (row[1] != f'{stamp}.png' or raw['index'] != i or raw['frame_ns'] != stamp
                or raw['path'] != name or raw['source_identity'] != metadata['source_identity']
                or execution.digest(dataset / 'inputs' / name) != raw['sha256']):
            raise ValueError('camera CSV/PPM differs from source journal')
        frame_times.append(stamp)
    ledger = frame_partition(frame_times, timestamps)
    if not any(x['status'] == 'native_requested' for x in ledger):
        raise ValueError('no overlapping source frames')
    output.mkdir(exist_ok=False)
    with (output / 'frames.csv').open('x', newline='', encoding='utf8') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['timestamp_ns', 'relative_ppm_path'])
        for item in ledger:
            if item['status'] == 'native_requested':
                writer.writerow([item['frame_ns'], f"rgb-frames/{item['frame_ns']}.ppm"])
    with (output / 'imu.csv').open('x', newline='', encoding='utf8') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['timestamp_us', 'gx', 'gy', 'gz', 'ax', 'ay', 'az'])
        writer.writerows([[microsecond_stamp(row[0]), *row[1:]] for row in imu])
    execution.write(output / 'frame-ledger.json', ledger)
    return {'verified': verified, 'frames_requested': sum(x['status'] == 'native_requested' for x in ledger),
            'source_frames': len(ledger), 'source_imu_rows': len(imu), 'source_identity': metadata['source_identity'],
            'bridge_sha256': {p.name: execution.digest(p) for p in output.iterdir()},
            'qualifications': False}


def execute(*, admission_record):
    if STUDY.exists():
        raise FileExistsError('cached study already reserved; follow actual handle only')
    first = cached_admission()
    execution.write(admission_record, first)
    if not first['admitted']:
        raise RuntimeError('cached runtime fresh admission refused; no dispatch')
    if execution.digest(ARCHIVE) != ARCHIVE_SHA:
        raise ValueError('archived native source/binary changed')
    execution.verify_input()
    STUDY.mkdir()
    execution.write(STUDY / 'first-admission.json', first)
    code = STUDY / 'code'
    code.mkdir()
    for path in [Path(__file__), ROOT / 'tools/benchmark/native_consumer_scope.py', Path(execution.__file__)]:
        (code / path.name).write_bytes(path.read_bytes())
    execution.write(STUDY / 'code-before.json', {p.name: execution.digest(p) for p in code.iterdir()})
    native = STUDY / 'native'
    native.mkdir()
    with zipfile.ZipFile(ARCHIVE) as archive:
        for name in ['runner-v3/offline_probe', 'runner-v3/offline_probe.cpp',
                     'config-v1/estimator_config.yaml', 'config-v1/kalibr_imu_chain.yaml',
                     'config-v1/kalibr_imucam_chain.yaml']:
            member = 'openvins-offline-1701/' + name
            target = native / Path(name).name
            target.write_bytes(archive.read(member))
    execution.wsl('chmod', 'u+x', execution.linux(native / 'offline_probe'))
    execution.write(STUDY / 'native-before.json', {p.name: execution.digest(p) for p in native.iterdir()})
    dependencies = execution.wsl('/usr/bin/env', '-u', 'LD_LIBRARY_PATH', '-u', 'LD_PRELOAD',
                                 '/usr/bin/ldd', execution.linux(native / 'offline_probe'))
    (STUDY / 'ldd.stdout').write_bytes(dependencies.stdout)
    (STUDY / 'ldd.stderr').write_bytes(dependencies.stderr)
    resolved = re.findall(r'^\s*libov_msckf_lib\.so => (\S+)', dependencies.stdout.decode(), re.M)
    if resolved != [execution.LIBRARY] or b'not found' in dependencies.stdout:
        raise ValueError('cached executable resolved library mismatch')
    binding = prepare(STUDY / 'bridge')
    execution.write(STUDY / 'binding.json', binding)
    second = cached_admission()
    execution.write(STUDY / 'second-admission.json', second)
    if not second['admitted']:
        raise RuntimeError('second cached runtime admission refused; no native dispatch')
    execution.verify_input()
    command = ['/usr/bin/env', '-u', 'LD_LIBRARY_PATH', '-u', 'LD_PRELOAD',
               execution.linux(native / 'offline_probe'), execution.linux(native / 'estimator_config.yaml'),
               execution.linux(STUDY / 'bridge'), execution.linux(execution.DATASET / 'inputs'),
               execution.linux(STUDY / 'states.csv')]
    execution.scoped(STUDY / 'run', command, label='cached-consume', memory=192 * 1024**2,
                     seconds=120, outer_seconds=150)
    counts = native_counts((STUDY / 'run/stdout.bin').read_text(encoding='utf8'),
                           binding['frames_requested'], binding['source_imu_rows'])
    state = rows(STUDY / 'states.csv', ['image_ns', 'initialized', 'state_timestamp_s',
                 'qx', 'qy', 'qz', 'qw', 'px', 'py', 'pz'])
    requested = [x['frame_ns'] for x in json.loads((STUDY / 'bridge/frame-ledger.json').read_text(encoding='utf8'))
                 if x['status'] == 'native_requested']
    if [int(row[0]) for row in state] != requested or sum(row[1] == '1' for row in state) != counts['public_initialized_frames']:
        raise ValueError('actual state rows disagree with bridge/native counts')
    for folder, manifest in [(native, 'native-before.json'), (code, 'code-before.json'),
                             (STUDY / 'bridge', None)]:
        expected = json.loads((STUDY / manifest).read_text(encoding='utf8')) if manifest else binding['bridge_sha256']
        if {p.name: execution.digest(p) for p in folder.iterdir()} != expected:
            raise ValueError('execution snapshot changed')
    execution.write(STUDY / 'completion.json', {'status': 'actual-cached-native-returned', **counts,
                     'input_after': execution.verify_input(), 'qualifications': False,
                     'ppm_consumed_png_not_consumed': True, 'lookahead': 'offline immediate-following IMU sample'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-once', action='store_true', required=True)
    parser.add_argument('--admission-record', type=Path, required=True,
                        help='Exclusive existing-parent JSON path, including refused admission facts')
    args = parser.parse_args()
    execute(admission_record=args.admission_record)
