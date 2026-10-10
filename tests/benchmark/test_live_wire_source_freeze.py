"""Audit leaf/source changes must invalidate prospective preparation."""
import importlib.util
from pathlib import Path

import pytest

from tests.benchmark.live_wire_study_fixture import fixture, write
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot
from tools.benchmark.live_wire_study import validate_live_wire_study_files


def test_missing_lazy_audit_leaf_refuses_even_with_consistent_declared_inventory(tmp_path):
    manifest, docs, path = fixture(tmp_path)
    binding = docs['binding']
    binding['inventory'] = {role: [p for p in paths if not p.endswith('/audit_live_wire_safety.py')
                                 and not p.endswith('\\audit_live_wire_safety.py')]
                            for role, paths in binding['inventory'].items()}
    binding['inventory'] = {k:v for k,v in binding['inventory'].items() if v}
    binding['baseline'] = snapshot(binding['inventory'])
    target = manifest['files']['binding']['requested']
    write(Path(target), binding)
    manifest['files']['binding'] = file_record(target)
    write(path, manifest)
    with pytest.raises(ValueError, match='audit source'):
        validate_live_wire_study_files(path)


def api():
    assert importlib.util.find_spec('tools.benchmark.repository_python_sources') is not None
    from tools.benchmark import repository_python_sources
    return repository_python_sources


def repository(root):
    pkg = root / 'pkg'
    pkg.mkdir()
    (pkg/'__init__.py').write_text('raise RuntimeError("must not import")\n')
    (pkg/'entry.py').write_text('def later():\n    from .leaf import result\nimport json\n')
    (pkg/'leaf.py').write_text('from pkg import helper\nresult = 1\n')
    (pkg/'helper.py').write_text('import importlib\ndef later(name):\n    return importlib.import_module(name)\n')
    return pkg/'entry.py'


def test_static_transitive_local_and_relative_imports_without_execution(tmp_path):
    entry = repository(tmp_path)
    result = api().discover_sources(tmp_path, [entry])
    assert {Path(r['requested']).name for r in result['files']} == {'__init__.py','entry.py','leaf.py','helper.py'}
    assert 'json' in result['external_imports']
    assert result['dynamic_edges']
    assert result['runtime_closure_qualified'] is False


@pytest.mark.parametrize('fault', ['drift', 'missing', 'initializer'])
def test_frozen_source_set_cannot_drop_or_change_dependencies(tmp_path, fault):
    entry = repository(tmp_path)
    module = api()
    before = module.discover_sources(tmp_path, [entry])['files']
    if fault == 'drift':
        (entry.parent/'leaf.py').write_text('result = 2\n')
    else:
        suffix = 'leaf.py' if fault == 'missing' else '__init__.py'
        before = [r for r in before if Path(r['requested']).name != suffix]
    with pytest.raises(ValueError, match='audit source'):
        module.verify_sources(tmp_path, [entry], before)


def test_missing_explicit_local_module_is_not_external(tmp_path):
    entry = repository(tmp_path)
    entry.write_text('import pkg.missing\n')
    with pytest.raises(ValueError, match='missing local'):
        api().discover_sources(tmp_path, [entry])


def test_ambiguous_repository_module_roots_refuse(tmp_path):
    entry = repository(tmp_path)
    duplicate = tmp_path/'src/pkg'
    duplicate.mkdir(parents=True)
    (duplicate/'leaf.py').write_text('result = 3\n')
    with pytest.raises(ValueError, match='ambiguous'):
        api().discover_sources(tmp_path, [entry])
