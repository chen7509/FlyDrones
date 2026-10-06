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

GENERATED_NAMES = ('world.sdf', 'world.json', 'ground_albedo.png', 'obstacle_albedo.png', 'board_albedo.png', 'gz_env.sh')
ENV_KEYS = ('GZ_SIM_RESOURCE_PATH', 'GZ_SIM_SYSTEM_PLUGIN_PATH', 'GZ_SIM_SERVER_CONFIG_PATH',
            'LD_LIBRARY_PATH', 'PYTHONPATH', 'SDF_PATH', 'GZ_FILE_PATH', 'GZ_HOMEDIR', 'HOME')


def validate_binding(doc):
    if type(doc) is not dict:
        raise ValueError('binding declaration schema keys')
    version = doc.get('schema')
    keys = {'schema', 'inventory', 'baseline', 'environment', 'generated'}
    if version == 'capture-resource-binding-v2':
        keys.add('graph')
    if set(doc) != keys:
        raise ValueError('binding declaration schema keys')
    if version not in ('capture-resource-binding-v1', 'capture-resource-binding-v2'):
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
    if (type(env) is not dict or set(env) != set(ENV_KEYS)
            or any(v is not None and type(v) is not str for v in env.values())):
        raise ValueError('binding environment must explicitly include lookup keys')
    generated = doc['generated']
    if (type(generated) is not dict or set(generated) != set(GENERATED_NAMES)
            or any(type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None for v in generated.values())):
        raise ValueError('binding generated hashes required')
    if version == 'capture-resource-binding-v2':
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
    return copy.deepcopy(doc)


def parse_maps(text):
    rows, seen = [], set()
    for line in text.splitlines():
        fields = line.split(maxsplit=5)
        if (len(fields) < 5 or not re.fullmatch(r'[0-9a-f]+-[0-9a-f]+', fields[0])
                or not re.fullmatch(r'[r-][w-][x-][ps]', fields[1])
                or not re.fullmatch(r'[0-9a-f]+', fields[2])
                or not re.fullmatch(r'[0-9a-f]+:[0-9a-f]+', fields[3])
                or not fields[4].isdigit()):
            raise ValueError('malformed process mapping')
        if len(fields) == 5 or (fields[5].startswith('[') and fields[5].endswith(']')):
            continue
        path = fields[5]
        if not path.startswith('/') or path.endswith(' (deleted)') or '\\' in path:
            raise ValueError('deleted/escaped/nonabsolute process mapping')
        identity = (path, fields[3], int(fields[4]))
        if identity not in seen:
            seen.add(identity)
            rows.append(dict(path=path, device=fields[3], inode=int(fields[4])))
    return rows


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
    def __init__(self, doc, output, *, map_reader=read_self_maps):
        self.doc = validate_binding(doc)
        self.output, self.map_reader = Path(output), map_reader
        self.pre_recorded = False
        self.before = None
        self.inventory = None
        self.errors = []
        self.phases = []
        self.closed = False
        self.graph_result = None

    def start(self, generated, environment, required_paths):
        if self.before is not None or self.pre_recorded or self.errors or self.closed:
            raise ValueError('binding already started or failed')
        try:
            actual_env = {key: environment.get(key) for key in ENV_KEYS}
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
            if self.doc['schema'] == 'capture-resource-binding-v2':
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
            return self._observe(phase, self.map_reader())
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
        return dict(pre_recorded=self.pre_recorded, declared_files_stable=stable,
                    local_file_graph_verified=bool(self.graph_result and self.pre_recorded and stable
                                                  and not self.errors and self.graph_result['local_file_graph_verified']),
                    phases=self.phases, errors=list(self.errors), runtime_closure_qualified=False,
                    scope='self-process phases only; lazy plugins and other processes not qualified')


def attach_binding(journal, result, doc, output, *, map_reader=read_self_maps):
    obj = RuntimeBinding(doc, output, map_reader=map_reader)
    def finalize():
        result['runtime_binding'] = obj.finish()
        if result['runtime_binding']['errors'] or not result['runtime_binding']['pre_recorded']:
            result['errors'].append('runtime binding: ' + json.dumps(result['runtime_binding']['errors']))
    journal.cleanup('runtime binding post', finalize, priority=110)
    return obj
