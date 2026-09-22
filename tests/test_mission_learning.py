from dataclasses import replace

from flydrones.mission_agent import AgentState, MissionAgent
from flydrones.mission_contract import MissionContract
from flydrones.mission_learning import MissionLearningAdapter, TaskEstimate


def contract():
    return MissionContract.from_dict(
        {
            "schema_version": 1,
            "mission_id": "learning-test",
            "mission_type": "search_confirm_rally",
            "area_polygon_m": [[0, 0], [40, 0], [40, 40], [0, 40]],
            "search_cell_size_m": 20,
            "target_classes": ["person"],
            "confirmation_quorum": 2,
            "rally_position_m": [50, 20, 20],
            "deadline_s": 60,
            "safety": {
                "maximum_speed_mps": 8,
                "minimum_separation_m": 3,
                "geofence_margin_m": 5,
                "minimum_battery_return_pct": 30,
            },
        }
    )


def state(**changes):
    values = {
        "position_m": (10.0, 10.0, 20.0),
        "velocity_mps": (0.0, 0.0, 0.0),
        "battery_pct": 90.0,
        "depth_age_s": 0.0,
        "localization_valid": True,
    }
    values.update(changes)
    return AgentState(**values)


def test_adapter_only_ranks_known_work_units_and_never_mutates_ledger():
    agent = MissionAgent.for_contract(0, 5, contract())
    before = agent.ledger.snapshot()
    adapter = MissionLearningAdapter(
        lambda unit, _: TaskEstimate(unit.task_id, 5.0, 2.0, 0.8)
    )
    ranked = adapter.preferred_task_ids(agent, state())
    assert set(ranked) <= set(agent.work_unit_ids)
    assert agent.ledger.snapshot() == before


def test_unknown_nonfinite_and_low_battery_estimates_are_ignored():
    agent = MissionAgent.for_contract(0, 5, contract())
    bad = MissionLearningAdapter(
        lambda unit, _: TaskEstimate("invented-task", float("nan"), -1.0, 2.0)
    )
    assert bad.preferred_task_ids(agent, state()) == ()
    low = replace(
        state(),
        battery_pct=contract().safety.minimum_battery_return_pct,
    )
    assert bad.preferred_task_ids(agent, low) == ()


def test_mission_safety_preempts_learned_preference():
    agent = MissionAgent.for_contract(0, 5, contract())
    decision = agent.step(
        0.0,
        state(battery_pct=30.0),
        (),
        (),
        (),
        preferred_task_ids=(agent.work_unit_ids[0],),
    )
    assert decision.safety_phase == "return"
    assert decision.intent.source == "safety-return"


def test_agent_uses_adapter_ranking_without_granting_ledger_authority():
    adapter = MissionLearningAdapter(
        lambda unit, _: TaskEstimate(
            unit.task_id,
            0.0 if unit.task_id == "search-0003" else 100.0,
            0.0,
            1.0,
        )
    )
    agent = MissionAgent.for_contract(0, 5, contract(), learning_adapter=adapter)
    decision = agent.step(0.0, state(), (), (), ())
    bids = [payload for kind, payload in decision.outbound_messages if kind == "bid"]
    assert [payload["task_id"] for payload in bids] == ["search-0003"]
