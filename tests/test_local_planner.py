import math
from types import SimpleNamespace

from flydrones.local_planner import LocalPlannerConfig, RollingObstacleMemory


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
