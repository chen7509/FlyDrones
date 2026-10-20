#!/usr/bin/env python3
# ruff: noqa: E402 - file-only producer binds this checkout
"""Export recorded calibration-input files; never launch a sensor or estimator."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))

from flydrones.benchmark.camera_imu_dataset import FLAGS, load_imu, write_bytes, write_dataset, write_json
from flydrones.benchmark.px4_camera_source import (
    MAX_DOCUMENT,
    MAX_ULOG,
    CameraRigBinding,
    _bound_bytes,
    _evidence,
    _linked,
    _unique,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ulog', 'rgb-manifest', 'rig', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('ulog-sha256', 'rgb-manifest-sha256', 'rig-sha256', 'body-id', 'camera-id'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--epoch-json', type=Path)
    parser.add_argument('--epoch-sha256')
    args = parser.parse_args()
    if _linked(args.output):
        raise ValueError('linked output path')
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output/'request.json', {'argv': sys.argv, **FLAGS})
    try:
        inputs = args.output/'inputs'
        inputs.mkdir()
        write_bytes(inputs/'source.ulg', _bound_bytes(args.ulog, args.ulog_sha256, MAX_ULOG))
        rig = _bound_bytes(args.rig, args.rig_sha256, MAX_DOCUMENT)
        doc = json.loads(rig, object_pairs_hook=_unique)
        for role in ('intrinsics', 'extrinsics'):
            ref = doc[role]
            _evidence(args.rig.parent, ref)
            path = inputs/ref['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            write_bytes(path, _bound_bytes(args.rig.parent/ref['path'], ref['sha256'], MAX_DOCUMENT))
        write_bytes(inputs/'rig.json', rig)
        binding = CameraRigBinding.load(inputs/'rig.json', args.rig_sha256,
                                        body_id=args.body_id, camera_id=args.camera_id)
        if (args.epoch_json is None) != (args.epoch_sha256 is None):
            raise ValueError('epoch path/hash must be paired')
        epoch = None
        if args.epoch_json is not None:
            raw = _bound_bytes(args.epoch_json, args.epoch_sha256, MAX_DOCUMENT)
            write_bytes(inputs/'epoch.json', raw)
            epoch = json.loads(raw, object_pairs_hook=_unique)
        data = load_imu(inputs/'source.ulg', args.ulog_sha256)
        summary = write_dataset(args.output, args.rgb_manifest, args.rgb_manifest_sha256,
                                binding, data, ulog_sha=args.ulog_sha256, epoch=epoch)
        write_json(args.output/'dataset.json', summary)
        write_json(args.output/'completion.json', {'status': 'file-dataset-production-complete', **summary})
    except Exception as exc:
        write_json(args.output/'completion.json', {'status': 'failed', 'error': repr(exc), **FLAGS})
        print(repr(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
