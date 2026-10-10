"""Exact Agent Git-blob input preparation; no build or network calls."""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/connectome/prepare_pinned_xrce_agent.py"


def _module():
    spec = importlib.util.spec_from_file_location("prepare_pinned_xrce_agent", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "agent"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _git(repo, "config", "user.name", "FlyDrones Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    cmake = (
        "set(UAGENT_P2P_CLIENT_TAG v2.4.3 CACHE STRING \"client\")\n"
        "set(_fastcdr_tag 2.2.x)\n"
        "set(_fastdds_tag 2.14.x)\n"
        "set(_foonathan_memory_tag v0.7-3)\n"
        "set(_spdlog_tag v1.9.2)\n"
    )
    (repo / "CMakeLists.txt").write_bytes(cmake.encode())
    (repo / "cmake").mkdir()
    (repo / "cmake/SuperBuild.cmake").write_bytes(b"GIT_TAG ${_fastcdr_tag}\n")
    (repo / "README.md").write_bytes(b"agent fixture\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    pins = {"fast_cdr": "a" * 40, "fast_dds": "b" * 40,
            "foonathan_memory": "c" * 40, "spdlog": "d" * 40,
            "xrce_client": "e" * 40}
    selected = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest()
                for name in ("CMakeLists.txt", "cmake/SuperBuild.cmake", "README.md")}
    return repo, _git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", "HEAD^{tree}"), selected, pins


def test_exact_git_blobs_are_copied_and_five_refs_are_pinned(source, tmp_path):
    module = _module()
    repo, commit, tree, selected, pins = source
    (repo / "README.md").write_bytes(b"changed checkout only\r\n")
    destination = tmp_path / "prepared"
    profile = module.prepare_source(repo, destination, commit, tree, selected, pins, 3)
    assert (destination / "README.md").read_bytes() == b"agent fixture\n"
    assert (destination / "cmake/SuperBuild.cmake").read_bytes() == b"GIT_TAG ${_fastcdr_tag}\n"
    changed = (destination / "CMakeLists.txt").read_text(encoding="utf-8")
    assert all(pin in changed for pin in pins.values())
    assert "2.2.x" not in changed and "2.14.x" not in changed
    assert profile["agent_commit"] == commit and profile["agent_tree"] == tree
    assert profile["file_count"] == 3
    assert profile["agent_binary_built_or_run"] is False
    assert profile["px4_agent_interoperability_verified"] is False
    assert json.loads((destination / "source-profile.json").read_text())["files"]["README.md"] == (
        hashlib.sha256(b"agent fixture\n").hexdigest()
    )


def test_fixed_selected_hashes_bind_git_blobs_not_windows_checkout():
    module = _module()
    assert module.SELECTED_SHA256 == {
        "CMakeLists.txt": "99a4934796b9bf98abb365e42eb6b0cdf57ca40067d2996aa4f03179491d329b",
        "cmake/SuperBuild.cmake": "86ac7d0e6643b62e4449b108e2ee76ae4e6d35004e3156970682841a74c65b29",
        "Dockerfile": "2bc2eb326b89001b74464b1c2234cfc2e28417c5d9b613f9be42d8e327d4c91c",
        "LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
        "README.md": "d59f374b872acefc3fd09cb96865abce53ec50129edee8952c8fe49cf50c5dc5",
    }


def test_wrong_commit_tree_or_selected_hash_refuses_before_writing(source, tmp_path):
    module = _module()
    repo, commit, tree, selected, pins = source
    for index, (bad_commit, bad_tree, bad_selected) in enumerate((
        ("0" * 40, tree, selected),
        (commit, "0" * 40, selected),
        (commit, tree, {**selected, "CMakeLists.txt": "0" * 64}),
    )):
        destination = tmp_path / f"bad-{index}"
        with pytest.raises(ValueError):
            module.prepare_source(repo, destination, bad_commit, bad_tree, bad_selected, pins, 3)
        assert not destination.exists()


@pytest.mark.parametrize("mutation", ["duplicate", "missing"])
def test_duplicate_or_missing_cmake_declaration_refuses(source, tmp_path, mutation):
    module = _module()
    repo, _, _, _, pins = source
    path = repo / "CMakeLists.txt"
    raw = path.read_bytes()
    target = b"set(_fastcdr_tag 2.2.x)\n"
    path.write_bytes(raw + target if mutation == "duplicate" else raw.replace(target, b""))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", mutation)
    selected = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest()
                for name in ("CMakeLists.txt", "cmake/SuperBuild.cmake", "README.md")}
    destination = tmp_path / "bad"
    with pytest.raises(ValueError, match="declaration"):
        module.prepare_source(repo, destination, _git(repo, "rev-parse", "HEAD"),
                              _git(repo, "rev-parse", "HEAD^{tree}"), selected, pins, 3)
    assert not destination.exists()


def test_existing_destination_refuses_without_overwrite(source, tmp_path):
    module = _module()
    repo, commit, tree, selected, pins = source
    destination = tmp_path / "exists"
    destination.mkdir()
    marker = destination / "keep"
    marker.write_text("old")
    with pytest.raises(FileExistsError):
        module.prepare_source(repo, destination, commit, tree, selected, pins, 3)
    assert marker.read_text() == "old"


def test_git_symlink_mode_refuses_before_writing(source, tmp_path, monkeypatch):
    module = _module()
    repo, commit, tree, selected, pins = source
    original = module._git

    def changed(path, *args):
        output = original(path, *args)
        if args[:3] == ("ls-tree", "-rz", "--full-tree"):
            return output.replace(b"100644 blob", b"120000 blob", 1)
        return output

    monkeypatch.setattr(module, "_git", changed)
    destination = tmp_path / "symlink"
    with pytest.raises(ValueError, match="mode"):
        module.prepare_source(repo, destination, commit, tree, selected, pins, 3)
    assert not destination.exists()


def test_unsafe_git_path_refuses_before_writing(source, tmp_path, monkeypatch):
    module = _module()
    repo, commit, tree, selected, pins = source
    original = module._git

    def changed(path, *args):
        output = original(path, *args)
        if args[:3] == ("ls-tree", "-rz", "--full-tree"):
            return output.replace(b"\tREADME.md\0", b"\t../outside\0", 1)
        return output

    monkeypatch.setattr(module, "_git", changed)
    destination = tmp_path / "unsafe"
    with pytest.raises(ValueError, match="unsafe"):
        module.prepare_source(repo, destination, commit, tree, selected, pins, 3)
    assert not destination.exists() and not (tmp_path / "outside").exists()


def test_git_replacement_ref_cannot_change_unselected_blob(source, tmp_path):
    module = _module()
    repo, commit, tree, selected, pins = source
    original = _git(repo, "rev-parse", "HEAD:README.md")
    replacement_path = tmp_path / "replacement.bin"
    replacement_path.write_bytes(b"replacement content\n")
    replacement = _git(repo, "hash-object", "-w", str(replacement_path))
    _git(repo, "replace", original, replacement)
    destination = tmp_path / "prepared"
    module.prepare_source(repo, destination, commit, tree,
                          {k: v for k, v in selected.items() if k != "README.md"}, pins, 3)
    assert (destination / "README.md").read_bytes() == b"agent fixture\n"


@pytest.mark.parametrize("name", ["readme.md", "source-profile.json", "CON.txt", "trailing. "])
def test_windows_alias_and_reserved_source_names_refuse_before_writing(
    source, tmp_path, monkeypatch, name,
):
    module = _module()
    repo, commit, tree, selected, pins = source
    original = module._git

    def changed(path, *args):
        output = original(path, *args)
        if args[:3] == ("ls-tree", "-rz", "--full-tree"):
            entry = next(x for x in output.split(b"\0") if x.endswith(b"\tREADME.md"))
            return output + entry.replace(b"\tREADME.md", b"\t" + name.encode()) + b"\0"
        return output

    monkeypatch.setattr(module, "_git", changed)
    destination = tmp_path / "unsafe-alias"
    with pytest.raises(ValueError, match="path|reserved|alias"):
        module.prepare_source(repo, destination, commit, tree, selected, pins, 4)
    assert not destination.exists()


def test_casefold_directory_alias_refuses_before_writing(source, tmp_path, monkeypatch):
    module = _module()
    repo, commit, tree, selected, pins = source
    original = module._git

    def changed(path, *args):
        output = original(path, *args)
        if args[:3] == ("ls-tree", "-rz", "--full-tree"):
            entry = next(x for x in output.split(b"\0") if x.endswith(b"\tREADME.md"))
            return (output + entry.replace(b"\tREADME.md", b"\tA/one") + b"\0"
                    + entry.replace(b"\tREADME.md", b"\ta/two") + b"\0")
        return output

    monkeypatch.setattr(module, "_git", changed)
    destination = tmp_path / "directory-alias"
    with pytest.raises(ValueError, match="alias"):
        module.prepare_source(repo, destination, commit, tree, selected, pins, 5)
    assert not destination.exists()
