"""Once-only pinned Kalibr native detector study; no sensor/flight authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.benchmark.run_openvins_dataset_consumer import (
    ROOT,
    admission,
    digest,
    linux,
    scoped,
    write,
    wsl,
)

PIN = '1f60227442d25e36365ef5f72cd80b9666d73467'
RESEARCH = ROOT/'results/target-excitation-research-dev-1701'
SOURCE_MANIFEST = RESEARCH/'pinned-detector-manifest.json'
STUDY = ROOT/'results/kalibr-native-target-consumption-dev-1701'
INPUT = ROOT/'results/aprilgrid-production-research-dev-1701/actual-target-v2/aprilgrid.png'
INPUT_SHA = '3f7fbfd01da1dc091aa9d7957d3e6e8603d596ed7a5bed2af08d1c525235b732'
SOURCE_MANIFEST_SHA = '726504cf412e49dc0e172251f8bc43e167d2e6c0c7c41b0ac85342a0de3d0ba5'
MIN_RESERVE = 1024**3


def admitted(facts):
    return (facts['windows_available'] >= MIN_RESERVE
            and facts['wsl']['available'] >= MIN_RESERVE
            and not facts['blocked_processes'] and facts['docker_exit'] == 0
            and not facts['docker_running'].strip())


def verify_sources():
    # Manifest identity is frozen at research completion, before build dispatch.
    if digest(SOURCE_MANIFEST) != SOURCE_MANIFEST_SHA:
        raise ValueError('pinned source manifest changed')
    data = json.loads(SOURCE_MANIFEST.read_text(encoding='utf8'))
    if data['pin'] != PIN or len(data['members']) != 40:
        raise ValueError('pinned source selection mismatch')
    for row in data['members']:
        path = ROOT/row['path']
        if path.is_symlink() or digest(path) != row['sha256']:
            raise ValueError('pinned source bytes changed')
    if INPUT.is_symlink() or digest(INPUT) != INPUT_SHA:
        raise ValueError('sealed target changed')
    return data


def execute_once(record: Path):
    if STUDY.exists() or STUDY.is_symlink():
        raise FileExistsError('study consumed; no retry')
    first = admission()
    write(Path(record), {'facts': first, 'new_independent_admitted': admitted(first),
                         'original_reserves_unchanged': True})
    if not admitted(first):
        raise RuntimeError('first resource gate refused before study/native')
    selected = verify_sources()
    STUDY.mkdir(exist_ok=False)
    try:
        code = STUDY/'code'
        code.mkdir()
        frozen = {}
        for row in selected['members']:
            source = ROOT/row['path']
            relative = source.relative_to(RESEARCH/'pinned-detector')
            target = code/'upstream'/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            if digest(target) != row['sha256']:
                raise ValueError('source changed during copy')
            frozen[target.relative_to(STUDY).as_posix()] = digest(target)
        for source in [Path(__file__), ROOT/'tools/benchmark/native/kalibr_target_detector.cpp',
                       ROOT/'tools/benchmark/native_consumer_scope.py',
                       ROOT/'tools/benchmark/run_openvins_dataset_consumer.py',
                       ROOT/'third_party/kalibr-aprilgrid/LICENSE', ROOT/'third_party/kalibr-aprilgrid/NOTICE.txt']:
            target = code/source.name
            target.write_bytes(source.read_bytes())
            frozen[target.relative_to(STUDY).as_posix()] = digest(target)
        (STUDY/'input.png').write_bytes(INPUT.read_bytes())
        if digest(STUDY/'input.png') != INPUT_SHA:
            raise ValueError('target changed during copy')
        write(STUDY/'source-before.json', {'pin': PIN, 'files': frozen, 'input': INPUT_SHA})
        commands = []
        sources = sorted((code/'upstream/src').glob('*.cc'))+[code/'kalibr_target_detector.cpp']
        flags = ['-std=c++11', '-O3', '-fPIC', '-I'+linux(code/'upstream/include'),
                 '-I/usr/include/opencv4', '-I/usr/include/eigen3']
        objects = []
        for source in sources:
            obj = STUDY/(source.stem+'.o')
            commands.append(['/usr/bin/g++', *flags, '-c', linux(source), '-o', linux(obj)])
            objects.append(linux(obj))
        binary = STUDY/'kalibr_target_detector'
        commands.append(['/usr/bin/g++', *objects, '-lopencv_imgcodecs', '-lopencv_imgproc',
                         '-lopencv_calib3d', '-lopencv_core', '-o', linux(binary)])
        write(STUDY/'build-commands.json', {'commands': commands})
        builder = ('import json,subprocess,sys; '
                   'commands=json.load(open(sys.argv[1]))["commands"]; '
                   '[(print(json.dumps(c),flush=True),subprocess.run(c,check=True)) for c in commands]')
        second = admission()
        write(STUDY/'build-admission.json', second)
        if not admitted(second):
            raise RuntimeError('second resource gate refused; study retained')
        build_result = scoped(STUDY/'build', ['/usr/bin/python3', '-c', builder,
                              linux(STUDY/'build-commands.json')], label='kalibr-target-build',
                              memory=512*1024**2, seconds=300, outer_seconds=330)
        dependencies = wsl('ldd', linux(binary))
        write(STUDY/'binary-before.json', {'sha256': digest(binary),
                                          'ldd': dependencies.stdout.decode(),
                                          'ldd_stderr_hex': dependencies.stderr.hex()})
        third = admission()
        write(STUDY/'runtime-admission.json', third)
        if not admitted(third):
            raise RuntimeError('runtime gate refused; binary retained')
        if any(digest(STUDY/name) != sha for name, sha in frozen.items()) or digest(STUDY/'input.png') != INPUT_SHA:
            raise ValueError('frozen execution input changed')
        run_result = scoped(STUDY/'run', [linux(binary), linux(STUDY/'input.png')],
                            label='kalibr-target-detect', memory=256*1024**2,
                            seconds=30, outer_seconds=60)
        if any(digest(STUDY/name) != sha for name, sha in frozen.items()) or digest(STUDY/'input.png') != INPUT_SHA:
            raise ValueError('frozen execution bytes changed')
        result = {'build': build_result, 'run': run_result, 'binary_sha256': digest(binary),
                  'source_clock_calibration_accuracy_teacher_fusion_training_flight': False}
        write(STUDY/'completion.json', result)
        return result
    except BaseException as error:
        write(STUDY/'failure.json', {'type': type(error).__name__, 'message': str(error),
                                    'retry': 'consumed; no rerun', 'qualification': False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-once', action='store_true', required=True)
    parser.add_argument('--admission-record', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(execute_once(args.admission_record), indent=2))


if __name__ == '__main__':
    main()
