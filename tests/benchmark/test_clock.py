import pytest
import numpy as np
from datetime import timedelta
from types import SimpleNamespace

from flydrones.benchmark.contract import Command
from flydrones.benchmark.clock import StepClock, require_offboard
from flydrones.benchmark.gateway import (
    WORLD_CONTROL_TIMEOUT_MS,
    contact_message_involves,
    control_retry_allowed,
    direct_step_complete,
    enu_to_ned,
    offboard_evidence_fresh,
    shape_command,
    sim_duration_ns,
    step_complete,
    transport_partition,
    world_control_request_text,
)


def test_pause_drift_is_not_hidden():
    clock = StepClock(dt_ns=50_000_000)
    clock.accept_time(1_000_000_000)
    assert clock.next_target() == 1_050_000_000
    with pytest.raises(RuntimeError):
        clock.assert_paused(1_000_000_000, 1_010_000_000)


def test_clock_backwards_rejected():
    clock = StepClock(dt_ns=50_000_000)
    clock.accept_time(100)
    with pytest.raises(ValueError):
        clock.accept_time(99)


@pytest.mark.parametrize('period', [0, -1, 1.2])
def test_period_must_be_positive_integer(period):
    with pytest.raises(ValueError):
        StepClock(dt_ns=period)


def test_unknown_mode_cannot_pass_pause_gate():
    with pytest.raises(RuntimeError):
        require_offboard(0, 0)
    require_offboard(6 << 16, 128)
    with pytest.raises(RuntimeError):
        require_offboard(6 << 16, 0)


def test_common_command_shaping_limits_speed_acceleration_and_yaw():
    shaped = shape_command(
        Command((10., 0., 0.), 2.), Command((0., 0., 0.), 0.),
        dt_s=.05, speed_max=0.8, acceleration_max=1.2, yaw_rate_max=.6,
    )
    assert np.allclose(shaped.velocity_enu, (.06, 0., 0.))
    assert shaped.yaw_rate == pytest.approx(.6)


def test_enu_velocity_and_counterclockwise_yaw_convert_to_local_ned():
    assert enu_to_ned(Command((1., 2., 3.), .4)) == pytest.approx((2., 1., -3., -.4))


def test_nonfinite_command_is_rejected():
    with pytest.raises(ValueError, match='finite'):
        shape_command(
            Command((np.nan, 0., 0.), 0.), Command((0., 0., 0.), 0.),
            dt_s=.05, speed_max=.8, acceleration_max=1.2, yaw_rate_max=.6,
        )


def test_step_is_incomplete_until_world_returns_to_paused_state():
    target = 1_050_000_000
    assert not step_complete({'sim_ns': target, 'paused': False}, target)
    assert step_complete({'sim_ns': target, 'paused': True}, target)
    assert not step_complete({'sim_ns': target - 1, 'paused': True}, target)


def test_direct_step_is_complete_only_at_exact_time_after_server_stops():
    target = 1_050_000_000
    assert not direct_step_complete({'sim_ns': target}, target, server_running=True)
    assert direct_step_complete({'sim_ns': target}, target, server_running=False)
    assert not direct_step_complete({'sim_ns': target - 1}, target, server_running=False)


def test_only_idempotent_pause_requests_may_retry():
    assert control_retry_allowed(pause=True, steps=0)
    assert not control_retry_allowed(pause=True, steps=50)
    assert not control_retry_allowed(pause=False, steps=0)


def test_contact_truth_filters_for_the_benchmark_vehicle():
    contacts = SimpleNamespace(contact=[
        SimpleNamespace(collision1='wall_0::body::collision', collision2='x500_benchmark_8::base_link::base_link_collision_0'),
    ])
    assert contact_message_involves(contacts, 'x500_benchmark_8')
    assert not contact_message_involves(contacts, 'x500_benchmark_7')


def test_contact_truth_reads_entity_names_from_gazebo_protobuf():
    contacts = SimpleNamespace(contact=[SimpleNamespace(
        collision1=SimpleNamespace(name='wall_0::body::collision'),
        collision2=SimpleNamespace(name='x500_benchmark_8::base_link::collision'),
    )])
    assert contact_message_involves(contacts, 'x500_benchmark_8')


def test_offboard_evidence_uses_simulation_time_freshness():
    assert offboard_evidence_fresh(1_000_000_000, 3_000_000_000)
    assert not offboard_evidence_fresh(1_000_000_000, 3_000_000_001)
    assert not offboard_evidence_fresh(None, 1_000_000_000)


def test_world_control_wait_allows_slow_rendered_steps():
    assert WORLD_CONTROL_TIMEOUT_MS >= 15_000


def test_world_control_cli_request_is_deterministic():
    assert world_control_request_text(True, 50) == 'pause: true multi_step: 50'
    assert world_control_request_text(False, 0) == 'pause: false multi_step: 0'


def test_transport_partition_is_unique_and_shell_safe():
    first = transport_partition('attempt-9', 123)
    second = transport_partition('attempt-10', 123)
    assert first != second
    assert first == 'fly_ego_123_attempt_9'


def test_post_update_duration_is_converted_to_exact_nanoseconds():
    assert sim_duration_ns(timedelta(seconds=29, milliseconds=50)) == 29_050_000_000
