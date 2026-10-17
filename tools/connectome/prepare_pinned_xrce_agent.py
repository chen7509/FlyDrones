"""Copy fixed XRCE Agent Git blobs and pin superbuild dependency refs.

This prepares source only. It never fetches, compiles, starts, or qualifies an Agent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

AGENT_COMMIT = "73622810d984349b80bbac0ef55fc0b694d62222"
AGENT_TREE = "30de05fce045d2cc40c3b911f4dc5085b24f1ab4"
SELECTED_SHA256 = {
    "CMakeLists.txt": "99a4934796b9bf98abb365e42eb6b0cdf57ca40067d2996aa4f03179491d329b",
    "cmake/SuperBuild.cmake": "86ac7d0e6643b62e4449b108e2ee76ae4e6d35004e3156970682841a74c65b29",
    "Dockerfile": "2bc2eb326b89001b74464b1c2234cfc2e28417c5d9b613f9be42d8e327d4c91c",
    "LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "README.md": "d59f374b872acefc3fd09cb96865abce53ec50129edee8952c8fe49cf50c5dc5",
}
DEPENDENCY_OBJECTS = {
    "fast_cdr": "757d5e422253568c487ad97c22e44680fc1ddbaf",
    "fast_dds": "575d045b55c16be1074ccd9eebf95e3e4274fe61",
    "foonathan_memory": "0f0775770fd1c506fa9c5ad566bd6ba59659db66",
    "spdlog": "eb3220622e73a4889eee355ffa37972b3cac3df5",
    "xrce_client": "d44dc3fa0c488376e34d26ed92853f1c66dcb670",
}
OLD_DECLARATIONS = {
    "fast_cdr": b"set(_fastcdr_tag 2.2.x)",
    "fast_dds": b"set(_fastdds_tag 2.14.x)",
    "foonathan_memory": b"set(_foonathan_memory_tag v0.7-3)",
    "spdlog": b"set(_spdlog_tag v1.9.2)",
    "xrce_client": b"set(UAGENT_P2P_CLIENT_TAG v2.4.3 CACHE STRING",
}
NEW_PREFIXES = {
    "fast_cdr": b"set(_fastcdr_tag ",
    "fast_dds": b"set(_fastdds_tag ",
    "foonathan_memory": b"set(_foonathan_memory_tag ",
    "spdlog": b"set(_spdlog_tag ",
    "xrce_client": b"set(UAGENT_P2P_CLIENT_TAG ",
}
MAX_FILES = 500
MAX_FILE_BYTES = 10_000_000
MAX_TOTAL_BYTES = 50_000_000


def _git(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True, capture_output=True,
        env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"},
    ).stdout


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(raw: bytes) -> PurePosixPath:
    name = raw.decode("utf-8")
    if (not name or name.startswith("/") or "\\" in name or ":" in name
            or any(part in ("", ".", "..") for part in name.split("/"))):
        raise ValueError("unsafe Git tree path")
    for part in name.split("/"):
        stem = part.split(".", 1)[0].casefold()
        if (part.endswith((".", " ")) or stem in {"con", "prn", "aux", "nul"}
                or re.fullmatch(r"(?:com|lpt)[1-9]", stem)):
            raise ValueError("unsafe Windows Git tree path")
    return PurePosixPath(name)


def _pin_cmake(raw: bytes, pins: dict[str, str]) -> bytes:
    if set(pins) != set(OLD_DECLARATIONS):
        raise ValueError("dependency pin set changed")
    for key, old in OLD_DECLARATIONS.items():
        if raw.count(old) != 1:
            raise ValueError(f"dependency declaration missing or duplicate: {key}")
        new = NEW_PREFIXES[key] + pins[key].encode("ascii")
        new += b" CACHE STRING" if key == "xrce_client" else b")"
        raw = raw.replace(old, new)
    return raw


def prepare_source(
    repo: Path,
    destination: Path,
    expected_commit: str,
    expected_tree: str,
    selected_sha256: dict[str, str],
    dependency_objects: dict[str, str],
    expected_file_count: int,
) -> dict:
    """Prepare a separate unqualified source candidate from exact Git blobs."""
    repo, destination = Path(repo), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    if (not re.fullmatch(r"[0-9a-f]{40}", expected_commit)
            or not re.fullmatch(r"[0-9a-f]{40}", expected_tree)
            or not isinstance(expected_file_count, int)
            or isinstance(expected_file_count, bool)
            or not 1 <= expected_file_count <= MAX_FILES):
        raise ValueError("fixed source identity invalid")
    if (set(dependency_objects) != set(OLD_DECLARATIONS)
            or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value)
                   for value in dependency_objects.values())):
        raise ValueError("dependency object ID invalid")
    if (not {"CMakeLists.txt", "cmake/SuperBuild.cmake"}.issubset(selected_sha256)
            or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                   for value in selected_sha256.values())):
        raise ValueError("selected source hashes invalid")
    if _git(repo, "rev-parse", "HEAD").decode().strip() != expected_commit:
        raise ValueError("Agent HEAD changed")
    if _git(repo, "cat-file", "-t", expected_commit).decode().strip() != "commit":
        raise ValueError("Agent object is not a commit")
    if _git(repo, "rev-parse", "HEAD^{tree}").decode().strip() != expected_tree:
        raise ValueError("Agent tree changed")

    entries: list[tuple[PurePosixPath, str, bytes]] = []
    seen: set[str] = set()
    directories: dict[str, str] = {}
    total = 0
    for raw in _git(repo, "ls-tree", "-rz", "--full-tree", expected_commit).split(b"\0"):
        if not raw:
            continue
        metadata, separator, path_raw = raw.partition(b"\t")
        fields = metadata.split()
        if separator != b"\t" or len(fields) != 3:
            raise ValueError("Git tree entry invalid")
        mode, kind, object_id = fields
        if mode not in (b"100644", b"100755") or kind != b"blob":
            raise ValueError("unsupported Git mode or object type")
        name = _safe_name(path_raw)
        folded = name.as_posix().casefold()
        if folded == "source-profile.json":
            raise ValueError("reserved source-profile path")
        parents = ["/".join(name.parts[:i]) for i in range(1, len(name.parts))]
        if folded in seen or folded in directories or any(parent.casefold() in seen for parent in parents):
            raise ValueError("Git tree path alias")
        if any(parent.casefold() in directories
               and directories[parent.casefold()] != parent for parent in parents):
            raise ValueError("Git tree directory alias")
        seen.add(folded)
        directories.update({parent.casefold(): parent for parent in parents})
        object_name = object_id.decode("ascii")
        size = int(_git(repo, "cat-file", "-s", object_name))
        if size < 0 or size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES:
            raise ValueError("Agent source exceeds size limit")
        blob = _git(repo, "cat-file", "blob", object_name)
        if len(blob) != size:
            raise ValueError("Git blob size changed")
        total += size
        entries.append((name, mode.decode("ascii"), blob))
    if len(entries) != expected_file_count:
        raise ValueError("Agent file count changed")
    source_files = {name.as_posix(): blob for name, _, blob in entries}
    for name, expected_hash in selected_sha256.items():
        if name not in source_files or _sha256(source_files[name]) != expected_hash:
            raise ValueError(f"selected Agent source changed: {name}")
    if "CMakeLists.txt" not in source_files:
        raise ValueError("Agent CMakeLists missing")
    patched_cmake = _pin_cmake(source_files["CMakeLists.txt"], dependency_objects)

    destination.mkdir(parents=True, exist_ok=False)
    files = {}
    modes = {}
    for name, mode, blob in entries:
        relative = name.as_posix()
        output = patched_cmake if relative == "CMakeLists.txt" else blob
        target = destination / Path(*name.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(output)
        if mode == "100755" and os.name != "nt":
            target.chmod(0o755)
        files[relative] = _sha256(output)
        modes[relative] = mode
    profile = {
        "schema": "flydrones.pinned_xrce_agent_source.v1",
        "agent_commit": expected_commit,
        "agent_tree": expected_tree,
        "original_selected_sha256": selected_sha256,
        "dependency_objects": dependency_objects,
        "file_count": len(entries),
        "total_original_bytes": total,
        "files": files,
        "git_modes": modes,
        "agent_binary_built_or_run": False,
        "dependency_commits_verified_locally": False,
        "px4_agent_interoperability_verified": False,
        "eligible_for_owned_source_trial": False,
    }
    (destination / "source-profile.json").write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = prepare_source(args.source, args.destination, AGENT_COMMIT, AGENT_TREE,
                            SELECTED_SHA256, DEPENDENCY_OBJECTS, 213)
    print(json.dumps({"agent_commit": result["agent_commit"],
                      "agent_tree": result["agent_tree"],
                      "file_count": result["file_count"],
                      "source_profile_sha256": _sha256(
                          (args.destination / "source-profile.json").read_bytes()),
                      "agent_binary_built_or_run": False}, sort_keys=True))


if __name__ == "__main__":
    main()
