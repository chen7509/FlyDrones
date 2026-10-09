"""Prospective metadata derived from the same limits used by capture."""
from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path

PROFILE_FIELDS = ('motion_profile', 'physics_trace_profile', 'reference_fault_profile', 'source_fanout_profile')
MOTION_INTENT_FIELD = 'motion_intent_profile'
HEALTH_PROFILE_FIELD = 'health_profile'
HEALTH_FAULT_FIELD = 'health_fault_profile'
PATH_FIELDS = ('shadow_binary', 'shadow_config', 'reference_module')
POLICY_FIELD = 'trajectory_gauge_policy'
SCALAR_FIELDS = ('simulation_seed',)


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


def _file_identity(path):
    requested = Path(path).absolute()
    resolved = requested.resolve(strict=True)
    before = resolved.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('trajectory gauge policy must be a regular file')
    payload = resolved.read_bytes()
    after = resolved.stat()
    def stable(value):
        return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                value.st_mtime_ns, value.st_ctime_ns)
    if stable(before) != stable(after):
        raise ValueError('trajectory gauge policy changed while read')
    return {
        'path': str(requested), 'resolved': str(resolved), 'bytes': len(payload),
        'sha256': hashlib.sha256(payload).hexdigest(),
    }


def trajectory_gauge_policy_record(path):
    from tools.benchmark.trajectory_gauge_contract import validate_trajectory_gauge_policy

    before = _file_identity(path)
    document = read_declaration(path)
    validate_trajectory_gauge_policy(document)
    after = _file_identity(path)
    if before != after:
        raise ValueError('trajectory gauge policy changed during validation')
    return {**before, 'schema': document['schema']}


def wire_configuration_record(path):
    """Freeze an explicit clock mapping; no implicit origin or live authority."""
    before = _file_identity(path)
    value = read_declaration(path)
    if (type(value) is not dict
            or value.keys() != {'schema', 'session_id', 'sim_origin_ns', 'remote_origin_ns'}
            or value['schema'] != 'capture-wire-v1'
            or type(value['session_id']) is not str
            or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value['session_id']) is None
            or type(value['sim_origin_ns']) is not int or value['sim_origin_ns'] != 0
            or type(value['remote_origin_ns']) is not int
            or not 0 <= value['remote_origin_ns'] < 2**63 - 25_000_000_000):
        raise ValueError('invalid capture wire clock configuration')
    if before != _file_identity(path):
        raise ValueError('wire configuration changed during validation')
    return dict(before, configuration=value)


def execution_contract(args, launch_environment=None):
    fault = args.reference_fault_profile
    if fault not in (None, 'native-pre-epoch-v1'):
        raise ValueError('unknown reference fault profile')
    policy_path = getattr(args, POLICY_FIELD, None)
    if policy_path is not None and launch_environment is None:
        raise ValueError('trajectory gauge policy requires explicit launch environment')
    result = dict(
        schema=('capture-execution-v3' if policy_path is not None else
                ('capture-execution-v1' if launch_environment is None else 'capture-execution-v2')),
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
    motion_intent = getattr(args, MOTION_INTENT_FIELD, None)
    if motion_intent is not None:
        result['profiles'][MOTION_INTENT_FIELD] = motion_intent
    health_profile = getattr(args, HEALTH_PROFILE_FIELD, None)
    if health_profile is not None:
        result['profiles'][HEALTH_PROFILE_FIELD] = health_profile
    health_fault = getattr(args, HEALTH_FAULT_FIELD, None)
    if health_fault is not None:
        result['profiles'][HEALTH_FAULT_FIELD] = health_fault
    if policy_path is not None:
        result['trajectory_gauge_policy'] = trajectory_gauge_policy_record(policy_path)
    simulation_seed = getattr(args, 'simulation_seed', None)
    if simulation_seed is not None:
        if type(simulation_seed) is not int or not 1 <= simulation_seed < 2**32:
            raise ValueError('invalid simulation seed')
        result['simulation_seed'] = simulation_seed
    wire_config = getattr(args, 'wire_config', None)
    if wire_config is not None:
        if not args.execution_contract or not args.runtime_binding or fault:
            raise ValueError('wire mode requires a declared bound ordinary capture')
        result['wire'] = wire_configuration_record(wire_config)
    if getattr(args, 'record_depth_payload', False):
        result['record_depth_payload'] = True
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
    for field in PATH_FIELDS + PROFILE_FIELDS + SCALAR_FIELDS + (
        MOTION_INTENT_FIELD, HEALTH_PROFILE_FIELD, HEALTH_FAULT_FIELD,
        'reference_sha256', 'execution_contract', 'runtime_binding', POLICY_FIELD, 'wire_config',
    ):
        value = getattr(args, field, None)
        if value is not None:
            if field in PATH_FIELDS + ('execution_contract', 'runtime_binding', POLICY_FIELD, 'wire_config'):
                value = str(Path(value).resolve())
            result += ['--' + field.replace('_', '-'), str(value)]
    if getattr(args, 'startup_preflight', False):
        result.append('--startup-preflight')
    if getattr(args, 'record_depth_payload', False):
        result.append('--record-depth-payload')
    return result


def declared_command(args, python, capture_script, launch_environment=None):
    """For future study launchers: refuse an undeclared or mismatched run."""
    if not args.execution_contract:
        raise ValueError('study launcher requires an execution declaration')
    validate_declaration(args, launch_environment)
    return [str(python), str(capture_script), '--output', str(args.output.resolve()), *worker_options(args)]
