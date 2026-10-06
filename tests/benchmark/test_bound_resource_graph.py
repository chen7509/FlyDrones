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
    def check_budget(self):
        return 0.0


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
        def check_budget(self):
            return 0.0
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


@pytest.mark.parametrize('failure', ['extra', 'role', 'duplicate', 'bytes', 'count'])
def test_v3_runtime_map_schema_is_strict(tmp_path, failure):
    doc, _, _, _, _ = graph_fixture(tmp_path)
    doc['schema'] = 'capture-resource-binding-v3'
    runtime = dict(self_phases=['postimports', 'postfinalize', 'postfirststep'],
                   owned_roles={'px4': ['ready', 'prestop']},
                   max_maps_bytes=1024, max_observations=8)
    doc['runtime_maps'] = runtime
    if failure == 'extra':
        runtime['ignored'] = True
    elif failure == 'role':
        runtime['owned_roles'] = {'unknown': ['ready']}
    elif failure == 'duplicate':
        runtime['self_phases'] = ['postimports', 'postimports']
    elif failure == 'bytes':
        runtime['max_maps_bytes'] = 8 * 1024 * 1024 + 1
    else:
        runtime['max_observations'] = True
    with pytest.raises(ValueError, match='runtime map'):
        binding.validate_binding(doc)


def test_v3_requires_all_self_and_owned_phases_for_mapping_qualification(tmp_path, monkeypatch):
    doc, generated, binary, _, output = graph_fixture(tmp_path)
    doc['schema'] = 'capture-resource-binding-v3'
    doc['runtime_maps'] = dict(self_phases=['postimports'], owned_roles={'px4': ['ready']},
                               max_maps_bytes=1024, max_observations=2)
    class Client:
        def __init__(self, *_args):
            pass
        def query(self, *_args):
            return dict(doc['graph']['expected_context'])
        def check_budget(self):
            return 0.0
    class Owned:
        def __init__(self, *_args, **_kwargs):
            self.calls = []
        def register(self, role, _process, executable):
            self.calls.append(('register', role, str(executable)))
            return {'role': role}
        def observe(self, role, phase):
            self.calls.append(('observe', role, phase))
            return {'observed_files_covered': True}
    monkeypatch.setattr(binding, 'QueryClient', Client)
    obj = binding.RuntimeBinding(doc, output, map_reader=lambda: '', owned_factory=Owned)
    obj.start(generated, doc['environment'] | doc['graph']['environment'], [binary])
    assert obj.finish()['runtime_mapping_coverage_verified'] is False

    output2 = tmp_path / 'capture2'
    output2.mkdir()
    obj = binding.RuntimeBinding(doc, output2, map_reader=lambda: '', owned_factory=Owned)
    obj.start(generated, doc['environment'] | doc['graph']['environment'], [binary])
    obj.observe('postimports')
    obj.register_owned('px4', type('P', (), {'pid': 123})(), binary)
    obj.observe_owned('px4', 'ready')
    result = obj.finish()
    assert result['runtime_mapping_coverage_verified'] is True
    assert result['runtime_closure_qualified'] is False


def test_v3_missing_required_phase_is_a_terminal_journal_error(tmp_path, monkeypatch):
    from tools.benchmark.disarmed_sensor_provenance import CaptureJournal

    doc, generated, binary, _, output = graph_fixture(tmp_path)
    doc['schema'] = 'capture-resource-binding-v3'
    doc['runtime_maps'] = dict(self_phases=['postimports'], owned_roles={'px4': ['ready']},
                               max_maps_bytes=1024, max_observations=2)
    class Client:
        def __init__(self, *_args):
            pass
        def query(self, *_args):
            return dict(doc['graph']['expected_context'])
        def check_budget(self):
            return 0.0
    class Owned:
        def __init__(self, *_args, **_kwargs):
            pass
    monkeypatch.setattr(binding, 'QueryClient', Client)
    monkeypatch.setattr(binding, 'OwnedRuntimeMaps', Owned)
    result = {'status': 'incomplete', 'errors': []}
    with CaptureJournal(output, result) as journal:
        obj = binding.attach_binding(journal, result, doc, output, map_reader=lambda: '')
        obj.owned_factory = Owned
        obj.start(generated, doc['environment'] | doc['graph']['environment'], [binary])
    assert any(error.startswith('runtime binding:') for error in result['errors'])
    assert result['runtime_binding']['runtime_mapping_coverage_verified'] is False


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
               shadowed_candidates=[], selection_profile='unique-canonical-v1',
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


def test_shadowed_collada_candidate_must_be_declared(tmp_path):
    build, _, _ = api()
    world = tmp_path / 'world.sdf'
    dae = tmp_path / 'model.dae'
    selected = tmp_path / 'meshes.png'
    shadowed = tmp_path / 'materials.png'
    world.write_text('<sdf><model><link><visual><geometry><mesh><uri>model.dae</uri></mesh></geometry></visual></link></model></sdf>')
    dae.write_text('<COLLADA><library_images><image><init_from>image.png</init_from></image></library_images></COLLADA>')
    selected.write_bytes(b'a')
    shadowed.write_bytes(b'b')

    class Client(GraphClient):
        def query(self, *args):
            if args[1] == 'mesh-path':
                return dict(selected=str(dae), lookup_selected=str(dae),
                            candidate_dependencies=[], model_config='', shadowed_candidates=[])
            return dict(selected=str(selected), lookup_selected=str(selected),
                        candidate_dependencies=[], model_config='',
                        shadowed_candidates=[str(shadowed)])

    rows = snapshot({'declared': [str(world), str(dae), str(selected)]})['files']
    (tmp_path / 'refused').mkdir()
    with pytest.raises(ValueError, match='declared'):
        build(world, Client({}), rows, tmp_path / 'refused')
    rows = snapshot({'declared': [str(world), str(dae), str(selected), str(shadowed)]})['files']
    (tmp_path / 'accepted').mkdir()
    result = build(world, Client({}), rows, tmp_path / 'accepted')
    image_edge = next(edge for edge in result['edges'] if edge['kind'] == 'collada-image')
    assert image_edge['shadowed_candidates'] == [str(shadowed)]


def test_bootstrap_mapping_cannot_authorize_graph_target(tmp_path):
    build, _, _ = api()
    world, mapped = tmp_path / 'world.sdf', tmp_path / 'mapped.so'
    world.write_text('<sdf><plugin name="x" filename="mapped"/></sdf>')
    mapped.write_bytes(b'mapped but not declared')
    before = snapshot({'declared': [str(world)], 'bootstrap:selfmaps': [str(mapped)]})
    class Client(GraphClient):
        def query(self, *args):
            return dict(selected=str(mapped))
    with pytest.raises(ValueError, match='declared'):
        build(world, Client({}), before['files'], tmp_path)


def test_projector_texture_cannot_be_silently_omitted(tmp_path):
    build, _, _ = api()
    world = tmp_path / 'world.sdf'
    world.write_text('<sdf><model><link><projector><texture>missing.png</texture></projector></link></model></sdf>')
    before = snapshot({'declared': [str(world)]})
    with pytest.raises(ValueError, match='unsupported'):
        build(world, GraphClient({}), before['files'], tmp_path)
    assert json.loads((tmp_path / 'resource-graph.json').read_text())['edges'][0]['text'] == 'missing.png'


def test_graph_deadline_covers_source_processing_without_queries(tmp_path):
    build, client_type, keys = api()
    world = tmp_path / 'world.sdf'
    world.write_text('<sdf/>')
    ticks = iter([0.0, 0.0, 61.0])
    client = client_type(tmp_path / 'binary', tmp_path, {k: None for k in keys}, tmp_path,
                         clock=lambda: next(ticks))
    with pytest.raises(ValueError, match='budget'):
        build(world, client, snapshot({'declared': [str(world)]})['files'], tmp_path)


def test_invalid_bytes_keep_raw_query_evidence(tmp_path):
    _, client_type, keys = api()
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, b'\xff', b'\xfe')
    client = client_type(tmp_path / 'binary', tmp_path, {k: None for k in keys}, tmp_path, runner=runner)
    with pytest.raises(ValueError):
        client.query('installation')
    record = json.loads((tmp_path / 'resource-query-0000.json').read_text())
    assert record['stdout_hex'] == 'ff' and record['stderr_hex'] == 'fe'


def test_bounded_native_byte_runner_exists():
    assert Path('tools/benchmark/native_query_process.py').is_file()


def test_early_pre_failure_has_post_attempt(tmp_path):
    from tests.benchmark.test_runtime_resource_binding import fixture
    doc, generated, source, output = fixture(tmp_path)
    source.write_bytes(b'drift')
    obj = binding.RuntimeBinding(doc, output, map_reader=lambda: '')
    with pytest.raises(ValueError):
        obj.start(generated, doc['environment'], [source])
    result = obj.finish()
    assert (output / 'runtime-binding-post-attempt.json').is_file()
    assert result['declared_files_stable'] is False


def test_real_byte_runner_limits_and_preserves_output(tmp_path):
    import os
    import sys

    from tools.benchmark.native_query_process import LIMIT, bounded_run
    for code, overflow in [("import os; os.write(1,b'\\xff')", False),
                           ("import os; os.write(1,b'x'*(2*1024*1024))", True)]:
        result = bounded_run([sys.executable, '-c', code], cwd=tmp_path, env=dict(os.environ), timeout=5)
        assert result.output_limit_exceeded is overflow
        assert len(result.stdout) + len(result.stderr) <= LIMIT
        if not overflow:
            assert result.stdout == b'\xff'
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_run([sys.executable, '-c', 'import time; time.sleep(10)'],
                    cwd=tmp_path, env=dict(os.environ), timeout=.1)


def test_declared_oversize_source_refuses_before_read(tmp_path):
    build, _, _ = api()
    world = tmp_path / 'world.sdf'
    world.write_text('<sdf/>')
    rows = snapshot({'declared': [str(world)]})['files']
    rows[0]['bytes'] = 32 * 1024 * 1024 + 1
    with pytest.raises(ValueError, match='32MiB'):
        build(world, GraphClient({}), rows, tmp_path)
