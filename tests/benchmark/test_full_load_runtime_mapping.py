import hashlib
import json
import subprocess
import zipfile

import pytest

from tools.benchmark import full_load_runtime_mapping as study
from tools.benchmark.declared_runtime_snapshot import snapshot


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


def test_generated_hashes_come_from_exact_archive_members_and_gz_env(tmp_path):
    archive = tmp_path / "scene.zip"
    prefix = "sealed/episode/"
    contents = {name: name.encode() for name in study.SCENE_NAMES}
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, data in contents.items():
            bundle.writestr(prefix + name, data)
    gz_env = tmp_path / "gz_env.sh"
    gz_env.write_bytes(b"environment")
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    hashes = study.generated_hashes(archive, archive_sha, prefix, gz_env)
    assert hashes["world.sdf"] == hashlib.sha256(b"world.sdf").hexdigest()
    assert hashes["gz_env.sh"] == hashlib.sha256(b"environment").hexdigest()
    with pytest.raises(ValueError, match="archive"):
        study.generated_hashes(archive, "0" * 64, prefix, gz_env)


def test_merge_v2_binding_to_v3_preserves_graph_and_records_overlap(tmp_path):
    shared = tmp_path / "shared.so"
    runtime = tmp_path / "runtime.so"
    for path in (shared, runtime):
        path.write_bytes(path.name.encode())
    base_inventory = {"graph:resolver": [str(shared)], "graph:source": [str(runtime)],
                      "graph:dependencies": [str(tmp_path / "dependency.so")]}
    (tmp_path / "dependency.so").write_bytes(b"dependency")
    base = dict(schema="capture-resource-binding-v2", inventory=base_inventory,
                baseline=snapshot(base_inventory), environment={key: None for key in study.ENV_KEYS},
                generated={name: "1" * 64 for name in study.GENERATED_NAMES},
                graph={"schema": "generated-resource-graph-v1", "cwd": str(tmp_path),
                       "environment": {key: None for key in study.QUERY_ENV_KEYS},
                       "expected_context": {"sentinel": "unchanged"}})
    merged, evidence = study.merge_binding(
        base, {"runtime-root:python": [str(shared.resolve())],
               "runtime-root:px4": [str(runtime.resolve())]},
        {name: "2" * 64 for name in study.GENERATED_NAMES})
    assert merged["schema"] == "capture-resource-binding-v3"
    assert merged["graph"] == base["graph"]
    assert merged["runtime_maps"] == study.RUNTIME_MAPS
    assert merged["generated"]["world.sdf"] == "2" * 64
    assert evidence["overlaps"] == sorted([str(shared.resolve()), str(runtime.resolve())])
    assert set(merged["inventory"]) == set(base_inventory)
    assert merged["baseline"]["files"] == snapshot(base_inventory)["files"]


def test_exact_execution_contract_and_declared_command(tmp_path):
    for name in ("online_probe", "config.yaml", "reference.so"):
        (tmp_path / name).write_bytes(name.encode())
    output = tmp_path / "capture"
    args = study.study_args(
        output, tmp_path / "online_probe", tmp_path / "config.yaml", tmp_path / "reference.so", "a" * 64)
    contract = study.execution_contract(args)
    assert contract["wall_budget_s"] == 300 and contract["supervisor_s"] == 300
    assert contract["simulation_duration_ns"] == 25_000_000_000
    assert contract["profiles"] == {
        "motion_profile": "supported-ready-v1", "physics_trace_profile": "substep-ready-v1",
        "reference_fault_profile": None, "source_fanout_profile": "ready-shadow-heartbeat-v1"}
    contract_path = tmp_path / "execution-contract.json"
    contract_path.write_text(json.dumps(contract))
    args.execution_contract = contract_path
    command = study.declared_study_command(args, "/usr/bin/python3", "/study/capture.py")
    assert command[-4:] == ["--execution-contract", str(contract_path.resolve()),
                            "--runtime-binding", str(args.runtime_binding.resolve())]


def test_prepare_refuses_active_resources_and_reused_destination(tmp_path):
    with pytest.raises(ValueError, match="competing"):
        study.ensure_prepare_allowed(tmp_path / "new", [{"pid": 1}])
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        study.ensure_prepare_allowed(existing, [])
