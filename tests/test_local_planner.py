import math
from types import SimpleNamespace

import pytest

from flydrones.local_planner import (
    HybridLocalPlanner,
    LocalPlannerConfig,
    PlannerPeer,
    RollingObstacleMemory,
)
from flydrones.motor.command import FlightCommand


def depth(captured_at, rays):
    return SimpleNamespace(captured_at=captured_at, ray_distances_m=tuple(rays))


def test_depth_rays_become_world_frame_evidence_and_expire():
    memory = RollingObstacleMemory(LocalPlannerConfig(obstacle_memory_s=2.0))
    memory.update(
        now=10.0,
        position=(1.0, 2.0, 1.8),
        yaw_rad=math.pi / 2,
        depth_observation=depth(10.0, [19.1] * 4 + [2.0] + [19.1] * 4),
    )
    live = memory.snapshot(now=11.9)
    assert live.obstacle_points
    assert live.is_observed_free((2.0, 2.0), margin_m=0.10)
    assert not live.is_observed_free((1.0, 1.0), margin_m=0.10)
    assert memory.snapshot(now=12.01).rays == ()


def test_left_image_ray_projects_to_body_left_in_world_frame():
    memory = RollingObstacleMemory(LocalPlannerConfig())
    memory.update(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        yaw_rad=math.pi / 2,
        depth_observation=depth(1.0, [1.0] + [19.1] * 8),
    )
    obstacle_x, obstacle_y = memory.snapshot(now=1.0).obstacle_points[0]
    assert obstacle_x > 0.0
    assert obstacle_y > 0.0


def test_memory_wraps_world_bearing_across_pi():
    memory = RollingObstacleMemory(LocalPlannerConfig(sector_count=72))
    memory.update(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        yaw_rad=-math.pi / 2 + 0.01,
        depth_observation=depth(1.0, [3.0] * 9),
    )
    sectors = {ray.sector for ray in memory.snapshot(now=1.1).rays}
    assert 0 in sectors or 71 in sectors
    assert max(sectors) - min(sectors) > 60


def test_max_range_ray_does_not_create_false_obstacle():
    memory = RollingObstacleMemory(LocalPlannerConfig(sensor_range_m=19.1))
    memory.update(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        yaw_rad=math.pi / 2,
        depth_observation=depth(1.0, [19.1] * 9),
    )
    snapshot = memory.snapshot(now=1.1)
    assert snapshot.obstacle_points == ()
    assert snapshot.is_observed_free((3.0, 0.0), margin_m=0.10)


def test_memory_replaces_older_evidence_in_the_same_world_sector():
    config = LocalPlannerConfig(sector_count=72, obstacle_memory_s=2.0)
    memory = RollingObstacleMemory(config)
    for frame in range(100):
        now = frame * 0.01
        memory.update(
            now=now,
            position=(frame * 0.001, 0.0, 1.8),
            yaw_rad=math.pi / 2,
            depth_observation=depth(now, [19.1] * 9),
        )
    snapshot = memory.snapshot(now=1.0)
    assert len(snapshot.rays) <= config.sector_count * 12
    assert all(
        sum(ray.sector == sector for ray in snapshot.rays) <= 12
        for sector in range(config.sector_count)
    )


def test_free_ray_does_not_immediately_erase_recent_obstacle_in_same_sector():
    memory = RollingObstacleMemory(LocalPlannerConfig())
    memory.update(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        yaw_rad=math.pi / 2,
        depth_observation=depth(1.0, [19.1] * 4 + [1.0] + [19.1] * 4),
    )
    memory.update(
        now=1.1,
        position=(0.0, 0.0, 1.8),
        yaw_rad=math.pi / 2,
        depth_observation=depth(1.1, [19.1] * 9),
    )
    assert memory.snapshot(now=1.1).obstacle_points


def clear_front(now=1.0):
    return depth(now, [19.1] * 9)


def test_unknown_rear_space_forbids_reverse_motion():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    decision = planner.plan(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        target=(6.0, 0.0),
        depth_observation=clear_front(),
        peers=(),
        preferred_command=FlightCommand(forward=-1.0),
        corridor_center_y=0.0,
        inside_forest=True,
    )
    assert decision.command.forward >= 0.0
    assert decision.rejection_counts["unknown"] > 0


def test_narrow_bypass_corridor_rejects_cross_track_drift():
    planner = HybridLocalPlanner(LocalPlannerConfig(unknown_is_blocked=False))
    decision = planner.plan(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        target=(6.0, 1.0),
        depth_observation=clear_front(),
        peers=(),
        preferred_command=FlightCommand(forward=1.0, lateral=-1.0, yaw=-1.0),
        corridor_center_y=0.0,
        corridor_half_width_m=0.35,
        inside_forest=True,
    )
    assert decision.rejection_counts["corridor"] > 0
    selected = next(
        candidate
        for candidate in planner._candidates(
            position=(0.0, 0.0, 1.8),
            velocity=(0.0, 0.0, 0.0),
            yaw_rad=math.pi / 2,
        )
        if candidate.candidate_id == decision.candidate_id
    )
    assert abs(selected.samples[-1][1]) <= 0.35


def test_remembered_tree_stays_blocked_after_camera_turns_away():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    obstacle = depth(1.0, [19.1] * 4 + [1.0] + [19.1] * 4)
    planner.observe(now=1.0, position=(0.0, 0.0, 1.8), yaw_rad=math.pi / 2, depth_observation=obstacle)
    decision = planner.plan(
        now=1.2,
        position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=0.0,
        target=(3.0, 0.0),
        depth_observation=clear_front(1.2),
        peers=(),
        preferred_command=FlightCommand(lateral=-1.0),
        corridor_center_y=0.0,
        inside_forest=True,
    )
    assert decision.minimum_static_clearance_m >= 0.60


def test_same_depth_frame_is_not_reprojected_after_vehicle_turns():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    obstacle = depth(1.0, [19.1] * 4 + [1.0] + [19.1] * 4)
    planner.observe(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        yaw_rad=math.pi / 2,
        depth_observation=obstacle,
    )
    planner.observe(
        now=1.1,
        position=(0.0, 0.0, 1.8),
        yaw_rad=0.0,
        depth_observation=obstacle,
    )
    snapshot = planner.memory.snapshot(now=1.1)
    assert len(snapshot.obstacle_points) == 1
    assert snapshot.obstacle_points[0] == pytest.approx((1.0, 0.0))


def test_crossing_peer_is_rejected_from_constant_velocity_prediction():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    peer = PlannerPeer(7, (1.0, 1.0, 1.8), (0.0, -1.0, 0.0), age_s=0.1)
    decision = planner.plan(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        target=(6.0, 0.0),
        depth_observation=clear_front(),
        peers=(peer,),
        preferred_command=FlightCommand(forward=1.0),
        corridor_center_y=0.0,
        inside_forest=True,
    )
    assert decision.minimum_peer_separation_m >= 0.90
    assert decision.rejection_counts["peer"] > 0


def test_invalid_peer_prediction_rejects_every_moving_candidate():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    peer = PlannerPeer(7, (1.0, 0.0, 1.8), (float("nan"), 0.0, 0.0), age_s=-0.1)
    decision = planner.plan(
        now=1.0,
        position=(0.0, 0.0, 1.8), velocity=(0.0, 0.0, 0.0), yaw_rad=math.pi / 2,
        target=(6.0, 0.0), depth_observation=clear_front(), peers=(peer,),
        preferred_command=FlightCommand(forward=1.0), corridor_center_y=0.0, inside_forest=True,
    )
    assert decision.mode == "hold-invalid-peer"
    assert decision.command.forward == decision.command.lateral == 0.0


def test_equal_scores_use_stable_candidate_order():
    kwargs = dict(
        now=1.0,
        position=(0.0, 0.0, 1.8), velocity=(0.0, 0.0, 0.0), yaw_rad=math.pi / 2,
        target=(6.0, 0.0), depth_observation=clear_front(), peers=(),
        preferred_command=FlightCommand(), corridor_center_y=0.0, inside_forest=False,
    )
    first = HybridLocalPlanner(LocalPlannerConfig()).plan(**kwargs)
    second = HybridLocalPlanner(LocalPlannerConfig()).plan(**kwargs)
    assert first.candidate_id == second.candidate_id
    assert first.command == second.command


def test_all_blocked_scene_returns_horizontal_hold():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    blocked = depth(1.0, [0.55] * 9)
    decision = planner.plan(
        now=1.0, position=(0.0, 0.0, 1.8), velocity=(0.0, 0.0, 0.0), yaw_rad=math.pi / 2,
        target=(6.0, 0.0), depth_observation=blocked, peers=(),
        preferred_command=FlightCommand(forward=1.0), corridor_center_y=0.0, inside_forest=True,
    )
    assert decision.mode == "hold-no-safe-trajectory"
    assert decision.command.forward == decision.command.lateral == 0.0


def test_rotation_candidates_check_inertial_translation_against_obstacles():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    blocked = depth(1.0, [0.55] * 9)
    decision = planner.plan(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        velocity=(0.8, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        target=(6.0, 0.0),
        depth_observation=blocked,
        peers=(),
        preferred_command=FlightCommand(yaw=1.0),
        corridor_center_y=0.0,
        inside_forest=True,
    )
    assert decision.mode == "hold-no-safe-trajectory"
    assert decision.rejection_counts["static"] == decision.generated_candidates


def test_observed_lateral_clearance_allows_side_escape():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    rays = [4.0, 4.0, 4.0, 0.7, 0.6, 0.7, 19.1, 19.1, 19.1]
    decision = planner.plan(
        now=1.0, position=(0.0, 0.0, 1.8), velocity=(0.0, 0.0, 0.0), yaw_rad=math.pi / 2,
        target=(6.0, 0.0), depth_observation=depth(1.0, rays), peers=(),
        preferred_command=FlightCommand(forward=1.0), corridor_center_y=0.0, inside_forest=True,
    )
    assert abs(decision.command.lateral) > 0.0 or abs(decision.command.yaw) > 0.0
    assert decision.command.forward < 1.0


def test_rotation_escape_keeps_one_direction_when_policy_preference_flips():
    planner = HybridLocalPlanner(LocalPlannerConfig(static_margin_m=0.60))
    rays = [4.0, 4.0, 4.0, 0.95, 0.90, 0.95, 19.1, 19.1, 19.1]
    common = dict(
        position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        target=(6.0, 0.0),
        peers=(),
        corridor_center_y=0.0,
        inside_forest=True,
    )
    first = planner.plan(
        now=1.0,
        depth_observation=depth(1.0, rays),
        preferred_command=FlightCommand(forward=1.0, yaw=1.0),
        **common,
    )
    second = planner.plan(
        now=1.1,
        depth_observation=depth(1.1, rays),
        preferred_command=FlightCommand(forward=1.0, yaw=-1.0),
        **common,
    )
    third = planner.plan(
        now=1.2,
        depth_observation=depth(1.2, rays),
        preferred_command=FlightCommand(forward=1.0, yaw=0.0),
        **common,
    )
    assert first.command.forward == second.command.forward == third.command.forward == 0.0
    assert first.command.yaw * second.command.yaw > 0.0
    assert first.command.yaw * third.command.yaw > 0.0


def test_planner_rotates_toward_target_instead_of_flying_farther_away():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    decision = planner.plan(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=-math.pi / 2,
        target=(6.0, 0.0),
        depth_observation=clear_front(),
        peers=(),
        preferred_command=FlightCommand(forward=1.0),
        corridor_center_y=0.0,
        inside_forest=True,
    )
    assert decision.command.forward == decision.command.lateral == 0.0
    assert decision.command.yaw > 0.0


def test_blocked_planner_reorients_to_target_when_peer_is_not_imminent():
    planner = HybridLocalPlanner(LocalPlannerConfig(static_margin_m=0.45))
    decision = planner.plan(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2 + 0.70,
        target=(4.0, 0.0),
        depth_observation=depth(1.0, [4.0, 4.0, 4.0, 0.75, 0.70, 0.75, 4.0, 4.0, 4.0]),
        peers=(PlannerPeer(8, (0.0, 3.0, 1.8), (0.0, 0.0, 0.0), age_s=0.1),),
        preferred_command=FlightCommand(forward=1.0, yaw=1.0),
        corridor_center_y=0.0,
        inside_forest=True,
    )
    assert decision.command.forward == 0.0
    assert decision.command.yaw < 0.0


def test_narrow_corridor_reorients_small_heading_error_against_policy_preference():
    planner = HybridLocalPlanner(LocalPlannerConfig(static_margin_m=0.38))
    decision = planner.plan(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2 - 0.20,
        target=(4.0, 0.0),
        depth_observation=depth(1.0, [4.0, 4.0, 4.0, 0.70, 0.65, 0.70, 4.0, 4.0, 4.0]),
        peers=(PlannerPeer(8, (0.0, 3.0, 1.8), (0.0, 0.0, 0.0), age_s=0.1),),
        preferred_command=FlightCommand(forward=1.0, yaw=-1.0),
        corridor_center_y=0.0,
        corridor_half_width_m=0.18,
        inside_forest=True,
    )
    assert decision.command.forward == 0.0
    assert decision.command.yaw > 0.0
