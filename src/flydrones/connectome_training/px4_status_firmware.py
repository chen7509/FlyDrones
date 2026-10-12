"""Fail-closed facts audit for an isolated PX4 EstimatorStatus source candidate.

Source preparation is not a firmware build or an authenticated DDS source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

_PROFILE_SCHEMA = "flydrones.px4_estimator_status_firmware_source.v1"
_TOPIC = "src/modules/uxrce_dds_client/dds_topics.yaml"
_CANDIDATE_STATUS = [" M " + _TOPIC]
_NO_AUTHORITY = {
    "firmware_compiled_verified": False,
    "live_source_authenticated": False,
    "fusion_qualified": False,
    "training_eligible": False,
}
_SOURCE_PATHS = (
    _TOPIC,
    "src/modules/uxrce_dds_client/generate_dds_topics.py",
    "src/modules/uxrce_dds_client/dds_topics.h.em",
    "msg/EstimatorStatus.msg",
)
_SUBMODULE_LINE = re.compile(r"^([ +\-U])([0-9a-f]{40}) ([^\s]+)(?: .*)?$")


def parse_submodule_status(output: str) -> dict[str, dict[str, str]]:
    """Preserve missing and modified gitlink states from `git submodule status`."""
    found: dict[str, dict[str, str]] = {}
    for line in output.splitlines():
        match = _SUBMODULE_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"invalid submodule status line: {line!r}")
        prefix, commit, path = match.groups()
        if path in found:
            raise ValueError(f"duplicate submodule status: {path}")
        state = {" ": "initialized", "-": "missing", "+": "modified", "U": "conflicted"}[prefix]
        found[path] = {"commit": commit, "state": state}
    return found


def _run_git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=True, timeout=30,
    )
    return proc.stdout


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_firmware_source_facts(
    root: Path, candidate: Path, result_path: Path, *, stage: str,
    namespace: str = "",
) -> dict:
    """Read source facts only; never initialize a submodule or copy the candidate."""
    root = Path(root)
    candidate = Path(candidate)
    result_path = Path(result_path)
    if not root.is_dir() or not candidate.is_file():
        raise ValueError("source root or candidate missing")
    return {
        "root": str(root),
        "root_canonical": root.is_absolute() and root.resolve(strict=True) == root,
        "candidate_canonical": candidate.is_absolute() and candidate.resolve(strict=True) == candidate,
        "result_path": str(result_path),
        "result_parent_canonical": (
            result_path.is_absolute()
            and result_path.parent.resolve(strict=True) == result_path.parent
        ),
        "result_path_exists": result_path.exists() or result_path.is_symlink(),
        "commit": _run_git(root, "rev-parse", "HEAD").strip(),
        "namespace": namespace,
        "stage": stage,
        "tracked_status": _run_git(root, "status", "--porcelain=v1", "--untracked-files=no").splitlines(),
        "source_sha256": {name: _sha256(root / name) for name in _SOURCE_PATHS},
        "candidate_sha256": _sha256(candidate),
        "submodules": parse_submodule_status(_run_git(root, "submodule", "status")),
    }


def audit_firmware_source_facts(profile: Mapping, facts: Mapping) -> dict:
    """Validate collected source facts without writing to either PX4 checkout."""
    errors: list[str] = []
    result = {
        "schema": "flydrones.px4_status_firmware_source_audit.v1",
        "stage": facts.get("stage") if isinstance(facts, Mapping) else None,
        "base_source_attested": False,
        "source_prepared": False,
        "errors": errors,
        **_NO_AUTHORITY,
    }
    if not isinstance(profile, Mapping) or profile.get("schema") != _PROFILE_SCHEMA:
        errors.append("profile_invalid")
        return result
    if not isinstance(facts, Mapping):
        errors.append("facts_invalid")
        return result
    expected_hashes = profile.get("source_sha256")
    expected_submodules = profile.get("required_sitl_submodules")
    if not isinstance(expected_hashes, Mapping) or not isinstance(expected_submodules, Mapping):
        errors.append("profile_invalid")
        return result
    if facts.get("root") != profile.get("isolated_root") or facts.get("root_canonical") is not True:
        errors.append("source_path_alias")
    if facts.get("candidate_canonical") is not True:
        errors.append("candidate_path_alias")
    if facts.get("result_path") != profile.get("build_result_path"):
        errors.append("result_path_mismatch")
    if facts.get("result_parent_canonical") is not True:
        errors.append("result_path_alias")
    if facts.get("result_path_exists") is not False:
        errors.append("result_path_reused")
    if facts.get("commit") != profile.get("px4_commit"):
        errors.append("px4_commit_mismatch")
    if facts.get("namespace") != profile.get("namespace") or profile.get("namespace") != "":
        errors.append("dds_namespace_unexpected")
    stage = facts.get("stage")
    if stage not in ("base", "candidate"):
        errors.append("source_stage_invalid")
    expected_status = [] if stage == "base" else _CANDIDATE_STATUS
    if facts.get("tracked_status") != expected_status:
        errors.append("tracked_changes_unexpected")
    observed_hashes = facts.get("source_sha256")
    if not isinstance(observed_hashes, Mapping):
        errors.append("source_hashes_missing")
    else:
        for name, expected in expected_hashes.items():
            if name == _TOPIC and stage == "candidate":
                expected = profile.get("candidate_yaml_sha256")
            if observed_hashes.get(name) != expected:
                errors.append(f"source_hash_mismatch:{name}")
        if set(observed_hashes) != set(expected_hashes):
            errors.append("source_file_set_mismatch")
    if facts.get("candidate_sha256") != profile.get("candidate_yaml_sha256"):
        errors.append("candidate_yaml_mismatch")
    observed_submodules = facts.get("submodules")
    if not isinstance(observed_submodules, Mapping):
        errors.append("submodules_missing")
    else:
        for name, expected in expected_submodules.items():
            item = observed_submodules.get(name)
            if (not isinstance(item, Mapping) or item.get("state") != "initialized"
                    or item.get("commit") != expected):
                errors.append(f"submodule_unavailable:{name}")
    if not errors:
        result["base_source_attested"] = True
        result["source_prepared"] = stage == "candidate"
    return result


def main(argv: list[str] | None = None) -> int:
    """Print a read-only audit; a refusal exits nonzero and preserves facts."""
    parser = argparse.ArgumentParser(description="Audit isolated PX4 status source")
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--result-path", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=("base", "candidate"))
    parser.add_argument("--namespace", default="")
    args = parser.parse_args(argv)
    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        facts = collect_firmware_source_facts(
            args.root, args.candidate, args.result_path,
            stage=args.stage, namespace=args.namespace,
        )
        audit = audit_firmware_source_facts(profile, facts)
        payload = {"facts": facts, "audit": audit}
        success = audit["source_prepared"] if args.stage == "candidate" else audit["base_source_attested"]
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        payload = {
            "facts": None,
            "audit": {
                "source_prepared": False, "base_source_attested": False,
                "errors": [f"collection_error:{type(exc).__name__}:{exc}"],
                **_NO_AUTHORITY,
            },
        }
        success = False
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
