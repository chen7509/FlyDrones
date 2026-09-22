import json
import random

import numpy as np
import pytest
import torch

from flydrones.connectome_training.checkpoint import (
    capture_rng_state,
    load_checkpoint,
    restore_rng_state,
    save_checkpoint,
)
from flydrones.connectome_training.curriculum_state import (
    CurriculumState,
    RunLock,
    StateStore,
)


def state(config_digest="a" * 64):
    return CurriculumState(
        run_id="run-1",
        config_digest=config_digest,
        profile="smoke",
        status="COMMITTED",
        stage_index=0,
        batch_index=1,
        global_updates=2,
        environment_steps=16,
        latest_checkpoint="checkpoints/stage-0-batch-1",
        best_checkpoint="checkpoints/stage-0-batch-1",
        best_score=0.1,
        completed_stages=(),
        failed_attempts=0,
        last_committed_batch="stability:1",
        baseline_losses={},
        model_identity="tiny:abc",
    )


def test_state_round_trip_is_atomic_and_rejects_config_change(tmp_path):
    store = StateStore(tmp_path, "a" * 64)
    store.commit(state())
    assert store.load() == state()
    assert not (tmp_path / "state.json.writing").exists()
    with pytest.raises(ValueError, match="config digest"):
        StateStore(tmp_path, "b" * 64).load()


def test_orphan_temporary_state_is_ignored(tmp_path):
    (tmp_path / "state.json.writing").write_text("partial", encoding="utf-8")
    assert StateStore(tmp_path, "a" * 64).load() is None


def test_run_lock_is_exclusive_and_released(tmp_path):
    with RunLock(tmp_path):
        payload = json.loads((tmp_path / "run.lock").read_text(encoding="utf-8"))
        assert payload["pid"] > 0
        with pytest.raises(RuntimeError, match="already locked"):
            with RunLock(tmp_path):
                pass
    with RunLock(tmp_path):
        assert (tmp_path / "run.lock").exists()


def test_run_lock_recovers_a_stale_process_lock(tmp_path):
    (tmp_path / "run.lock").write_text(
        json.dumps({"pid": 2_000_000_000, "token": "stale"}) + "\n",
        encoding="utf-8",
    )
    with RunLock(tmp_path):
        payload = json.loads((tmp_path / "run.lock").read_text(encoding="utf-8"))
        assert payload["pid"] != 2_000_000_000
    assert not (tmp_path / "run.lock").exists()


def test_rng_state_restores_python_numpy_and_torch():
    random.seed(9)
    np.random.seed(9)
    torch.manual_seed(9)
    saved = capture_rng_state()
    expected = (random.random(), float(np.random.random()), float(torch.rand(())))
    random.seed(100)
    np.random.seed(100)
    torch.manual_seed(100)
    restore_rng_state(saved)
    actual = (random.random(), float(np.random.random()), float(torch.rand(())))
    assert actual == expected


def test_checkpoint_can_require_exact_identity_metadata(tmp_path):
    out = save_checkpoint(
        tmp_path / "checkpoint",
        model_state={"weight": torch.tensor([1.0])},
        optimizer_state={},
        metadata={
            "epoch": 1,
            "seed": 2,
            "dataset_sha256": "c" * 64,
            "topology_sha256": "d" * 64,
            "parameter_mapping_sha256": "e" * 64,
        },
    )
    load_checkpoint(
        out,
        expected_metadata={
            "topology_sha256": "d" * 64,
            "parameter_mapping_sha256": "e" * 64,
        },
    )
    with pytest.raises(ValueError, match="topology_sha256"):
        load_checkpoint(out, expected_metadata={"topology_sha256": "f" * 64})
