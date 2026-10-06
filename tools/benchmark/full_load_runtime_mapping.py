"""Prospective contracts for one full-load runtime mapping study."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import file_record, parse_ldd


def select_unique_candidate(reason, candidates):
    if type(reason) is not str or not reason:
        raise ValueError("selection reason required")
    lexical = [str(Path(path).absolute()) for path in candidates]
    selected = {}
    for path in lexical:
        candidate = Path(path)
        if candidate.is_file():
            resolved = str(candidate.resolve(strict=True))
            selected.setdefault(resolved, []).append(path)
    if len(selected) != 1:
        raise ValueError(f"{reason} requires one canonical candidate, found {len(selected)}")
    canonical = next(iter(selected))
    return dict(selection_reason=reason, candidates=lexical, selected=canonical,
                aliases=selected[canonical], identity=file_record(canonical))


def ldd_closure(roots, *, runner=subprocess.run, parser=parse_ldd):
    if type(roots) is not list or not roots:
        raise ValueError("runtime roots required")
    root_paths = sorted({row["selected"] for row in roots})
    dependencies = {}
    commands = []
    for root in root_paths:
        before = file_record(root)
        command = ["/usr/bin/ldd", root]
        completed = runner(command, capture_output=True, text=True, timeout=10)
        record = dict(command=command, returncode=completed.returncode,
                      stdout=completed.stdout, stderr=completed.stderr)
        commands.append(record)
        resolved = parser(completed.stdout, completed.returncode)
        after = file_record(root)
        if before != after:
            raise ValueError("runtime root changed during ldd")
        for path in resolved:
            row = file_record(path)
            dependencies[row["resolved"]] = row
    return dict(roots=root_paths, dependencies=sorted(dependencies),
                dependency_records=[dependencies[path] for path in sorted(dependencies)], commands=commands)


def runtime_inventory(roots, closure):
    if type(roots) is not list or type(closure) is not dict:
        raise ValueError("runtime inventory inputs")
    inventory = {}
    selected = set()
    for row in sorted(roots, key=lambda item: item["selection_reason"]):
        role = "runtime-root:" + row["selection_reason"]
        path = row["selected"]
        if role in inventory or path in selected:
            raise ValueError("duplicate runtime root role or canonical path")
        selected.add(path)
        inventory[role] = [path]
    dependencies = [path for path in closure["dependencies"] if path not in selected]
    if len(dependencies) != len(set(dependencies)):
        raise ValueError("duplicate runtime dependency")
    if dependencies:
        inventory["runtime:dependencies"] = sorted(dependencies)
    return inventory
