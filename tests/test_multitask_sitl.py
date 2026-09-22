import pytest

from flydrones.multitask_contract import PolicyIntent, Skill
from flydrones.multitask_sitl import MultiTaskSITLAdapter


def test_adapter_converts_only_local_normalized_intent_to_bounded_setpoint():
    adapter = MultiTaskSITLAdapter(
        maximum_speed_mps=8.0,
        maximum_yaw_rate_rps=1.5,
    )
    setpoint = adapter.to_setpoint(
        vehicle_id=4,
        intent=PolicyIntent(
            Skill.TRACK_TARGET,
            (2.0, -2.0, 0.5, 1.0),
            0.9,
            0.5,
        ),
    )
    assert setpoint.vehicle_id == 4
    assert setpoint.velocity_mps == (8.0, -8.0, 4.0)
    assert setpoint.yaw_rate_rps == 1.5
    assert setpoint.source == "local-multitask-policy"


def test_adapter_rejects_global_or_cross_vehicle_commands():
    adapter = MultiTaskSITLAdapter(
        maximum_speed_mps=8.0,
        maximum_yaw_rate_rps=1.5,
    )
    with pytest.raises(ValueError, match="vehicle"):
        adapter.step_vehicle(local_vehicle_id=4, commanded_vehicle_id=5, intent=None)
    with pytest.raises(TypeError, match="PolicyIntent"):
        adapter.step_vehicle(
            local_vehicle_id=4,
            commanded_vehicle_id=4,
            intent=(1, 0, 0, 0),
        )


def test_optional_pybullet_backend_fails_with_install_instruction_when_absent():
    adapter = MultiTaskSITLAdapter(
        maximum_speed_mps=8.0,
        maximum_yaw_rate_rps=1.5,
    )
    if not adapter.pybullet_available:
        with pytest.raises(RuntimeError, match="gym-pybullet-drones"):
            adapter.validate_backend("pybullet")


def test_step_vehicle_invokes_only_the_injected_local_sender():
    sent = []
    adapter = MultiTaskSITLAdapter(
        maximum_speed_mps=4.0,
        maximum_yaw_rate_rps=1.0,
        sender=sent.append,
    )
    result = adapter.step_vehicle(
        local_vehicle_id=2,
        commanded_vehicle_id=2,
        intent=PolicyIntent(Skill.NAVIGATE_EXIT, (0.5, 0.0, 0.0, 0.0), 1.0, 0.2),
    )
    assert sent == [result]
