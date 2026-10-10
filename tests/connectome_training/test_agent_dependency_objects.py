"""Fail-closed checks for fixed direct Agent dependency Git objects."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/connectome/audit_agent_dependency_objects.py"


def _module():
    spec = importlib.util.spec_from_file_location("audit_agent_dependency_objects", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def bare_source(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.name", "Dependency Fixture")
    _git(work, "config", "user.email", "test@example.invalid")
    (work / "LICENSE").write_bytes(b"fixture license\n")
    (work / "CMakeLists.txt").write_bytes(b"project(fixture)\n")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "fixture")
    commit = _git(work, "rev-parse", "HEAD")
    bare = tmp_path / "bare.git"
    _git(tmp_path, "init", "--bare", "-q", str(bare))
    _git(bare, "fetch", str(work), commit)
    _git(bare, "update-ref", "refs/flydrones/pins/source", commit)
    return work, bare, commit


def test_exact_commit_tree_and_license_are_local(bare_source):
    _, bare, commit = bare_source
    result = _module().audit_repository(bare, commit)
    assert result["commit"] == commit
    assert len(result["tree"]) == 40
    assert result["license_path"] == "LICENSE"
    assert result["gitlinks"] == []
    assert result["direct_source_object_verified"] is True
    assert result["transitive_source_closure_verified"] is False


@pytest.mark.parametrize("changed", ["wrong_id", "tree_object", "missing_license"])
def test_wrong_identity_or_missing_license_refuses(bare_source, changed):
    work, bare, commit = bare_source
    if changed == "wrong_id":
        target = "0" * 40
    elif changed == "tree_object":
        target = _git(work, "rev-parse", "HEAD^{tree}")
    else:
        (work / "LICENSE").unlink()
        _git(work, "add", "-u")
        _git(work, "commit", "-qm", "no license")
        target = _git(work, "rev-parse", "HEAD")
        _git(bare, "fetch", str(work), target)
        _git(bare, "update-ref", "refs/flydrones/pins/source", target)
    with pytest.raises(ValueError):
        _module().audit_repository(bare, target)


def test_gitlink_without_module_mapping_refuses(bare_source):
    work, bare, _ = bare_source
    _git(work, "update-index", "--add", "--cacheinfo", "160000," + "1" * 40 + ",vendor/missing")
    _git(work, "commit", "-qm", "unmapped gitlink")
    target = _git(work, "rev-parse", "HEAD")
    _git(bare, "fetch", str(work), target)
    _git(bare, "update-ref", "refs/flydrones/pins/source", target)
    with pytest.raises(ValueError, match="gitlink"):
        _module().audit_repository(bare, target)


def test_replacement_ref_does_not_change_license(bare_source, tmp_path):
    work, bare, commit = bare_source
    original = _git(work, "rev-parse", "HEAD:LICENSE")
    altered = tmp_path / "altered-license"
    altered.write_bytes(b"altered license\n")
    replacement = _git(bare, "hash-object", "-w", str(altered))
    _git(bare, "replace", original, replacement)
    result = _module().audit_repository(bare, commit)
    assert result["license_sha256"] == __import__("hashlib").sha256(b"fixture license\n").hexdigest()


def test_missing_immutable_source_ref_refuses(bare_source):
    _, bare, commit = bare_source
    _git(bare, "update-ref", "-d", "refs/flydrones/pins/source")
    with pytest.raises(ValueError, match="pin"):
        _module().audit_repository(bare, commit)


def test_nested_fetch_declaration_is_reported_without_closure_claim(bare_source):
    work, bare, _ = bare_source
    (work / "CMakeLists.txt").write_bytes(
        b"ExternalProject_Add(child GIT_REPOSITORY https://example.invalid/child.git)\n"
    )
    _git(work, "add", "CMakeLists.txt")
    _git(work, "commit", "-qm", "nested fetch")
    target = _git(work, "rev-parse", "HEAD")
    _git(bare, "fetch", str(work), target)
    _git(bare, "update-ref", "refs/flydrones/pins/source", target)
    result = _module().audit_repository(bare, target)
    assert any("GIT_REPOSITORY" in row["text"] for row in result["build_fetch_declarations"])
    assert result["transitive_source_closure_verified"] is False


def test_symlink_mode_license_refuses(bare_source):
    work, bare, _ = bare_source
    blob = _git(work, "rev-parse", "HEAD:LICENSE")
    _git(work, "update-index", "--cacheinfo", f"120000,{blob},LICENSE")
    _git(work, "commit", "-qm", "symlink license")
    target = _git(work, "rev-parse", "HEAD")
    _git(bare, "fetch", str(work), target)
    _git(bare, "update-ref", "refs/flydrones/pins/source", target)
    with pytest.raises(ValueError, match="regular"):
        _module().audit_repository(bare, target)


def test_symlink_mode_gitmodules_refuses(bare_source, monkeypatch):
    work, bare, _ = bare_source
    (work / ".gitmodules").write_bytes(
        b'[submodule "x"]\n\tpath = vendor/x\n\turl = https://example.invalid/x\n'
    )
    _git(work, "add", ".gitmodules")
    _git(work, "update-index", "--add", "--cacheinfo", "160000," + "1" * 40 + ",vendor/x")
    _git(work, "commit", "-qm", "symlink modules")
    target = _git(work, "rev-parse", "HEAD")
    _git(bare, "fetch", str(work), target)
    _git(bare, "update-ref", "refs/flydrones/pins/source", target)
    module = _module()
    original = module._git

    def altered(repo, *args):
        output = original(repo, *args)
        if args[:3] == ("ls-tree", "-rz", "--full-tree"):
            rows = output.split(b"\0")
            rows = [row.replace(b"100644 blob", b"120000 blob", 1)
                    if row.endswith(b"\t.gitmodules") else row for row in rows]
            return b"\0".join(rows)
        return output

    monkeypatch.setattr(module, "_git", altered)
    with pytest.raises(ValueError, match="regular"):
        module.audit_repository(bare, target)


@pytest.mark.parametrize("raw", [
    b"", b"0" * 40 + b"\trefs/tags/v2.0.1\n",
    b"3d1b17703c7cf4f22def2910bc845bdb5152d7b5\trefs/tags/other\n",
    b"3d1b17703c7cf4f22def2910bc845bdb5152d7b5\trefs/tags/v2.0.1\nextra\n",
])
def test_bad_remote_tag_observation_refuses(raw):
    with pytest.raises(ValueError, match="tag"):
        _module().verify_micro_cdr_tag_observation(raw)


def test_exact_remote_tag_observation_is_accepted():
    raw = b"3d1b17703c7cf4f22def2910bc845bdb5152d7b5\trefs/tags/v2.0.1\n"
    assert _module().verify_micro_cdr_tag_observation(raw) == (
        "3d1b17703c7cf4f22def2910bc845bdb5152d7b5"
    )
