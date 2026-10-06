"""Bind a declared baseline and generated inputs before capture initializes native code.

Self-process mapping observations are phase evidence, never whole-runtime qualification.
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

from tools.benchmark.capture_contract import _typed_equal
from tools.benchmark.declared_runtime_snapshot import snapshot, write_manifest

GENERATED_NAMES = ('world.sdf', 'world.json', 'ground_albedo.png', 'obstacle_albedo.png', 'board_albedo.png', 'gz_env.sh')
ENV_KEYS = ('GZ_SIM_RESOURCE_PATH', 'GZ_SIM_SYSTEM_PLUGIN_PATH', 'GZ_SIM_SERVER_CONFIG_PATH',
            'LD_LIBRARY_PATH', 'PYTHONPATH', 'SDF_PATH', 'GZ_FILE_PATH', 'GZ_HOMEDIR', 'HOME')


def validate_binding(doc):
    if type(doc) is not dict or set(doc) != {'schema', 'inventory', 'baseline', 'environment', 'generated'}:
        raise ValueError('binding declaration schema keys')
    if doc['schema'] != 'capture-resource-binding-v1':
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
            self.before.update(environment=actual_env, partition=environment.get('GZ_PARTITION'),
                               declaration=self.doc, generated=copies,
                               required_paths=[str(Path(p).absolute()) for p in required_paths],
                               launch_environment={key: environment.get(key) for key in (
                                   'HEADLESS', 'PX4_GZ_STANDALONE', 'PX4_SYS_AUTOSTART', 'PX4_GZ_WORLD',
                                   'PX4_SIM_MODEL', 'PX4_GZ_MODEL_NAME', 'PX4_UXRCE_DDS_PORT')})
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
