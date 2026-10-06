"""Prospective metadata derived from the same limits used by capture."""
from __future__ import annotations

import json
from pathlib import Path

PROFILE_FIELDS = ('motion_profile', 'physics_trace_profile', 'reference_fault_profile', 'source_fanout_profile')
PATH_FIELDS = ('shadow_binary', 'shadow_config', 'reference_module')


def validate_launch_environment(value):
    if type(value) is not dict or not value:
        raise ValueError('explicit launch environment required')
    if any(type(key) is not str for key in value):
        raise ValueError('invalid launch environment name or value')
    total = 0
    result = {}
    for key in sorted(value):
        item = value[key]
        if (type(key) is not str or not key or '=' in key or '\0' in key
                or (item is not None and type(item) is not str)
                or (isinstance(item, str) and '\0' in item)):
            raise ValueError('invalid launch environment name or value')
        total += len(key.encode('utf-8')) + (len(item.encode('utf-8')) if item is not None else 0) + 2
        result[key] = item
    if total > 65536:
        raise ValueError('launch environment exceeds bounded size')
    return result


def derive_launch_environment(binding):
    if type(binding) is not dict or binding.get('schema') != 'capture-resource-binding-v3':
        raise ValueError('v3 binding required for launch environment')
    declared = binding.get('environment')
    graph = binding.get('graph')
    if type(declared) is not dict or type(graph) is not dict or type(graph.get('environment')) is not dict:
        raise ValueError('binding and graph launch environment required')
    result = dict(graph['environment'])
    for key, value in declared.items():
        if key in result and not _typed_equal(result[key], value):
            raise ValueError('binding and graph launch environment conflict: ' + key)
        result[key] = value
    return validate_launch_environment(result)


def materialize_launch_environment(value):
    return {key: item for key, item in validate_launch_environment(value).items() if item is not None}


def execution_contract(args, launch_environment=None):
    fault = args.reference_fault_profile
    if fault not in (None, 'native-pre-epoch-v1'):
        raise ValueError('unknown reference fault profile')
    result = dict(
        schema='capture-execution-v1' if launch_environment is None else 'capture-execution-v2',
        wall_budget_s=60 if fault else 300,
        supervisor_s=90 if fault else 300,
        simulation_duration_ns=25_000_000_000,
        physics_step_ns=1_000_000, imu_hz=250, rgbd_hz=10, rgbd_size=[160, 120],
        estimator_run=bool(args.shadow_binary),
        profiles={name: getattr(args, name) for name in PROFILE_FIELDS},
        inputs={name: str(getattr(args, name).resolve()) if getattr(args, name) else None for name in PATH_FIELDS},
        reference_sha256=args.reference_sha256,
    )
    if launch_environment is not None:
        result['launch_environment'] = validate_launch_environment(launch_environment)
    return result


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


def validate_declaration(args, launch_environment=None):
    actual = execution_contract(args, launch_environment)
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


def declared_command(args, python, capture_script, launch_environment=None):
    """For future study launchers: refuse an undeclared or mismatched run."""
    if not args.execution_contract:
        raise ValueError('study launcher requires an execution declaration')
    validate_declaration(args, launch_environment)
    return [str(python), str(capture_script), '--output', str(args.output.resolve()), *worker_options(args)]
