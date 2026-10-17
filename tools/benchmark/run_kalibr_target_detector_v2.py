"""New once-only header-fix continuation; the failed v1 attempt stays consumed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.benchmark.run_kalibr_target_detector import INPUT_SHA, ROOT, admitted, verify_sources
from tools.benchmark.run_openvins_dataset_consumer import admission, digest, linux, scoped, write, wsl

STUDY = ROOT/'results/kalibr-native-target-consumption-dev-1701-v2'
CACHE = ROOT/'results/kalibr-native-target-consumption-dev-1701'
CACHE_MANIFEST = ROOT/'results/target-excitation-research-dev-1701/objects-before.json'

CACHE_MANIFEST_SHA = '37d28b93049e92cb2abd231333667b45e628d3ec563141504b1a001475dfbc6c'
SOURCE_BEFORE_SHA = 'e1a6e8d748a79aca3ab072bb667accddefba82556d6e2b9a9cc55f5c64498495'

def verify_cache():
    if digest(CACHE_MANIFEST) != CACHE_MANIFEST_SHA:
        raise ValueError('cache manifest changed')
    if digest(CACHE/'source-before.json') != SOURCE_BEFORE_SHA:
        raise ValueError('cache source ledger changed')
    objects = json.loads(CACHE_MANIFEST.read_text())
    source = json.loads((CACHE/'source-before.json').read_text())
    if len(objects) != 14 or any(digest(CACHE/name) != value['sha256'] for name, value in objects.items()):
        raise ValueError('cache objects changed')
    if any(digest(CACHE/name) != sha for name, sha in source['files'].items()) or digest(CACHE/'input.png') != INPUT_SHA:
        raise ValueError('cache source/input changed')
    return objects, source


def execute_once(record: Path):
    if STUDY.exists() or STUDY.is_symlink():
        raise FileExistsError('v2 consumed; no retry and v1 guard unchanged')
    first = admission()
    write(Path(record), {'facts': first, 'independent_admitted': admitted(first), 'v1_consumed': True})
    if not admitted(first):
        raise RuntimeError('first admission refused before v2 creation')
    verify_sources()
    objects, source = verify_cache()
    STUDY.mkdir(exist_ok=False)
    try:
        frozen = {}
        for name, sha in source['files'].items():
            target = STUDY/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((CACHE/name).read_bytes())
            if digest(target) != sha:
                raise ValueError('cache source copy changed')
            frozen[name] = sha
        for name, value in objects.items():
            target = STUDY/'objects'/name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes((CACHE/name).read_bytes())
            if digest(target) != value['sha256']:
                raise ValueError('cache object copy changed')
            frozen['objects/'+name] = value['sha256']
        code = STUDY/'code'
        for path in [Path(__file__), ROOT/'tools/benchmark/native/kalibr_target_detector_v2.cpp']:
            (code/path.name).write_bytes(path.read_bytes())
            frozen['code/'+path.name] = digest(code/path.name)
        (STUDY/'input.png').write_bytes((CACHE/'input.png').read_bytes())
        write(STUDY/'source-before.json', {'files': frozen, 'input': INPUT_SHA, 'cache_manifest': CACHE_MANIFEST_SHA})
        binary = STUDY/'kalibr_target_detector_v2'
        wrapper = STUDY/'wrapper.o'
        commands = [
            ['/usr/bin/g++', '-std=c++11', '-O3', '-fPIC', '-I'+linux(code/'upstream/include'),
             '-I/usr/include/opencv4', '-I/usr/include/eigen3', '-c', linux(code/'kalibr_target_detector_v2.cpp'),
             '-o', linux(wrapper)],
            ['/usr/bin/g++', *[linux(STUDY/'objects'/name) for name in sorted(objects)], linux(wrapper),
             '-lopencv_imgcodecs', '-lopencv_imgproc', '-lopencv_calib3d', '-lopencv_core', '-o', linux(binary)]
        ]
        write(STUDY/'build-commands.json', {'commands': commands, 'no_upstream_recompile': True})
        builder = ('import json,subprocess,sys; commands=json.load(open(sys.argv[1]))["commands"]; '
                   '[(print(json.dumps(c),flush=True),subprocess.run(c,check=True)) for c in commands]')
        second = admission()
        write(STUDY/'build-admission.json', second)
        if not admitted(second):
            raise RuntimeError('second admission refused; v2 consumed')
        build = scoped(STUDY/'build', ['/usr/bin/python3', '-c', builder, linux(STUDY/'build-commands.json')],
                       label='kalibr-target-v2-build', memory=512*1024**2, seconds=300, outer_seconds=330)
        write(STUDY/'binary-before.json', {'sha256': digest(binary), 'ldd': wsl('ldd', linux(binary)).stdout.decode()})
        third = admission()
        write(STUDY/'runtime-admission.json', third)
        if not admitted(third):
            raise RuntimeError('runtime admission refused; no native dispatch')
        if any(digest(STUDY/name) != sha for name, sha in frozen.items()) or digest(STUDY/'input.png') != INPUT_SHA:
            raise ValueError('frozen input changed')
        run = scoped(STUDY/'run', [linux(binary), linux(STUDY/'input.png')], label='kalibr-target-v2-detect',
                     memory=256*1024**2, seconds=30, outer_seconds=60)
        if any(digest(STUDY/name) != sha for name, sha in frozen.items()) or digest(STUDY/'input.png') != INPUT_SHA:
            raise ValueError('frozen bytes changed after native')
        verify_cache()
        result = {'build': build, 'run': run, 'binary_sha256': digest(binary),
                  'source_clock_calibration_accuracy_teacher_fusion_training_flight': False}
        write(STUDY/'completion.json', result)
        return result
    except BaseException as error:
        write(STUDY/'failure.json', {'type': type(error).__name__, 'message': str(error),
                                    'retry': 'v2 consumed; no rerun', 'qualification': False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-once', action='store_true', required=True)
    parser.add_argument('--admission-record', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(execute_once(args.admission_record), indent=2))


if __name__ == '__main__':
    main()
