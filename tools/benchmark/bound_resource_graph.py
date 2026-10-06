"""Original-byte dependency graph, restricted to explicitly snapshotted inputs."""
from __future__ import annotations

import hashlib
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import write_manifest
from tools.benchmark.selected_resource_graph import references

CLASSIC = 'file://media/materials/scripts/gazebo.material'


def build_graph(world, client, known_rows, output):
    known = {p: row for row in known_rows if not row['role'].startswith('bootstrap:') for p in (row['requested'], row['resolved'])}
    result = dict(schema='bound-local-resource-graph-v1', documents=[], edges=[], errors=[],
                  local_file_graph_verified=False, runtime_closure_qualified=False,
                  scope='fixed local file dependencies; no decoding, rendering or runtime callback proof')
    visited = set()
    installation = None

    def declared(path):
        if type(path) is not str or not Path(path).is_absolute() or '..' in Path(path).parts or path not in known:
            raise ValueError('selected resource absent from declared baseline: ' + str(path))
        return known[path]

    def source_bytes(path):
        client.check_budget()
        row = declared(path)
        if row['bytes'] > 32 * 1024 * 1024:
            raise ValueError('source exceeds 32MiB graph limit')
        with Path(path).open('rb') as stream:
            data = stream.read(32 * 1024 * 1024 + 1)
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('original source drift after baseline')
        client.check_budget()
        return row, data

    def visit(path, format, ancestors):
        nonlocal installation
        row, data = source_bytes(path)
        identity = row['resolved']
        if identity in ancestors:
            raise ValueError('cyclic resource graph')
        if (path, format) in visited:
            return
        if len(visited) >= 256 or len(ancestors) >= 32:
            raise ValueError('resource graph document/depth limit')
        visited.add((path, format))
        result['documents'].append(dict(source=path, canonical=identity, sha256=row['sha256'], format=format))
        refs = references(data, format)
        client.check_budget()
        for ref in refs:
            client.check_budget()
            if len(result['edges']) >= 4096:
                raise ValueError('resource graph edge limit')
            edge = dict(source=path, **ref, status='unresolved')
            result['edges'].append(edge)
            kind, uri = ref['kind'], ref['text']
            if kind in ('script', 'material-name'):
                parent = ref['position'].rsplit('/', 1)[0]
                paired = any(x['kind'] == 'script' and x['text'] == CLASSIC
                             and x['position'].rsplit('/', 1)[0] == parent for x in refs)
                if ((kind == 'script' and uri != CLASSIC)
                        or (kind == 'material-name' and (uri != 'Gazebo/DarkGrey' or not paired))):
                    raise ValueError('unsupported classic material profile')
                if installation is None:
                    installation = client.query('installation')
                target = installation['classic_material']
                declared(target)
                edge.update(selected=target, status='classic-dependency-only')
            elif kind == 'plugin':
                reply = client.query('plugin', uri)
                target = reply['selected']
                declared(target)
                edge.update(selected=target, query=reply, status='selected')
            elif kind in ('include', 'mesh', 'texture', 'collada-image'):
                reply = client.query('bound-uri', 'mesh-path' if kind == 'mesh' else kind, path, uri)
                target = reply['selected']
                declared(target)
                shadowed = reply.get('shadowed_candidates', [])
                for dependency in (reply['candidate_dependencies'] + shadowed
                                   + ([reply['model_config']] if reply['model_config'] else [])):
                    declared(dependency)
                edge.update(selected=target, shadowed_candidates=shadowed,
                            query=reply, status='selected')
                if kind == 'include':
                    visit(reply['lookup_selected'], 'sdf', ancestors + (identity,))
                elif kind == 'mesh':
                    suffix = Path(target).suffix.lower()
                    if suffix == '.dae':
                        visit(reply['lookup_selected'], 'dae', ancestors + (identity,))
                    elif suffix != '.stl':
                        raise ValueError('unsupported mesh dependency format')
            else:
                raise ValueError('unsupported resource edge: ' + kind)
        return

    try:
        visit(str(world), 'sdf', ())
        client.check_budget()
        result['local_file_graph_verified'] = True
        return result
    except Exception as exc:
        result['errors'].append(repr(exc))
        raise
    finally:
        write_manifest(Path(output) / 'resource-graph.json', result)
