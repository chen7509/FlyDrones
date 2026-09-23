from __future__ import annotations

from flydrones.multitask_contract import PolicyIntent, ScenarioManifest, Skill
from flydrones.multitask_env import MultiTaskEnv
from flydrones.multitask_reflex import ReflexDecision, ReflexEvidence
from flydrones.multitask_trainer import PPOTrainer


class NoopLiveReflex:
    def __init__(self, *, override: bool = False) -> None:
        self.override = override
        self.calls = 0

    def evaluate(self, observation):
        self.calls += 1
        intent = None
        if self.override:
            intent = PolicyIntent(
                Skill.YIELD_RETURN_LAND,
                (0.0, 0.0, 0.0, 0.0),
                1.0,
                0.2,
            )
        return ReflexDecision(
            intent,
            ReflexEvidence(
                "malecns-v1.0-live", 166_700, 25_582_837, self.calls, 0, 0.5
            ),
        )


def manifest() -> ScenarioManifest:
    return ScenarioManifest.from_dict(
        {
            "schema_version": 1,
            "seed": 22,
            "world": "forest",
            "fleet_size": 1,
            "active_skills": ["navigate_exit"],
            "disturbances": [],
            "failure_vehicle_ids": [],
            "minimum_active_factors": 1,
        }
    )


def trainer_for(*, seed: int = 22, override: bool = False) -> PPOTrainer:
    scenario = manifest()
    environment = MultiTaskEnv(scenario, max_steps=16)
    environment.reset(seed=scenario.seed)
    dimension = int(environment.critic_observation().shape[0])
    return PPOTrainer(
        seed=seed,
        critic_input_dimension=dimension,
        device="cpu",
        reflex_factory=lambda vehicle_id, item: NoopLiveReflex(override=override),
    )


def test_checkpoint_round_trip_restores_optimizer_rng_and_counters(tmp_path):
    trainer = trainer_for(seed=22)
    trainer.train_batch(manifest(), steps=8)
    checkpoint = tmp_path / "trainer.pt"
    trainer.save(
        checkpoint,
        config_digest="a" * 64,
        state_digest="b" * 64,
    )

    restored = PPOTrainer.load(
        checkpoint,
        device="cpu",
        config_digest="a" * 64,
        reflex_factory=lambda vehicle_id, item: NoopLiveReflex(),
    )

    assert restored.actor_digest() == trainer.actor_digest()
    assert restored.critic_digest() == trainer.critic_digest()
    assert restored.global_updates == trainer.global_updates
    assert restored.environment_steps == trainer.environment_steps
    assert restored.random_state_digest() == trainer.random_state_digest()


def test_reflex_overridden_sample_updates_critic_but_not_actor():
    trainer = trainer_for(override=True)
    before_actor = trainer.actor_digest()
    before_critic = trainer.critic_digest()

    report = trainer.train_batch(manifest(), steps=8)

    assert report.actor_samples == 0
    assert report.critic_samples > 0
    assert trainer.actor_digest() == before_actor
    assert trainer.critic_digest() != before_critic


def test_interrupted_and_uninterrupted_batches_have_identical_actor(tmp_path):
    continuous = trainer_for(seed=37)
    continuous.train_batch(manifest(), steps=8)
    continuous.train_batch(manifest(), steps=8)

    interrupted = trainer_for(seed=37)
    interrupted.train_batch(manifest(), steps=8)
    checkpoint = tmp_path / "resume.pt"
    interrupted.save(
        checkpoint,
        config_digest="c" * 64,
        state_digest="d" * 64,
    )
    resumed = PPOTrainer.load(
        checkpoint,
        device="cpu",
        config_digest="c" * 64,
        reflex_factory=lambda vehicle_id, item: NoopLiveReflex(),
    )
    resumed.train_batch(manifest(), steps=8)

    assert resumed.actor_digest() == continuous.actor_digest()
    assert resumed.critic_digest() == continuous.critic_digest()
    assert resumed.random_state_digest() == continuous.random_state_digest()
