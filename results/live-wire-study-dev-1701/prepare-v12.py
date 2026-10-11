"""One-off Agent-inclusive offline study preparation; never executes capture."""
# ruff: noqa: E402
import copy
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from tools.benchmark.agent_capture_runtime import agent_runtime_record
from tools.benchmark.bound_resource_graph import build_graph
from tools.benchmark.capture_contract import declared_command, derive_launch_environment, execution_contract, read_declaration
from tools.benchmark.capture_disarmed_sensors import active_resources
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, verify_unchanged, write_manifest
from tools.benchmark.execute_openvins_health_physical_run import prepare_live_wire_execution
from tools.benchmark.live_wire_study import ENDPOINT, LIMITS, validate_live_wire_study_files
from tools.benchmark.native_resource_client import QueryClient
from tools.benchmark.repository_python_sources import audit_source_roots, discover_sources
from tools.benchmark.runtime_resource_binding import GENERATED_NAMES, validate_binding

HERE = Path(__file__).resolve().parent
STUDY = HERE / 'study-v12-retry2'
SOURCE = HERE / 'study-v11'
ARCHIVE = ROOT / 'evidence/live-wire-v11-startup-preparation-dev-1701.zip'
ARCHIVE_SHA = 'ea31808ff8b835a851a84c12f6fd65329fac05170fe8ceef411a8167565e9b26'
AGENT_CONFIG = ROOT / 'results/agent-capture-contract-dev-1701/agent-runtime.json'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def extend_missing(inventory, role, paths):
    """Extend an inherited role without introducing duplicate resolved files."""
    known = {str(Path(path).resolve(strict=True)) for values in inventory.values() for path in values}
    selected = set(inventory.get(role, ()))
    for path in paths:
        resolved = str(Path(path).resolve(strict=True))
        if resolved not in known:
            known.add(resolved)
            selected.add(resolved)
    if selected:
        inventory[role] = sorted(selected)


def add_agent_selection(inventory, selected_paths, binary):
    """Keep each checked SONAME alias; distinct names can share one inode."""
    if (type(selected_paths) is not list or len(selected_paths) < 3
            or selected_paths[2] != binary or len(set(selected_paths)) != len(selected_paths)):
        raise ValueError('invalid exact Agent selected paths')
    existing = {path for paths in inventory.values() for path in paths}
    if existing.intersection(selected_paths):
        raise ValueError('Agent requested path already selected under another role')
    inventory['runtime-root:agent'] = [binary]
    inventory['runtime:agent-selected'] = [path for path in selected_paths if path != binary]


def negative_binding_name(case):
    if case not in {'lazy_leaf_missing', 'agent_missing_role'}:
        raise ValueError('unsupported negative binding case')
    return case + '-binding.json'


def assert_original_selection_unchanged(original_rows, augmented_rows):
    """Compare each original file exactly, while allowing new declared files."""
    original = {}
    augmented = {}
    for rows, target in ((original_rows, original), (augmented_rows, augmented)):
        for row in rows:
            path = row['requested']
            if path in target:
                raise ValueError('duplicate selected path: ' + path)
            target[path] = row
    for path, expected in original.items():
        if augmented.get(path) != expected:
            raise ValueError('original selection changed while preparing: ' + path)


def prepare():
    resources = active_resources()
    if resources:
        raise ValueError('competing resources: ' + repr(resources))
    STUDY.mkdir()
    version = read_declaration(HERE / 'committed-source-v12-retry2.json')
    if version['tracked_worktree_clean'] is not True:
        raise ValueError('tracked source must be committed')
    generator = file_record(__file__)
    if generator['sha256'] != version['preparer_sha256']:
        raise ValueError('v12 preparer differs from selected bytes')
    agent = agent_runtime_record(AGENT_CONFIG)
    if digest(ARCHIVE.read_bytes()) != ARCHIVE_SHA:
        raise ValueError('installed preflight archive changed')
    consumed = {}
    copies = STUDY / 'resource-check'
    copies.mkdir()
    with zipfile.ZipFile(ARCHIVE) as sealed:
        if sealed.testzip() is not None:
            raise ValueError('source archive CRC')
        members = {row['path']: row for row in json.loads(sealed.read('MANIFEST.json'))['members']}
        selected = [SOURCE / name for name in ('runtime-binding-v3.json', 'execution-contract.json',
                                              'trajectory-gauge-policy.json', 'study-manifest.json')]
        selected += [SOURCE / 'resource-check' / name for name in GENERATED_NAMES if name != 'gz_env.sh']
        for path in selected:
            member = path.relative_to(ROOT).as_posix()
            raw = path.read_bytes()
            if raw != sealed.read(member) or digest(raw) != members[member]['sha256']:
                raise ValueError('sealed source mismatch: ' + member)
            consumed[member] = file_record(path)
            if path.name in GENERATED_NAMES:
                with (copies / path.name).open('xb') as stream:
                    stream.write(raw)
    original = validate_binding(read_declaration(SOURCE / 'runtime-binding-v3.json'))
    # Historical runtime copied this file into an ephemeral directory that was
    # correctly removed during cleanup. This is a NEW copy from the identical
    # declared producer input, not a recovered historical runtime byte stream.
    env_rows = [row for row in original['baseline']['files'] if row['requested'].endswith('/rootfs/gz_env.sh')]
    if len(env_rows) != 1:
        raise ValueError('ambiguous declared gz_env producer')
    env_source = Path(env_rows[0]['requested'])
    env_raw = env_source.read_bytes()
    if digest(env_raw) != env_rows[0]['sha256'] or digest(env_raw) != original['generated']['gz_env.sh']:
        raise ValueError('gz_env source differs from declared generated hash')
    with (copies / 'gz_env.sh').open('xb') as stream:
        stream.write(env_raw)
    consumed['current_declared_gz_env_source_not_historical_copy'] = file_record(env_source)
    source_execution = read_declaration(SOURCE / 'execution-contract.json')
    current = snapshot(original['inventory'])
    old = {row['requested']: row for row in original['baseline']['files']}
    changes = []
    for row in current['files']:
        prior = old[row['requested']]
        if (row['resolved'] != prior['resolved'] or
                [(r['path'], r['target']) for r in row['links']] !=
                [(r['path'], r['target']) for r in prior['links']]):
            raise ValueError('unapproved selected resolution change: ' + row['requested'])
        if (row['sha256'], row['bytes']) == (prior['sha256'], prior['bytes']):
            continue
        path = Path(row['requested'])
        relative = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else None
        accepted = bool(relative and relative.endswith('.py') and
                        version['source_sha256'].get(relative) == row['sha256'])
        changes.append(dict(path=row['requested'], before=prior['sha256'], after=row['sha256'],
                            accepted_committed_source=accepted))
    write_manifest(STUDY / 'source-drift.json', dict(changes=changes))
    if any(not row['accepted_committed_source'] for row in changes):
        raise ValueError('unapproved input changed; no automatic rebaseline')
    policy = STUDY / 'trajectory-gauge-policy.json'
    with policy.open('xb') as stream:
        stream.write((SOURCE / policy.name).read_bytes())
    study_id = 'live-wire-agent-dev-1701-v12-retry2'
    wire = STUDY / 'wire-config.json'
    write_manifest(wire, dict(schema='capture-wire-startup-v2', session_id=study_id + '.clock',
                             sim_origin_ns=0, remote_origin_ns=0,
                             startup_max_wall_ns=60_000_000_000))
    declared = copy.deepcopy(original)
    loaded = sorted({str(Path(m.__file__).resolve()) for m in tuple(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).suffix == '.py'
                     and Path(m.__file__).resolve().is_relative_to(ROOT)})
    auditor = ROOT / 'tools/benchmark/audit_live_wire_study.py'
    extend_missing(declared['inventory'], 'runtime:prospective-loaded-source', loaded + [str(auditor)])
    source_graph = discover_sources(ROOT, audit_source_roots(ROOT))
    write_manifest(STUDY / 'audit-source-dependencies.json', source_graph)
    extend_missing(declared['inventory'], 'runtime:static-audit-source', [r['requested'] for r in source_graph['files']])
    extend_missing(declared['inventory'], 'runtime:prospective-policy', [policy, wire])
    add_agent_selection(declared['inventory'], agent['selected_paths'], agent['configuration']['binary'])
    declared['runtime_maps']['owned_roles']['agent'] = ['ready', 'prestop']
    declared['baseline'] = snapshot(declared['inventory'])
    # Do not absorb a race during the augmented snapshot.
    assert_original_selection_unchanged(current['files'], declared['baseline']['files'])
    validate_binding(declared)
    graph = declared['graph']
    generated = snapshot({'generated:' + name: [str(copies / name)] for name in GENERATED_NAMES})
    for row in generated['files']:
        if row['sha256'] != declared['generated'][Path(row['requested']).name]:
            raise ValueError('generated source differs from fixed profile')
    client = QueryClient(declared['inventory']['graph:resolver'][0], Path(graph['cwd']), graph['environment'], copies)
    observed = client.query('context')
    if observed != graph['expected_context']:
        raise ValueError('installed SDK search context changed')
    checked_graph = build_graph(copies / 'world.sdf', client, declared['baseline']['files'] + generated['files'], copies)
    verify_unchanged(declared['baseline'], snapshot(declared['inventory']))
    binding_path = STUDY / 'runtime-binding-v3.json'
    execution_path = STUDY / 'execution-contract.json'
    outputs = {key: str(STUDY / name) for key, name in dict(capture='capture-v1', dispatch='dispatch.json',
                completion='completion.json', audit='audit.json').items()}
    values = dict(output=Path(outputs['capture']), worker=False, startup_preflight=False,
                  execution_contract=execution_path, runtime_binding=binding_path, trajectory_gauge_policy=policy,
                  wire_config=wire, agent_runtime_config=AGENT_CONFIG,
                  simulation_seed=27602, reference_sha256=source_execution['reference_sha256'])
    values.update({key: Path(value) if value is not None else None for key,value in source_execution['inputs'].items()})
    values.update(source_execution['profiles'])
    args = SimpleNamespace(**values)
    env = derive_launch_environment(declared)
    execution = execution_contract(args, env)
    write_manifest(binding_path, declared)
    write_manifest(execution_path, execution)
    capture = ROOT / 'tools/benchmark/capture_disarmed_sensors.py'
    files = dict(execution=execution_path, binding=binding_path, wire_config=wire, gauge_policy=policy,
                 agent_config=AGENT_CONFIG, python=Path('/usr/bin/python3'), capture=capture, auditor=auditor)
    manifest = dict(schema='live-wire-study-v2', study_id=study_id, producer_commit=version['head'],
                    role='development', simulation_seed=27602, expected_status='capture_completed',
                    clock_scope='postupdate-simulation-epoch-v1', live_activation_authorized=False,
                    endpoint=ENDPOINT, limits=LIMITS, outputs=outputs,
                    files={key:file_record(path) for key,path in files.items()},
                    command=declared_command(args, '/usr/bin/python3', capture, env))
    manifest_path = STUDY / 'study-manifest.json'
    write_manifest(manifest_path, manifest)
    validated = validate_live_wire_study_files(manifest_path)
    binding = prepare_live_wire_execution(manifest_path)
    write_manifest(STUDY / 'executor-binding.json', binding)
    negative = STUDY / 'negative-cases'
    negative.mkdir()
    outcomes = {}
    for name in ('seed', 'startup_command', 'auditor_hash', 'clock_scope', 'lazy_leaf_missing',
                 'agent_missing_role', 'agent_config_missing'):
        changed = copy.deepcopy(manifest)
        if name == 'seed':
            changed['simulation_seed'] = 27601
        elif name == 'startup_command':
            changed['command'].append('--startup-preflight')
        elif name == 'auditor_hash':
            changed['files']['auditor']['sha256'] = '0' * 64
        elif name == 'clock_scope':
            changed['clock_scope'] = 'echo-request'
        elif name == 'agent_config_missing':
            del changed['files']['agent_config']
        else:
            absent = copy.deepcopy(declared)
            if name == 'agent_missing_role':
                del absent['runtime_maps']['owned_roles']['agent']
            else:
                leaf = str(ROOT / 'tools/benchmark/audit_live_wire_safety.py')
                absent['inventory'] = {role:[p for p in paths if p != leaf]
                                       for role,paths in absent['inventory'].items()}
                absent['inventory'] = {role:paths for role,paths in absent['inventory'].items() if paths}
                absent['baseline']['files'] = [r for r in absent['baseline']['files'] if r['requested'] != leaf]
            malformed = negative / negative_binding_name(name)
            write_manifest(malformed, absent)
            changed['files']['binding'] = file_record(malformed)
            changed['command'][changed['command'].index('--runtime-binding') + 1] = str(malformed)
        path = negative / (name + '.json')
        write_manifest(path, changed)
        try:
            validate_live_wire_study_files(path)
        except ValueError as exc:
            outcomes[name] = repr(exc)
        else:
            raise AssertionError('mutated actual declaration accepted: ' + name)
    if generator != file_record(__file__):
        raise ValueError('preparation generator changed')
    for relative, expected in version['source_sha256'].items():
        if digest((ROOT / relative).read_bytes()) != expected:
            raise ValueError('committed source drift: ' + relative)
    result = dict(schema='live-wire-offline-preparation-v1', files_verified=validated['files_verified'],
                  static_audit_sources_verified=validated['static_audit_sources_verified'],
                  static_audit_source_count=validated['static_audit_source_count'],
                  producer_commit=version['head'], generator=generator, consumed_source=consumed,
                  source_archive_sha256=ARCHIVE_SHA, original_declared_files=len(current['files']),
                  committed_source_changes=sum(row['accepted_committed_source'] for row in changes),
                  selected_agent_files=len(agent['selected_paths']),
                  agent_declaration_sha256=agent['declaration_sha256'],
                  prepared_declared_files=len(declared['baseline']['files']),
                  local_resource_graph_verified=checked_graph['local_file_graph_verified'],
                  resource_documents=len(checked_graph['documents']), resource_edges=len(checked_graph['edges']),
                  native_read_only_queries=client.count, mutation_refusals=outcomes,
                  installed_capture_run=False, native_estimator_run=False, physical_run=False, network_enabled=False,
                  live_activation_available=False, live_qualified=False, fusion_eligible=False,
                  runtime_closure_qualified=False, independent_review_complete=False,
                  source_scope='current tracked Python bytes plus exact preflight selection; not complete OS closure')
    write_manifest(STUDY / 'preparation-result.json', result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('generator','consumed_source')}))


if __name__ == '__main__':
    try:
        prepare()
    except BaseException as exc:
        if STUDY.exists():
            write_manifest(STUDY / 'prepare-failed.json', dict(error=repr(exc), physical_run=False))
        raise
