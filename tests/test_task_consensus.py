from __future__ import annotations

import itertools
import math

import pytest

from flydrones.mission_contract import WorkUnit
from flydrones.task_consensus import (
    AgentCapability,
    Bid,
    TaskAssignment,
    TaskLedger,
)

DIGEST = "a" * 64


def search_unit(task_id: str = "search-0000") -> WorkUnit:
    return WorkUnit(
        task_id,
        "search_cell",
        (10.0, 0.0, 20.0),
        (("target_classes", "person"),),
    )


def confirm_unit(task_id: str = "confirm-person-10-0-deadbeef") -> WorkUnit:
    return WorkUnit(
        task_id,
        "confirm_detection",
        (10.0, 0.0, 20.0),
        (("required_sensor", "person"),),
    )


def capability(
    vehicle_id: int = 5,
    *,
    position_m: tuple[float, float, float] = (0.0, 0.0, 20.0),
    battery_pct: float = 80.0,
    sensor_classes: tuple[str, ...] = ("person",),
    active_tasks: int = 1,
) -> AgentCapability:
    return AgentCapability(
        vehicle_id,
        position_m,
        battery_pct,
        sensor_classes,
        active_tasks,
    )


def test_equal_bids_converge_to_lower_vehicle_id_in_every_delivery_order() -> None:
    bids = [
        Bid("search-0000", 7, 4.5, 0, 1.0),
        Bid("search-0000", 2, 4.5, 0, 1.0),
    ]
    winners = set()
    for order in itertools.permutations(bids):
        ledger = TaskLedger(9, DIGEST, [search_unit()], lease_timeout_s=3.0)
        for bid in order:
            ledger.observe_bid(bid, now=1.0)
        winners.add(ledger.assignment("search-0000").winner_id)
    assert winners == {2}


def test_higher_round_dominates_utility_and_same_round_uses_highest_utility() -> None:
    ledger = TaskLedger(9, DIGEST, [search_unit()])
    ledger.observe_bid(Bid("search-0000", 1, 10.0, 0, 0.0), now=0.0)
    ledger.observe_bid(Bid("search-0000", 2, 9.0, 0, 0.1), now=0.1)
    assert ledger.assignment("search-0000").winner_id == 1

    ledger.observe_bid(Bid("search-0000", 2, -500.0, 1, 0.2), now=0.2)
    assert ledger.assignment("search-0000").winner_id == 2
    assert ledger.assignment("search-0000").allocation_round == 1


def test_expired_owner_reopens_task_and_completion_never_regresses() -> None:
    ledger = TaskLedger(0, DIGEST, [search_unit()], lease_timeout_s=3.0)
    ledger.observe_bid(Bid("search-0000", 3, 8.0, 0, 0.0), now=0.0)
    assert ledger.expire(now=3.01) == ("search-0000",)
    reopened = ledger.assignment("search-0000")
    assert reopened.status == "open" and reopened.allocation_round == 1
    ledger.complete("search-0000", winner_id=4, evidence_hash="b" * 64, now=4.0)
    ledger.merge_assignment(reopened, now=5.0)
    assert ledger.assignment("search-0000").status == "completed"


def test_renew_requires_current_owner_and_extends_lease() -> None:
    ledger = TaskLedger(0, DIGEST, [search_unit()])
    ledger.observe_bid(Bid("search-0000", 3, 8.0, 0, 0.0), now=0.0)
    with pytest.raises(ValueError, match="winner"):
        ledger.renew("search-0000", winner_id=4, allocation_round=0, now=1.0)
    renewed = ledger.renew("search-0000", winner_id=3, allocation_round=0, now=1.0)
    assert renewed.status == "active"
    assert renewed.lease_until == pytest.approx(4.0)


def test_live_local_owner_ignores_remote_reauction_until_its_lease_expires() -> None:
    ledger = TaskLedger(3, DIGEST, [search_unit()])
    ledger.observe_bid(Bid("search-0000", 3, 8.0, 0, 0.0), now=0.0)
    ledger.renew("search-0000", winner_id=3, allocation_round=0, now=0.1)
    remote = TaskAssignment("search-0000", "claimed", 8, 100.0, 4, 5.0, None, ())
    protected = ledger.merge_assignment(remote, now=1.0)
    assert protected.winner_id == 3
    assert protected.allocation_round == 0


def test_confirmation_requires_two_distinct_agents() -> None:
    ledger = TaskLedger(0, DIGEST, [confirm_unit()], confirmation_quorum=2)
    ledger.observe_bid(Bid(confirm_unit().task_id, 3, 8.0, 0, 0.0), now=0.0)
    first = ledger.complete(confirm_unit().task_id, 3, "b" * 64, now=1.0)
    assert first.status == "active"
    assert first.confirmers == (3,)
    duplicate = ledger.complete(confirm_unit().task_id, 3, "b" * 64, now=1.1)
    assert duplicate.status == "active"
    completed = ledger.complete(confirm_unit().task_id, 8, "c" * 64, now=1.2)
    assert completed.status == "completed"
    assert completed.confirmers == (3, 8)


def test_completed_records_merge_confirmer_sets_but_keep_local_evidence() -> None:
    ledger = TaskLedger(0, DIGEST, [confirm_unit()], confirmation_quorum=2)
    ledger.complete(confirm_unit().task_id, 3, "b" * 64, now=1.0)
    ledger.complete(confirm_unit().task_id, 8, "c" * 64, now=1.1)
    remote = TaskAssignment(
        confirm_unit().task_id,
        "completed",
        8,
        4.0,
        0,
        None,
        "d" * 64,
        (8, 11),
    )
    merged = ledger.merge_assignment(remote, now=2.0)
    assert merged.evidence_hash == "b" * 64
    assert merged.confirmers == (3, 8, 11)
    assert merged.winner_id == 3


def test_non_confirmation_completion_does_not_accumulate_executor_ids() -> None:
    ledger = TaskLedger(0, DIGEST, [search_unit()])
    ledger.complete("search-0000", 8, "b" * 64, now=1.0)
    remote = TaskAssignment("search-0000", "completed", 3, 4.0, 1, None, "c" * 64, (3,))
    merged = ledger.merge_assignment(remote, now=2.0)
    assert merged.winner_id == 3
    assert merged.confirmers == (3,)


def test_partial_confirmation_survives_reauction_and_previous_confirmer_cannot_rebid() -> None:
    ledger = TaskLedger(3, DIGEST, [confirm_unit()], confirmation_quorum=2)
    ledger.observe_bid(Bid(confirm_unit().task_id, 3, 8.0, 0, 0.0), now=0.0)
    partial = ledger.complete(confirm_unit().task_id, 3, "b" * 64, now=1.0)
    ledger.merge_assignment(
        TaskAssignment(
            partial.task_id,
            "open",
            None,
            None,
            partial.allocation_round + 1,
            None,
            partial.evidence_hash,
            partial.confirmers,
        ),
        now=1.1,
    )
    assert ledger.bid_for(confirm_unit().task_id, capability(vehicle_id=3), now=1.2) is None
    next_bid = ledger.bid_for(confirm_unit().task_id, capability(vehicle_id=8), now=1.2)
    assert next_bid is not None
    claimed = ledger.observe_bid(next_bid, now=1.2)
    assert claimed.confirmers == (3,)
    assert claimed.evidence_hash == "b" * 64


def test_two_partial_confirmation_records_merge_into_completed_consensus() -> None:
    ledger = TaskLedger(0, DIGEST, [confirm_unit()], confirmation_quorum=2)
    first = TaskAssignment(
        confirm_unit().task_id,
        "active",
        3,
        8.0,
        1,
        4.0,
        "b" * 64,
        (3,),
    )
    second = TaskAssignment(
        confirm_unit().task_id,
        "active",
        8,
        7.0,
        1,
        4.0,
        "c" * 64,
        (8,),
    )
    ledger.merge_assignment(first, now=1.0)
    merged = ledger.merge_assignment(second, now=1.1)
    assert merged.status == "completed"
    assert merged.confirmers == (3, 8)


def test_dynamic_work_units_are_idempotent_but_conflicts_are_rejected() -> None:
    ledger = TaskLedger(0, DIGEST, [search_unit()])
    dynamic = confirm_unit()
    assert ledger.add_work_unit(dynamic).status == "open"
    assert ledger.add_work_unit(dynamic).status == "open"
    with pytest.raises(ValueError, match="conflict"):
        ledger.add_work_unit(
            WorkUnit(dynamic.task_id, dynamic.kind, (11.0, 0.0, 20.0), dynamic.payload)
        )
    with pytest.raises(ValueError, match="kind"):
        ledger.add_work_unit(WorkUnit("bad", "unsupported", (0.0, 0.0, 0.0)))  # type: ignore[arg-type]


def test_bid_scoring_and_eligibility_are_auditable() -> None:
    ledger = TaskLedger(
        5,
        DIGEST,
        [search_unit(), WorkUnit("rally-final", "rally", (0.0, 0.0, 20.0))],
        minimum_battery_return_pct=20.0,
    )
    bid = ledger.bid_for("search-0000", capability(), now=2.0)
    assert bid is not None
    assert bid.utility == pytest.approx(100.0 - 10.0 - 4.0 + 20.0 + 20.0)
    assert ledger.bid_for(
        "search-0000",
        capability(sensor_classes=("thermal",)),
        now=2.0,
    ) is None
    assert ledger.bid_for("search-0000", capability(battery_pct=20.0), now=2.0) is None

    rally_bid = ledger.bid_for(
        "rally-final",
        capability(sensor_classes=()),
        now=2.0,
    )
    assert rally_bid is not None
    assert rally_bid.utility == pytest.approx(116.0)


def test_unknown_tasks_bad_values_and_bad_digests_are_rejected() -> None:
    with pytest.raises(ValueError, match="digest"):
        TaskLedger(0, "short", [search_unit()])
    ledger = TaskLedger(0, DIGEST, [search_unit()])
    with pytest.raises(KeyError):
        ledger.assignment("missing")
    with pytest.raises(ValueError, match="finite"):
        ledger.observe_bid(Bid("search-0000", 1, math.nan, 0, 0.0), now=0.0)
    with pytest.raises(ValueError, match="mission digest"):
        ledger.observe_bid(object(), now=0.0, mission_digest="b" * 64)  # type: ignore[arg-type]


def test_snapshot_is_immutable_and_sorted_by_task_id() -> None:
    ledger = TaskLedger(0, DIGEST, [search_unit("search-0002"), search_unit("search-0001")])
    snapshot = ledger.snapshot()
    assert tuple(item.task_id for item in snapshot) == ("search-0001", "search-0002")
    assert isinstance(snapshot, tuple)
