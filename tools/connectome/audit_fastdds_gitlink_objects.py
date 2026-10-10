"""Verify fixed Fast-DDS gitlink objects without building software."""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

PARENT_COMMIT = "575d045b55c16be1074ccd9eebf95e3e4274fe61"
LINKS = {
    "thirdparty/android-ifaddrs": {
        "url": "https://github.com/michalsrb/android-ifaddrs.git",
        "commit": "7b1ce82817226e481d3cda0a5d06b66ebcc211f8",
    },
    "thirdparty/asio": {
        "url": "https://github.com/chriskohlhoff/asio.git",
        "commit": "ed6aa8a13d51dfc6c00ae453fc9fb7df5d6ea963",
    },
    "thirdparty/fastcdr": {
        "url": "https://github.com/eProsima/Fast-CDR.git",
        "commit": "1bc9c919311ffce555b445560bf7ae062a4e1c72",
    },
    "thirdparty/tinyxml2": {
        "url": "https://github.com/leethomason/tinyxml2.git",
        "commit": "8c8293ba8969a46947606a93ff0cb5a083aab47a",
    },
}
GIT_ENV = {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}
CHILD_SPECS = {
    "android_ifaddrs": ("thirdparty/android-ifaddrs", ("README.md", "ifaddrs.c", "ifaddrs.h")),
    "asio": ("thirdparty/asio", ("asio/COPYING", "asio/LICENSE_1_0.txt")),
    "fastcdr_gitlink": ("thirdparty/fastcdr", ("LICENSE",)),
    "tinyxml2": ("thirdparty/tinyxml2", ("readme.md", "tinyxml2.h", "tinyxml2.cpp")),
}


def _git(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], env=GIT_ENV,
            check=True, capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"unavailable fixed Git object: {args}") from exc


def verify_parent_links(
    repo: Path, parent_commit: str, expected_links: dict[str, dict[str, str]],
) -> dict:
    """Bind exact parent tree modes, gitlinks and .gitmodules URLs."""
    if not re.fullmatch(r"[0-9a-f]{40}", parent_commit):
        raise ValueError("invalid parent commit")
    if _git(repo, "rev-parse", "--is-bare-repository").strip() != b"true":
        raise ValueError("parent source must be a bare Git store")
    if _git(repo, "rev-parse", "FETCH_HEAD").decode().strip() != parent_commit:
        raise ValueError("parent fetch identity differs")
    if _git(repo, "rev-parse", "refs/flydrones/pins/source").decode().strip() != parent_commit:
        raise ValueError("parent pin identity differs")
    if _git(repo, "cat-file", "-t", parent_commit).strip() != b"commit":
        raise ValueError("parent object is not a commit")
    tree = _git(repo, "rev-parse", f"{parent_commit}^{{tree}}").decode().strip()
    entries = {}
    for raw in _git(repo, "ls-tree", "-rz", "--full-tree", parent_commit).split(b"\0"):
        if not raw:
            continue
        metadata, sep, path = raw.partition(b"\t")
        fields = metadata.split()
        if sep != b"\t" or len(fields) != 3:
            raise ValueError("invalid parent tree entry")
        mode, kind, oid = fields
        name = path.decode("utf-8")
        if name in entries or not re.fullmatch(rb"[0-9a-f]{40}", oid):
            raise ValueError("duplicate or invalid parent tree entry")
        entries[name] = (mode, kind, oid)
    modules = entries.get(".gitmodules")
    if not modules or modules[:2] not in ((b"100644", b"blob"), (b"100755", b"blob")):
        raise ValueError("parent .gitmodules must be a regular blob")
    modules_raw = _git(repo, "cat-file", "blob", modules[2].decode())
    config = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        config.read_string(modules_raw.decode("utf-8"))
        module_links = {}
        for section in config.sections():
            path = config.get(section, "path")
            url = config.get(section, "url")
            if path in module_links:
                raise ValueError("duplicate module path")
            module_links[path] = url
    except (configparser.Error, UnicodeDecodeError) as exc:
        raise ValueError("invalid parent .gitmodules") from exc
    gitlinks = {
        name: {"url": module_links.get(name), "commit": oid.decode()}
        for name, (mode, kind, oid) in entries.items()
        if (mode, kind) == (b"160000", b"commit")
    }
    if set(module_links) != set(gitlinks) or gitlinks != expected_links:
        raise ValueError("parent gitlink path/URL/object inventory differs")
    return {
        "parent_commit": parent_commit,
        "parent_tree": tree,
        "gitmodules_blob": modules[2].decode(),
        "gitmodules_sha256": hashlib.sha256(modules_raw).hexdigest(),
        "links": gitlinks,
    }


def audit_child(repo: Path, expected_commit: str, license_paths: tuple[str, ...]) -> dict:
    """Read an exact child tree and its fixed license-bearing source blobs."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("invalid child commit")
    if not license_paths or len(license_paths) != len(set(license_paths)):
        raise ValueError("child license source inventory incomplete")
    if _git(repo, "rev-parse", "--is-bare-repository").strip() != b"true":
        raise ValueError("child source must be a bare Git store")
    if _git(repo, "rev-parse", "FETCH_HEAD").decode().strip() != expected_commit:
        raise ValueError("child fetch identity differs")
    if _git(repo, "rev-parse", "refs/flydrones/pins/source").decode().strip() != expected_commit:
        raise ValueError("child pin identity differs")
    if _git(repo, "cat-file", "-t", expected_commit).strip() != b"commit":
        raise ValueError("child object is not a commit")
    tree = _git(repo, "rev-parse", f"{expected_commit}^{{tree}}").decode().strip()
    entries = {}
    for raw in _git(repo, "ls-tree", "-rz", "--full-tree", expected_commit).split(b"\0"):
        if not raw:
            continue
        metadata, sep, path = raw.partition(b"\t")
        fields = metadata.split()
        if sep != b"\t" or len(fields) != 3:
            raise ValueError("invalid child tree entry")
        mode, kind, oid = fields
        name = path.decode("utf-8")
        if name in entries or not re.fullmatch(rb"[0-9a-f]{40}", oid):
            raise ValueError("duplicate or invalid child tree entry")
        if (mode, kind) not in ((b"100644", b"blob"), (b"100755", b"blob"),
                                (b"120000", b"blob"), (b"160000", b"commit")):
            raise ValueError("unsupported child tree entry")
        entries[name] = (mode, kind, oid)
    license_sources = []
    for path in license_paths:
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError("invalid child license path")
        entry = entries.get(path)
        if not entry or entry[:2] not in ((b"100644", b"blob"), (b"100755", b"blob")):
            raise ValueError(f"child license source is not a regular blob: {path}")
        raw = _git(repo, "cat-file", "blob", entry[2].decode())
        if not raw.strip():
            raise ValueError(f"child license source empty: {path}")
        license_sources.append({
            "path": path, "git_blob": entry[2].decode(),
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        })
    modules_raw = b""
    if ".gitmodules" in entries:
        module_entry = entries[".gitmodules"]
        if module_entry[:2] not in ((b"100644", b"blob"), (b"100755", b"blob")):
            raise ValueError("child .gitmodules is not a regular blob")
        modules_raw = _git(repo, "cat-file", "blob", module_entry[2].decode())
    config = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        config.read_string(modules_raw.decode("utf-8"))
        module_links = {}
        for section in config.sections():
            path = config.get(section, "path")
            url = config.get(section, "url")
            if path in module_links:
                raise ValueError("duplicate nested module path")
            module_links[path] = url
    except (configparser.Error, UnicodeDecodeError) as exc:
        raise ValueError("invalid child .gitmodules") from exc
    gitlinks = {
        name: {"path": name, "url": module_links.get(name), "commit": oid.decode()}
        for name, (mode, kind, oid) in entries.items()
        if (mode, kind) == (b"160000", b"commit")
    }
    if set(module_links) != set(gitlinks):
        raise ValueError("nested gitlink without exact module mapping")
    build_fetch_lines = []
    for path, (mode, kind, oid) in entries.items():
        if kind != b"blob" or mode == b"120000":
            continue
        if not (path.endswith(".cmake") or path.endswith("CMakeLists.txt")):
            continue
        raw = _git(repo, "cat-file", "blob", oid.decode())
        for line_number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            if re.search(r"\b(?:GIT_REPOSITORY|GIT_TAG|FetchContent_Declare|ExternalProject_Add)\b", line):
                build_fetch_lines.append({"path": path, "line": line_number, "text": line.strip()})
    return {
        "commit": expected_commit,
        "tree": tree,
        "tree_entry_count": len(entries),
        "license_sources": license_sources,
        "gitmodules_sha256": hashlib.sha256(modules_raw).hexdigest() if modules_raw else None,
        "nested_gitlinks": [gitlinks[path] for path in sorted(gitlinks)],
        "build_fetch_declarations": build_fetch_lines,
        "source_object_verified": True,
        "build_selection_verified": False,
        "transitive_source_closure_verified": False,
        "agent_binary_built_or_run": False,
    }


def build_manifest(parent_repo, parent_commit, expected_links, child_repos, child_specs):
    """Require exactly one verified child object for every fixed parent gitlink."""
    if set(child_repos) != set(child_specs):
        raise ValueError("child source inventory incomplete")
    paths = [spec[0] for spec in child_specs.values()]
    if len(set(paths)) != len(paths) or set(paths) != set(expected_links):
        raise ValueError("child path inventory incomplete")
    parent = verify_parent_links(parent_repo, parent_commit, expected_links)
    children = {}
    for name, (path, licenses) in child_specs.items():
        children[name] = audit_child(
            child_repos[name], parent["links"][path]["commit"], licenses,
        )
    return {
        "schema": "flydrones.fastdds_gitlink_objects.v1",
        "parent": parent,
        "children": children,
        "source_objects_verified": True,
        "build_selection_verified": False,
        "transitive_source_closure_verified": False,
        "agent_binary_built_or_run": False,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-repo", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    children = {name: args.root / f"{name}.git" for name in CHILD_SPECS}
    print(json.dumps(build_manifest(
        args.parent_repo, PARENT_COMMIT, LINKS, children, CHILD_SPECS,
    ), sort_keys=True))


if __name__ == "__main__":
    main()
