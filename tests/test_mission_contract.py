from __future__ import annotations

import copy
import json

import pytest

from flydrones.mission_contract import MissionContract, load_mission_contract


def valid_contract_dict() -> dict:
    return {
        "schema_version": 1,
        "mission_id": "forest-search-001",
        "mission_type": "search_confirm_rally",
        "area_polygon_m": [[0.0, 0.0], [200.0, 0.0], [200.0, 200.0], [0.0, 200.0]],
        "search_cell_size_m": 20.0,
        "target_classes": ["person"],
        "confirmation_quorum": 2,
        "rally_position_m": [220.0, 100.0, 20.0],
        "deadline_s": 600.0,
        "safety": {
            "maximum_speed_mps": 8.0,
            "minimum_separation_m": 3.0,
            "geofence_margin_m": 5.0,
            "minimum_battery_return_pct": 30.0,
        },
    }


def test_contract_rejects_unknown_fields_nonfinite_values_and_boolean_numbers():
    valid = valid_contract_dict()
    for mutation in (
        lambda item: item.update(extra="forbidden"),
        lambda item: item.update(deadline_s=float("nan")),
        lambda item: item["safety"].update(maximum_speed_mps=True),
    ):
        candidate = copy.deepcopy(valid)
        mutation(candidate)
        with pytest.raises(ValueError):
            MissionContract.from_dict(candidate)


def test_contract_expands_identical_search_cells_and_rally_task_on_every_node():
    first = MissionContract.from_dict(valid_contract_dict())
    second = MissionContract.from_dict(json.loads(json.dumps(valid_contract_dict())))

    assert first.digest == second.digest
    assert first.expand_work_units() == second.expand_work_units()
    assert sum(unit.kind == "search_cell" for unit in first.expand_work_units()) == 100
    assert first.expand_work_units()[0].task_id == "search-0000"
    assert first.expand_work_units()[0].center_m == (10.0, 10.0, 20.0)
    assert first.expand_work_units()[-1].task_id == "rally-final"
    assert first.expand_work_units()[-1].kind == "rally"


def test_loading_contract_rejects_duplicate_json_keys_and_nan(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_mission_contract(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    invalid = valid_contract_dict()
    invalid["deadline_s"] = float("nan")
    nonfinite.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError):
        load_mission_contract(nonfinite)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("mission_type", "waypoint_show"),
        ("area_polygon_m", [[0.0, 0.0], [1.0, 1.0]]),
        ("search_cell_size_m", 0.0),
        ("target_classes", []),
        ("confirmation_quorum", 1),
        ("deadline_s", -1.0),
    ],
)
def test_contract_rejects_unsupported_or_unsafe_top_level_values(field, value):
    candidate = valid_contract_dict()
    candidate[field] = value
    with pytest.raises(ValueError):
        MissionContract.from_dict(candidate)


def test_contract_round_trip_preserves_digest_and_immutable_values(tmp_path):
    expected = MissionContract.from_dict(valid_contract_dict())
    path = tmp_path / "mission.json"
    path.write_text(json.dumps(expected.to_dict()), encoding="utf-8")

    loaded = load_mission_contract(path)

    assert loaded == expected
    assert loaded.digest == expected.digest
    assert isinstance(loaded.area_polygon_m, tuple)
    assert isinstance(loaded.target_classes, tuple)
