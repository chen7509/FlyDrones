#!/usr/bin/env python3
# ruff: noqa: E402 - binds the repository src for the file-only producer
"""Produce bound recorded PX4 camera rows; never a live backend or publisher."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))

from flydrones.benchmark.px4_camera_source import (
    MAX_DOCUMENT,
    MAX_ULOG,
    CameraRigBinding,
    Px4UlogCameraSource,
    _bound_bytes,
    _evidence,
    _linked,
    _unique,
)


def _write(path, data):
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _json(path, value):
    _write(path, (json.dumps(value, indent=2, allow_nan=False)+'\n').encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ulog', 'rig', 'frames-json', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('ulog-sha256', 'rig-sha256', 'frames-sha256', 'body-id', 'camera-id'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--epoch-declaration-json', type=Path)
    parser.add_argument('--epoch-sha256')
    parser.add_argument('--calibration-artifact', type=Path)
    parser.add_argument('--calibration-sha256')
    args = parser.parse_args()
    if _linked(args.output):
        raise ValueError('linked producer result path')
    args.output.mkdir(parents=True, exist_ok=False)
    _json(args.output/'request.json', {'schema': 'flydrones-px4-camera-file-request-v1',
                                     'argv': sys.argv, 'live_source_authenticated': False,
                                     'training_eligible': False, 'flight_eligible': False})
    try:
        inputs = args.output/'inputs'
        inputs.mkdir()
        _write(inputs/'source.ulg', _bound_bytes(args.ulog, args.ulog_sha256, MAX_ULOG))
        raw_rig = _bound_bytes(args.rig, args.rig_sha256, MAX_DOCUMENT)
        rig_doc = json.loads(raw_rig, object_pairs_hook=_unique)
        # Validate original references before snapshotting their exact expected bytes.
        for role in ('intrinsics', 'extrinsics'):
            ref = rig_doc[role]
            _evidence(args.rig.parent, ref)
            dst = inputs/ref['path']
            dst.parent.mkdir(parents=True, exist_ok=True)
            _write(dst, _bound_bytes(args.rig.parent/ref['path'], ref['sha256'], MAX_DOCUMENT))
        _write(inputs/'rig.json', raw_rig)
        raw_frames = _bound_bytes(args.frames_json, args.frames_sha256, MAX_DOCUMENT)
        _write(inputs/'frames.json', raw_frames)
        frames = json.loads(raw_frames, object_pairs_hook=_unique)
        if type(frames) is not dict or set(frames) != {'frame_ns'}:
            raise ValueError('frame schedule fields invalid')
        declaration = None
        if (args.epoch_declaration_json is None) != (args.epoch_sha256 is None):
            raise ValueError('epoch declaration path/hash must be paired')
        if args.epoch_declaration_json is not None:
            raw_epoch = _bound_bytes(args.epoch_declaration_json, args.epoch_sha256, MAX_DOCUMENT)
            _write(inputs/'epoch.json', raw_epoch)
            declaration = json.loads(raw_epoch, object_pairs_hook=_unique)
        binding = CameraRigBinding.load(inputs/'rig.json', args.rig_sha256,
                                        body_id=args.body_id, camera_id=args.camera_id)
        calibration = None
        if (args.calibration_artifact is None) != (args.calibration_sha256 is None):
            raise ValueError('calibration artifact path/hash must be paired')
        if args.calibration_artifact is not None:
            from flydrones.benchmark.kalibr_camera_consumption import KalibrCameraArtifact, references

            raw, doc, payload = references(args.calibration_artifact, args.calibration_sha256)
            root = inputs/'calibration'
            root.mkdir()
            _write(root/'artifact.json', raw)
            for role, data in payload.items():
                dst = root/doc[role]['path']
                dst.parent.mkdir(parents=True, exist_ok=True)
                _write(dst, data)
            calibration = KalibrCameraArtifact.load(root/'artifact.json', args.calibration_sha256, binding)
        source = Px4UlogCameraSource.from_ulog(inputs/'source.ulg', args.ulog_sha256, binding)
        produced = source.produce(frames['frame_ns'], epoch_declaration=declaration, calibration_artifact=calibration)
        rows = produced.pop('records')
        with (args.output/'rows.jsonl').open('x', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row, allow_nan=False)+'\n')
            stream.flush()
            os.fsync(stream.fileno())
        _json(args.output/'production.json', produced)
        _json(args.output/'completion.json', {'schema': 'flydrones-px4-camera-file-completion-v1',
                                            'status': 'file-production-complete', 'frames': len(rows),
                                            'diagnostic_geometry_rows': sum(r['geometry'] is not None for r in rows),
                                            'live_source_authenticated': False, 'clock_epoch_qualified': False,
                                            'camera_calibration_qualified': False,
                                            'training_eligible': False, 'flight_eligible': False})
    except Exception as exc:
        _json(args.output/'completion.json', {'schema': 'flydrones-px4-camera-file-completion-v1',
                                            'status': 'failed', 'error': repr(exc),
                                            'live_source_authenticated': False, 'clock_epoch_qualified': False,
                                            'camera_calibration_qualified': False,
                                            'training_eligible': False, 'flight_eligible': False})
        print(repr(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
