"""Integrity checks for the one-shot status type evidence sealer."""

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

SEAL_PATH = (Path(__file__).resolve().parents[2] / "results"
             / "px4-status-ros-type-build-dev-1701-seal.py")
SPEC = importlib.util.spec_from_file_location("status_type_seal", SEAL_PATH)
seal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seal)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _qualified_result() -> dict:
    return {
        "build_started": True,
        "docker_exit": 0,
        "timed_out": False,
        "launch_error": None,
        "source_after_verified": True,
        "postflight_error": None,
        "installed_status_sha256": seal.STATUS_SHA,
        "generated_idl_sha256": "a" * 64,
        "generated_struct_sha256": "b" * 64,
        "generated_type_support_sha256": "c" * 64,
        "generated_type_support_library_sha256": "d" * 64,
        "owned_container_remaining": "",
        "container_inspection_error": None,
        "daemon_id_before": "pinned-daemon",
        "daemon_id_after": "pinned-daemon",
    }


@pytest.mark.parametrize("field,bad", [
    ("build_started", False), ("docker_exit", 1), ("timed_out", True),
    ("launch_error", "failed"), ("source_after_verified", False),
    ("postflight_error", "failed"), ("installed_status_sha256", "0" * 64),
    ("generated_idl_sha256", None), ("owned_container_remaining", "running"),
    ("container_inspection_error", "failed"), ("daemon_id_after", "other"),
])
def test_success_qualification_rejects_failure_fields(field, bad):
    result = _qualified_result()
    assert seal._reported_success(result)
    result[field] = bad
    assert not seal._reported_success(result)


def test_launched_failure_cannot_drop_docker_log(tmp_path, monkeypatch):
    monkeypatch.setattr(seal, "RUN", tmp_path)
    for name in ("run-profile.json", "result.json", "launch.json",
                 "source-verify-before-copy.json", "copy-verify-before-build.json",
                 "preflight.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="docker-colcon.log"):
        seal._selected({"build_started": True}, success=False)


def test_source_seal_checks_every_profile_file(tmp_path, monkeypatch):
    run = tmp_path / "run"
    workspace = run / "workspace-v1"
    workspace.mkdir(parents=True)
    files = {"src/px4_msgs/msg/EstimatorStatus.msg": b"fixed status"}
    files.update({f"src/px4_msgs/msg/other{i:03}.msg": b"fixed other"
                  for i in range(259)})
    profile = {"files": {name: _sha(data) for name, data in files.items()},
               "git_commit": "fixed-commit"}
    profile_bytes = json.dumps(profile).encode("utf-8")
    seal_files = {
        "build-source-profile.json": profile_bytes,
        "build-source-profile.sha256": _sha(profile_bytes).encode("ascii"),
        "parent-build-source-profile.json": b"{}",
    }
    for name, data in {**files, **seal_files}.items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    parent = tmp_path / "parent.zip"
    with zipfile.ZipFile(parent, "w") as archive:
        for name, data in {**seal_files,
                           "src/px4_msgs/msg/EstimatorStatus.msg": b"fixed status"}.items():
            archive.writestr(seal.PARENT_PREFIX + name, data)
    monkeypatch.setattr(seal, "RUN", run)
    monkeypatch.setattr(seal, "PARENT", parent)
    monkeypatch.setattr(seal, "SOURCE_PROFILE_SHA", _sha(profile_bytes))
    monkeypatch.setattr(seal, "STATUS_SHA", _sha(b"fixed status"))
    monkeypatch.setattr(seal, "PINNED_COMMIT", "fixed-commit")
    seal._source_seals()
    (workspace / "src/px4_msgs/msg/other100.msg").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="workspace source changed"):
        seal._source_seals()
