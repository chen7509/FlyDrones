import importlib
import json
import weakref
from dataclasses import replace

import pytest
import torch
import yaml
from test_learning_roles import PROFILES
from test_learning_roles import config as _config
from test_learning_roles import inert_backends as _inert

from flydrones.connectome_training import curriculum_session as sessions
from flydrones.connectome_training.curriculum_config import load_curriculum_config
from tools.connectome_training import run_curriculum as cli

config = _config
inert_backends = _inert


def producer():
    return importlib.import_module("flydrones.connectome_training.role_comparison")


def test_actual_three_roles_train_checkpoint_and_release_between_variants(config, tmp_path, monkeypatch):
    module = producer()
    actual = sessions.ConnectomeCurriculumSession
    previous = []
    changed = []
    run = module.run_curriculum

    def build(*args, **kwargs):
        assert all(ref() is None for ref in previous)
        current = actual(*args, **kwargs)
        previous.append(weakref.ref(current))
        return current

    def train(cfg, path, current, **kwargs):
        before = {n: p.detach().clone() for n, p in current.model.named_parameters()}
        state = run(cfg, path, current, **kwargs)
        updated = {n for n, p in current.model.named_parameters() if not torch.equal(before[n], p)}
        assert updated and updated <= PROFILES[current.learning_roles["profile"]]
        changed.append(updated)
        return state

    monkeypatch.setattr(module, "ConnectomeCurriculumSession", build)
    monkeypatch.setattr(module, "run_curriculum", train)
    result = module.run_role_comparison(
        config, tmp_path / "experiment", max_batches=2, device="cpu", dynamics_format="frozen-drive-exponential-v1"
    )
    assert result["status"] == "FINISHED" and len(changed) == 3
    assert all(ref() is None for ref in previous)
    assert result["training_success_verified"] is False and result["flight_eligible"] is False
    assert [r["learning_profile"] for r in result["variants"]] == list(PROFILES)
    assert len({r["state"]["model_identity"] for r in result["variants"]}) == 3
    for row in result["variants"]:
        root = tmp_path / "experiment" / row["learning_profile"]
        reports = [json.loads(p.read_bytes()) for p in (root / "reports").glob("*.json")]
        assert 1 <= len(reports) <= 2
        assert row["committed_batches"] == len(reports)
        assert row["state"]["global_updates"] == sum(r["train_metrics"]["updates"] for r in reports)
        assert row["state"]["environment_steps"] == sum(r["train_metrics"]["environment_steps"] for r in reports)
        assert (root / row["state"]["latest_checkpoint"] / "manifest.json").is_file()
        assert set(row["final_validation"]) == {s.id for s in config.stages}
    assert json.loads((tmp_path / "experiment/comparison.json").read_bytes()) == result


@pytest.mark.parametrize(
    "field",
    [
        "dataset_sha256",
        "mapping_sha256",
        "initial_losses",
        "learning_initialization",
        "truncate_steps",
        "loss_weights",
        "optimizer",
    ],
)
def test_later_baseline_drift_stops_before_second_training(config, tmp_path, monkeypatch, field):
    module = producer()
    actual = sessions.ConnectomeCurriculumSession
    train = module.run_curriculum
    calls = []

    def build(*args, **kwargs):
        current = actual(*args, **kwargs)
        if kwargs["learning_profile"] == "sensory-readout-v1":
            if field == "initial_losses":
                current.initial_losses = {k: v + 1 for k, v in current.initial_losses.items()}
            elif field == "learning_initialization":
                current.learning_initialization = {"different": True}
            elif field == "loss_weights":
                current.loss_weights = replace(current.loss_weights, imitation=7.0)
            elif field == "optimizer":
                current.optimizer.param_groups[0]["lr"] *= 2
            elif field == "truncate_steps":
                current.truncate_steps += 1
            else:
                setattr(current, field, "changed")
        return current

    def observed(cfg, path, current, **kwargs):
        calls.append(current.learning_roles["profile"])
        return train(cfg, path, current, **kwargs)

    monkeypatch.setattr(module, "ConnectomeCurriculumSession", build)
    monkeypatch.setattr(module, "run_curriculum", observed)
    with pytest.raises(ValueError, match="shared baseline"):
        module.run_role_comparison(config, tmp_path / "experiment", max_batches=1, device="cpu")
    assert calls == ["descending-only-v1"]
    record = json.loads((tmp_path / "experiment/comparison.json").read_bytes())
    assert record["status"] == "ERROR" and record["variants"][-1]["status"] == "ERROR"
    assert not (tmp_path / "experiment/shared-dynamics-v1").exists()


def test_partial_training_failure_preserves_artifacts_and_never_retries(config, tmp_path, monkeypatch):
    module = producer()
    actual = sessions.ConnectomeCurriculumSession.train_batch
    calls = []

    def train(current, *args, **kwargs):
        result = actual(current, *args, **kwargs)
        calls.append(current.learning_roles["profile"])
        if current.learning_roles["profile"] == "sensory-readout-v1":
            raise RuntimeError("after real optimizer updates")
        return result

    monkeypatch.setattr(sessions.ConnectomeCurriculumSession, "train_batch", train)
    path = tmp_path / "experiment"
    with pytest.raises(RuntimeError, match="after real"):
        module.run_role_comparison(config, path, max_batches=1, device="cpu")
    assert calls == ["descending-only-v1", "sensory-readout-v1"]
    record = (path / "comparison.json").read_bytes()
    assert json.loads(record)["status"] == "ERROR"
    monkeypatch.setattr(module, "ConnectomeCurriculumSession", lambda *a, **k: pytest.fail("reused root reached model"))
    with pytest.raises(FileExistsError):
        module.run_role_comparison(config, path, max_batches=1, device="cpu")
    assert (path / "comparison.json").read_bytes() == record


@pytest.mark.parametrize("cap", [None, True, 0, -1, 1.5])
def test_invalid_cap_rejected_before_output_or_session(config, tmp_path, monkeypatch, cap):
    module = producer()
    monkeypatch.setattr(module, "ConnectomeCurriculumSession", lambda *a, **k: pytest.fail("invalid cap reached model"))
    with pytest.raises(ValueError, match="max_batches"):
        module.run_role_comparison(config, tmp_path / "absent", max_batches=cap)
    assert not (tmp_path / "absent").exists()


def test_cli_comparison_rejects_restart_before_any_effect(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_curriculum", "--compare-learning-roles", "--max-batches", "1", "--restart"])
    monkeypatch.setattr(cli, "_restart", lambda *a: pytest.fail("destructive restart"))
    monkeypatch.setattr(cli, "load_curriculum_config", lambda *a: pytest.fail("configuration effect"))
    with pytest.raises(ValueError, match="restart"):
        cli.main()


@pytest.mark.parametrize("stop", ["cap", "stage-failed", "early-complete"])
def test_actual_curriculum_stops_keep_status_and_true_effort_distinct(tmp_path, stop):
    value = yaml.safe_load(__import__("pathlib").Path("configs/connectome_curriculum_v1.yaml").read_bytes())
    stage = value["stages"][0]
    value["profiles"]["smoke"]["stages"] = [stage["id"]]
    stage["epochs_per_batch"] = 1
    stage["maximum_validation_loss"] = 1e-15 if stop != "early-complete" else 1e6
    stage["maximum_loss_ratio"] = 1e-15 if stop != "early-complete" else 1e6
    stage["max_batches"] = 2 if stop == "stage-failed" else 3
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump(value))
    cfg = load_curriculum_config(path, "smoke")
    cap = 1 if stop == "cap" else 3
    result = producer().run_role_comparison(cfg, tmp_path / "e", max_batches=cap, device="cpu", topology_format="csr_compact_v1")
    assert result["status"] == "FINISHED"
    expected = {"cap": ("COMMITTED", 1), "stage-failed": ("FAILED", 2), "early-complete": ("COMPLETE", 1)}[stop]
    for row in result["variants"]:
        assert (row["state"]["status"], row["committed_batches"]) == expected
        assert row["state"]["global_updates"] == expected[1]
    assert result["all_curricula_complete"] == (stop == "early-complete")
    assert not result["training_success_verified"]


@pytest.mark.parametrize(
    "options",
    [
        {"learning_rate": float("nan")},
        {"learning_rate": float("inf")},
        {"learning_rate": True},
        {"truncate_steps": True},
        {"topology_format": "unknown"},
        {"dynamics_format": "unknown"},
        {"device": "other"},
    ],
)
def test_invalid_session_options_have_no_output_effect(config, tmp_path, options):
    with pytest.raises(ValueError):
        producer().run_role_comparison(config, tmp_path / "no", max_batches=1, **options)
    assert not (tmp_path / "no").exists()


def test_cli_routes_comparison_and_preserves_single_session_boundary(config, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_curriculum",
            "--compare-learning-roles",
            "--max-batches",
            "2",
            "--output",
            str(tmp_path / "e"),
            "--device",
            "cpu",
            "--topology-format",
            "csr_compact_v1",
            "--dynamics-format",
            "frozen-drive-exponential-v1",
        ],
    )
    monkeypatch.setattr(cli, "load_curriculum_config", lambda *a: config)
    monkeypatch.setattr(cli, "ConnectomeCurriculumSession", lambda *a, **k: pytest.fail("single-session path"))
    calls = []

    def compare(cfg, output, **options):
        calls.append((cfg, output, options))
        return {"status": "FINISHED", "all_curricula_complete": False, "variants": [{"state": {"status": "COMMITTED"}}]}

    monkeypatch.setattr(cli, "run_role_comparison", compare)
    cli.main()
    assert json.loads(capsys.readouterr().out)["status"] == "FINISHED"
    assert len(calls) == 1 and calls[0][0] is config
    assert calls[0][2]["topology_format"] == "csr_compact_v1"
    assert calls[0][2]["dynamics_format"] == "frozen-drive-exponential-v1"
    assert calls[0][2]["max_batches"] == 2


@pytest.mark.parametrize("extra", [[], ["--learning-profile", "descending-only-v1", "--max-batches", "1"]])
def test_cli_missing_cap_or_conflicting_role_cannot_reach_config(monkeypatch, extra):
    monkeypatch.setattr("sys.argv", ["run_curriculum", "--compare-learning-roles", *extra])
    monkeypatch.setattr(cli, "load_curriculum_config", lambda *a: pytest.fail("configuration effect"))
    with pytest.raises((ValueError, SystemExit)):
        cli.main()


def test_actual_two_stage_producer_keeps_curriculum_seed_order_and_rehearsal(tmp_path):
    value = yaml.safe_load(__import__("pathlib").Path("configs/connectome_curriculum_v1.yaml").read_bytes())
    for stage in value["stages"][:2]:
        stage.update(epochs_per_batch=1, maximum_validation_loss=1e6, maximum_loss_ratio=1e6, maximum_regression_ratio=1e6)
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump(value))
    cfg = load_curriculum_config(path, "smoke")
    result = producer().run_role_comparison(cfg, tmp_path / "e", max_batches=2, device="cpu")
    assert result["all_curricula_complete"]
    for row in result["variants"]:
        reports = [
            json.loads(p.read_bytes()) for p in sorted((tmp_path / "e" / row["learning_profile"] / "reports").glob("*.json"))
        ]
        assert [(r["stage_id"], r["seed"]) for r in reports] == [(s.id, s.train_seeds[0]) for s in cfg.stages]
        assert [r["train_metrics"]["environment_steps"] for r in reports] == [16, 32]
        assert row["state"]["environment_steps"] == 48
        assert set(row["final_validation"]) == {"stability", "looming"}


def test_cli_failed_curriculum_returns_nonzero_without_false_experiment_failure(config, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv", ["run_curriculum", "--compare-learning-roles", "--max-batches", "1", "--output", str(tmp_path / "e")]
    )
    monkeypatch.setattr(cli, "load_curriculum_config", lambda *a: config)
    monkeypatch.setattr(
        cli,
        "run_role_comparison",
        lambda *a, **k: {"status": "FINISHED", "all_curricula_complete": False, "variants": [{"state": {"status": "FAILED"}}]},
    )
    with pytest.raises(SystemExit) as raised:
        cli.main()
    assert raised.value.code == 2 and json.loads(capsys.readouterr().out)["status"] == "FINISHED"
