"""Contract tests for EGO plan/input identity, separate from flight safety."""

from copy import deepcopy

import pytest

from flydrones.benchmark.ego_causal_join import EgoCausalJoin

RUN = "development-ego-causal-1"
SESSION = "ego-process-epoch-1"
DEPTH = "a" * 64
CALIBRATION = "b" * 64
ODOM = "c" * 64
POSE = "d" * 64


def observation(seq=1, **changes):
    row = {
        "run_id": RUN, "session_id": SESSION, "sequence": seq,
        "sim_ns": seq * 100_000_000, "frame_ns": seq * 100_000_000,
        "odom_sample_ns": seq * 100_000_000, "depth_sha256": DEPTH,
        "odom_sha256": ODOM, "camera_pose_sha256": POSE,
        "calibration_sha256": CALIBRATION, "odom_source": "px4_ekf2",
        "camera_source": "calibrated_rgbd", "source_healthy": True,
        "truth_used": False,
    }
    row.update(changes)
    return row


def map_applied(seq=1, **changes):
    row = {
        "run_id": RUN, "session_id": SESSION, "revision": seq,
        "source_sequence": seq, "frame_ns": seq * 100_000_000,
        "depth_sha256": DEPTH, "camera_pose_sha256": POSE,
        "applied_sim_ns": seq * 100_000_000 + 1,
        "update_completed": True,
    }
    row.update(changes)
    return row


def plan(seq=1, trajectory_id=7, **changes):
    row = {
        "run_id": RUN, "session_id": SESSION,
        "trajectory_id_raw": trajectory_id,
        "trajectory_id_stored": trajectory_id,
        "start_time_ns": 900_000_000 + seq,
        "available_odom_sequence": seq, "available_odom_sha256": ODOM,
        "start_state_origin": "odometry", "parent_trajectory_id": 0,
        "map_revision": seq,
        "map_source_sequence": seq,
        "created_sim_ns": seq * 100_000_000 + 2,
    }
    row.update(changes)
    return row


def command(trajectory_id=7, seq=1, **changes):
    row = {
        "run_id": RUN, "session_id": SESSION,
        "trajectory_id": trajectory_id,
        "header_stamp_ns": 1_700_000_000_000_000_000,
        "position_ref": [1., 2., 3.], "velocity_ref": [0.1, 0., 0.],
        "yaw_rate": 0.,
    }
    row.update(changes)
    return row


def ready_join():
    join = EgoCausalJoin(run_id=RUN, session_id=SESSION)
    join.add_observation(observation())
    join.add_applied_map(map_applied())
    join.add_plan(plan())
    return join


def test_exact_source_map_plan_and_command_match_without_claiming_teacher_safety():
    match = ready_join().match_command(command(), observation_sequence=1)
    assert match["observation_sequence"] == 1
    assert match["map_revision"] == 1
    assert match["trajectory_id"] == 7
    assert match["depth_sha256"] == DEPTH
    assert match["teacher_qualified"] is False


def test_received_image_without_completed_map_update_does_not_match():
    join = EgoCausalJoin(run_id=RUN, session_id=SESSION)
    join.add_observation(observation())
    with pytest.raises(ValueError, match="map update incomplete"):
        join.add_applied_map(map_applied(update_completed=False))
    with pytest.raises(ValueError, match="map revision"):
        join.add_plan(plan())


def test_old_plan_command_after_new_observation_is_not_new_frame_teacher_label():
    join = ready_join()
    join.add_observation(observation(2))
    with pytest.raises(ValueError, match="latest observation"):
        join.match_command(command(), observation_sequence=2)


@pytest.mark.parametrize("bad", [0, -1, 2**31, 2**32 + 7, True])
def test_raw_trajectory_id_narrowing_or_alias_is_rejected(bad):
    join = EgoCausalJoin(run_id=RUN, session_id=SESSION)
    join.add_observation(observation())
    join.add_applied_map(map_applied())
    with pytest.raises(ValueError, match="trajectory id"):
        join.add_plan(plan(trajectory_id=bad))


def test_stored_id_narrowing_and_same_session_reuse_are_rejected():
    join = ready_join()
    with pytest.raises(ValueError, match="trajectory id"):
        join.add_plan(plan(trajectory_id=2**31 + 7, trajectory_id_stored=7))
    with pytest.raises(ValueError, match="duplicate trajectory id"):
        join.add_plan(plan())


def test_target_cpp_int_max_is_lossless_but_a_new_session_never_joins_old_records():
    join = EgoCausalJoin(run_id=RUN, session_id=SESSION)
    join.add_observation(observation())
    join.add_applied_map(map_applied())
    join.add_plan(plan(trajectory_id=2**31 - 1))
    assert join.match_command(command(trajectory_id=2**31 - 1), observation_sequence=1)["trajectory_id"] == 2**31 - 1
    second = EgoCausalJoin(run_id=RUN, session_id="ego-process-epoch-2")
    second.add_observation(observation(session_id="ego-process-epoch-2"))
    second.add_applied_map(map_applied(session_id="ego-process-epoch-2"))
    with pytest.raises(ValueError, match="matching trajectory id"):
        second.match_command(command(trajectory_id=2**31 - 1, session_id="ego-process-epoch-2"),
                             observation_sequence=1)


def test_cross_session_command_cannot_join_same_numeric_trajectory_id():
    join = ready_join()
    with pytest.raises(ValueError, match="session"):
        join.match_command(command(session_id="ego-process-epoch-2"), observation_sequence=1)


def test_unpublished_start_time_cannot_be_synthesized_on_position_command():
    join = ready_join()
    with pytest.raises(ValueError, match="fields"):
        join.match_command(command(traj_start_time_ns=999), observation_sequence=1)


def test_header_stamp_is_not_treated_as_plan_start_time_or_input_identity():
    join = ready_join()
    match = join.match_command(command(header_stamp_ns=123), observation_sequence=1)
    assert match["plan_start_time_ns"] == 900_000_001
    assert match["command_header_stamp_ns"] == 123
    assert match["teacher_qualified"] is False


def test_map_uses_exact_image_identity_and_completed_revision():
    join = EgoCausalJoin(run_id=RUN, session_id=SESSION)
    join.add_observation(observation())
    with pytest.raises(ValueError, match="depth identity"):
        join.add_applied_map(map_applied(depth_sha256="c" * 64))
    join.add_applied_map(map_applied())
    with pytest.raises(ValueError, match="map revision"):
        join.add_plan(plan(map_revision=2))


def test_map_pose_and_plan_odometry_bytes_must_match_source():
    join = EgoCausalJoin(run_id=RUN, session_id=SESSION)
    join.add_observation(observation())
    with pytest.raises(ValueError, match="camera pose identity"):
        join.add_applied_map(map_applied(camera_pose_sha256="e" * 64))
    join.add_applied_map(map_applied())
    with pytest.raises(ValueError, match="odometry identity"):
        join.add_plan(plan(available_odom_sha256="e" * 64))
    join.add_plan(plan())
    assert join.match_command(command(), observation_sequence=1)["available_odom_sha256"] == ODOM


def test_failure_has_no_partial_state_and_registered_input_is_copied():
    join = EgoCausalJoin(run_id=RUN, session_id=SESSION)
    row = observation()
    join.add_observation(row)
    row["depth_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="depth identity"):
        join.add_applied_map(map_applied(depth_sha256="c" * 64))
    join.add_applied_map(map_applied())
    join.add_plan(plan())
    cmd = command()
    original = deepcopy(cmd)
    match = join.match_command(cmd, observation_sequence=1)
    assert cmd == original
    assert match["depth_sha256"] == DEPTH


@pytest.mark.parametrize("change", [
    {"truth_used": True}, {"source_healthy": False},
    {"odom_source": "gazebo_truth"}, {"calibration_sha256": ""},
    {"frame_ns": 200_000_000}, {"sequence": True},
])
def test_unhealthy_unattested_or_malformed_observation_is_rejected(change):
    join = EgoCausalJoin(run_id=RUN, session_id=SESSION)
    with pytest.raises(ValueError):
        join.add_observation(observation(**change))


def test_plan_cannot_use_future_or_unapplied_map_revision():
    join = EgoCausalJoin(run_id=RUN, session_id=SESSION)
    join.add_observation(observation())
    join.add_applied_map(map_applied())
    with pytest.raises(ValueError, match="plan time"):
        join.add_plan(plan(created_sim_ns=100_000_000))
    with pytest.raises(ValueError, match="map revision"):
        join.add_plan(plan(map_revision=3))


def test_plan_odom_sequence_must_match_map_applied_source_sequence():
    join = EgoCausalJoin(run_id=RUN, session_id=SESSION)
    join.add_observation(observation())
    join.add_applied_map(map_applied())
    join.add_observation(observation(2))
    with pytest.raises(ValueError, match="input sequence"):
        join.add_plan(plan(2, trajectory_id=8, map_revision=1, map_source_sequence=1))


def test_replan_from_prior_trajectory_records_lineage_without_claiming_odom_start():
    join = ready_join()
    join.add_observation(observation(2))
    join.add_applied_map(map_applied(2))
    join.add_plan(plan(2, trajectory_id=8, start_state_origin="previous_trajectory",
                       parent_trajectory_id=7))
    match = join.match_command(command(trajectory_id=8, seq=2), observation_sequence=2)
    assert match["start_state_origin"] == "previous_trajectory"
    assert match["parent_trajectory_id"] == 7
    assert match["teacher_qualified"] is False


def test_replan_cannot_claim_missing_parent_or_odometry_with_parent():
    join = ready_join()
    join.add_observation(observation(2))
    join.add_applied_map(map_applied(2))
    with pytest.raises(ValueError, match="parent trajectory"):
        join.add_plan(plan(2, trajectory_id=8, start_state_origin="previous_trajectory",
                           parent_trajectory_id=6))
    with pytest.raises(ValueError, match="start state origin"):
        join.add_plan(plan(2, trajectory_id=8, start_state_origin="odometry",
                           parent_trajectory_id=7))


def test_oversized_numeric_command_and_timestamp_fail_closed_as_value_errors():
    join = ready_join()
    with pytest.raises(ValueError, match="position reference"):
        join.match_command(command(position_ref=[10**1000, 0., 0.]), observation_sequence=1)
    with pytest.raises(ValueError, match="command header time"):
        join.match_command(command(header_stamp_ns=2**63), observation_sequence=1)
