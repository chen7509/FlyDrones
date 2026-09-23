from __future__ import annotations

import json

import pytest

from flydrones.multitask_curriculum import (
    CurriculumConfig,
    CurriculumStore,
    manifest_for_batch,
    promotion_decision,
)


def config_with(
    *,
    profile: str = "smoke",
    fleets=(1,),
    train_seeds=(1, 2),
    eval_seeds=(101, 102),
):
    return {
        "schema_version": 2,
        "seed": 42,
        "algorithm": {"learning_rate": 0.0003},
        "frozen": ["malecns_reflex", "safety_projector", "px4_inner_loop"],
        "deployment": {"maximum_skill_drop": 0.02},
        "acceptance": {
            "minimums": {"exit_success": 0.95},
            "maximums": {"maximum_skill_drop": 0.02},
            "zeros": ["collisions"],
        },
        "profiles": {
            profile: [
                {
                    "id": f"{profile}-exit",
                    "index": 0,
                    "level": 1,
                    "active_skills": ["navigate_exit"],
                    "fleets": list(fleets),
                    "train_seeds": list(train_seeds),
                    "eval_seeds": list(eval_seeds),
                    "regression_seeds": [201],
                    "steps_per_batch": 8,
                    "maximum_batches": 3,
                    "patience": 2,
                    "thresholds": {"exit_success": 0.95},
                }
            ]
        },
    }


def valid_config() -> CurriculumConfig:
    return CurriculumConfig.from_dict(config_with())


def test_config_rejects_seed_overlap_and_implicit_full_scale():
    with pytest.raises(ValueError, match="overlap"):
        CurriculumConfig.from_dict(
            config_with(train_seeds=[1], eval_seeds=[1])
        )
    with pytest.raises(ValueError, match="100"):
        CurriculumConfig.from_dict(
            config_with(profile="desktop", fleets=[100])
        )


def test_partial_batch_is_not_resumed_as_committed(tmp_path):
    store = CurriculumStore(tmp_path)
    committed = store.initialize(valid_config())
    (tmp_path / "latest-trainer.pt").write_bytes(b"orphan")

    loaded = store.load()

    assert loaded.last_committed_batch == committed.last_committed_batch
    assert loaded.latest_checkpoint is None


def test_skill_regression_rolls_back_candidate():
    decision = promotion_decision(
        current={"admission_passed": True, "success": 0.96},
        baselines={"search": 0.95},
        regressions={"search": 0.92},
        maximum_drop=0.02,
    )

    assert not decision.promote
    assert decision.reasons == ("skill-regression:search",)


def test_manifest_schedule_rotates_seeds_and_fleets_deterministically():
    data = config_with(fleets=[1, 5], train_seeds=[7, 8])
    config = CurriculumConfig.from_dict(data)

    first = manifest_for_batch(config, "smoke", stage_index=0, batch_index=0)
    second = manifest_for_batch(config, "smoke", stage_index=0, batch_index=1)
    wrapped = manifest_for_batch(config, "smoke", stage_index=0, batch_index=2)

    assert (first.seed, first.fleet_size) == (7, 1)
    assert (second.seed, second.fleet_size) == (8, 5)
    assert (wrapped.seed, wrapped.fleet_size) == (7, 1)
    assert [skill.value for skill in first.active_skills] == ["navigate_exit"]


def test_state_file_is_canonical_json_and_config_digest_is_stable(tmp_path):
    config = valid_config()
    state = CurriculumStore(tmp_path).initialize(config)

    payload = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))

    assert payload == state.to_dict()
    assert len(config.digest) == 64
