"""Read-only, fail-closed audit of the *isolated* PX4 status build output.

Run with WSL Python after the one-shot build. This module never builds or starts
PX4. A generated header or a successful launcher exit alone grants nothing.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

# Import the read-only source collector without the training package __init__,
# which imports torch on hosts where only the PX4 build toolchain is installed.
_SOURCE_MODULE = Path(__file__).resolve().parents[2] / "src/flydrones/connectome_training/px4_status_firmware.py"
_SOURCE_SPEC = importlib.util.spec_from_file_location("px4_status_firmware_readonly", _SOURCE_MODULE)
if _SOURCE_SPEC is None or _SOURCE_SPEC.loader is None:
    raise RuntimeError("source_collector_unavailable")
_source_module = importlib.util.module_from_spec(_SOURCE_SPEC)
_SOURCE_SPEC.loader.exec_module(_source_module)
collect_firmware_source_facts = _source_module.collect_firmware_source_facts

HEADER_SHA256 = "bef5afc679cb23ede466cd1ce22db270d3611492ab2326a1e41ce513cbe1c4fc"
BUILD_PROFILE_SHA256 = "12990af3daa437772aae3d6440a3f209ab6c4b0c1af4bad8a6e85a5adf9bee3a"
BUILD_REL = Path("build/px4_sitl_default")
HEADER_REL = Path("src/modules/uxrce_dds_client/dds_topics.h")
BINARY_REL = Path("bin/px4")
ARCHIVE = "src/modules/uxrce_dds_client/libmodules__uxrce_dds_client.a"
OBJECT = "src/modules/uxrce_dds_client/CMakeFiles/modules__uxrce_dds_client.dir/uxrce_dds_client.cpp.o"
TOPIC = "src/modules/uxrce_dds_client/dds_topics.yaml"
_NO_AUTHORITY = {
    "live_source_authenticated": False,
    "fusion_qualified": False,
    "training_eligible": False,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_file(path: Path, *, maximum: int | None = None) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"regular_file_required:{path}")
    before = path.stat()
    if maximum is not None and before.st_size > maximum:
        raise ValueError(f"file_too_large:{path}")
    digest = _sha256(path)
    after = path.stat()
    def identity(stat) -> tuple[int, ...]:
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    if identity(before) != identity(after):
        raise ValueError(f"file_changed_during_read:{path}")
    return {"sha256": digest, "size": before.st_size}


def _json(path: Path) -> dict:
    _stable_file(path, maximum=1024 * 1024)
    def unique(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate_json_key:{key}")
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"object_required:{path}")
    return value


def _capture(*command: str, cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            check=True, timeout=30)
    return result.stdout


def _pinned_toolchain_from_runner(source: str) -> dict:
    """Read pinned literal hashes without importing the resource-heavy runner."""
    found = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in (
                    "EXPECTED_TOOLCHAIN_FILES", "EXPECTED_TOOLCHAIN_MODULES"):
                if target.id in found:
                    raise ValueError("duplicate_runner_toolchain_pin")
                found[target.id] = ast.literal_eval(node.value)
    if set(found) != {"EXPECTED_TOOLCHAIN_FILES", "EXPECTED_TOOLCHAIN_MODULES"}:
        raise ValueError("runner_toolchain_pin_missing")
    return {"files": found["EXPECTED_TOOLCHAIN_FILES"],
            "modules": found["EXPECTED_TOOLCHAIN_MODULES"]}


def _ninja_log_chain(text: object) -> bool:
    if not isinstance(text, str) or not text.startswith("# ninja log v5\n"):
        return False
    targets = (OBJECT, ARCHIVE, "bin/px4")
    matching = {}
    for line in text.splitlines()[1:]:
        fields = line.split("\t")
        if len(fields) != 5:
            return False
        if fields[3] not in targets:
            continue
        if (fields[3] in matching or not all(x.isdecimal() for x in fields[:3])
                or int(fields[1]) < int(fields[0])
                or not re.fullmatch(r"[0-9a-f]+", fields[4])):
            return False
        matching[fields[3]] = (int(fields[0]), int(fields[1]))
    if set(matching) != set(targets):
        return False
    return (matching[OBJECT][1] <= matching[ARCHIVE][0]
            and matching[ARCHIVE][1] <= matching["bin/px4"][0])


def _fixed_scope_command(command: object, profile: Mapping) -> bool:
    """Match the actual launcher vector, including its sole random scope name."""
    if not isinstance(command, list) or len(command) != 30:
        return False
    expected = [
        "wsl.exe", "--distribution", profile.get("wsl_distro"), "--exec",
        "/usr/bin/systemd-run", "--user", "--scope", command[7],
        "--property=MemoryMax=4G", "--property=CPUQuota=100%",
        "--property=TimeoutStopSec=10s",
        f"--working-directory={profile.get('isolated_root')}",
        "/usr/bin/env", "-i", "HOME=/home/yuchen7509", "USER=yuchen7509",
        "PATH=/usr/bin:/bin", "GIT_CONFIG_COUNT=1",
        "GIT_CONFIG_KEY_0=protocol.allow", "GIT_CONFIG_VALUE_0=never",
        "GIT_TERMINAL_PROMPT=0", "CCACHE_DISABLE=1", "MAKEFLAGS=-j1",
        "/usr/bin/timeout", "--signal=TERM", "--kill-after=10s", "5400s",
        "/usr/bin/make", "-j1", "px4_sitl_default",
    ]
    return (command == expected and isinstance(command[7], str)
            and re.fullmatch(r"--unit=flydrones-px4-status-build-v1-[0-9a-f]{24}",
                             command[7]) is not None)


def collect_binary_facts(root: Path, evidence: Path, build_profile: Mapping) -> dict:
    """Collect from real files; call under WSL, never from an old checkout."""
    root = Path(root)
    evidence = Path(evidence)
    if (not isinstance(build_profile.get("build_result_path"), str)
            or str(root) != build_profile.get("isolated_root") or not root.is_dir()
            or root.resolve(strict=True) != root or evidence.is_symlink()
            or not evidence.is_dir()):
        raise ValueError("isolated_root_or_evidence_invalid")
    build = root / BUILD_REL
    header = build / HEADER_REL
    binary = build / BINARY_REL
    ninja = build / "build.ninja"
    archive = build / ARCHIVE
    obj = build / OBJECT
    for path in (header, binary, ninja, archive, obj):
        if not path.is_file() or path.is_symlink() or path.resolve(strict=True) != path:
            raise ValueError(f"build_artifact_missing_or_aliased:{path}")
    source = collect_firmware_source_facts(
        root, root / TOPIC, Path(str(build_profile["build_result_path"])), stage="candidate",
    )
    binary_id = _stable_file(binary)
    runner_path = Path(__file__).with_name("run_px4_status_firmware_build.py")
    runner_id = _stable_file(runner_path)
    runner_source = runner_path.read_text(encoding="utf-8")
    if hashlib.sha256(runner_source.encode("utf-8")).hexdigest() != runner_id["sha256"]:
        raise ValueError("runner_changed_during_read")
    log_path = build / ".ninja_log"
    log_identity = _stable_file(log_path, maximum=64 * 1024 * 1024)
    log_text = log_path.read_text(encoding="utf-8")
    if hashlib.sha256(log_text.encode("utf-8")).hexdigest() != log_identity["sha256"]:
        raise ValueError("ninja_log_changed_during_read")
    member = subprocess.run(["/usr/bin/ar", "p", str(archive), "uxrce_dds_client.cpp.o"],
                            cwd=build, capture_output=True, check=True, timeout=30).stdout
    with binary.open("rb") as stream:
        elf_magic = stream.read(4).hex()
    return {
        "source": source,
        "header": _stable_file(header),
        "binary": binary_id,
        "binary_elf_magic": elf_magic,
        "ninja": _stable_file(ninja),
        "archive": _stable_file(archive),
        "object": _stable_file(obj),
        "binary_query": _capture("/usr/bin/ninja", "-t", "query", "bin/px4", cwd=build),
        "archive_query": _capture("/usr/bin/ninja", "-t", "query", ARCHIVE, cwd=build),
        "object_deps": _capture("/usr/bin/ninja", "-t", "deps", OBJECT, cwd=build),
        "archive_members": _capture("/usr/bin/ar", "t", str(archive), cwd=build),
        "archive_member_sha256": hashlib.sha256(member).hexdigest(),
        "ninja_log": log_identity,
        "ninja_log_text": log_text,
        "runner_sha256": runner_id["sha256"],
        "pinned_toolchain": _pinned_toolchain_from_runner(runner_source),
        "readelf_notes": _capture("/usr/bin/readelf", "-n", str(binary), cwd=build),
        "preflight": _json(evidence / "preflight.json"),
        "launch": _json(evidence / "launch.json"),
        "dispatch": _json(evidence / "dispatch-result.json"),
        "stdout": _stable_file(evidence / "stdout.bin"),
        "stderr": _stable_file(evidence / "stderr.bin"),
    }


def audit_binary_facts(
    build_profile: Mapping, source_profile: Mapping, facts: Mapping,
    *, expected_header_sha256: str = HEADER_SHA256,
) -> dict:
    """Qualify only a fresh fixed build with a header→object→archive→ELF chain."""
    errors: list[str] = []
    result = {
        "schema": "flydrones.px4_status_firmware_binary_audit.v1",
        "firmware_compiled_verified": False,
        "dependency_closure_qualified": False,
        "errors": errors,
        **_NO_AUTHORITY,
    }
    if not all(isinstance(x, Mapping) for x in (build_profile, source_profile, facts)):
        errors.append("audit_input_invalid")
        return result
    preflight = facts.get("preflight")
    launch = facts.get("launch")
    dispatch = facts.get("dispatch")
    source = facts.get("source")
    if not all(isinstance(x, Mapping) for x in (preflight, launch, dispatch, source)):
        errors.append("build_record_missing")
        return result
    if (not all(isinstance(preflight.get(name), Mapping) for name in (
            "profile", "two_phase", "build_tree_audit", "build_tree_before",
            "toolchain_audit", "toolchain_before"))
            or not all(isinstance(dispatch.get(name), Mapping) for name in (
                "cleanup", "toolchain_after"))):
        errors.append("build_record_malformed")
        return result
    if (preflight.get("profile") != build_profile
            or build_profile.get("schema") != "flydrones.px4_status_firmware_build_admission.v1"
            or not _fixed_scope_command(preflight.get("command"), build_profile)
            or launch.get("command") != preflight.get("command")
            or launch.get("unit") != preflight["command"][7].removeprefix("--unit=") + ".scope"
            or type(launch.get("launcher_pid")) is not int
            or launch.get("launcher_pid") != dispatch.get("launcher_pid")
            or build_profile.get("command") != ["make", "-j1", "px4_sitl_default"]
            or preflight.get("two_phase", {}).get("dispatch_permitted") is not True
            or preflight.get("build_tree_audit", {}).get("build_tree_verified") is not True
            or preflight.get("build_tree_before", {}).get("build_exists") is not False
            or preflight.get("toolchain_audit", {}).get("toolchain_verified") is not True):
        errors.append("preflight_unqualified")
    if facts.get("build_profile_sha256") != BUILD_PROFILE_SHA256:
        errors.append("build_profile_unbound")
    if (facts.get("runner_sha256") != preflight.get("runner_sha256")
            or preflight.get("toolchain_before") != facts.get("pinned_toolchain")):
        errors.append("toolchain_identity_unverified")
    if (source_profile.get("schema") != "flydrones.px4_estimator_status_firmware_source.v1"
            or facts.get("source_profile_sha256") != build_profile.get("source_profile_sha256")):
        errors.append("source_profile_unbound")
    if (dispatch.get("build_dispatched") is not True
            or type(dispatch.get("build_exit_code")) is not int
            or dispatch.get("build_exit_code") != 0
            or dispatch.get("owned_scope_released") is not True
            or dispatch.get("cleanup", {}).get("graceful_scope_exit") is not True
            or dispatch.get("toolchain_unchanged") is not True
            or dispatch.get("toolchain_after") != preflight.get("toolchain_before")
            or dispatch.get("final_record_persisted") is not True
            or dispatch.get("timed_out") is not False
            or dispatch.get("errors") != []):
        errors.append("build_execution_unqualified")
    expected_sources = source_profile.get("source_sha256")
    expected_modules = source_profile.get("required_sitl_submodules")
    if (source.get("root") != build_profile.get("isolated_root")
            or source.get("root_canonical") is not True
            or source.get("candidate_canonical") is not True
            or source.get("result_path") != build_profile.get("build_result_path")
            or source.get("result_parent_canonical") is not True
            or source.get("result_path_exists") is not True
            or source.get("stage") != "candidate"
            or source.get("commit") != source_profile.get("px4_commit")
            or source.get("tracked_status") != [" M " + TOPIC]
            or source.get("namespace") != ""
            or not isinstance(expected_sources, Mapping)
            or not isinstance(expected_modules, Mapping)
            or not isinstance(source.get("source_sha256"), Mapping)
            or not isinstance(source.get("submodules"), Mapping)):
        errors.append("post_source_unqualified")
    else:
        selected = dict(expected_sources)
        selected[TOPIC] = source_profile.get("candidate_yaml_sha256")
        if (dict(source["source_sha256"]) != selected
                or source.get("candidate_sha256") != selected[TOPIC]
                or any(source["submodules"].get(name) != {"commit": commit, "state": "initialized"}
                       for name, commit in expected_modules.items())):
            errors.append("post_source_drift")
    header = facts.get("header")
    if not isinstance(header, Mapping) or header.get("sha256") != expected_header_sha256:
        errors.append("generated_header_mismatch")
    binary = facts.get("binary")
    if (not isinstance(binary, Mapping) or not isinstance(binary.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", binary["sha256"]) is None
            or type(binary.get("size")) is not int or binary["size"] <= 0
            or facts.get("binary_elf_magic") != "7f454c46"
            or re.search(r"Build ID: [0-9a-f]{16,}", str(facts.get("readelf_notes", ""))) is None):
        errors.append("binary_identity_invalid")
    binary_query = str(facts.get("binary_query", ""))
    archive_query = str(facts.get("archive_query", ""))
    object_deps = str(facts.get("object_deps", ""))
    archive_members = str(facts.get("archive_members", ""))
    object_identity = facts.get("object")
    if (not re.search(r"^bin/px4:\s*$", binary_query, re.M)
            or not re.search(r"^\s*[|]?\s*" + re.escape(ARCHIVE) + r"\s*$", binary_query, re.M)
            or not re.search(r"^" + re.escape(ARCHIVE) + r":\s*$", archive_query, re.M)
            or not re.search(r"^\s*" + re.escape(OBJECT) + r"\s*$", archive_query, re.M)
            or not re.search(r"^" + re.escape(OBJECT)
                             + r": #deps \d+, deps mtime \d+ \(VALID\)$", object_deps, re.M)
            or "src/modules/uxrce_dds_client/dds_topics.h" not in object_deps
            or archive_members.splitlines().count("uxrce_dds_client.cpp.o") != 1
            or not isinstance(object_identity, Mapping)
            or facts.get("archive_member_sha256") != object_identity.get("sha256")
            or not _ninja_log_chain(facts.get("ninja_log_text"))):
        errors.append("compiled_dependency_chain_unverified")
    for name in ("ninja", "archive", "object", "stdout", "stderr", "ninja_log"):
        item = facts.get(name)
        if (not isinstance(item, Mapping) or not isinstance(item.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
                or type(item.get("size")) is not int or item["size"] < 0):
            errors.append(f"artifact_identity_invalid:{name}")
    if not errors:
        result["firmware_compiled_verified"] = True
        result["binary_sha256"] = binary["sha256"]
        result["generated_header_sha256"] = header["sha256"]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only isolated PX4 binary audit")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--build-profile", required=True, type=Path)
    parser.add_argument("--source-profile", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        profile = _json(args.build_profile)
        source = _json(args.source_profile)
        facts = collect_binary_facts(args.root, args.evidence, profile)
        facts["build_profile_sha256"] = _stable_file(args.build_profile)["sha256"]
        facts["source_profile_sha256"] = _stable_file(args.source_profile)["sha256"]
        audit = audit_binary_facts(profile, source, facts)
        result = {"facts": facts, "audit": audit}
        success = audit["firmware_compiled_verified"]
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        result = {"audit": {"firmware_compiled_verified": False,
                            "errors": [f"audit_or_collection_error:{type(exc).__name__}:{exc}"],
                            **_NO_AUTHORITY}}
        success = False
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
