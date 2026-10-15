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
    if type(binding) is not dict or binding.get('schema') not in ('capture-resource-binding-v3', 'capture-resource-binding-v4'):
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
    validate_wire_configuration(value)
    if before != _file_identity(path):
        raise ValueError('wire configuration changed during validation')
    return dict(before, configuration=value)


def validate_wire_configuration(value):
    """Pure wire semantics shared by native and transported record auditing."""
    staged = type(value) is dict and value.get('schema') == 'capture-wire-startup-v2'
    keys = {'schema', 'session_id', 'sim_origin_ns', 'remote_origin_ns'}
    if staged:
        keys.add('startup_max_wall_ns')
    if (type(value) is not dict
            or value.keys() != keys
            or value['schema'] not in ('capture-wire-v1', 'capture-wire-startup-v2')
            or type(value['session_id']) is not str
            or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value['session_id']) is None
            or type(value['sim_origin_ns']) is not int or value['sim_origin_ns'] != 0
            or type(value['remote_origin_ns']) is not int
            or not 0 <= value['remote_origin_ns'] < 2**63 - 25_000_000_000
            or staged and (type(value['startup_max_wall_ns']) is not int
                           or not 0 < value['startup_max_wall_ns'] <= 60_000_000_000)):
        raise ValueError('invalid capture wire clock configuration')


def execution_contract(args, launch_environment=None, *, record_provider=None):
    if record_provider is not None and getattr(args,'capture_profile',None)!='target-bearing-raw-v1':
        raise ValueError('retained record provider requires explicit raw profile')
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
        inputs={name: (str(getattr(args, name).resolve()) if record_provider is None
                       else record_provider.input_path(getattr(args, name))) if getattr(args, name) else None
                for name in PATH_FIELDS},
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
        result['wire'] = (wire_configuration_record(wire_config) if record_provider is None
                          else record_provider.wire_configuration_record(wire_config))
    agent_config = getattr(args, 'agent_runtime_config', None)
    if agent_config is not None:
        if wire_config is None or not args.execution_contract or not args.runtime_binding or fault:
            raise ValueError('Agent requires a declared unarmed wire capture')
        from tools.benchmark.agent_capture_runtime import agent_runtime_record

        result['agent'] = (agent_runtime_record(agent_config) if record_provider is None
                           else record_provider.agent_runtime_record(agent_config))
    logger_diagnostic = getattr(args, 'logger_diagnostic_profile', None)
    if logger_diagnostic is not None:
        if (logger_diagnostic != 'source-diagnostic-v1' or agent_config is None
                or wire_config is None or not args.execution_contract
                or not args.runtime_binding or fault):
            raise ValueError('diagnostic logger requires declared owned Agent wire capture')
        from tools.benchmark.px4_logger_runtime import PROFILE_RELATIVE, profile_record

        result['logger_diagnostic'] = (profile_record(Path(__file__).resolve().parents[2] / PROFILE_RELATIVE)
                                      if record_provider is None else record_provider.logger_profile_record())
    if getattr(args, 'record_owned_ulog', False):
        if 'logger_diagnostic' not in result:
            raise ValueError('owned ULog source requires declared diagnostic logger')
        from tools.benchmark.owned_ulog_source import LIMITS

        result['owned_ulog_source'] = {'schema': 'capture-owned-ULog-opener-v1', **LIMITS}
    if getattr(args, 'record_depth_payload', False):
        result['record_depth_payload'] = True
    if getattr(args, 'capture_profile', None) is not None:
        from tools.benchmark.calibration_capture_contract import PROFILE, raw_graph

        if args.capture_profile != PROFILE or launch_environment is None:
            raise ValueError('raw capture requires explicit bound launch environment')
        if result.get('wire', {}).get('configuration', {}).get('schema') != 'capture-wire-startup-v2':
            raise ValueError('raw capture requires staged wire startup')
        result['raw_measurement'] = raw_graph(args) if record_provider is None else record_provider.raw_graph(args)
    elif getattr(args, 'calibration_scene', None) is not None:
        raise ValueError('calibration scene requires explicit raw capture profile')
    binding_path = getattr(args, 'runtime_binding', None)
    if (getattr(args, 'capture_profile', None) == 'target-bearing-raw-v1'
            and binding_path is not None and (record_provider is not None or Path(binding_path).is_file())):
        declaration = read_declaration(binding_path) if record_provider is None else record_provider.binding
        if 'graph:loader-selected-paths' in declaration.get('inventory', {}):
            from tools.benchmark.calibration_capture_pipeline_v4 import declared_context
            result['python_extension_context']=(declared_context(declaration) if record_provider is None
                                                 else record_provider.declared_context())
        elif 'runtime:python-extension-context' in declaration.get('inventory', {}):
            if getattr(args, 'capture_profile', None) != 'target-bearing-raw-v1':
                raise ValueError('Python extension context requires explicit raw profile')
            from tools.benchmark.native_entry_context_v3 import declared_python_context

            result['python_extension_context'] = declared_python_context(declaration)
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
        'reference_sha256', 'execution_contract', 'runtime_binding', POLICY_FIELD,
        'wire_config', 'agent_runtime_config', 'logger_diagnostic_profile',
        'capture_profile', 'calibration_scene',
    ):
        value = getattr(args, field, None)
        if value is not None:
            if field in PATH_FIELDS + ('execution_contract', 'runtime_binding', POLICY_FIELD,
                                      'wire_config', 'agent_runtime_config', 'calibration_scene'):
                value = str(Path(value).resolve())
            result += ['--' + field.replace('_', '-'), str(value)]
    if getattr(args, 'startup_preflight', False):
        result.append('--startup-preflight')
    if getattr(args, 'record_depth_payload', False):
        result.append('--record-depth-payload')
    if getattr(args, 'record_owned_ulog', False):
        result.append('--record-owned-ulog')
    if getattr(args, 'prepared_scene', False):
        result.append('--prepared-scene')
    return result


def declared_command(args, python, capture_script, launch_environment=None):
    """For future study launchers: refuse an undeclared or mismatched run."""
    if not args.execution_contract:
        raise ValueError('study launcher requires an execution declaration')
    validate_declaration(args, launch_environment)
    return [str(python), str(capture_script), '--output', str(args.output.resolve()), *worker_options(args)]
