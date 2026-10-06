"""Strict, journaled SDK queries. No simulator or estimator process is launched."""
from __future__ import annotations

import json
import math
import subprocess
import time
from pathlib import Path

from tools.benchmark.capture_contract import _typed_equal, _unique_pairs
from tools.benchmark.declared_runtime_snapshot import write_manifest
from tools.benchmark.native_query_process import bounded_run

LOOKUP_KEYS = ('GZ_SIM_RESOURCE_PATH', 'SDF_PATH', 'GZ_FILE_PATH', 'GZ_PLUGIN_PATH',
               'GZ_SIM_SYSTEM_PLUGIN_PATH', 'HOME', 'GZ_HOMEDIR', 'GZ_MESH_FORCE_ASSIMP',
               'IGN_PLUGIN_PATH', 'IGN_FILE_PATH', 'IGN_GAZEBO_RESOURCE_PATH',
               'IGN_GAZEBO_SYSTEM_PLUGIN_PATH', 'GZ_LOG_PATH', 'IGN_LOG_PATH')
QUERY_ENV_KEYS = LOOKUP_KEYS + ('LD_LIBRARY_PATH', 'PATH', 'LANG')


def environment(value, keys=QUERY_ENV_KEYS):
    if (type(value) is not dict or set(value) != set(keys)
            or any(v is not None and type(v) is not str for v in value.values())
            or sum(len(v or '') for v in value.values()) > 65536):
        raise ValueError('explicit finite query environment required')
    return dict(value)


def _reject_constant(value):
    raise ValueError('nonfinite query JSON: ' + value)


def _shape(doc, strings=(), arrays=(), flags=(), nullable=(), extra=()):
    keys = set(strings) | set(arrays) | set(flags) | set(nullable) | set(extra)
    if type(doc) is not dict or set(doc) != keys:
        raise ValueError('native response schema keys')
    if any(type(doc[k]) is not str for k in strings):
        raise ValueError('native response string type')
    if any(type(doc[k]) is not list or any(type(v) is not str for v in doc[k]) for k in arrays):
        raise ValueError('native response array type')
    if any(type(doc[k]) is not bool for k in flags) or any(doc[k] is not None for k in nullable):
        raise ValueError('native response flag/unknown type')


def validate_response(doc, args, cwd, env):
    op = args[0]
    if op == 'installation':
        _shape(doc, strings=('media', 'plugins', 'classic_material'))
    elif op == 'plugin':
        _shape(doc, strings=('error', 'selected', 'normalized', 'candidate_profile'),
               arrays=('paths', 'candidates', 'examined_paths'), flags=('ok', 'runtime_closure_qualified'))
        if (doc['ok'] is not True or doc['error'] or doc['candidate_profile'] != 'common-442a7ab-spellings'
                or doc['normalized'] != args[1].replace('ignition-gazebo', 'gz-sim', 1)
                or doc['candidates'] != [doc['selected']] or not doc['examined_paths']):
            raise ValueError('unqualified plugin candidates')
    elif op == 'bound-uri':
        _shape(doc, strings=('kind', 'source', 'uri', 'transformed', 'lookup_selected', 'selected',
                            'model_config', 'cwd', 'error', 'local_profile', 'selection_profile'),
               arrays=('local_candidates', 'shadowed_candidates', 'examined_paths',
                       'candidate_dependencies'),
               flags=('ok', 'local_candidates_qualified', 'ambiguity_qualified', 'runtime_closure_qualified'),
               extra=('before_environment', 'after_environment'))
        if ([doc['kind'], doc['source'], doc['uri']] != list(args[1:]) or doc['cwd'] != str(cwd)
                or doc['ok'] is not True or doc['error'] or doc['local_candidates_qualified'] is not True
                or doc['local_profile'] != 'fixed-local-files-v1'
                or doc['local_candidates'] != [doc['selected']] or not doc['examined_paths']
                or doc['ambiguity_qualified'] is not False):
            raise ValueError('unqualified or mismatched native URI response')
        if (doc['kind'] == 'collada-image'):
            if (doc['selection_profile'] != 'material-ordered-fallback-v1'
                    or doc['selected'] in doc['shadowed_candidates']
                    or len(set(doc['shadowed_candidates'])) != len(doc['shadowed_candidates'])):
                raise ValueError('invalid COLLADA ordered fallback evidence')
        elif doc['selection_profile'] != 'unique-canonical-v1' or doc['shadowed_candidates']:
            raise ValueError('unexpected shadowed candidates')
    elif op == 'context':
        _shape(doc, strings=('cwd', 'sdf_share_path', 'sdf_version', 'common_callback_observation'),
               arrays=('file_paths', 'plugin_paths'),
               flags=('sdf_callback_present', 'search_context_qualified', 'runtime_closure_qualified'),
               nullable=('common_file_callbacks_present', 'common_uri_callbacks_present'),
               extra=('sdf_uri_paths', 'before_environment', 'after_environment'))
        if (doc['cwd'] != str(cwd) or doc['sdf_callback_present'] is not False
                or doc['search_context_qualified'] is not False or doc['sdf_uri_paths'] != {}
                or doc['common_callback_observation'] != 'unavailable: SDK has no callback inspection API'):
            raise ValueError('unsupported SDK context')
    else:
        raise ValueError('unsupported query operation')
    if op in ('context', 'bound-uri'):
        for key in ('before_environment', 'after_environment'):
            environment(doc[key], LOOKUP_KEYS)
        if not _typed_equal(doc['before_environment'], {k: env[k] for k in LOOKUP_KEYS}):
            raise ValueError('native query environment mismatch')
    if op != 'installation' and doc['runtime_closure_qualified'] is not False:
        raise ValueError('unexpected native runtime qualification')
    return doc


class QueryClient:
    def __init__(self, binary, cwd, env, output, *, runner=bounded_run, clock=time.monotonic):
        self.binary, self.cwd, self.output = Path(binary), Path(cwd), Path(output)
        if not self.binary.is_absolute() or not self.cwd.is_absolute():
            raise ValueError('absolute query executable and cwd required')
        self.env, self.runner, self.clock = environment(env), runner, clock
        self.started = self.last = clock()
        self.count, self.failed = 0, False

    def check_budget(self):
        now = self.clock()
        if (self.failed or not math.isfinite(now) or not math.isfinite(self.started)
                or now < self.last or now - self.started >= 60):
            self.failed = True
            raise ValueError('native graph query budget/clock exceeded')
        self.last = now
        return now

    def query(self, *args):
        if self.failed:
            raise ValueError('native query client failed')
        record = None
        number = self.count
        try:
            now = self.check_budget()
            if self.count >= 512:
                raise ValueError('native graph query budget exceeded')
            if not args or args[0] not in ('installation', 'context', 'plugin', 'bound-uri'):
                raise ValueError('unsupported native operation')
            if any(type(arg) is not str or len(arg) > 16384 or '\x00' in arg for arg in args):
                raise ValueError('invalid native query argument')
            self.last = now
            self.count += 1
            command = [str(self.binary), *args]
            record = dict(command=command, cwd=str(self.cwd), environment=self.env,
                          started_monotonic=now, stdout='', stderr='', returncode=None, error=None)
            try:
                p = self.runner(command, cwd=self.cwd, env={k: v for k, v in self.env.items() if v is not None},
                                capture_output=True, text=False, timeout=min(10, 60 - (now - self.started)))
                for key, data in (('stdout', p.stdout), ('stderr', p.stderr)):
                    raw = data.encode('utf-8') if isinstance(data, str) else data
                    if not isinstance(raw, bytes):
                        raise ValueError('native output must be bytes')
                    record[key + '_hex'] = raw[:1024 * 1024].hex()
                    record[key] = raw[:1024 * 1024].decode('utf-8', errors='replace')
                record.update(returncode=p.returncode,
                              output_limit_exceeded=getattr(p, 'output_limit_exceeded', False),
                              collection_errors=getattr(p, 'collection_errors', []))
            except subprocess.TimeoutExpired as exc:
                for key, data in (('stdout', exc.stdout), ('stderr', exc.stderr)):
                    record[key] = data.decode('utf-8', errors='replace') if isinstance(data, bytes) else data or ''
                    if isinstance(data, bytes):
                        record[key + '_hex'] = data.hex()
                record['error'] = repr(exc)
                raise
            except Exception as exc:
                record['error'] = repr(exc)
                raise
            finally:
                record['ended_monotonic'] = self.clock()
                write_manifest(self.output / f'resource-query-{number:04d}.json', record)
            end = record['ended_monotonic']
            if not math.isfinite(end) or end < now or end - self.started >= 60:
                raise ValueError('native graph query budget/clock exceeded')
            self.last = end
            if (type(p.returncode) is not int or p.returncode != 0
                    or record['output_limit_exceeded'] or record['collection_errors']
                    or len(p.stdout) + len(p.stderr) > 1024 * 1024):
                raise ValueError('native query failed or oversized output')
            try:
                stdout = p.stdout.decode('utf-8') if isinstance(p.stdout, bytes) else p.stdout
                if isinstance(p.stderr, bytes):
                    p.stderr.decode('utf-8')
            except UnicodeError as exc:
                raise ValueError('invalid native UTF-8') from exc
            doc = json.loads(stdout, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
            return validate_response(doc, args, self.cwd, self.env)
        except Exception as exc:
            self.failed = True
            write_manifest(self.output / f'resource-query-{number:04d}-refusal.json', dict(error=repr(exc)))
            raise
