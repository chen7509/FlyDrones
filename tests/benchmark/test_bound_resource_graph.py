import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tools.benchmark import runtime_resource_binding as binding
from tools.benchmark.declared_runtime_snapshot import snapshot


def api():
    from tools.benchmark.bound_resource_graph import build_graph
    from tools.benchmark.native_resource_client import QUERY_ENV_KEYS, QueryClient
    return build_graph, QueryClient, QUERY_ENV_KEYS


def test_required_graph_interfaces_exist():
    assert Path('tools/benchmark/bound_resource_graph.py').is_file()
    assert Path('tools/benchmark/native_resource_client.py').is_file()


@pytest.mark.parametrize('failure', ['nonzero', 'timeout', 'duplicate', 'nonfinite', 'extra', 'wrong_type'])
def test_query_failure_keeps_raw_and_locks(tmp_path, failure):
    _, client_type, keys = api()
    def runner(*args, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(args[0], 10, output=b'partial', stderr=b'error')
        payload = dict(media=str(tmp_path), plugins=str(tmp_path), classic_material=str(tmp_path / 'gazebo.material'))
        raw = json.dumps(payload)
        if failure == 'duplicate':
            raw = raw[:-1] + ',"media":"duplicate"}'
        elif failure == 'nonfinite':
            raw = '{"media":NaN}'
        elif failure == 'extra':
            payload['extra'] = True
            raw = json.dumps(payload)
        elif failure == 'wrong_type':
            payload['plugins'] = 1
            raw = json.dumps(payload)
        return subprocess.CompletedProcess(args[0], 2 if failure == 'nonzero' else 0, raw, 'native detail')
    client = client_type(tmp_path / 'resolver', tmp_path, {key: None for key in keys}, tmp_path, runner=runner)
    with pytest.raises((ValueError, subprocess.TimeoutExpired)):
        client.query('installation')
    assert (tmp_path / 'resource-query-0000.json').is_file()
    saved = json.loads((tmp_path / 'resource-query-0000.json').read_text())
    assert saved['stderr']
    with pytest.raises(ValueError, match='failed'):
        client.query('installation')
    assert not (tmp_path / 'resource-query-0001.json').exists()


def test_query_validated_output_and_clock_limit(tmp_path):
    _, client_type, keys = api()
    ticks = iter([0.0, 61.0])
    client = client_type(tmp_path / 'resolver', tmp_path, {key: None for key in keys}, tmp_path,
                         clock=lambda: next(ticks))
    with pytest.raises(ValueError, match='budget'):
        client.query('installation')


class GraphClient:
    def __init__(self, files):
        self.files = files
    def query(self, op, kind, source, uri):
        target = self.files[uri]
        return dict(selected=str(target), lookup_selected=str(target), model_config='',
                    candidate_dependencies=[], local_candidates_qualified=True)


def test_recursive_graph_preserves_duplicate_edges(tmp_path):
    build, _, _ = api()
    world, model, image = (tmp_path / n for n in ('world.sdf', 'model.sdf', 'image.png'))
    world.write_text('<sdf><world><include><uri>x</uri></include><include><uri>x</uri></include></world></sdf>')
    model.write_text('<sdf><model><material><pbr><metal><albedo_map>image.png</albedo_map></metal></pbr></material></model></sdf>')
    image.write_bytes(b'pixels')
    before = snapshot({'files': [str(world), str(model), str(image)]})
    graph = build(world, GraphClient({'x': model, 'image.png': image}), before['files'], tmp_path)
    assert len(graph['edges']) == 3
    assert len(graph['documents']) == 2
    assert graph['local_file_graph_verified'] is True
    assert graph['runtime_closure_qualified'] is False


@pytest.mark.parametrize('failure', ['undeclared', 'drift', 'cycle', 'unsupported'])
def test_graph_partial_evidence_and_refusal(tmp_path, failure):
    build, _, _ = api()
    world, target = tmp_path / 'world.sdf', tmp_path / 'target.sdf'
    world.write_text('<sdf><include><uri>x</uri></include></sdf>')
    target.write_text('<sdf/>')
    if failure == 'unsupported':
        world.write_text('<sdf><heightmap><uri>x</uri></heightmap></sdf>')
    before = snapshot({'files': [str(world)] + ([] if failure == 'undeclared' else [str(target)])})
    if failure == 'drift':
        world.write_text('<sdf><model/></sdf>')
    if failure == 'cycle':
        target = world
    with pytest.raises(ValueError):
        build(world, GraphClient({'x': target}), before['files'], tmp_path)
    result = json.loads((tmp_path / 'resource-graph.json').read_text())
    assert result['errors'] and result['local_file_graph_verified'] is False


def test_runtime_v1_reports_graph_not_verified(tmp_path):
    from tests.benchmark.test_runtime_resource_binding import fixture
    doc, generated, source, output = fixture(tmp_path)
    obj = binding.RuntimeBinding(doc, output, map_reader=lambda: '')
    obj.start(generated, doc['environment'], [source])
    assert obj.finish()['local_file_graph_verified'] is False


def graph_fixture(tmp_path):
    from tests.benchmark.test_runtime_resource_binding import fixture
    _, _, keys = api()
    doc, generated, binary, output = fixture(tmp_path)
    cpp, dep = tmp_path / 'resolver.cc', tmp_path / 'library.so'
    cpp.write_text('source')
    dep.write_bytes(b'lib')
    generated['world.sdf'].write_text('<sdf/>')
    doc['generated']['world.sdf'] = hashlib.sha256(generated['world.sdf'].read_bytes()).hexdigest()
    doc['schema'] = 'capture-resource-binding-v2'
    doc['inventory'] = {'graph:resolver': [str(binary)], 'graph:source': [str(cpp)], 'graph:dependencies': [str(dep)]}
    doc['baseline'] = snapshot(doc['inventory'])
    env = {k: None for k in keys}
    from tools.benchmark.native_resource_client import LOOKUP_KEYS
    context = dict(cwd=str(Path.cwd()), sdf_share_path=str(tmp_path), sdf_version='1.11',
                   common_callback_observation='unavailable: SDK has no callback inspection API',
                   file_paths=[], plugin_paths=[], sdf_callback_present=False,
                   search_context_qualified=False, runtime_closure_qualified=False,
                   common_file_callbacks_present=None, common_uri_callbacks_present=None,
                   sdf_uri_paths={}, before_environment={k: None for k in LOOKUP_KEYS},
                   after_environment={k: None for k in LOOKUP_KEYS})
    doc['graph'] = dict(schema='generated-resource-graph-v1', cwd=str(Path.cwd()),
                        environment=env, expected_context=context)
    return doc, generated, binary, dep, output


@pytest.mark.parametrize('failure', [None, 'context', 'query', 'drift'])
def test_runtime_v2_graph_gate_and_post(tmp_path, monkeypatch, failure):
    doc, generated, binary, dep, output = graph_fixture(tmp_path)
    calls = []
    class Client:
        def __init__(self, *args):
            calls.append('client')
            assert not (output / 'runtime-binding-pre.json').exists()
        def query(self, *args):
            if failure == 'query':
                raise ValueError('native refused')
            if failure == 'drift':
                dep.write_bytes(b'changed')
            context = dict(doc['graph']['expected_context'])
            if failure == 'context':
                context['file_paths'] = ['different']
            return context
    monkeypatch.setattr(binding, 'QueryClient', Client, raising=False)
    obj = binding.RuntimeBinding(doc, output, map_reader=lambda: '')
    env = doc['environment'] | doc['graph']['environment']
    if failure:
        with pytest.raises(ValueError):
            obj.start(generated, env, [binary])
    else:
        obj.start(generated, env, [binary])
    assert calls == ['client']
    terminal = obj.finish()
    assert terminal['local_file_graph_verified'] is (failure is None)
    assert (output / 'runtime-binding-post.json').is_file()
    assert (output / 'runtime-binding-pre.json').exists() is (failure is None)


def test_v2_missing_resolver_source_role_refuses(tmp_path):
    doc, _, _, _, _ = graph_fixture(tmp_path)
    del doc['inventory']['graph:source']
    with pytest.raises(ValueError):
        binding.validate_binding(doc)


def test_plugin_response_echo_must_match_requested_name(tmp_path):
    from tools.benchmark.native_resource_client import validate_response
    response = dict(ok=True, error='', selected=str(tmp_path / 'x.so'), normalized='wrong-name',
                    candidate_profile='common-442a7ab-spellings', paths=[str(tmp_path)],
                    candidates=[str(tmp_path / 'x.so')], examined_paths=[str(tmp_path / 'x.so')],
                    runtime_closure_qualified=False)
    with pytest.raises(ValueError):
        validate_response(response, ('plugin', 'wanted-name'), tmp_path, {})


@pytest.mark.parametrize('failure', ['echo', 'numeric_bool', 'environment', 'ambiguous', 'unknown_key', 'unqualified'])
def test_native_uri_protocol_rejects_mismatched_evidence(tmp_path, failure):
    from tools.benchmark.native_resource_client import LOOKUP_KEYS, validate_response
    source, target = str(tmp_path / 'source.sdf'), str(tmp_path / 'image.png')
    env = {key: None for key in LOOKUP_KEYS}
    doc = dict(ok=True, kind='texture', source=source, uri='image.png', transformed=target,
               lookup_selected=target, selected=target, model_config='', cwd=str(tmp_path), error='',
               local_profile='fixed-local-files-v1', local_candidates=[target], examined_paths=[target],
               candidate_dependencies=[], local_candidates_qualified=True, ambiguity_qualified=False,
               runtime_closure_qualified=False, before_environment=dict(env), after_environment=dict(env))
    args = ('bound-uri', 'texture', source, 'image.png')
    assert validate_response(doc, args, tmp_path, env) == doc
    if failure == 'echo':
        doc['uri'] = 'different.png'
    elif failure == 'numeric_bool':
        doc['ok'] = 1
    elif failure == 'environment':
        doc['before_environment']['SDF_PATH'] = 'different'
    elif failure == 'ambiguous':
        doc['local_candidates'].append('other')
    elif failure == 'unknown_key':
        doc['ignored'] = False
    else:
        doc['local_candidates_qualified'] = False
    with pytest.raises(ValueError):
        validate_response(doc, args, tmp_path, env)
