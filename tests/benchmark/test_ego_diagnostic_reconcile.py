"""Synthetic bridge/planner/server joins; never a live teacher qualification."""

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from flydrones.benchmark.ego_diagnostic_reconcile import _EVENT_FIELDS, reconcile_diagnostics

RUN = "dev-ego-1"
SESSION = "planner-session-1"
D = "a" * 64
P = "b" * 64
ODOM_DIGEST = "c" * 64
B = "d" * 64
C = "e" * 64
PROFILE = "f" * 64


def bridge(kind, digest, sample_ns, steady_ns, sequence, source):
    return {
        "schema": 1, "run_id": RUN, "session": SESSION,
        "pid": 10, "sequence": sequence, "kind": kind,
        "message_sha256": digest, "sample_ns": sample_ns,
        "event_steady_ns": steady_ns, "source": source,
        "source_profile_sha256": PROFILE, "truth_used": False,
    }


def trace(pid, sequence, steady_ns, event, **fields):
    return {"schema": 1, "session": SESSION, "pid": pid,
            "sequence": sequence, "event_steady_ns": steady_ns,
            "event": event, **{key: str(value) for key, value in fields.items()}}


def bundle():
    bridge_events = [
        bridge("odometry", ODOM_DIGEST, 1000, 10, 1, "px4_ekf2"),
        bridge("depth", D, 1000, 11, 2, "calibrated_rgbd"),
        bridge("camera_pose", P, 1000, 12, 3, "px4_ekf2_calibrated_extrinsic"),
        bridge("position_command", C, 9000, 90, 4, "ego_server"),
    ]
    planner = [
        trace(20, 1, 20, "fsm_odometry_received", odom_sequence=1,
              odom_sha256=ODOM_DIGEST, stamp_ns=1000, receive_node_ns=1001,
              frame_id="world", child_frame_id="base_link"),
        trace(20, 2, 21, "depth_pose_received", receive_sequence=1,
              image_sha256=D, pose_sha256=P, image_stamp_ns=1000,
              pose_stamp_ns=1000, receive_node_ns=1002,
              pending_for_apply="true"),
        trace(20, 3, 22, "map_depth_applied", revision=1,
              depth_sequence=1, receive_sequence=1, image_sha256=D,
              pose_sha256=P, image_stamp_ns=1000, pose_stamp_ns=1000,
              pose_kind="pose_stamped", map_apply_node_ns=1005),
        trace(20, 4, 30, "plan_published", trajectory_id=7,
              start_time_ns=3000, bspline_sha256=B, start_origin="odometry",
              parent_trajectory_id=0, parent_start_time_ns=-1,
              parent_sample_s=-1, available_odom_sequence=1,
              available_odom_sha256=ODOM_DIGEST, available_odom_stamp_ns=1000,
              map_before_revision=1, map_after_revision=1,
              map_depth_sequence=1, map_depth_receive_sequence=1,
              map_cloud_sequence=0, map_image_sha256=D, map_pose_sha256=P,
              map_image_stamp_ns=1000, map_pose_stamp_ns=1000,
              map_pose_kind="pose_stamped", plan_publish_node_ns=1010,
              start_x=0, start_y=0, start_z=1,
              start_vx=0, start_vy=0, start_vz=0),
    ]
    server = [
        trace(30, 1, 40, "server_bspline_received", raw_trajectory_id=7,
              stored_trajectory_id=7, start_time_ns=3000,
              bspline_sha256=B),
        trace(30, 2, 80, "server_command_published", raw_trajectory_id=7,
              stored_trajectory_id=7, emitted_trajectory_id=7,
              command_stamp_ns=9000, bspline_sha256=B,
              command_sha256=C),
    ]
    return bridge_events, planner, server


def reconcile(data):
    return reconcile_diagnostics(*data, run_id=RUN, session_id=SESSION)


def cdr_bundle(tmp_path, *, duplicate_depth=False, payloads=None):
    from tools.benchmark.ego_bridge_cdr_journal import BridgeCDRJournal

    if payloads is None:
        payloads = {"odometry": b"odom-cdr", "depth": b"depth-cdr",
                    "camera_pose": b"pose-cdr", "position_command": b"command-cdr"}
    replacement = {original: hashlib.sha256(payloads[kind]).hexdigest()
                   for kind, original in (("odometry", ODOM_DIGEST), ("depth", D),
                                          ("camera_pose", P), ("position_command", C))}
    _, planner, server = bundle()
    for row in planner + server:
        for key, value in row.items():
            if value in replacement:
                row[key] = replacement[value]
    if "clock" in payloads and "trigger" in payloads:
        times = iter([1, 2, 3, 4, 10, 11, 12, 13, 14, 15, 16, 17,
                      *([18, 19] if duplicate_depth else []), 90, 91, 92])
    else:
        times = iter([1, 2, 10, 11, 12, 13, 14, 15,
                      *([16, 17] if duplicate_depth else []), 90, 91, 92])
    path = tmp_path / "bridge.jsonl"
    journal = BridgeCDRJournal(path.open("x", encoding="utf-8"),
                               run_id=RUN, session_id=SESSION, pid=10,
                               serializer=lambda message: message,
                               clock=lambda: next(times))
    journal.start_reset(1)
    if "clock" in payloads:
        journal.publish("clock", payloads["clock"], 1000, lambda raw: None)
    journal.publish("odometry", payloads["odometry"], 1000, lambda raw: None)
    if "trigger" in payloads:
        journal.publish("trigger", payloads["trigger"], 1000, lambda raw: None)
    journal.publish("depth", payloads["depth"], 1000, lambda raw: None)
    journal.publish("camera_pose", payloads["camera_pose"], 1000, lambda raw: None)
    if duplicate_depth:
        journal.publish("depth", payloads["depth"], 1000, lambda raw: None)
    sequence = journal.receive_command(payloads["position_command"])
    journal.command_decoded(sequence, stamp_ns=9000, trajectory_id=7, ready=True)
    journal.close()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return rows, planner, server


def test_real_cdr_journal_projects_only_unattested_identity(tmp_path):
    from tools.benchmark.ego_cdr_diagnostic_join import reconcile_cdr_diagnostics

    match = reconcile_cdr_diagnostics(*cdr_bundle(tmp_path),
                                      run_id=RUN, session_id=SESSION)
    assert match["digest_identity_candidate"] is True
    assert match["identity_match"] is False
    assert match["cdr_journal_internal_complete"] is True
    assert match["cdr_payload_fields_verified"] is False
    assert match["stamp_binding_verified"] is False
    assert match["runtime_source_verified"] is False
    assert match["teacher_qualified"] is False


def _typed_cdr_payloads(*, image_encoding="32FC1", command_id=7):
    from zipfile import ZipFile

    import numpy as np
    from rosbags.typesys import Stores, get_types_from_msg, get_typestore

    store = get_typestore(Stores.ROS2_HUMBLE)
    with ZipFile("evidence/ego-causal-provenance-dev-1701.zip") as archive:
        definition = archive.read(
            "results/ego-causal-provenance-dev-1701/source/PositionCommand.msg")
    store.register(get_types_from_msg(definition.decode(), "quadrotor_msgs/msg/PositionCommand"))
    t = store.types
    time = t["builtin_interfaces/msg/Time"](sec=0, nanosec=1000)
    header = t["std_msgs/msg/Header"](stamp=time, frame_id="world")
    point = t["geometry_msgs/msg/Point"](x=0., y=0., z=1.)
    vector = t["geometry_msgs/msg/Vector3"](x=0., y=0., z=0.)
    quat = t["geometry_msgs/msg/Quaternion"](x=0., y=0., z=0., w=1.)
    pose = t["geometry_msgs/msg/Pose"](position=point, orientation=quat)
    pose_stamped = t["geometry_msgs/msg/PoseStamped"](header=header, pose=pose)
    pose_cov = t["geometry_msgs/msg/PoseWithCovariance"](pose=pose, covariance=np.zeros(36))
    twist = t["geometry_msgs/msg/Twist"](linear=vector, angular=vector)
    twist_cov = t["geometry_msgs/msg/TwistWithCovariance"](twist=twist, covariance=np.zeros(36))
    odom = t["nav_msgs/msg/Odometry"](header=header, child_frame_id="base_link",
                                       pose=pose_cov, twist=twist_cov)
    image_header = t["std_msgs/msg/Header"](stamp=time, frame_id="camera_optical")
    image = t["sensor_msgs/msg/Image"](
        header=image_header, height=1, width=1, encoding=image_encoding, is_bigendian=0,
        step=4, data=np.frombuffer(b"\x00\x00\x80?", dtype=np.uint8))
    command_header = t["std_msgs/msg/Header"](
        stamp=t["builtin_interfaces/msg/Time"](sec=0, nanosec=9000), frame_id="world")
    command = t["quadrotor_msgs/msg/PositionCommand"](
        header=command_header, position=point, velocity=vector, acceleration=vector,
        yaw=0., yaw_dot=0., kx=np.zeros(3), kv=np.zeros(3),
        trajectory_id=command_id, trajectory_flag=1)
    clock = t["rosgraph_msgs/msg/Clock"](clock=time)
    return {
        "clock": bytes(store.serialize_cdr(clock, clock.__msgtype__)),
        "odometry": bytes(store.serialize_cdr(odom, odom.__msgtype__)),
        "trigger": bytes(store.serialize_cdr(pose_stamped, pose_stamped.__msgtype__)),
        "depth": bytes(store.serialize_cdr(image, image.__msgtype__)),
        "camera_pose": bytes(store.serialize_cdr(pose_stamped, pose_stamped.__msgtype__)),
        "position_command": bytes(store.serialize_cdr(command, command.__msgtype__)),
    }


def test_opt_in_cdr_fields_bind_actual_bytes_without_qualifying_teacher(tmp_path):
    from tools.benchmark.ego_cdr_diagnostic_join import reconcile_cdr_diagnostics

    match = reconcile_cdr_diagnostics(
        *cdr_bundle(tmp_path, payloads=_typed_cdr_payloads()),
        run_id=RUN, session_id=SESSION, verify_payload_fields=True)
    assert match["cdr_payload_fields_verified"] is True
    assert match["stamp_binding_verified"] is True
    assert match["cdr_field_audit"]["rosbags_version"] == "0.11.5"
    assert match["ros_runtime_type_support_verified"] is False
    assert match["identity_match"] is False
    assert match["runtime_source_verified"] is False
    assert match["teacher_qualified"] is False


def test_opt_in_cdr_rejects_journal_metadata_and_trailing_bytes(tmp_path):
    from tools.benchmark.ego_cdr_diagnostic_join import reconcile_cdr_diagnostics

    payloads = _typed_cdr_payloads()
    payloads["position_command"] += b"\x00"
    with pytest.raises(ValueError, match="CDR|canonical"):
        reconcile_cdr_diagnostics(
            *cdr_bundle(tmp_path, payloads=payloads),
            run_id=RUN, session_id=SESSION, verify_payload_fields=True)
    second = tmp_path / "second"
    second.mkdir()
    rows, planner, server = cdr_bundle(second, payloads=_typed_cdr_payloads())
    for row in rows:
        if row["kind"] == "odometry" and row["phase"] in ("publish_intent", "publish_returned"):
            row["sample_ns"] = 1001
    with pytest.raises(ValueError, match="sample|stamp"):
        reconcile_cdr_diagnostics(rows, planner, server,
                                  run_id=RUN, session_id=SESSION, verify_payload_fields=True)


def test_independent_cdr_audit_checks_clock_trigger_image_and_command(tmp_path):
    from tools.benchmark.ego_bridge_cdr_journal import BridgeCDRJournal
    from tools.benchmark.ego_cdr_field_audit import audit_ego_cdr_fields

    payloads = _typed_cdr_payloads()
    path = tmp_path / "all-kinds.jsonl"
    journal = BridgeCDRJournal.open_new(path, run_id=RUN, session_id=SESSION,
                                        serializer=lambda message: message)
    journal.start_reset(1)
    for kind in ("clock", "odometry", "trigger", "camera_pose", "depth"):
        journal.publish(kind, payloads[kind], 1000, lambda raw: None)
    sequence = journal.receive_command(payloads["position_command"])
    journal.command_decoded(sequence, stamp_ns=9000, trajectory_id=7, ready=True)
    journal.close()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    result = audit_ego_cdr_fields(rows)
    assert result["message_count_by_kind"] == dict.fromkeys(payloads, 1)
    assert result["ros_runtime_type_support_verified"] is False
    assert result["teacher_qualified"] is False


def test_independent_cdr_audit_does_not_claim_stamps_without_publications(tmp_path):
    from tools.benchmark.ego_bridge_cdr_journal import BridgeCDRJournal
    from tools.benchmark.ego_cdr_field_audit import audit_ego_cdr_fields

    path = tmp_path / "command-only.jsonl"
    journal = BridgeCDRJournal.open_new(path, run_id=RUN, session_id=SESSION,
                                        serializer=lambda message: message)
    journal.start_reset(1)
    sequence = journal.receive_command(_typed_cdr_payloads()["position_command"])
    journal.command_decoded(sequence, stamp_ns=9000, trajectory_id=7, ready=True)
    journal.close()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    with pytest.raises(ValueError, match="missing.*CDR"):
        audit_ego_cdr_fields(rows)


@pytest.mark.parametrize("payloads,reason", [
    ({"image_encoding": "mono8"}, "image geometry"),
    ({"command_id": 8}, "trajectory"),
])
def test_independent_cdr_audit_refuses_valid_bytes_with_false_metadata(tmp_path, payloads, reason):
    from tools.benchmark.ego_cdr_diagnostic_join import reconcile_cdr_diagnostics

    with pytest.raises(ValueError, match=reason):
        reconcile_cdr_diagnostics(
            *cdr_bundle(tmp_path, payloads=_typed_cdr_payloads(**payloads)),
            run_id=RUN, session_id=SESSION, verify_payload_fields=True)


def test_public_reconciler_cannot_skip_cdr_audit_mode():
    with pytest.raises(TypeError, match="source_mode"):
        reconcile_diagnostics(*bundle(), run_id=RUN, session_id=SESSION,
                              source_mode="unattested_cdr")


def test_cdr_join_rejects_ambiguous_repeated_depth(tmp_path):
    from tools.benchmark.ego_cdr_diagnostic_join import reconcile_cdr_diagnostics

    with pytest.raises(ValueError, match="ambiguous"):
        reconcile_cdr_diagnostics(*cdr_bundle(tmp_path, duplicate_depth=True),
                                  run_id=RUN, session_id=SESSION)


def test_cdr_join_rejects_missing_publish_return_and_relabel(tmp_path):
    from tools.benchmark.ego_cdr_diagnostic_join import reconcile_cdr_diagnostics

    rows, planner, server = cdr_bundle(tmp_path)
    missing_return = [row for row in rows if not (
        row["phase"] == "publish_returned" and row["kind"] == "depth")]
    with pytest.raises(ValueError, match="sequence|publish"):
        reconcile_cdr_diagnostics(missing_return, planner, server,
                                  run_id=RUN, session_id=SESSION)
    rows[3]["source"] = "px4_ekf2"
    with pytest.raises(ValueError, match="source"):
        reconcile_cdr_diagnostics(rows, planner, server,
                                  run_id=RUN, session_id=SESSION)


@pytest.mark.parametrize("field,value", [("ready", False), ("trajectory_id", 8),
                                          ("sample_ns", 9001)])
def test_cdr_join_rejects_unbound_command_decode(tmp_path, field, value):
    from tools.benchmark.ego_cdr_diagnostic_join import reconcile_cdr_diagnostics

    rows, planner, server = cdr_bundle(tmp_path)
    decoded = next(row for row in rows if row["phase"] == "command_decoded")
    decoded[field] = value
    with pytest.raises(ValueError, match="command"):
        reconcile_cdr_diagnostics(rows, planner, server,
                                  run_id=RUN, session_id=SESSION)


def test_cdr_join_rejects_changed_bytes_and_cross_session(tmp_path):
    from tools.benchmark.ego_cdr_diagnostic_join import reconcile_cdr_diagnostics

    rows, planner, server = cdr_bundle(tmp_path)
    intent = next(row for row in rows if row["phase"] == "publish_intent")
    intent["message_cdr_b64"] = "eA=="
    with pytest.raises(ValueError, match="digest|length"):
        reconcile_cdr_diagnostics(rows, planner, server,
                                  run_id=RUN, session_id=SESSION)
    second = tmp_path / "second"
    second.mkdir()
    rows, planner, server = cdr_bundle(second)
    with pytest.raises(ValueError, match="session"):
        reconcile_cdr_diagnostics(rows, planner, server,
                                  run_id=RUN, session_id="other-session")


def test_exact_causal_chain_is_only_an_unqualified_identity_candidate():
    match = reconcile(bundle())
    assert match["identity_match"] is True
    assert match["trajectory_id"] == 7
    assert match["map_revision"] == 1
    assert match["depth_sha256"] == D
    assert match["command_sha256"] == C
    assert match["current_observation_match"] is True
    assert match["runtime_source_verified"] is False
    assert match["teacher_qualified"] is False


def test_event_schema_matches_the_exact_versioned_upstream_patch():
    root = Path(__file__).resolve().parents[2]
    patch = (root / "tools/benchmark/ego_causal_readonly_v2.patch").read_text(
        encoding="utf-8")
    source = re.sub(r"(?m)^\+", "", patch)
    for event, fields in _EVENT_FIELDS.items():
        found = re.search(r'fly_ego_diag::emit\("' + re.escape(event)
                          + r'", \{(.*?)\}\);', source, re.DOTALL)
        assert found is not None, event
        assert set(re.findall(r'\{"([a-z_0-9]+)"', found.group(1))) == fields, event


def test_received_image_without_completed_map_is_rejected():
    data = list(bundle())
    data[1] = [row for row in data[1] if row["event"] != "map_depth_applied"]
    data[1][-1]["sequence"] = 3
    with pytest.raises(ValueError, match="map"):
        reconcile(data)


def test_old_plan_command_remains_historical_control_reference_only():
    data = list(bundle())
    old_command = data[0].pop()
    data[0].extend([
        bridge("odometry", "1" * 64, 2000, 50, 4, "px4_ekf2"),
        bridge("depth", "2" * 64, 2000, 51, 5, "calibrated_rgbd"),
        bridge("camera_pose", "3" * 64, 2000, 52, 6,
               "px4_ekf2_calibrated_extrinsic"),
    ])
    old_command["sequence"] = 7
    data[0].append(old_command)
    match = reconcile(data)
    assert match["identity_match"] is True
    assert match["current_observation_match"] is False
    assert match["teacher_qualified"] is False


def test_duplicate_depth_hash_is_ambiguous_even_with_matching_stamps():
    data = list(bundle())
    data[0].insert(3, bridge("depth", D, 1000, 13, 4, "calibrated_rgbd"))
    data[0][-1]["sequence"] = 5
    with pytest.raises(ValueError, match="ambiguous"):
        reconcile(data)


def test_any_cloud_map_mutation_requires_separate_source_proof():
    data = list(bundle())
    data[1].insert(3, trace(20, 4, 23, "map_cloud_applied", revision=2,
                             cloud_sequence=1, cloud_sha256="1" * 64,
                             map_cloud_node_ns=1006))
    data[1][-1]["sequence"] = 5
    with pytest.raises(ValueError, match="cloud"):
        reconcile(data)


@pytest.mark.parametrize("bad_id", [0, -1, 2**31, 2**32 + 7, True])
def test_raw_id_narrowing_or_alias_is_rejected(bad_id):
    data = list(bundle())
    data[1][-1]["trajectory_id"] = str(bad_id)
    with pytest.raises(ValueError, match="trajectory"):
        reconcile(data)


def test_server_id_or_command_digest_mismatch_is_rejected():
    data = list(bundle())
    data[2][-1]["emitted_trajectory_id"] = "8"
    with pytest.raises(ValueError, match="trajectory"):
        reconcile(data)
    data = list(bundle())
    data[2][-1]["command_sha256"] = "1" * 64
    with pytest.raises(ValueError, match="command"):
        reconcile(data)


def test_gapped_journal_or_cross_session_records_are_rejected():
    data = list(bundle())
    data[1][2]["sequence"] = 5
    with pytest.raises(ValueError, match="sequence"):
        reconcile(data)
    data = list(bundle())
    data[2][0]["session"] = "other"
    with pytest.raises(ValueError, match="session"):
        reconcile(data)


def test_clock_regression_or_future_source_is_rejected():
    data = list(bundle())
    data[1][2]["event_steady_ns"] = 19
    with pytest.raises(ValueError, match="clock"):
        reconcile(data)
    data = list(bundle())
    data[0][1]["event_steady_ns"] = 25
    data[0][2]["event_steady_ns"] = 26
    with pytest.raises(ValueError, match="source.*after"):
        reconcile(data)


def test_unbound_depth_odometry_extrinsic_fails_closed():
    data = list(bundle())
    data[1][1]["event"] = "depth_odom_received"
    data[1][1].pop("pending_for_apply")
    data[1][2]["pose_kind"] = "odometry"
    data[1][3]["map_pose_kind"] = "odometry"
    with pytest.raises(ValueError, match="extrinsic|pose"):
        reconcile(data)


def test_truth_source_or_missing_profile_is_rejected():
    data = list(bundle())
    data[0][1]["truth_used"] = True
    with pytest.raises(ValueError, match="truth|source"):
        reconcile(data)
    data = list(bundle())
    data[0][1]["source_profile_sha256"] = ""
    with pytest.raises(ValueError, match="profile"):
        reconcile(data)


def test_input_mutation_after_registration_cannot_change_result():
    data = bundle()
    original = deepcopy(data)
    reconcile(data)
    assert data == original


def test_bool_schema_and_non_ascii_serialized_integer_are_rejected():
    data = list(bundle())
    data[1][0]["schema"] = True
    with pytest.raises(ValueError, match="schema"):
        reconcile(data)
    data = list(bundle())
    data[1][-1]["parent_start_time_ns"] = "-١"
    with pytest.raises(ValueError, match="parent_start_time_ns"):
        reconcile(data)


def test_unhashable_event_and_bridge_kind_fail_as_value_errors():
    data = list(bundle())
    data[1][0]["event"] = []
    with pytest.raises(ValueError, match="event"):
        reconcile(data)
    data = list(bundle())
    data[0][0]["kind"] = []
    with pytest.raises(ValueError, match="source|kind"):
        reconcile(data)


def test_unknown_diagnostic_field_and_duplicate_plan_id_are_rejected():
    data = list(bundle())
    data[1][2]["gazebo_truth"] = "1"
    with pytest.raises(ValueError, match="fields"):
        reconcile(data)
    data = list(bundle())
    duplicate = deepcopy(data[1][-1])
    duplicate.update(sequence=5, event_steady_ns=31,
                     bspline_sha256="1" * 64)
    data[1].append(duplicate)
    with pytest.raises(ValueError, match="duplicate trajectory"):
        reconcile(data)


def test_hidden_log_loss_in_independent_odom_counter_is_rejected():
    data = list(bundle())
    earlier = deepcopy(data[1][0])
    earlier.update(odom_sequence="2", event_steady_ns=19)
    data[1].insert(0, earlier)
    for sequence, row in enumerate(data[1], 1):
        row["sequence"] = sequence
    with pytest.raises(ValueError, match="odometry.*sequence"):
        reconcile(data)


def test_unselected_map_application_cannot_hide_a_missing_depth_receipt():
    data = list(bundle())
    hidden = deepcopy(data[1][2])
    hidden.update(sequence=5, event_steady_ns=31, revision="2",
                  depth_sequence="2", receive_sequence="2")
    data[1].append(hidden)
    with pytest.raises(ValueError, match="map.*receipt"):
        reconcile(data)


def test_received_depth_not_marked_pending_cannot_be_claimed_applied():
    data = list(bundle())
    data[1][1]["pending_for_apply"] = "false"
    with pytest.raises(ValueError, match="pending"):
        reconcile(data)


def test_asynchronous_two_plan_history_selects_latest_exact_command_lineage():
    bridge_events, planner, server = bundle()
    second_odom, second_depth, second_pose = "1" * 64, "2" * 64, "3" * 64
    second_bspline, second_command = "4" * 64, "5" * 64
    bridge_events.extend([
        bridge("odometry", second_odom, 2000, 100, 5, "px4_ekf2"),
        bridge("depth", second_depth, 2000, 101, 6, "calibrated_rgbd"),
        bridge("camera_pose", second_pose, 2000, 102, 7,
               "px4_ekf2_calibrated_extrinsic"),
        bridge("position_command", second_command, 9500, 150, 8, "ego_server"),
    ])
    followup = deepcopy(planner)
    for offset, row in enumerate(followup, 5):
        row["sequence"] = offset
        row["event_steady_ns"] += 90
    followup[0].update(odom_sequence="2", odom_sha256=second_odom,
                       stamp_ns="2000", receive_node_ns="2001")
    followup[1].update(receive_sequence="2", image_sha256=second_depth,
                       pose_sha256=second_pose, image_stamp_ns="2000",
                       pose_stamp_ns="2000", receive_node_ns="2002")
    followup[2].update(revision="2", depth_sequence="2", receive_sequence="2",
                       image_sha256=second_depth, pose_sha256=second_pose,
                       image_stamp_ns="2000", pose_stamp_ns="2000",
                       map_apply_node_ns="2005")
    followup[3].update(trajectory_id="8", start_time_ns="4000",
                       bspline_sha256=second_bspline, start_origin="previous_trajectory",
                       parent_trajectory_id="7", parent_start_time_ns="3000",
                       parent_sample_s="0.2", available_odom_sequence="2",
                       available_odom_sha256=second_odom,
                       available_odom_stamp_ns="2000", map_before_revision="2",
                       map_after_revision="2", map_depth_sequence="2",
                       map_depth_receive_sequence="2", map_image_sha256=second_depth,
                       map_pose_sha256=second_pose, map_image_stamp_ns="2000",
                       map_pose_stamp_ns="2000", plan_publish_node_ns="2010")
    planner.extend(followup)
    second_server = deepcopy(server)
    second_server[0].update(sequence=3, event_steady_ns=130,
                            raw_trajectory_id="8", stored_trajectory_id="8",
                            start_time_ns="4000", bspline_sha256=second_bspline)
    second_server[1].update(sequence=4, event_steady_ns=140,
                            raw_trajectory_id="8", stored_trajectory_id="8",
                            emitted_trajectory_id="8", command_stamp_ns="9500",
                            bspline_sha256=second_bspline,
                            command_sha256=second_command)
    server.extend(second_server)
    result = reconcile((bridge_events, planner, server))
    assert result["trajectory_id"] == 8
    assert result["parent_trajectory_id"] == 7
    assert result["depth_sha256"] == second_depth
    assert result["teacher_qualified"] is False
