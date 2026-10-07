"""Bind a declared baseline and generated inputs before capture initializes native code.

Self-process mapping observations are phase evidence, never whole-runtime qualification.
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

from tools.benchmark.bound_resource_graph import build_graph
from tools.benchmark.capture_contract import _typed_equal
from tools.benchmark.declared_runtime_snapshot import snapshot, write_manifest
from tools.benchmark.native_resource_client import QUERY_ENV_KEYS, QueryClient, environment, validate_response
from tools.benchmark.owned_runtime_maps import OwnedRuntimeMaps, parse_maps

GENERATED_NAMES = ('world.sdf', 'world.json', 'ground_albedo.png', 'obstacle_albedo.png', 'board_albedo.png', 'gz_env.sh')
ENV_KEYS = ('GZ_SIM_RESOURCE_PATH', 'GZ_SIM_SYSTEM_PLUGIN_PATH', 'GZ_SIM_SERVER_CONFIG_PATH',
            'LD_LIBRARY_PATH', 'PYTHONPATH', 'SDF_PATH', 'GZ_FILE_PATH', 'GZ_HOMEDIR', 'HOME')
OPTIONAL_ENV_KEYS = ('MESA_SHADER_CACHE_DISABLE',)
OWNED_RUNTIME_ROLES = {'px4', 'openvins', 'openvins-restart'}


def validate_binding(doc):
    if type(doc) is not dict:
        raise ValueError('binding declaration schema keys')
    version = doc.get('schema')
    keys = {'schema', 'inventory', 'baseline', 'environment', 'generated'}
    if version in ('capture-resource-binding-v2', 'capture-resource-binding-v3'):
        keys.add('graph')
    if version == 'capture-resource-binding-v3':
        keys.add('runtime_maps')
    if set(doc) != keys:
        raise ValueError('binding declaration schema keys')
    if version not in ('capture-resource-binding-v1', 'capture-resource-binding-v2', 'capture-resource-binding-v3'):
        raise ValueError('binding schema version')
    inventory = doc['inventory']
    if type(inventory) is not dict or not inventory:
        raise ValueError('binding requires explicit inventory')
    seen = set()
    for role, paths in inventory.items():
        if type(role) is not str or not role or type(paths) is not list or not paths:
            raise ValueError('binding inventory role/paths')
        if role.startswith(('generated:', 'bootstrap:')):
            raise ValueError('reserved inventory role')
        for path in paths:
            if type(path) is not str or not Path(path).is_absolute() or '..' in Path(path).parts:
                raise ValueError('binding inventory absolute path required')
            normalized = os.path.normcase(str(Path(path)))
            if normalized in seen:
                raise ValueError('duplicate binding path')
            seen.add(normalized)
    baseline = doc['baseline']
    if type(baseline) is not dict or baseline.get('schema') != 'declared-files-v1' or not baseline.get('files'):
        raise ValueError('binding baseline missing')
    env = doc['environment']
    valid_env_sets = (set(ENV_KEYS), set(ENV_KEYS) | set(OPTIONAL_ENV_KEYS))
    if (type(env) is not dict or set(env) not in valid_env_sets
            or any(v is not None and type(v) is not str for v in env.values())
            or ('MESA_SHADER_CACHE_DISABLE' in env and env['MESA_SHADER_CACHE_DISABLE'] != 'true')):
        raise ValueError('binding environment must explicitly include lookup keys')
    generated = doc['generated']
    if (type(generated) is not dict or set(generated) != set(GENERATED_NAMES)
            or any(type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None for v in generated.values())):
        raise ValueError('binding generated hashes required')
    if version in ('capture-resource-binding-v2', 'capture-resource-binding-v3'):
        graph = doc['graph']
        if (type(graph) is not dict or set(graph) != {'schema', 'cwd', 'environment', 'expected_context'}
                or graph['schema'] != 'generated-resource-graph-v1'
                or type(graph['cwd']) is not str or not Path(graph['cwd']).is_absolute()
                or '..' in Path(graph['cwd']).parts):
            raise ValueError('resource graph declaration schema')
        query_env = environment(graph['environment'])
        validate_response(graph['expected_context'], ('context',), Path(graph['cwd']), query_env)
        for role, count in (('graph:resolver', 1), ('graph:source', 1), ('graph:dependencies', None)):
            if role not in inventory or (count is not None and len(inventory[role]) != count):
                raise ValueError('graph resolver source/binary/dependencies must be declared')
    if version == 'capture-resource-binding-v3':
        runtime = doc['runtime_maps']
        if type(runtime) is not dict or set(runtime) != {
                'self_phases', 'owned_roles', 'max_maps_bytes', 'max_observations'}:
            raise ValueError('runtime maps declaration schema')
        self_phases = runtime['self_phases']
        roles = runtime['owned_roles']
        if (type(self_phases) is not list or not self_phases
                or type(roles) is not dict or not roles or not set(roles) <= OWNED_RUNTIME_ROLES):
            raise ValueError('runtime maps phases and roles required')
        lists = [self_phases, *roles.values()]
        if any(type(items) is not list or not items for items in lists):
            raise ValueError('runtime maps phases required')
        if any(type(phase) is not str or re.fullmatch('[a-z][a-z0-9-]*', phase) is None
               for items in lists for phase in items):
            raise ValueError('invalid runtime map phase')
        if any(len(items) != len(set(items)) for items in lists):
            raise ValueError('duplicate runtime map phase')
        if (type(runtime['max_maps_bytes']) is not int or not 0 < runtime['max_maps_bytes'] <= 8 * 1024 * 1024
                or type(runtime['max_observations']) is not int
                or not 0 < runtime['max_observations'] <= 16):
            raise ValueError('invalid runtime map bounds')
    return copy.deepcopy(doc)


def read_self_maps():
    return Path('/proc/self/maps').read_text(encoding='utf-8')


def estimator_inputs(binary, config, reference):
    """Include every file consumed by the existing fixed configuration contract."""
    result = [p for p in (binary, reference) if p is not None]
    if config is not None:
        from tools.benchmark.openvins_online_shadow import validate_frozen_config

        config = Path(config)
        frozen = validate_frozen_config(config)
        result += [config.parent / name for name in frozen['sha256']]
        result.append(config.parent / 'freeze.json')
    return result


class RuntimeBinding:
    def __init__(self, doc, output, *, map_reader=read_self_maps, owned_factory=OwnedRuntimeMaps):
        self.doc = validate_binding(doc)
        self.output, self.map_reader = Path(output), map_reader
        self.pre_recorded = False
        self.before = None
        self.inventory = None
        self.errors = []
        self.phases = []
        self.closed = False
        self.graph_result = None
        self.owned_factory = owned_factory
        self.owned_maps = None
        self.required_self = list(self.doc.get('runtime_maps', {}).get('self_phases', []))
        self.required_owned = copy.deepcopy(self.doc.get('runtime_maps', {}).get('owned_roles', {}))
        self.completed_self = []
        self.completed_owned = {role: [] for role in self.required_owned}

    def start(self, generated, environment, required_paths):
        if self.before is not None or self.pre_recorded or self.errors or self.closed:
            raise ValueError('binding already started or failed')
        try:
            actual_env = {key: environment.get(key) for key in self.doc['environment']}
            if not _typed_equal(actual_env, self.doc['environment']):
                raise ValueError('resource lookup environment mismatch')
            baseline = snapshot(self.doc['inventory'])
            if not _typed_equal(baseline['files'], self.doc['baseline']['files']):
                raise ValueError('declared baseline drift or type mismatch')
            known = {p for row in baseline['files'] for p in (row['requested'], row['resolved'])}
            if not required_paths or any(str(Path(p).absolute()) not in known for p in required_paths):
                raise ValueError('actual selected input absent from declared baseline')
            if set(generated) != set(GENERATED_NAMES):
                raise ValueError('actual generated input set mismatch')
            copies = snapshot({name: [generated[name]] for name in GENERATED_NAMES})
            if any(row['sha256'] != self.doc['generated'][row['role']] for row in copies['files']):
                raise ValueError('actual generated copy hash mismatch')
            self.inventory = dict(self.doc['inventory'])
            used = {os.path.normcase(str(Path(p).absolute())) for paths in self.inventory.values() for p in paths}
            for name in GENERATED_NAMES:
                path = str(Path(generated[name]).absolute())
                if os.path.normcase(path) in used:
                    raise ValueError('generated path duplicates baseline')
                used.add(os.path.normcase(path))
                self.inventory['generated:' + name] = [path]
            raw = self.map_reader()
            bootstrap = []
            for row in parse_maps(raw):
                key = os.path.normcase(row['path'])
                if key not in used:
                    bootstrap.append(row['path'])
                    used.add(key)
            if bootstrap:
                self.inventory['bootstrap:selfmaps'] = bootstrap
            self.before = snapshot(self.inventory)
            if self.doc['schema'] == 'capture-resource-binding-v3':
                known = {row['resolved']: row['identity'] for row in self.before['files']}
                limits = self.doc['runtime_maps']
                self.owned_maps = self.owned_factory(
                    self.output, known, max_maps_bytes=limits['max_maps_bytes'],
                    max_observations=limits['max_observations'])
            checked_baseline = [row for row in self.before['files'] if row['role'] in self.doc['inventory']]
            checked_copies = [dict(row, role=row['role'].removeprefix('generated:'))
                              for row in self.before['files'] if row['role'].startswith('generated:')]
            if (not _typed_equal(checked_baseline, baseline['files'])
                    or not _typed_equal(checked_copies, copies['files'])):
                raise ValueError('declared inputs changed between validation and merged snapshot')
            self.before.update(environment=actual_env, partition=environment.get('GZ_PARTITION'),
                               declaration=self.doc, generated=copies,
                               required_paths=[str(Path(p).absolute()) for p in required_paths],
                               launch_environment={key: environment.get(key) for key in (
                                   'HEADLESS', 'PX4_GZ_STANDALONE', 'PX4_SYS_AUTOSTART', 'PX4_GZ_WORLD',
                                   'PX4_SIM_MODEL', 'PX4_GZ_MODEL_NAME', 'PX4_UXRCE_DDS_PORT')})
            if self.doc['schema'] in ('capture-resource-binding-v2', 'capture-resource-binding-v3'):
                graph = self.doc['graph']
                if (str(Path.cwd()) != graph['cwd']
                        or not _typed_equal({k: environment.get(k) for k in QUERY_ENV_KEYS}, graph['environment'])
                        or any(environment.get(k) for k in ('LD_PRELOAD', 'LD_AUDIT'))):
                    raise ValueError('actual graph search context or loader environment differs')
                client = QueryClient(self.doc['inventory']['graph:resolver'][0], Path(graph['cwd']),
                                     graph['environment'], self.output)
                observed = client.query('context')
                write_manifest(self.output / 'resource-search-context.json', observed)
                if not _typed_equal(observed, graph['expected_context']):
                    raise ValueError('SDK search context differs from prospective declaration')
                self.graph_result = build_graph(generated['world.sdf'], client, self.before['files'], self.output)
                after_query = snapshot(self.inventory)
                write_manifest(self.output / 'runtime-binding-after-queries.json', after_query)
                if not _typed_equal(after_query['files'], self.before['files']):
                    raise ValueError('declared files changed during graph queries')
                client.check_budget()
                self.before['resource_graph'] = self.graph_result
                self._observe('postgraph', self.map_reader())
                client.check_budget()
            self._observe('bootstrap', raw)
            write_manifest(self.output / 'runtime-binding-pre.json', self.before)
            self.pre_recorded = True
        except Exception as exc:
            self.errors.append(repr(exc))
            raise

    def _observe(self, phase, raw):
        if re.fullmatch('[a-z][a-z0-9-]*', phase) is None or phase in self.phases:
            raise ValueError('invalid or repeated mapping phase')
        self.phases.append(phase)
        with (self.output / ('runtime-maps-' + phase + '.txt')).open('x', encoding='utf-8') as stream:
            if stream.write(raw) != len(raw):
                raise OSError('short maps write')
            stream.flush()
        known = {row['resolved']: row['identity'] for row in self.before['files']}
        unknown, mismatched, parse_error = [], [], None
        try:
            for row in parse_maps(raw):
                identity = known.get(row['path'])
                if identity is None:
                    unknown.append(row)
                elif (not hasattr(os, 'major') or row['inode'] != identity['inode']
                      or tuple(int(x, 16) for x in row['device'].split(':'))
                      != (os.major(identity['device']), os.minor(identity['device']))):
                    mismatched.append(row)
        except ValueError as exc:
            parse_error = repr(exc)
        record = dict(phase=phase, unknown=unknown, mismatched=mismatched, parse_error=parse_error,
                      observed_files_covered=not (unknown or mismatched or parse_error), runtime_closure_qualified=False)
        write_manifest(self.output / ('runtime-maps-' + phase + '.json'), record)
        if not record['observed_files_covered']:
            raise ValueError('process mapping not covered by declared pre snapshot')
        return record

    def observe(self, phase):
        if not self.pre_recorded or self.errors or self.closed:
            raise ValueError('binding unavailable for mapping phase')
        try:
            if self.required_self:
                index = len(self.completed_self)
                if index >= len(self.required_self) or phase != self.required_self[index]:
                    raise ValueError('out-of-order or undeclared self mapping phase')
            result = self._observe(phase, self.map_reader())
            if self.required_self:
                self.completed_self.append(phase)
            return result
        except Exception as exc:
            self.errors.append(repr(exc))
            raise

    def register_owned(self, role, process, executable):
        if not self.pre_recorded or self.errors or self.closed or role not in self.required_owned:
            raise ValueError('binding unavailable for owned registration')
        try:
            return self.owned_maps.register(role, process, executable)
        except Exception as exc:
            self.errors.append(repr(exc))
            raise

    def observe_owned(self, role, phase):
        if not self.pre_recorded or self.errors or self.closed or role not in self.required_owned:
            raise ValueError('binding unavailable for owned mapping phase')
        try:
            index = len(self.completed_owned[role])
            if index >= len(self.required_owned[role]) or phase != self.required_owned[role][index]:
                raise ValueError('out-of-order or undeclared owned mapping phase')
            result = self.owned_maps.observe(role, phase)
            self.completed_owned[role].append(phase)
            return result
        except Exception as exc:
            self.errors.append(repr(exc))
            raise

    def finish(self):
        if self.closed:
            raise ValueError('binding already closed')
        self.closed = True
        stable = False
        if self.before is None:
            attempt = dict(scope='declared inventory only; generated inputs unverified', error=None)
            try:
                attempt['snapshot'] = snapshot(self.doc['inventory'])
            except Exception as exc:
                attempt['error'] = repr(exc)
                self.errors.append(repr(exc))
            try:
                write_manifest(self.output / 'runtime-binding-post-attempt.json', attempt)
            except Exception as exc:
                self.errors.append(repr(exc))
        if self.before is not None:
            try:
                after = snapshot(self.inventory)
                write_manifest(self.output / 'runtime-binding-post.json', after)
                if not _typed_equal(self.before['files'], after['files']):
                    raise ValueError('declared input drift at post capture')
                stable = self.pre_recorded
            except Exception as exc:
                self.errors.append(repr(exc))
        mapping_complete = (self.doc['schema'] == 'capture-resource-binding-v3'
                            and self.completed_self == self.required_self
                            and self.completed_owned == self.required_owned)
        return dict(pre_recorded=self.pre_recorded, declared_files_stable=stable,
                    local_file_graph_verified=bool(self.graph_result and self.pre_recorded and stable
                                                  and not self.errors and self.graph_result['local_file_graph_verified']),
                    phases=self.phases, owned_phases=self.completed_owned,
                    runtime_mapping_coverage_verified=bool(mapping_complete and stable and not self.errors),
                    errors=list(self.errors), runtime_closure_qualified=False,
                    scope='declared self and registered owned phases only; whole runtime not qualified')


def attach_binding(journal, result, doc, output, *, map_reader=read_self_maps):
    obj = RuntimeBinding(doc, output, map_reader=map_reader)
    def finalize():
        result['runtime_binding'] = obj.finish()
        if (result['runtime_binding']['errors'] or not result['runtime_binding']['pre_recorded']
                or doc['schema'] == 'capture-resource-binding-v3'
                and not result['runtime_binding']['runtime_mapping_coverage_verified']):
            result['errors'].append('runtime binding: ' + json.dumps(result['runtime_binding']['errors']))
    journal.cleanup('runtime binding post', finalize, priority=110)
    return obj
