"""Real analytic ULog/codec and production cleanup; no native/network dispatch."""

import hashlib
import json
import os
import socket
import struct
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def inert(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("native/network forbidden")

    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(os, "system", denied)


def record(kind, payload):
    return struct.pack("<HB", len(payload), ord(kind)) + payload


def material():
    from tools.benchmark.disarmed_odometry_receiver import DisarmedOdometryReceiver
    from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock
    from tools.benchmark.openvins_timesync_wire import PinnedCodec

    codec = PinnedCodec()
    clock = RemoteMonotonicClock("wire", sim_origin_ns=0, remote_origin_ns=1_000_000)
    state = dict(
        sample_ns=120_000_000,
        reset_counter=0,
        reset_total=0,
        native_profile="offset-reset-v2",
        native_state13=[0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0, 0.0, 0.5],
        native_covariance12=np.eye(12).tolist(),
        native_session="a" * 64,
        native_pid=42,
        quality=None,
    )
    receiver = DisarmedOdometryReceiver(SimpleNamespace(wire_snapshot=lambda sim: dict(state, sample_ns=sim)))
    receiver.response_ns = 100
    sends = []
    rows = []
    for index, ns in enumerate((120_000_000, 140_000_000)):
        raw = receiver.odometry(codec, clock, index, 101, ns, disarmed=True)
        receiver.send_events[-1]["bytes_returned"] = len(raw)
        wire = codec.decode_datagram(raw)[0]["fields"]
        rows.append(
            dict(
                timestamp=wire["time_usec"] + 501000,
                timestamp_sample=wire["time_usec"] + 500000,
                pose_frame=2,
                velocity_frame=3,
                position=[wire[k] for k in ("x", "y", "z")],
                q=wire["q"],
                velocity=[wire[k] for k in ("vx", "vy", "vz")],
                angular_velocity=[wire[k] for k in ("rollspeed", "pitchspeed", "yawspeed")],
                position_variance=[wire["pose_covariance"][i] for i in (0, 6, 11)],
                orientation_variance=[wire["pose_covariance"][i] for i in (15, 18, 20)],
                velocity_variance=[wire["velocity_covariance"][i] for i in (0, 6, 11)],
                reset_counter=0,
                quality=0,
            )
        )
    sends = receiver.send_events
    columns = {
        "vehicle_visual_odometry": [
            ("uint64_t", "timestamp", "Q"),
            ("uint64_t", "timestamp_sample", "Q"),
            ("uint8_t", "pose_frame", "B"),
            ("uint8_t", "velocity_frame", "B"),
        ]
        + [
            (f"float[{n}]", name, f"{n}f")
            for name, n in [
                ("position", 3),
                ("q", 4),
                ("velocity", 3),
                ("angular_velocity", 3),
                ("position_variance", 3),
                ("orientation_variance", 3),
                ("velocity_variance", 3),
            ]
        ]
        + [("uint8_t", "reset_counter", "B"), ("int8_t", "quality", "b")],
        "timesync_status": [
            ("uint64_t", "timestamp", "Q"),
            ("uint8_t", "source_protocol", "B"),
            ("uint64_t", "remote_timestamp", "Q"),
            ("int64_t", "estimated_offset", "q"),
            ("uint32_t", "round_trip_time", "I"),
        ],
        "vehicle_status": [("uint64_t", "timestamp", "Q"), ("uint8_t", "arming_state", "B")],
        "actuator_armed": [("uint64_t", "timestamp", "Q"), ("bool", "armed", "B")],
        "estimator_status": [("uint64_t", "timestamp", "Q"), ("uint32_t", "filter_fault_flags", "I")],
        "estimator_selector_status": [("uint64_t", "timestamp", "Q"), ("uint8_t", "primary_instance", "B")],
        "estimator_status_flags": [("uint64_t", "timestamp", "Q")]
        + [("bool", k, "B") for k in ("cs_ev_pos", "cs_ev_vel", "cs_ev_hgt", "cs_ev_yaw")],
    }
    data = {
        "vehicle_visual_odometry": rows,
        "timesync_status": [
            dict(timestamp=t, source_protocol=0, remote_timestamp=t - 500000, estimated_offset=500000, round_trip_time=1000)
            for t in (610000, 630000)
        ],
        "vehicle_status": [dict(timestamp=t, arming_state=1) for t in (600000, 700000)],
        "actuator_armed": [dict(timestamp=t, armed=0) for t in (600000, 700000)],
        "estimator_status": [dict(timestamp=t, filter_fault_flags=0) for t in (600000, 700000)],
        "estimator_selector_status": [dict(timestamp=t, primary_instance=0) for t in (600000, 700000)],
        "estimator_status_flags": [
            dict(timestamp=t, cs_ev_pos=0, cs_ev_vel=0, cs_ev_hgt=0, cs_ev_yaw=0) for t in (600000, 700000)
        ],
    }
    for topic, n in (("estimator_aid_src_ev_pos", 2), ("estimator_aid_src_ev_vel", 3), ("estimator_aid_src_ev_hgt", 1)):
        cols = [
            ("uint64_t", "timestamp", "Q"),
            ("uint64_t", "timestamp_sample", "Q"),
            ("uint8_t", "estimator_instance", "B"),
            ("uint64_t", "time_last_fuse", "Q"),
            ("bool", "fused", "B"),
            ("bool", "innovation_rejected", "B"),
        ]
        vector_names = ("observation", "observation_variance", "innovation", "innovation_variance", "test_ratio")
        cols += [("float" if n == 1 else f"float[{n}]", k, "f" if n == 1 else f"{n}f") for k in vector_names]
        columns[topic] = cols
        data[topic] = [
            dict(
                timestamp=r["timestamp"],
                timestamp_sample=r["timestamp_sample"],
                estimator_instance=0,
                time_last_fuse=0,
                fused=0,
                innovation_rejected=0,
                **{k: (0.1 if n == 1 else [0.1] * n) for k in vector_names},
            )
            for r in rows
        ]
    return sends, columns, data


def encode(columns, data, ev=0):
    raw = b"ULog\x01\x12\x35\x01" + struct.pack("<Q", 1) + record("B", bytes(40))
    for name, cols in columns.items():
        raw += record("F", (name + ":" + "".join(t + " " + k + ";" for t, k, _ in cols)).encode())
    key = b"int32_t EKF2_EV_CTRL"
    raw += record("P", bytes([len(key)]) + key + struct.pack("<i", ev))
    for index, (name, cols) in enumerate(columns.items()):
        raw += record("A", struct.pack("<BH", 0, index) + name.encode())
        for row in data[name]:
            payload = struct.pack("<H", index)
            for _, k, fmt in cols:
                values = row[k] if isinstance(row[k], list) else [row[k]]
                payload += struct.pack("<" + fmt, *values)
            raw += record("D", payload)
    return raw


def test_complete_real_bytes_receipt_is_distinct_from_disabled_fusion():
    from tools.benchmark.px4_disarmed_receipts import analyze_log

    sends, columns, data = material()
    facts = analyze_log(encode(columns, data), sends)
    assert facts["matched_receipts"] == 2 and facts["receiver_fields_correlated"] is True
    assert facts["disabled_ev_observed"] is True and facts["positive_fusion_samples"] == 0
    assert facts["fusion_verified"] is False and facts["flight_eligible"] is False


@pytest.mark.parametrize("protocol", [0, 1, 2])
def test_pinned_source_protocol_matches_wrapper_without_authentication(protocol):
    from tools.benchmark.px4_disarmed_receipts import analyze_log

    sends, columns, data = material()
    for row in data["timesync_status"]:
        row["source_protocol"] = protocol
    facts = analyze_log(encode(columns, data), sends)
    assert facts["receiver_fields_correlated"] is (protocol == 0)
    assert facts["receiver_only_evidence_complete"] is (protocol == 0)
    assert facts["source_authenticated"] is False
    assert facts["timesync_convergence_qualified"] is False


@pytest.mark.parametrize("fault", ["armed", "offset", "reset", "field", "short", "missing", "fused", "dropout", "parameter"])
def test_actual_evidence_faults_do_not_gain_acceptance(fault):
    from tools.benchmark.px4_disarmed_receipts import analyze_log

    sends, columns, data = material()
    if fault == "armed":
        data["vehicle_status"][1]["arming_state"] = 2
    if fault == "offset":
        data["timesync_status"][0]["estimated_offset"] += 100
    if fault == "reset":
        data["vehicle_visual_odometry"][1]["reset_counter"] = 1
    if fault == "field":
        data["vehicle_visual_odometry"][1]["position"][0] += 1
    if fault == "short":
        sends[0]["bytes_returned"] = 2
    if fault == "missing":
        del columns["estimator_aid_src_ev_vel"]
    if fault == "fused":
        data["estimator_aid_src_ev_pos"][0]["fused"] = 1
    raw = encode(columns, data, ev=1 if fault == "parameter" else 0)
    if fault == "dropout":
        raw += record("O", b"\x01\x00")
    try:
        facts = analyze_log(raw, sends)
    except ValueError:
        return
    assert facts["errors"] and facts["receiver_only_evidence_complete"] is False
    assert facts["fusion_verified"] is False


def test_cleanup_consumes_after_collection_and_association_without_native(tmp_path, monkeypatch):
    from tools.benchmark import capture_disarmed_sensors as capture
    from tools.benchmark import px4_disarmed_receipts as receipt
    from tools.benchmark.disarmed_sensor_provenance import CaptureJournal

    events = []
    monkeypatch.setattr(capture, "collect_ulogs", lambda *args: events.append("collect") or [])

    class Source:
        def __init__(self, *args, **kwargs):
            pass

        def finish(self, records):
            events.append("associate")
            return dict(errors=[], all_logs_associated=True)

    monkeypatch.setattr("tools.benchmark.owned_ulog_source.OwnedUlogSource", Source)
    monkeypatch.setattr(
        receipt, "consume_capture", lambda *args, **kwargs: events.append("consume") or dict(errors=[], fusion_verified=False)
    )
    result = dict(status="capture_completed", errors=[])
    with CaptureJournal(tmp_path, result) as journal:
        capture.prepare_owned_ulog_collection(
            dict(owned_ulog_source={}, disarmed_receipt_evidence={}),
            tmp_path,
            tmp_path,
            "a" * 64,
            result,
            journal,
            deadline_ns=time.monotonic_ns() + 1_000_000_000,
        )
    assert events == ["collect", "associate", "consume"]
    assert result["disarmed_receipt_evidence"]["fusion_verified"] is False


def capture_files(tmp_path):
    sends, columns, data = material()
    raw = encode(columns, data)
    log = tmp_path / "px4-ulog/log.ulg"
    log.parent.mkdir()
    log.write_bytes(raw)
    entry = dict(path="px4-ulog/log.ulg", bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), valid_header=True)
    (tmp_path / "px4-ulog-manifest.json").write_text(json.dumps(dict(logs=[entry])))
    owner = dict(pid=84, pgrp=84, session=84, start_ticks=100, executable="/owned/px4")
    (tmp_path / "wire-owner.json").write_text(
        json.dumps(dict(owner=dict(pid=84, pgrp=84, session=84, start_ticks=100, exe="/owned/px4")))
    )
    return dict(
        status="capture_completed",
        errors=[],
        px4_ulogs=[entry],
        owned_ulog_source=dict(
            owner=owner,
            owner_exit=0,
            errors=[],
            all_logs_associated=True,
            logs=[dict(path=entry["path"], sha256=entry["sha256"], observed_writable_opener=True)],
        ),
        wire_lifecycle=dict(
            failure=None, session=dict(clock_signature=["wire", 0, 1_000_000], estimate_receiver=dict(send_events=sends))
        ),
    )


def test_actual_terminal_consumer_binds_owned_files_and_preserves_summary(tmp_path):
    from tools.benchmark.px4_disarmed_receipts import consume_capture

    result = capture_files(tmp_path)
    facts = consume_capture(tmp_path, result, deadline_ns=time.monotonic_ns() + 10_000_000_000)
    assert facts["errors"] == [] and facts["receiver_only_evidence_complete"] is True
    assert facts["logs"][0]["observations"]["matched_receipts"] == 2
    assert json.loads((tmp_path / "px4-disarmed-receipts.json").read_bytes()) == facts
    assert facts["fusion_verified"] is False


@pytest.mark.parametrize("fault", ["owner", "manifest", "witness", "clock", "deadline", "capture", "wire", "replace_log"])
def test_actual_terminal_consumer_refuses_missing_or_changed_provenance(tmp_path, fault):
    from tools.benchmark.px4_disarmed_receipts import consume_capture

    result = capture_files(tmp_path)
    if fault == "owner":
        result["owned_ulog_source"]["owner"]["pid"] = 85
    if fault == "manifest":
        result["px4_ulogs"][0]["sha256"] = "b" * 64
    if fault == "witness":
        result["owned_ulog_source"]["logs"][0]["observed_writable_opener"] = False
    if fault == "clock":
        result["wire_lifecycle"]["session"]["clock_signature"][2] += 1000
    if fault == "capture":
        result["errors"].append("source already failed")
    if fault == "wire":
        result["wire_lifecycle"]["failure"] = "native child lost"
    if fault == "replace_log":
        (tmp_path / "px4-ulog/log.ulg").write_bytes(b"replacement")
    facts = consume_capture(tmp_path, result, deadline_ns=0 if fault == "deadline" else time.monotonic_ns() + 10_000_000_000)
    assert facts["errors"] and facts["receiver_only_evidence_complete"] is False
    assert facts["fusion_verified"] is False


def test_exact_receipt_logger_stages_and_rejects_drift(tmp_path):
    from tools.benchmark import px4_logger_runtime as logger

    source = Path(logger.__file__).resolve().parents[2] / "config/px4/disarmed-receipt-v2"
    record = logger.profile_record(source)
    assert record["profile_id"] == "disarmed-receipt-v2"
    staged = logger.stage_profile(record, tmp_path.resolve())
    assert logger.verify_profile(record, staged, tmp_path.resolve())["copy_stable"] is True
    target = tmp_path / "etc/logging/logger_topics.txt"
    target.write_bytes(target.read_bytes() + b"unexpected 0 0\n")
    with pytest.raises(ValueError):
        logger.verify_profile(record, staged, tmp_path.resolve())


def test_capture_parser_worker_and_execution_declaration_select_actual_consumer(tmp_path, monkeypatch):
    from tests.benchmark.test_native_offset_odometry import selected_args
    from tools.benchmark import capture_contract as contract
    from tools.benchmark import capture_disarmed_sensors as capture

    args = selected_args(tmp_path)
    args.agent_runtime_config = tmp_path / "agent.json"
    args.record_owned_ulog = True
    args.consume_disarmed_odometry_evidence = True
    args.logger_diagnostic_profile = "disarmed-receipt-v2"
    monkeypatch.setattr(contract, "wire_configuration_record", lambda *args: {})
    monkeypatch.setattr(contract, "_managed_record", lambda *args, **kwargs: {}, raising=False)
    monkeypatch.setattr("tools.benchmark.managed_capture_source.configuration_record", lambda *args, **kwargs: {})
    monkeypatch.setattr("tools.benchmark.agent_capture_runtime.agent_runtime_record", lambda *args: {})
    actual = contract.execution_contract(args)
    assert actual["disarmed_receipt_evidence"]["fusion_verified"] is False
    flags = contract.worker_options(args)
    assert "--consume-disarmed-odometry-evidence" in flags
    parsed = capture.parse_capture_args(["--output", str(tmp_path), *flags])
    assert parsed.consume_disarmed_odometry_evidence is True
    args.record_owned_ulog = False
    with pytest.raises(ValueError, match="receipt"):
        contract.execution_contract(args)


def test_positive_fusion_is_retained_even_when_disabled_profile_is_violated():
    from tools.benchmark.px4_disarmed_receipts import analyze_log

    sends, cols, data = material()
    data["estimator_status_flags"][0]["cs_ev_pos"] = 1
    data["estimator_aid_src_ev_pos"][0]["fused"] = 1
    facts = analyze_log(encode(cols, data), sends)
    assert facts["positive_fusion_samples"] == 1
    assert facts["errors"] and facts["fusion_verified"] is False


def test_disabled_flags_must_bracket_receipt_window():
    from tools.benchmark.px4_disarmed_receipts import analyze_log

    sends, cols, data = material()
    data["estimator_status_flags"][0]["timestamp"] = 100
    data["estimator_status_flags"][1]["timestamp"] = 200
    facts = analyze_log(encode(cols, data), sends)
    assert facts["disabled_ev_observed"] is False and facts["errors"]


@pytest.mark.parametrize(
    "fault", ["late_sync", "extra_receiver", "instance", "nan_innovation", "last_fuse", "missing_parameter", "truncated"]
)
def test_new_real_parser_refuses_ambiguous_or_incomplete_observations(fault):
    from tools.benchmark.px4_disarmed_receipts import analyze_log

    sends, cols, data = material()
    if fault == "late_sync":
        data["timesync_status"][0]["timestamp"] = 623000
    if fault == "extra_receiver":
        data["vehicle_visual_odometry"].append(
            dict(data["vehicle_visual_odometry"][-1], timestamp=650000, timestamp_sample=649000)
        )
    if fault == "instance":
        data["estimator_selector_status"][1]["primary_instance"] = 1
    if fault == "nan_innovation":
        data["estimator_aid_src_ev_vel"][0]["innovation"][1] = float("nan")
    if fault == "last_fuse":
        data["estimator_aid_src_ev_hgt"][0]["time_last_fuse"] = 600000
    raw = encode(cols, data)
    if fault == "missing_parameter":
        key = b"int32_t EKF2_EV_CTRL"
        raw = raw.replace(record("P", bytes([len(key)]) + key + struct.pack("<i", 0)), b"")
    if fault == "truncated":
        raw = raw[:-1]
    try:
        facts = analyze_log(raw, sends)
    except ValueError:
        return
    assert facts["errors"] and facts["receiver_only_evidence_complete"] is False


def test_existing_logger_profile_remains_exact_and_separate():
    from tools.benchmark.px4_logger_runtime import profile_record

    root = Path(__file__).resolve().parents[2]
    old = profile_record(root / "config/px4/source-diagnostic-v1")
    assert old["profile_id"] == "source-diagnostic-v1"
    assert old["topics_sha256"] == "0bb9a3d9b57c6a73c73e8fee75569b9e690857654c4631b6f6cd5b6654328994"


def test_parser_rejects_receipt_flag_without_bound_source_before_any_effect(tmp_path):
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    with pytest.raises(SystemExit):
        parse_capture_args(["--output", str(tmp_path), "--consume-disarmed-odometry-evidence"])
    assert list(tmp_path.iterdir()) == []


def test_evidence_read_limit_rejects_before_whole_file_pin(tmp_path, monkeypatch):
    from tools.benchmark import px4_disarmed_receipts as receipt

    path = tmp_path / "oversize.json"
    path.write_bytes(b"x" * 65)
    monkeypatch.setattr(receipt, "file_record", lambda *args: pytest.fail("whole file pin before narrow bound"))
    with pytest.raises(ValueError, match="bound"):
        receipt._stable_read(path, 64)
