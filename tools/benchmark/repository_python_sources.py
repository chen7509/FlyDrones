"""Static repository Python dependencies, without importing reviewed code.

Uses Python 3.12 ast.Import/ImportFrom, including function-local syntax:
https://docs.python.org/3.12/library/ast.html#imports (PSF documentation).
Only repository and repository/src Python files are resolved. This is not a
Python loader, external dependency resolver, or proof of dynamic runtime closure.
"""
from __future__ import annotations

import ast
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import file_record


def audit_source_roots(root):
    return [Path(root) / 'tools/benchmark' / name for name in (
        'audit_live_wire_study.py', 'live_wire_study.py',
        'execute_openvins_health_physical_run.py',
    )]


def discover_sources(root, entries):
    root = Path(root).resolve(strict=True)
    bases = [root / 'src', root]
    pending = [Path(p).resolve(strict=True) for p in entries]
    files, external, dynamic, unresolved = {}, set(), [], []

    def locate(name, *, optional=False):
        if not name or any(not p.isidentifier() for p in name.split('.')):
            raise ValueError('invalid static module name')
        parts = name.split('.')
        candidates = set()
        for base in bases:
            for path in (base.joinpath(*parts).with_suffix('.py'), base.joinpath(*parts, '__init__.py')):
                if path.is_file():
                    resolved = path.resolve(strict=True)
                    if not resolved.is_relative_to(root):
                        raise ValueError('repository source escapes root')
                    candidates.add(resolved)
        if len(candidates) > 1:
            raise ValueError('ambiguous repository module: ' + name)
        if candidates:
            pending.extend(sorted(candidates))
            return True
        namespace = any(base.joinpath(*parts).is_dir() for base in bases)
        local = any((base / parts[0]).exists() or (base / (parts[0] + '.py')).exists() for base in bases)
        if local and not namespace and not optional:
            raise ValueError('missing local module: ' + name)
        if not local:
            external.add(name)
        return namespace

    while pending:
        path = pending.pop()
        if str(path) in files:
            continue
        if len(files) >= 1024 or not path.is_relative_to(root) or path.suffix != '.py':
            raise ValueError('repository source scope/size limit')
        before = file_record(path)
        if before['bytes'] > 4 * 1024 * 1024:
            raise ValueError('repository source file too large')
        raw = path.read_bytes()
        if file_record(path) != before:
            raise ValueError('audit source changed during parse')
        tree = ast.parse(raw, filename=str(path))
        files[str(path)] = before
        base = next(b for b in bases if path.is_relative_to(b))
        parts = path.relative_to(base).with_suffix('').parts
        package = parts[:-1]
        for depth in range(1, len(parts)):
            initializer = base.joinpath(*parts[:depth], '__init__.py')
            if initializer.is_file():
                pending.append(initializer.resolve(strict=True))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    locate(alias.name)
            elif isinstance(node, ast.ImportFrom):
                prefix = []
                if node.level:
                    if node.level > len(package):
                        raise ValueError('relative import escapes package')
                    prefix = list(package[:len(package) - node.level + 1])
                name = '.'.join(prefix + ([node.module] if node.module else []))
                local = locate(name)
                if local:
                    for alias in node.names:
                        if alias.name != '*' and not locate(name + '.' + alias.name, optional=True):
                            unresolved.append(dict(source=str(path), line=node.lineno,
                                                   name=name + '.' + alias.name,
                                                   reason='attribute or unresolved optional submodule'))
            elif isinstance(node, ast.Call):
                function = node.func
                name = function.id if isinstance(function, ast.Name) else (
                    function.attr if isinstance(function, ast.Attribute) else '')
                if name in ('__import__', 'import_module', 'exec', 'eval', 'spec_from_file_location'):
                    dynamic.append(dict(source=str(path), line=node.lineno, operation=name))
    # Catch ordinary drift throughout traversal, not merely each individual read.
    for path, before in files.items():
        if file_record(path) != before:
            raise ValueError('audit source changed during traversal')
    return dict(schema='repository-python-static-imports-v1',
                files=[files[p] for p in sorted(files)], external_imports=sorted(external),
                dynamic_edges=dynamic, unresolved_edges=unresolved,
                runtime_closure_qualified=False,
                scope='static Python imports only; dynamic/extension/external/OS closure not established')


def verify_sources(root, entries, expected_rows):
    result = discover_sources(root, entries)
    expected = {row['resolved']: {k:v for k,v in row.items() if k != 'role'} for row in expected_rows}
    for record in result['files']:
        if expected.get(record['resolved']) != record:
            raise ValueError('audit source missing or changed: ' + record['requested'])
    return result
