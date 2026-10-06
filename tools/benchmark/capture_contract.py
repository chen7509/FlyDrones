"""Prospective metadata derived from the same limits used by capture."""
from __future__ import annotations

import json
from pathlib import Path

PROFILE_FIELDS = ('motion_profile', 'physics_trace_profile', 'reference_fault_profile', 'source_fanout_profile')
PATH_FIELDS = ('shadow_binary', 'shadow_config', 'reference_module')


def execution_contract(args):
    fault = args.reference_fault_profile
    if fault not in (None, 'native-pre-epoch-v1'):
        raise ValueError('unknown reference fault profile')
    return dict(
        schema='capture-execution-v1',
        wall_budget_s=60 if fault else 300,
        supervisor_s=90 if fault else 300,
        simulation_duration_ns=25_000_000_000,
        physics_step_ns=1_000_000, imu_hz=250, rgbd_hz=10, rgbd_size=[160, 120],
        estimator_run=bool(args.shadow_binary),
        profiles={name: getattr(args, name) for name in PROFILE_FIELDS},
        inputs={name: str(getattr(args, name).resolve()) if getattr(args, name) else None for name in PATH_FIELDS},
        reference_sha256=args.reference_sha256,
    )


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate declaration key: ' + key)
        result[key] = value
    return result


def read_declaration(path):
    def invalid_constant(value):
        raise ValueError('nonfinite declaration value: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique_pairs,
                      parse_constant=invalid_constant)


def _typed_equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_typed_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def validate_declaration(args):
    actual = execution_contract(args)
    if args.execution_contract and not _typed_equal(read_declaration(args.execution_contract), actual):
        raise ValueError('prospective execution declaration differs from enforced contract')
    return actual


def worker_options(args):
    result = []
    for field in PATH_FIELDS + PROFILE_FIELDS + ('reference_sha256', 'execution_contract', 'runtime_binding'):
        value = getattr(args, field, None)
        if value is not None:
            if field in PATH_FIELDS + ('execution_contract', 'runtime_binding'):
                value = str(Path(value).resolve())
            result += ['--' + field.replace('_', '-'), str(value)]
    return result


def declared_command(args, python, capture_script):
    """For future study launchers: refuse an undeclared or mismatched run."""
    if not args.execution_contract:
        raise ValueError('study launcher requires an execution declaration')
    validate_declaration(args)
    return [str(python), str(capture_script), '--output', str(args.output.resolve()), *worker_options(args)]
