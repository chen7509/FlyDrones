"""Inspect exact local Agent dependency commits without building or checkout conversion."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

DEPENDENCIES = {
    "fast_cdr": ("https://github.com/eProsima/Fast-CDR.git",
                 "757d5e422253568c487ad97c22e44680fc1ddbaf"),
    "fast_dds": ("https://github.com/eProsima/Fast-DDS.git",
                 "575d045b55c16be1074ccd9eebf95e3e4274fe61"),
    "foonathan_memory": ("https://github.com/foonathan/memory.git",
                         "0f0775770fd1c506fa9c5ad566bd6ba59659db66"),
    "spdlog": ("https://github.com/gabime/spdlog.git",
               "eb3220622e73a4889eee355ffa37972b3cac3df5"),
    "xrce_client": ("https://github.com/eProsima/Micro-XRCE-DDS-Client.git",
                    "d44dc3fa0c488376e34d26ed92853f1c66dcb670"),
}
TRANSITIVE_CANDIDATES = {
    "micro_cdr": ("https://github.com/eProsima/Micro-CDR.git",
                  "3d1b17703c7cf4f22def2910bc845bdb5152d7b5"),
}
GIT_ENV = {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}
MICRO_CDR_TAG_LINE = (
    b"3d1b17703c7cf4f22def2910bc845bdb5152d7b5\trefs/tags/v2.0.1"
)


def _git(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], env=GIT_ENV,
            check=True, capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"Git object unavailable: {args}") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_micro_cdr_tag_observation(raw: bytes) -> str:
    """Accept only the exact lightweight tag response observed from upstream."""
    if raw.strip() != MICRO_CDR_TAG_LINE or len(raw.splitlines()) != 1:
        raise ValueError("Micro-CDR tag observation differs from fixed object")
    return MICRO_CDR_TAG_LINE.split(b"\t", 1)[0].decode("ascii")


def audit_repository(repo: Path, expected_commit: str) -> dict:
    """Qualify a direct Git commit; never claim its transitive closure."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("invalid expected commit ID")
    if _git(repo, "rev-parse", "--is-bare-repository").strip() != b"true":
        raise ValueError("dependency repository is not bare")
    if _git(repo, "rev-parse", "FETCH_HEAD").decode().strip() != expected_commit:
        raise ValueError("fetched object differs from requested commit")
    if _git(repo, "rev-parse", "refs/flydrones/pins/source").decode().strip() != expected_commit:
        raise ValueError("local source pin differs from requested commit")
    if _git(repo, "cat-file", "-t", expected_commit).strip() != b"commit":
        raise ValueError("dependency object is not a commit")
    tree = _git(repo, "rev-parse", f"{expected_commit}^{{tree}}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise ValueError("invalid dependency tree")
    entries = {}
    for raw in _git(repo, "ls-tree", "-rz", "--full-tree", expected_commit).split(b"\0"):
        if not raw:
            continue
        metadata, tab, path = raw.partition(b"\t")
        fields = metadata.split()
        if tab != b"\t" or len(fields) != 3:
            raise ValueError("invalid dependency tree entry")
        mode, kind, oid = fields
        name = path.decode("utf-8")
        if name in entries or not re.fullmatch(rb"[0-9a-f]{40}", oid):
            raise ValueError("duplicate or invalid dependency entry")
        if (mode, kind) not in ((b"100644", b"blob"), (b"100755", b"blob"),
                                (b"120000", b"blob"), (b"160000", b"commit")):
            raise ValueError("unsupported dependency entry")
        entries[name] = {"mode": mode.decode(), "kind": kind.decode(), "object": oid.decode()}
    if "LICENSE" not in entries:
        raise ValueError("dependency LICENSE missing")
    if entries["LICENSE"]["mode"] not in ("100644", "100755"):
        raise ValueError("dependency LICENSE must be a regular file")
    license_raw = _git(repo, "cat-file", "blob", entries["LICENSE"]["object"])
    if not license_raw.strip():
        raise ValueError("dependency LICENSE empty")
    gitlinks = {name: entry["object"] for name, entry in entries.items()
                if entry["mode"] == "160000"}
    modules_raw = b""
    if ".gitmodules" in entries:
        if entries[".gitmodules"]["mode"] not in ("100644", "100755"):
            raise ValueError("dependency .gitmodules must be a regular file")
        modules_raw = _git(repo, "cat-file", "blob", entries[".gitmodules"]["object"])
    for name in gitlinks:
        if not re.search(rb"(?m)^\s*path\s*=\s*" + re.escape(name.encode()) + rb"\s*$", modules_raw):
            raise ValueError(f"gitlink without .gitmodules mapping: {name}")
    build_fetch_lines = []
    for name, entry in entries.items():
        if entry["kind"] != "blob" or not (name.endswith(".cmake") or name.endswith("CMakeLists.txt")):
            continue
        raw = _git(repo, "cat-file", "blob", entry["object"])
        for line_number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            if re.search(r"\b(?:GIT_REPOSITORY|GIT_TAG|FetchContent_Declare|ExternalProject_Add)\b", line):
                build_fetch_lines.append({"path": name, "line": line_number, "text": line.strip()})
    return {
        "commit": expected_commit,
        "tree": tree,
        "tree_entry_count": len(entries),
        "license_path": "LICENSE",
        "license_git_blob": entries["LICENSE"]["object"],
        "license_sha256": _sha(license_raw),
        "license_bytes": len(license_raw),
        "gitlinks": [{"path": name, "object": oid} for name, oid in sorted(gitlinks.items())],
        "gitmodules_sha256": _sha(modules_raw) if modules_raw else None,
        "build_fetch_declarations": build_fetch_lines,
        "direct_source_object_verified": True,
        "transitive_source_closure_verified": False,
        "agent_binary_built_or_run": False,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--micro-cdr-tag-observation", type=Path, required=True)
    args = parser.parse_args()
    observed_micro_cdr = verify_micro_cdr_tag_observation(
        args.micro_cdr_tag_observation.read_bytes()
    )
    if observed_micro_cdr != TRANSITIVE_CANDIDATES["micro_cdr"][1]:
        raise ValueError("Micro-CDR tag and transitive candidate differ")
    report = {name: {"source_url": url,
                     **audit_repository(args.root / f"{name}.git", commit)}
              for name, (url, commit) in DEPENDENCIES.items()}
    transitive = {name: {"source_url": url,
                         "observed_ref": "refs/tags/v2.0.1",
                         **audit_repository(args.root / f"{name}.git", commit)}
                  for name, (url, commit) in TRANSITIVE_CANDIDATES.items()}
    print(json.dumps({"schema": "flydrones.agent_dependency_objects.v2",
                      "dependencies": report,
                      "transitive_candidates": transitive,
                      "all_direct_source_objects_verified": True,
                      "transitive_source_closure_verified": False,
                      "agent_binary_built_or_run": False}, sort_keys=True))


if __name__ == "__main__":
    main()
