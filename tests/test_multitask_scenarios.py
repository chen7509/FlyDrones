import pytest

from flydrones.multitask_contract import Skill
from flydrones.multitask_scenarios import ScenarioGenerator


def test_same_seed_produces_identical_manifest_and_different_seed_changes_it():
    a = ScenarioGenerator(41).generate(level=4, fleet_size=100)
    b = ScenarioGenerator(41).generate(level=4, fleet_size=100)
    c = ScenarioGenerator(42).generate(level=4, fleet_size=100)
    assert a == b
    assert a.digest == b.digest
    assert a.digest != c.digest


def test_level_four_contains_all_skills_and_required_failure_mix():
    manifest = ScenarioGenerator(8).generate(level=4, fleet_size=100)
    assert set(manifest.active_skills) == set(Skill)
    assert manifest.failure_vehicle_ids
    assert {"packet_loss", "battery_variation"} <= set(manifest.disturbances)
    assert len(manifest.active_skills) + len(manifest.disturbances) + 1 >= 8


def test_invalid_level_and_impossible_fleet_are_rejected():
    with pytest.raises(ValueError, match="level"):
        ScenarioGenerator(1).generate(level=9, fleet_size=20)
    with pytest.raises(ValueError, match="fleet"):
        ScenarioGenerator(1).generate(level=4, fleet_size=1)


def test_held_out_rejects_duplicates_and_sorts_by_seed():
    generator = ScenarioGenerator(99)
    manifests = generator.held_out([9, 3, 7], level=2, fleet_size=5)
    assert [manifest.seed for manifest in manifests] == [3, 7, 9]
    with pytest.raises(ValueError, match="duplicate"):
        generator.held_out([3, 3], level=2, fleet_size=5)
