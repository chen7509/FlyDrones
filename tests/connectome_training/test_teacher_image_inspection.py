"""The teacher image must be inspected without starting its planner."""

import json
import subprocess
import sys

import pytest

IMAGE = "sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a"
COMMIT = "23a8d5a191711dd65633df689bd00f55d4dea8f9"
REMOTE = "https://github.com/ZJU-FAST-Lab/ego-planner-swarm.git"
NODE = "/ego_ws/install/ego_planner/lib/ego_planner/ego_planner_node"
SERVER = "/ego_ws/install/ego_planner/lib/ego_planner/traj_server"


def _outputs(*, image=IMAGE, head=COMMIT, status="", remote=REMOTE, executables=None):
    if executables is None:
        executables = "ego_planner ego_planner_node\nego_planner traj_server\n"
    return [
        image + "\n",
        head + "\n",
        status,
        remote + "\n",
        executables,
        f"{'a' * 64}  {NODE}\n{'b' * 64}  {SERVER}\n",
    ]


class _Runner:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, next(self.outputs), "")


def test_inspection_pins_source_and_built_executables_without_network(tmp_path):
    from flydrones.connectome_training.teacher_image import inspect_pinned_ego_image

    runner = _Runner(_outputs())
    result = inspect_pinned_ego_image(tmp_path / "inspection", run=runner)
    assert result["inspected"] is True
    assert result["image_id"] == IMAGE
    assert result["upstream_commit"] == COMMIT
    assert result["executables"] == {NODE: "a" * 64, SERVER: "b" * 64}
    assert len(runner.calls) == 6
    for args, kwargs in runner.calls[1:]:
        assert args[args.index("--network") + 1] == "none"
        assert "--read-only" in args
        assert "--pull=never" in args
        assert "--name" in args
        assert args[args.index("--entrypoint") + 2] == IMAGE
        assert kwargs["timeout"] <= 20
    assert json.loads((tmp_path / "inspection" / "inspection.json").read_text()) == result


@pytest.mark.parametrize("bad,reason", [
    ({"image": "sha256:" + "0" * 64}, "image ID"),
    ({"head": "0" * 40}, "upstream commit"),
    ({"status": " M src/planner.cpp\n"}, "dirty"),
    ({"remote": REMOTE + "\nhttps://example.invalid/rewrite.git"}, "remote"),
    ({"remote": "https://example.invalid/rewrite.git"}, "remote"),
    ({"executables": "ego_planner ego_planner_node\n"}, "executables"),
])
def test_inspection_refuses_identity_drift_and_retains_partial_evidence(tmp_path, bad, reason):
    from flydrones.connectome_training.teacher_image import inspect_pinned_ego_image

    runner = _Runner(_outputs(**bad))
    with pytest.raises(ValueError, match=reason):
        inspect_pinned_ego_image(tmp_path / "inspection", run=runner)
    evidence = json.loads((tmp_path / "inspection" / "inspection.json").read_text())
    assert evidence["inspected"] is False
    assert len(evidence["commands"]) == len(runner.calls)
    assert all("argv" in command and "stdout" in command for command in evidence["commands"])


def test_inspection_timeout_is_retained_and_cannot_be_overwritten(tmp_path):
    from flydrones.connectome_training.teacher_image import inspect_pinned_ego_image

    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"], output=b"partial")

    output = tmp_path / "inspection"
    with pytest.raises(ValueError, match="timeout"):
        inspect_pinned_ego_image(output, run=timeout)
    evidence = json.loads((output / "inspection.json").read_text())
    assert evidence["inspected"] is False
    assert evidence["commands"][0]["stdout"] == "partial"
    with pytest.raises(FileExistsError):
        inspect_pinned_ego_image(output, run=timeout)


def test_inspection_rejects_failed_docker_command_and_invalid_binary_digest(tmp_path):
    from flydrones.connectome_training.teacher_image import inspect_pinned_ego_image

    def failed_image(args, **kwargs):
        return subprocess.CompletedProcess(args, 125, "", "daemon unavailable")

    with pytest.raises(ValueError, match="image ID failed"):
        inspect_pinned_ego_image(tmp_path / "failed", run=failed_image)
    failure = json.loads((tmp_path / "failed" / "inspection.json").read_text())
    assert failure["commands"][0]["returncode"] == 125
    assert failure["commands"][0]["stderr"] == "daemon unavailable"

    outputs = _outputs()
    outputs[-1] = f"{'0' * 63}  {NODE}\n{'b' * 64}  {SERVER}\n"
    with pytest.raises(ValueError, match="binary hashes invalid"):
        inspect_pinned_ego_image(tmp_path / "bad-hash", run=_Runner(outputs))
    assert json.loads((tmp_path / "bad-hash" / "inspection.json").read_text())["inspected"] is False


def test_bounded_runner_caps_output_before_accumulating():
    from flydrones.connectome_training.teacher_image import _bounded_run

    result = _bounded_run(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000)"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert len(result.stdout) <= 65537
    assert result.returncode != 0


def test_bounded_runner_refuses_unverified_owned_container_cleanup(monkeypatch):
    import flydrones.connectome_training.teacher_image as teacher_image
    from flydrones.connectome_training.teacher_image import _bounded_run

    calls = []

    def failed_cleanup(name):
        args = ["docker", "rm", "-f", name]
        calls.append(args)
        return {"label": "owned container cleanup", "argv": args,
                "stdout": "", "stderr": "daemon error", "returncode": 1}

    monkeypatch.setattr(teacher_image, "_cleanup_owned", failed_cleanup)
    with pytest.raises(RuntimeError, match="cleanup unverified"):
        _bounded_run(
            [sys.executable, "-c", "import time; time.sleep(5)", "--name", "owned-test"],
            capture_output=True, text=True, timeout=0.1, check=False,
        )
    assert calls == [["docker", "rm", "-f", "owned-test"]]


def test_failed_cleanup_retains_original_output_and_cleanup_evidence(tmp_path, monkeypatch):
    import flydrones.connectome_training.teacher_image as teacher_image
    from flydrones.connectome_training.teacher_image import _bounded_run, inspect_pinned_ego_image

    def failed_cleanup(name):
        args = ["docker", "rm", "-f", name]
        return {"label": "owned container cleanup", "argv": args,
                "stdout": "", "stderr": "daemon error", "returncode": 1}

    monkeypatch.setattr(teacher_image, "_cleanup_owned", failed_cleanup)

    def run(args, **kwargs):
        if args[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(args, 0, IMAGE + "\n", "")
        return _bounded_run(
            [sys.executable, "-c", "import sys,time; print('partial', flush=True); time.sleep(5)",
             "--name", args[args.index("--name") + 1]],
            **{**kwargs, "timeout": 1.0},
        )

    with pytest.raises(ValueError, match="cleanup unverified"):
        inspect_pinned_ego_image(tmp_path / "inspection", run=run)
    evidence = json.loads((tmp_path / "inspection" / "inspection.json").read_text())
    assert evidence["inspected"] is False
    assert evidence["commands"][1]["stdout"].replace("\r\n", "\n") == "partial\n"
    assert evidence["commands"][2]["label"] == "owned container cleanup"
    assert evidence["commands"][2]["returncode"] == 1
