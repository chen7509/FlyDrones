"""Fixed-parent and local-object checks for Fast-DDS gitlink candidates."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/connectome/audit_fastdds_gitlink_objects.py"


def _module():
    spec = importlib.util.spec_from_file_location("audit_fastdds_gitlink_objects", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def parent_source(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.name", "Fixed Parent Fixture")
    _git(work, "config", "user.email", "test@example.invalid")
    (work / ".gitmodules").write_text(
        '[submodule "thirdparty/asio"]\n'
        '\tpath = thirdparty/asio\n'
        '\turl = https://example.invalid/asio.git\n',
        encoding="utf-8",
    )
    _git(work, "add", ".gitmodules")
    oid = "1" * 40
    _git(work, "update-index", "--add", "--cacheinfo", f"160000,{oid},thirdparty/asio")
    _git(work, "commit", "-qm", "fixed parent")
    commit = _git(work, "rev-parse", "HEAD")
    bare = tmp_path / "parent.git"
    _git(tmp_path, "init", "--bare", "-q", str(bare))
    _git(bare, "fetch", str(work), commit)
    _git(bare, "update-ref", "refs/flydrones/pins/source", commit)
    expected = {"thirdparty/asio": {"url": "https://example.invalid/asio.git", "commit": oid}}
    return work, bare, commit, expected


def test_parent_exact_path_url_and_gitlink_are_bound(parent_source):
    _, bare, commit, expected = parent_source
    result = _module().verify_parent_links(bare, commit, expected)
    assert result["links"] == expected
    assert len(result["parent_tree"]) == 40
    assert result["parent_commit"] == commit


@pytest.mark.parametrize("field", ["url", "commit", "path"])
def test_parent_mismatch_refuses(parent_source, field):
    _, bare, commit, expected = parent_source
    changed = {name: dict(value) for name, value in expected.items()}
    if field == "path":
        changed = {"thirdparty/other": changed["thirdparty/asio"]}
    elif field == "url":
        changed["thirdparty/asio"]["url"] = "https://example.invalid/other.git"
    else:
        changed["thirdparty/asio"]["commit"] = "2" * 40
    with pytest.raises(ValueError):
        _module().verify_parent_links(bare, commit, changed)


def test_parent_missing_pin_refuses(parent_source):
    _, bare, commit, expected = parent_source
    _git(bare, "update-ref", "-d", "refs/flydrones/pins/source")
    with pytest.raises(ValueError):
        _module().verify_parent_links(bare, commit, expected)


@pytest.fixture
def child_source(tmp_path):
    work = tmp_path / "child_work"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.name", "Fixed Child Fixture")
    _git(work, "config", "user.email", "test@example.invalid")
    (work / "README.md").write_text("Permission is granted to use this fixture.\n")
    (work / "CMakeLists.txt").write_text("project(fixture)\n")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "fixed child")
    commit = _git(work, "rev-parse", "HEAD")
    bare = tmp_path / "child.git"
    _git(tmp_path, "init", "--bare", "-q", str(bare))
    _git(bare, "fetch", str(work), commit)
    _git(bare, "update-ref", "refs/flydrones/pins/source", commit)
    return work, bare, commit


def test_child_records_nonstandard_fixed_license_path(child_source):
    _, bare, commit = child_source
    row = _module().audit_child(bare, commit, ("README.md",))
    assert row["commit"] == commit
    assert row["license_sources"][0]["path"] == "README.md"
    assert len(row["license_sources"][0]["sha256"]) == 64
    assert row["nested_gitlinks"] == []
    assert row["build_selection_verified"] is False


@pytest.mark.parametrize("license_path", ["MISSING", "README.md/other", ""])
def test_child_unknown_license_path_refuses(child_source, license_path):
    _, bare, commit = child_source
    with pytest.raises(ValueError):
        _module().audit_child(bare, commit, (license_path,))


def test_child_missing_pin_refuses(child_source):
    _, bare, commit = child_source
    _git(bare, "update-ref", "-d", "refs/flydrones/pins/source")
    with pytest.raises(ValueError):
        _module().audit_child(bare, commit, ("README.md",))


def test_child_unmapped_nested_gitlink_refuses(child_source):
    work, bare, _ = child_source
    _git(work, "update-index", "--add", "--cacheinfo", "160000," + "1" * 40 + ",nested/x")
    _git(work, "commit", "-qm", "nested gitlink")
    commit = _git(work, "rev-parse", "HEAD")
    _git(bare, "fetch", str(work), commit)
    _git(bare, "update-ref", "refs/flydrones/pins/source", commit)
    with pytest.raises(ValueError, match="gitlink"):
        _module().audit_child(bare, commit, ("README.md",))


def test_manifest_requires_every_fixed_child_object(parent_source, child_source):
    work, bare_parent, _, _ = parent_source
    _, bare_child, child_commit = child_source
    _git(work, "update-index", "--add", "--cacheinfo",
         f"160000,{child_commit},thirdparty/asio")
    _git(work, "commit", "-qm", "link exact child")
    parent_commit = _git(work, "rev-parse", "HEAD")
    _git(bare_parent, "fetch", str(work), parent_commit)
    _git(bare_parent, "update-ref", "refs/flydrones/pins/source", parent_commit)
    expected = {"thirdparty/asio": {
        "url": "https://example.invalid/asio.git", "commit": child_commit,
    }}
    specs = {"asio": ("thirdparty/asio", ("README.md",))}
    result = _module().build_manifest(
        bare_parent, parent_commit, expected, {"asio": bare_child}, specs,
    )
    assert result["source_objects_verified"] is True
    assert result["build_selection_verified"] is False
    assert result["children"]["asio"]["commit"] == child_commit
    with pytest.raises(ValueError, match="inventory"):
        _module().build_manifest(bare_parent, parent_commit, expected, {}, specs)
