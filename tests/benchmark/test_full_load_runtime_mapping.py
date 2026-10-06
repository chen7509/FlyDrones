import subprocess
from pathlib import Path

import pytest

from tools.benchmark import full_load_runtime_mapping as study


def test_unique_candidate_records_lexical_and_canonical_identity(tmp_path):
    target = tmp_path / "libselected.so.1"
    target.write_bytes(b"elf")
    alias = tmp_path / "libselected.so"
    try:
        alias.symlink_to(target.name)
    except OSError:
        pytest.skip("symlink unavailable")
    row = study.select_unique_candidate("renderer:ogre2", [alias, target])
    assert row["selected"] == str(target.resolve())
    assert row["candidates"] == [str(alias.absolute()), str(target.absolute())]
    assert row["selection_reason"] == "renderer:ogre2"


@pytest.mark.parametrize("kind", ["missing", "ambiguous"])
def test_unique_candidate_refuses_zero_or_distinct_canonical_files(tmp_path, kind):
    candidates = []
    if kind == "ambiguous":
        for name in ("a.so", "b.so"):
            path = tmp_path / name
            path.write_bytes(name.encode())
            candidates.append(path)
    with pytest.raises(ValueError, match="candidate"):
        study.select_unique_candidate("runtime", candidates)


def test_ldd_closure_is_strict_bounded_and_stable(tmp_path):
    root = tmp_path / "program"
    dep = tmp_path / "libdep.so"
    root.write_bytes(b"root")
    dep.write_bytes(b"dep")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, f"libdep.so => {dep} (0x1)\n", "")

    result = study.ldd_closure([dict(selection_reason="program", selected=str(root.resolve()))], runner=runner,
                               parser=lambda _output, _code: [str(dep.resolve())])
    assert result["roots"] == [str(root.resolve())]
    assert result["dependencies"] == [str(dep.resolve())]
    assert calls[0][0] == ["/usr/bin/ldd", str(root.resolve())]
    assert calls[0][1]["timeout"] == 10


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "missing", "unsupported", "drift"])
def test_ldd_closure_refuses_failures_and_input_drift(tmp_path, failure):
    root = tmp_path / "program"
    dep = tmp_path / "libdep.so"
    root.write_bytes(b"root")
    dep.write_bytes(b"dep")

    def runner(command, **_kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 10)
        if failure == "drift":
            root.write_bytes(b"changed")
        if failure == "missing":
            output = "libdep.so => not found\n"
        elif failure == "unsupported":
            output = "unexpected loader output\n"
        else:
            output = f"libdep.so => {dep} (0x1)\n"
        return subprocess.CompletedProcess(command, 1 if failure == "nonzero" else 0, output, "detail")

    with pytest.raises((ValueError, subprocess.TimeoutExpired)):
        parser = (lambda _output, _code: [str(dep.resolve())]) if failure == "drift" else study.parse_ldd
        study.ldd_closure([dict(selection_reason="program", selected=str(root.resolve()))],
                          runner=runner, parser=parser)


def test_inventory_roles_are_deterministic_and_duplicate_canonical_paths_refuse(tmp_path):
    roots = []
    for role in ("px4", "openvins"):
        path = tmp_path / role
        path.write_bytes(role.encode())
        roots.append(dict(selection_reason=role, selected=str(path.resolve())))
    dependency = tmp_path / "libcommon.so"
    dependency.write_bytes(b"dependency")

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, f"libcommon.so => {dependency} (0x1)\n", "")

    result = study.ldd_closure(list(reversed(roots)), runner=runner,
                               parser=lambda _output, _code: [str(dependency.resolve())])
    inventory = study.runtime_inventory(roots, result)
    assert list(inventory) == ["runtime-root:openvins", "runtime-root:px4", "runtime:dependencies"]
    assert inventory["runtime:dependencies"] == [str(dependency.resolve())]
    with pytest.raises(ValueError, match="duplicate"):
        study.runtime_inventory(roots + [dict(roots[0], selection_reason="duplicate")], result)
