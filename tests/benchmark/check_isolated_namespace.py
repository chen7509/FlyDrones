"""Prospective Linux ordinary-process checks, never PX4/Gazebo/MAVLink."""
from __future__ import annotations

import argparse
import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

from tools.benchmark import isolated_namespace as ns  # noqa: E402
from tools.benchmark.declared_runtime_snapshot import parse_ldd, snapshot, verify_unchanged, write_manifest  # noqa: E402
from tools.benchmark.disarmed_sensor_provenance import supervise_worker  # noqa: E402


def child(mode, marker):
    if mode == 'timeout':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    write_manifest(marker, dict(identity=ns.namespace_identity(), environment=dict(os.environ), mode=mode))
    if mode == 'timeout':
        time.sleep(60)
    return 7 if mode == 'exit7' else 0


def inventory(output):
    selected = dict(unshare=['/usr/bin/unshare'], ip=['/usr/sbin/ip'], python=[sys.executable],
                    wrapper=[str(Path(ns.__file__).resolve())],
                    dependencies=[], **{'command-inputs': [str(Path(__file__).resolve())]})
    # Explicit direct executable ldd inventory, not all lazy runtime mappings.
    for role in ('unshare', 'ip', 'python'):
        executable = selected[role][0]
        before = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
        run = subprocess.run(['/usr/bin/ldd', executable], capture_output=True, text=True, timeout=5)
        write_manifest(output / f'{role}-ldd.json', dict(executable=executable, before_sha256=before,
                       stdout=run.stdout, stderr=run.stderr, returncode=run.returncode))
        assert before == hashlib.sha256(Path(executable).read_bytes()).hexdigest()
        selected['dependencies'].extend(parse_ldd(run.stdout, run.returncode))
    selected['dependencies'] += [str(ROOT / name) for name in (
        'tools/benchmark/owned_group_evidence.py', 'tools/benchmark/disarmed_sensor_provenance.py',
        'tools/benchmark/declared_runtime_snapshot.py', 'tools/benchmark/capture_contract.py',
        'src/flydrones/benchmark/camera_info_capture.py', 'src/flydrones/benchmark/rgb_capture.py')]
    selected['dependencies'] = sorted(set(selected['dependencies']))
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--producer')
    parser.add_argument('--child', choices=['normal', 'exit7', 'timeout'])
    parser.add_argument('--marker', type=Path)
    args = parser.parse_args()
    if args.child:
        return child(args.child, args.marker)
    if args.output is None or args.producer is None:
        parser.error('output/producer required')
    out = args.output.absolute()
    out.mkdir(parents=True, exist_ok=False)
    selected = inventory(out)
    env = {'HOME': str(Path.home()), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    initial = snapshot(selected)
    original = ns.namespace_identity()
    write_manifest(out / 'prospective.json', dict(producer=args.producer, inventory=selected, baseline=initial,
                   environment=env, cases=['normal', 'exit7', 'timeout', 'direct-refusal'],
                   supervisor_seconds={'normal': 20, 'exit7': 20, 'timeout': 4, 'direct-refusal': 20},
                   no_px4_or_mavlink=True, physical_qualified=False))
    records = []
    for mode in ('normal', 'exit7', 'timeout'):
        marker = out / f'{mode}-command.json'
        command = [sys.executable, '-I', str(Path(__file__).resolve()), '--child', mode, '--marker', str(marker)]
        started = time.monotonic()
        result = ns.launch_isolated(command, out / mode, selected, env, 4 if mode == 'timeout' else 20)
        write_manifest(out / f'{mode}-assessment.json', dict(elapsed_s=time.monotonic() - started, result=result))
        assert marker.exists(), result
        assert result['isolated_launch_qualified'] is (mode == 'normal'), result
        cleanup = result['supervisor']['cleanup']
        assert cleanup['no_executing_members'] and cleanup['group_absent'], result
        assert cleanup['sigkill_dispatched'] is (mode == 'timeout'), result
        if mode == 'exit7':
            assert result['worker']['command_exit'] == 7
        if mode == 'timeout':
            assert result['supervisor']['status'] == 'supervisor_timeout'
        records.append(dict(case=mode, assessed_as_expected=True))
    # Same wrapper, same identity checks, but deliberately omit unshare. No target command should run.
    marker = out / 'direct-command.json'
    doc = dict(schema='isolated-loopback-launch-v1',
               command=[sys.executable, '-I', str(Path(__file__).resolve()), '--child', 'normal', '--marker', str(marker)],
               inventory=selected, baseline=snapshot(selected), parent=ns.namespace_identity(), environment=env, timeout_s=20)
    declaration = out / 'direct-declaration.json'
    write_manifest(declaration, doc)
    digest = hashlib.sha256(declaration.read_bytes()).hexdigest()
    result = supervise_worker([sys.executable, '-I', ns.__file__, '--worker', str(declaration), digest, str(out / 'direct')],
                              out / 'direct', timeout_s=20, launch_environment=env, execution_contract=declaration)
    assert result['worker_exit'] == 2 and not marker.exists(), result
    assert result['cleanup']['no_executing_members'] and result['cleanup']['group_absent'], result
    records.append(dict(case='direct-refusal', assessed_as_expected=True))
    after = snapshot(selected)
    write_manifest(out / 'post-files.json', after)
    verify_unchanged(initial, after)
    assert ns.namespace_identity() == original
    write_manifest(out / 'assessment.json', dict(cases=records, parent_identity_unchanged=True,
                   declared_files_unchanged=True, physical_network_qualified=False,
                   cold_px4_qualified=False, fusion_qualified=False))
    print(records)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
