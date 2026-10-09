import json
from types import SimpleNamespace

import pytest

from tools.connectome import run_byte_bound_ros_build as build


def test_resume_preserves_initial_preflight_failure_and_never_launches(tmp_path, monkeypatch):
    result = tmp_path / "result"
    workspace = result / "workspace-v1"
    workspace.mkdir(parents=True)
    source = tmp_path / "source"
    source.mkdir()
    original = {"status": "preflight_failed", "build_started": False}
    (result / "result.json").write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(build, "RESULT", result)
    monkeypatch.setattr(build, "WORKSPACE", workspace)
    monkeypatch.setattr(build, "SOURCE", source)
    (result / "run-profile.json").write_text(
        json.dumps(build._profile()), encoding="utf-8"
    )
    monkeypatch.setattr(build, "verify_workspace", lambda _: {"verified": True})
    monkeypatch.setattr(build, "_preflight", lambda *args: (_ for _ in ()).throw(
        RuntimeError("memory below gate")
    ))

    with pytest.raises(RuntimeError, match="memory below gate"):
        build.main(resume=True)

    assert json.loads((result / "result.json").read_text()) == original
    assert json.loads((result / "resume-result.json").read_text()) == {
        "status": "preflight_failed", "error": "RuntimeError('memory below gate')",
        "build_started": False,
    }
    assert (result / "resume-reserved.json").is_file()
    with pytest.raises(FileExistsError):
        build.main(resume=True)
    assert not (result / "launch.json").exists()


def test_resume_rejects_changed_source_pin_before_preflight(tmp_path, monkeypatch):
    result = tmp_path / "result"
    result.mkdir()
    (result / "result.json").write_text(
        json.dumps({"status": "preflight_failed", "build_started": False}),
        encoding="utf-8",
    )
    monkeypatch.setattr(build, "RESULT", result)
    monkeypatch.setattr(build, "SOURCE", tmp_path / "source")
    monkeypatch.setattr(build, "WORKSPACE", result / "workspace-v1")
    changed = build._profile()
    changed["source_profile_sha256"] = "0" * 64
    (result / "run-profile.json").write_text(
        json.dumps(changed), encoding="utf-8"
    )
    monkeypatch.setattr(
        build, "_preflight", lambda *args: pytest.fail("preflight must not run")
    )

    with pytest.raises(RuntimeError, match="immutable runner pin"):
        build.main(resume=True)
    assert json.loads((result / "resume-result.json").read_text())["build_started"] is False
    assert not (result / "launch.json").exists()


def test_docker_process_creation_failure_is_not_reported_as_started(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "build-source-profile.json").write_text("profile", encoding="utf-8")
    result = tmp_path / "result"
    monkeypatch.setattr(build, "SOURCE", source)
    monkeypatch.setattr(build, "RESULT", result)
    monkeypatch.setattr(build, "WORKSPACE", result / "workspace-v1")
    monkeypatch.setattr(build, "verify_workspace", lambda _: {"verified": True})
    monkeypatch.setattr(build, "_hash", lambda _: build.SOURCE_PROFILE_SHA256)
    monkeypatch.setattr(
        build, "_preflight",
        lambda *args: {"source_profile_sha256": build.SOURCE_PROFILE_SHA256},
    )
    monkeypatch.setattr(
        build.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("docker launch unavailable")
        ),
    )
    monkeypatch.setattr(
        build.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    assert build.main() == 1
    actual = json.loads((result / "result.json").read_text())
    assert actual["build_started"] is False
    assert "docker launch unavailable" in actual["launch_error"]
