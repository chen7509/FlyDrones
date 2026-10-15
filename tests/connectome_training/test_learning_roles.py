import json
from hashlib import sha256

import pytest
import torch
import yaml

from flydrones.connectome_training import curriculum_session as sessions
from flydrones.connectome_training.checkpoint import save_checkpoint
from flydrones.connectome_training.curriculum_config import load_curriculum_config
from flydrones.connectome_training.inference_artifact import CheckpointIdentity, load_inference_core
from flydrones.connectome_training.model import ConnectomeConstrainedCore
from flydrones.connectome_training.parameters import parameter_mapping_digest
from tools.benchmark.software_process_boundary import install
from tools.connectome_training import run_curriculum as cli

PROFILES = {
    "descending-only-v1": {"readout"},
    "sensory-readout-v1": {"raw_input_gain", "readout"},
    "shared-dynamics-v1": {"raw_input_gain", "type_bias_mv", "raw_tau_m", "readout"},
}


@pytest.fixture(autouse=True)
def inert_backends(monkeypatch):
    install(monkeypatch)
    monkeypatch.setattr(sessions, "_peak_process_memory_bytes", lambda: 0)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)


@pytest.fixture
def config(tmp_path):
    value = yaml.safe_load(__import__("pathlib").Path("configs/connectome_curriculum_v1.yaml").read_bytes())
    value["profiles"]["smoke"]["stages"] = [value["stages"][0]["id"]]
    value["stages"][0]["epochs_per_batch"] = 2
    path = tmp_path / "curriculum.yaml"
    path.write_text(yaml.safe_dump(value))
    return load_curriculum_config(path, "smoke")


def session(config, profile):
    return sessions.ConnectomeCurriculumSession(config, device="cpu", learning_profile=profile)


def save_session(model, path):
    model.save_checkpoint(
        path, dict(stage_index=0, batch_index=0, seed=11, config_digest=model.config.digest, model_identity=model.model_identity)
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_actual_curriculum_updates_only_its_declared_roles(config, profile):
    current = session(config, profile)
    before = {n: p.detach().clone() for n, p in current.model.named_parameters()}
    buffers = {n: p.detach().clone() for n, p in current.model.named_buffers()}
    expected = PROFILES[profile]
    assert {n for n, p in current.model.named_parameters() if p.requires_grad} == expected
    actual_optimizer = [p for group in current.optimizer.param_groups for p in group["params"]]
    assert {id(p) for p in actual_optimizer} == {id(p) for n, p in current.model.named_parameters() if n in expected}
    result = current.train_batch(config.stages[0], 1101)
    assert result["learning_roles"] == current.learning_roles
    assert result["peak_process_memory_bytes"] == 0  # Explicit inert protocol, no measured peak claim.
    changed = {n for n, p in current.model.named_parameters() if not torch.equal(p, before[n])}
    assert changed and changed <= expected
    for n, p in current.model.named_parameters():
        if n not in expected:
            assert torch.equal(p, before[n]) and p.grad is None
    for n, p in current.model.named_buffers():
        a, b = (p.to_dense(), buffers[n].to_dense()) if p.layout != torch.strided else (p, buffers[n])
        assert torch.equal(a, b)


@pytest.mark.parametrize("profile", PROFILES)
def test_same_role_checkpoint_resumes_all_coefficients(config, tmp_path, profile):
    first = session(config, profile)
    first.train_batch(config.stages[0], 1101)
    path = tmp_path / "checkpoint"
    save_session(first, path)
    resumed = session(config, profile)
    resumed.restore_checkpoint(path)
    for a, b in zip(first.model.parameters(), resumed.model.parameters()):
        assert torch.equal(a, b)
    assert resumed.learning_roles == first.learning_roles
    assert resumed.optimizer.state_dict()["param_groups"] == first.optimizer.state_dict()["param_groups"]


def test_cross_role_checkpoint_refuses_before_copy(config, tmp_path):
    first = session(config, "descending-only-v1")
    first.train_batch(config.stages[0], 1101)
    save_session(first, tmp_path / "checkpoint")
    other = session(config, "shared-dynamics-v1")
    before = [p.detach().clone() for p in other.model.parameters()]
    with pytest.raises(ValueError, match="metadata mismatch"):
        other.restore_checkpoint(tmp_path / "checkpoint")
    assert all(torch.equal(a, b) for a, b in zip(before, other.model.parameters()))


def rewrite_payload(path, change):
    payload = torch.load(path / "checkpoint.pt", weights_only=True)
    change(payload)
    torch.save(payload, path / "checkpoint.pt")
    manifest = json.loads((path / "manifest.json").read_bytes())
    manifest["checkpoint_sha256"] = sha256((path / "checkpoint.pt").read_bytes()).hexdigest()
    manifest["metadata"] = payload["metadata"]
    (path / "manifest.json").write_text(json.dumps(manifest))


def test_coherent_frozen_payload_tamper_refuses_before_copy(config, tmp_path):
    current = session(config, "descending-only-v1")
    path = tmp_path / "checkpoint"
    save_session(current, path)
    rewrite_payload(path, lambda value: value["model_state"]["type_bias_mv"].add_(0.25))
    before = [p.detach().clone() for p in current.model.parameters()]
    with pytest.raises(ValueError, match="frozen"):
        current.restore_checkpoint(path)
    assert all(torch.equal(a, b) for a, b in zip(before, current.model.parameters()))


@pytest.mark.parametrize("drift", ["flags", "optimizer", "frozen"])
def test_actual_setup_drift_is_rejected_before_training(config, drift):
    current = session(config, "descending-only-v1")
    if drift == "flags":
        current.model.type_bias_mv.requires_grad_(True)
    elif drift == "optimizer":
        current.optimizer.add_param_group({"params": [current.model.type_bias_mv]})
    else:
        with torch.no_grad():
            current.model.type_bias_mv.add_(0.25)
    with pytest.raises(ValueError, match="learning|frozen|optimizer"):
        current.train_batch(config.stages[0], 1101)


def test_unknown_role_fails_before_model_construction(config, monkeypatch):
    monkeypatch.setattr(sessions, "_smoke_components", lambda config: pytest.fail("model construction reached"))
    with pytest.raises(ValueError, match="learning profile"):
        session(config, "anything")


def inference_checkpoint(tmp_path, artifacts, profile=None):
    source, folder, connectome, parameters = artifacts
    model = ConnectomeConstrainedCore(connectome, parameters)
    mapping = parameter_mapping_digest(parameters)
    i = parameters.identity
    identity = f"tiny-connectome:{i.model_sha256}:{i.topology_sha256}:{mapping}:device=cpu"
    metadata = dict(
        epoch=1,
        seed=11,
        config_digest="c" * 64,
        dataset_sha256="d" * 64,
        topology_sha256=i.topology_sha256,
        parameter_mapping_sha256=mapping,
    )
    if profile:
        from flydrones.connectome_training.training_roles import configure_learning_roles, learning_identity_suffix

        roles = configure_learning_roles(model, profile)
        metadata["learning_roles"] = roles
        identity += learning_identity_suffix(roles)
    metadata["model_identity"] = identity
    values = {n: p.detach().clone() for n, p in model.named_parameters()}
    values["readout"] += 0.1
    path = save_checkpoint(tmp_path / "checkpoint", model_state=values, optimizer_state={}, metadata=metadata)
    pinned = CheckpointIdentity(sha256((path / "checkpoint.pt").read_bytes()).hexdigest(), "c" * 64, "d" * 64)
    return source, folder, path, pinned


@pytest.mark.parametrize("profile", PROFILES)
def test_explicit_inference_joins_roles_and_remains_unqualified(tmp_path, tiny_artifacts, profile):
    source, folder, path, pinned = inference_checkpoint(tmp_path, tiny_artifacts(), profile)
    loaded = load_inference_core(
        source, folder, mode="tiny-fixture", checkpoint_path=path, checkpoint_identity=pinned, learning_profile=profile
    )
    assert loaded.provenance["learning_profile"] == profile
    assert loaded.provenance["learning_roles"]["profile"] == profile
    assert not loaded.provenance["training_success_verified"] and not loaded.provenance["flight_eligible"]
    assert all(not p.requires_grad for p in loaded.core.parameters())
    with pytest.raises(ValueError, match="metadata mismatch"):
        load_inference_core(source, folder, mode="tiny-fixture", checkpoint_path=path, checkpoint_identity=pinned)


def test_legacy_checkpoint_is_compatible_but_role_unspecified(tmp_path, tiny_artifacts):
    source, folder, path, pinned = inference_checkpoint(tmp_path, tiny_artifacts())
    loaded = load_inference_core(source, folder, mode="tiny-fixture", checkpoint_path=path, checkpoint_identity=pinned)
    assert loaded.provenance["learning_profile"] == "legacy-unspecified"
    assert loaded.provenance["learning_roles"] is None


def test_inference_refuses_changed_frozen_values_with_fresh_hash(tmp_path, tiny_artifacts):
    source, folder, path, pinned = inference_checkpoint(tmp_path, tiny_artifacts(), "descending-only-v1")
    rewrite_payload(path, lambda value: value["model_state"]["raw_tau_m"].add_(0.1))
    pinned = CheckpointIdentity(
        sha256((path / "checkpoint.pt").read_bytes()).hexdigest(), pinned.config_digest, pinned.dataset_sha256
    )
    with pytest.raises(ValueError, match="frozen"):
        load_inference_core(
            source,
            folder,
            mode="tiny-fixture",
            checkpoint_path=path,
            checkpoint_identity=pinned,
            learning_profile="descending-only-v1",
        )


def test_cli_routes_explicit_profile_in_process(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv", ["run_curriculum.py", "--learning-profile", "descending-only-v1", "--output", str(tmp_path / "unused")]
    )
    assert cli.parse_args().learning_profile == "descending-only-v1"
    seen = []

    def factory(*args, **kwargs):
        seen.append(kwargs["learning_profile"])
        raise RuntimeError("inert session boundary")

    monkeypatch.setattr(cli, "ConnectomeCurriculumSession", factory)
    with pytest.raises(RuntimeError, match="inert session"):
        cli.main()
    assert seen == ["descending-only-v1"] and not (tmp_path / "unused").exists()


def test_bad_checkpoint_hash_refuses_before_core_construction(tmp_path, tiny_artifacts, monkeypatch):
    from flydrones.connectome_training import inference_artifact as artifacts

    source, folder, path, pinned = inference_checkpoint(tmp_path, tiny_artifacts())
    wrong = CheckpointIdentity("0" * 64, pinned.config_digest, pinned.dataset_sha256)
    monkeypatch.setattr(
        artifacts, "ConnectomeConstrainedCore", lambda *args: pytest.fail("unverified checkpoint reached core construction")
    )
    with pytest.raises(ValueError, match="checkpoint hash"):
        artifacts.load_inference_core(source, folder, mode="tiny-fixture", checkpoint_path=path, checkpoint_identity=wrong)


@pytest.mark.parametrize("drift", ["flags", "order", "replacement"])
def test_restore_preflights_live_role_objects_before_copy(config, tmp_path, drift):
    first = session(config, "sensory-readout-v1")
    first.train_batch(config.stages[0], 1101)
    save_session(first, tmp_path / "checkpoint")
    current = session(config, "sensory-readout-v1")
    if drift == "flags":
        current.model.type_bias_mv.requires_grad_(True)
    elif drift == "order":
        current.optimizer.param_groups[0]["params"].reverse()
    else:
        current.optimizer.param_groups[0]["params"][-1] = torch.nn.Parameter(torch.zeros_like(current.model.readout))
    before = [p.detach().clone() for p in current.model.parameters()]
    with pytest.raises(ValueError, match="learning|optimizer"):
        current.restore_checkpoint(tmp_path / "checkpoint")
    assert all(torch.equal(a, b) for a, b in zip(before, current.model.parameters()))


@pytest.mark.parametrize("fault", ["order", "moment", "groups", "nonfinite", "step", "step_bool"])
def test_restore_preflights_serialized_adam_before_copy(config, tmp_path, fault):
    first = session(config, "sensory-readout-v1")
    first.train_batch(config.stages[0], 1101)
    path = tmp_path / "checkpoint"
    save_session(first, path)

    def change(value):
        state = value["optimizer_state"]
        if fault == "order":
            state["param_groups"][0]["params"].reverse()
        elif fault == "groups":
            state["param_groups"] = []
        elif fault == "moment":
            state["state"][0]["exp_avg"] = torch.zeros(999)
        elif fault == "nonfinite":
            state["state"][0]["exp_avg_sq"].fill_(float("nan"))
        elif fault == "step":
            state["state"][0]["step"] = torch.tensor([1.0, 2.0])
        else:
            state["state"][0]["step"] = torch.tensor(True)

    rewrite_payload(path, change)
    current = session(config, "sensory-readout-v1")
    before = [p.detach().clone() for p in current.model.parameters()]
    try:
        current.restore_checkpoint(path)
    except ValueError:
        pass
    else:
        pytest.fail("invalid serialized Adam state accepted")
    assert all(torch.equal(a, b) for a, b in zip(before, current.model.parameters())), "model copied before Adam validation"
