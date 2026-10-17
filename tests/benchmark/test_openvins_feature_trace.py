import copy
import hashlib
import json
from pathlib import Path

import pytest

TRACK = (
    "FD_TRACK t=3.100000000 cam=0 initial=0 previous=40 topped=50 "
    "klt_or_ransac=8 out_of_bounds=1 masked=0 accepted=41 reset=0"
)
PIPE = (
    "FD_PIPE t=3.100000000 db=76 lost=3 marg=2 maxtracks=1 "
    "msckf_selected=5 msckf_accepted=1 slam_delayed=1 "
    "slam_delayed_accepted=0 slam_update=0 slam_update_accepted=0"
)
MSCKF = (
    "FD_MSCKF t=3.100000000 input=5 insufficient=1 triangulation=2 "
    "refinement=0 chi2=1 accepted=1"
)
SLAM_DELAY = (
    "FD_SLAM_DELAY t=3.100000000 input=1 insufficient=0 triangulation=0 "
    "refinement=0 initialization=1 accepted=0"
)
SLAM_UPDATE = (
    "FD_SLAM_UPDATE t=3.100000000 input=2 no_measurements=0 "
    "representation_insufficient=0 chi2=1 accepted=1"
)


def _detail_log(timestamp="3.100000000", feature_offset=0):
    track = (
        f"FD_TRACK t={timestamp} cam=0 initial=0 previous=3 topped=3 "
        "klt_or_ransac=0 out_of_bounds=0 masked=0 accepted=3 reset=0"
    )
    pipe = (
        f"FD_PIPE t={timestamp} db=3 lost=3 marg=0 maxtracks=0 "
        "msckf_selected=3 msckf_accepted=1 slam_delayed=1 "
        "slam_delayed_accepted=0 slam_update=0 slam_update_accepted=0"
    )
    msckf = (
        f"FD_MSCKF t={timestamp} input=3 insufficient=2 triangulation=0 "
        "refinement=0 chi2=0 accepted=1"
    )
    slam = (
        f"FD_SLAM_DELAY t={timestamp} input=1 insufficient=0 triangulation=1 "
        "refinement=0 initialization=0 accepted=0"
    )
    rows = [track, pipe, msckf, slam]
    histories = (
        (10 + feature_offset, "lost", 1, 1, 0, "3.000000000", "3.000000000"),
        (11 + feature_offset, "lost", 3, 1, 2, "2.700000000", "3.000000000"),
        (12 + feature_offset, "lost", 3, 2, 1, "2.800000000", "3.000000000"),
    )
    for feat, origin, before, after, removed, first, last in histories:
        rows.append(
            f"FD_SELECT t={timestamp} stage=msckf feat={feat} origin={origin} "
            f"raw_meas={before} raw_cams=1 raw_first={first} raw_last={last}"
        )
        rows.append(
            f"FD_HISTORY t={timestamp} stage=msckf feat={feat} before={before} "
            f"after={after} removed={removed} cams_before=1 cams_after=1 "
            f"before_range=1 first_before={first} last_before={last} "
            f"after_range=1 first_after=3.000000000 last_after=3.000000000 "
            "clones=11 clone_first=2.100000000 clone_last=3.100000000"
        )
    rows.append(
        f"FD_TRI t={timestamp} stage=msckf feat={12 + feature_offset} mode=3d "
        "meas=2 cams=1 anchor_cam=0 anchor_t=3.000000000 cond_finite=1 "
        "cond=12.5 depth_finite=1 depth=4.0 max_anchor_baseline=0.20 "
        "geometry_finite=1 "
        "max_pair_baseline=0.20 max_parallax_rad=0.04 reject_cond=0 "
        "reject_min_depth=0 reject_max_depth=0 reject_nonfinite=0 accepted=1"
    )
    slam_feat = 20 + feature_offset
    rows.append(
        f"FD_SELECT t={timestamp} stage=slam_delay feat={slam_feat} "
        "origin=maxtracks_to_slam raw_meas=4 raw_cams=1 "
        "raw_first=2.700000000 raw_last=3.000000000"
    )
    rows.append(
        f"FD_HISTORY t={timestamp} stage=slam_delay feat={slam_feat} before=4 "
        "after=4 removed=0 cams_before=1 cams_after=1 before_range=1 "
        "first_before=2.700000000 last_before=3.000000000 after_range=1 "
        "first_after=2.700000000 last_after=3.000000000 clones=11 "
        "clone_first=2.100000000 clone_last=3.100000000"
    )
    rows.append(
        f"FD_TRI t={timestamp} stage=slam_delay feat={slam_feat} mode=3d "
        "meas=4 cams=1 anchor_cam=0 anchor_t=3.000000000 cond_finite=1 "
        "cond=20000.0 depth_finite=1 depth=4.0 max_anchor_baseline=0.001 "
        "geometry_finite=1 "
        "max_pair_baseline=0.001 max_parallax_rad=0.0001 reject_cond=1 "
        "reject_min_depth=0 reject_max_depth=0 reject_nonfinite=0 accepted=0"
    )
    return "\n".join(rows) + "\n"


def test_parse_trace_reconciles_history_and_geometry_records():
    from tools.benchmark.openvins_feature_trace import parse_trace

    parsed = parse_trace(_detail_log(), require_detail=True)
    record = parsed["records"][0]
    assert len(record["select"]) == 4
    assert len(record["history"]) == 4
    assert len(record["triangulation"]) == 2
    classes = {
        row["feat"]: row["classification"] for row in record["history"]
    }
    assert classes[10] == "raw_short"
    assert classes[11] == "clone_pruned"
    assert classes[12] == "sufficient"
    assert record["triangulation"][1]["reject_cond"] == 1


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        ("cond=12.5", "cond=nan", "numeric"),
        ("cond_finite=1 cond=12.5", "cond_finite=0 cond=12.5", "placeholder"),
        ("mode=3d", "mode=1d", "triangulation mode"),
        ("after=2 removed=1", "after=2 removed=2", "measurement count"),
        ("origin=lost", "origin=unknown", "origin"),
        ("raw_first=2.700000000", "raw_first=2.600000000", "history range"),
        ("geometry_finite=1 max_pair_baseline=0.20", "geometry_finite=0 max_pair_baseline=0.20", "placeholder"),
    ],
)
def test_parse_trace_rejects_invalid_history_geometry(old, new, match):
    from tools.benchmark.openvins_feature_trace import parse_trace

    with pytest.raises(ValueError, match=match):
        parse_trace(_detail_log().replace(old, new, 1), require_detail=True)


def test_parse_trace_rejects_duplicate_or_missing_detail_records():
    from tools.benchmark.openvins_feature_trace import parse_trace

    text = _detail_log()
    select = next(line for line in text.splitlines() if "stage=msckf feat=10 " in line)
    with pytest.raises(ValueError, match="duplicate"):
        parse_trace(text + select + "\n", require_detail=True)
    without_history = "\n".join(
        line
        for line in text.splitlines()
        if not (line.startswith("FD_HISTORY") and "feat=10 " in line)
    )
    with pytest.raises(ValueError, match="history"):
        parse_trace(without_history + "\n", require_detail=True)
    without_tri = "\n".join(
        line
        for line in text.splitlines()
        if not (line.startswith("FD_TRI") and "stage=msckf" in line)
    )
    with pytest.raises(ValueError, match="triangulation"):
        parse_trace(without_tri + "\n", require_detail=True)


def test_parse_trace_scopes_same_feature_to_stage_and_timestamp():
    from tools.benchmark.openvins_feature_trace import parse_trace

    parsed = parse_trace(
        _detail_log("3.100000000", 0) + _detail_log("3.200000000", 0),
        require_detail=True,
    )
    assert parsed["frames"] == 2
    assert parsed["records"][0]["select"][0]["feat"] == 10
    assert parsed["records"][1]["select"][0]["feat"] == 10


def test_parse_trace_allows_preinitialization_tracker_only_frames():
    from tools.benchmark.openvins_feature_trace import parse_trace

    tracker_only = TRACK.replace("t=3.100000000", "t=0.002000000")
    parsed = parse_trace(tracker_only + "\n" + _detail_log(), require_detail=True)
    assert parsed["frames"] == 1
    assert parsed["records"][0]["track"]["t"] == "3.100000000"


def test_feature_history_geometry_patch_is_trace_only_and_preserves_rejections():
    patch = Path(
        "tools/benchmark/gpl/openvins_feature_history_geometry.patch"
    ).read_text(encoding="utf-8")
    for source in (
        "ov_core/src/feat/FeatureInitializer.cpp",
        "ov_core/src/feat/FeatureInitializer.h",
        "ov_msckf/src/core/VioManager.cpp",
        "ov_msckf/src/update/UpdaterMSCKF.cpp",
        "ov_msckf/src/update/UpdaterSLAM.cpp",
    ):
        assert f"diff --git a/{source} b/{source}" in patch
    for marker in ("FD_SELECT", "FD_HISTORY", "FD_TRI"):
        assert marker in patch
    assert "std::abs(condA) > _options.max_cond_number" in patch
    assert "p_f(2, 0) < _options.min_dist" in patch
    assert "p_f(2, 0) > _options.max_dist" in patch
    assert "std::isnan(p_f.norm())" in patch
    assert "parse_config" not in patch
    assert "initialize_with_gt" not in patch


def test_parse_trace_binds_exact_counts_and_stages():
    from tools.benchmark.openvins_feature_trace import parse_trace

    parsed = parse_trace("\n".join([TRACK, PIPE, MSCKF, SLAM_DELAY]) + "\n")
    assert parsed["frames"] == 1
    assert parsed["records"][0]["track"]["accepted"] == 41
    assert parsed["records"][0]["msckf"]["triangulation"] == 2
    assert parsed["records"][0]["pipe"]["msckf_accepted"] == 1


def test_parse_trace_accepts_fixed_openvins_log_prefixes():
    from tools.benchmark.openvins_feature_trace import parse_trace

    text = "\n".join(
        [
            f"TrackKLT.cpp:189 {TRACK}",
            f"VioManager.cpp:1095 {PIPE}",
            f"UpdaterMSCKF.cpp:221 {MSCKF}",
            f"UpdaterSLAM.cpp:251 {SLAM_DELAY}",
        ]
    )
    parsed = parse_trace(text + "\n")
    assert parsed["frames"] == 1
    assert parsed["records"][0]["track"]["accepted"] == 41


@pytest.mark.parametrize(
    "line",
    [
        MSCKF.replace("accepted=1", "accepted=2"),
        MSCKF.replace("chi2=1", "chi2=-1"),
        PIPE.replace("msckf_selected=5", "msckf_selected=4"),
        TRACK.replace("accepted=41", "accepted=42"),
        TRACK + " truth_speed=0.0",
        MSCKF.replace("input=5", "input=nan"),
    ],
)
def test_parse_trace_rejects_count_schema_and_truth_mutations(line):
    from tools.benchmark.openvins_feature_trace import parse_trace

    lines = [TRACK, PIPE, MSCKF, SLAM_DELAY]
    prefix = line.split(" ", 1)[0]
    lines[[item.split(" ", 1)[0] for item in lines].index(prefix)] = line
    with pytest.raises(ValueError):
        parse_trace("\n".join(lines) + "\n")


def test_parse_trace_rejects_duplicate_or_missing_stage():
    from tools.benchmark.openvins_feature_trace import parse_trace

    with pytest.raises(ValueError, match="duplicate"):
        parse_trace("\n".join([TRACK, PIPE, MSCKF, SLAM_DELAY, TRACK]) + "\n")
    with pytest.raises(ValueError, match="missing"):
        parse_trace("\n".join([TRACK, PIPE]) + "\n")


def test_parse_trace_binds_slam_rejection_categories():
    from tools.benchmark.openvins_feature_trace import parse_trace

    pipe = PIPE.replace("slam_update=0", "slam_update=2").replace(
        "slam_update_accepted=0", "slam_update_accepted=1"
    )
    parsed = parse_trace(
        "\n".join([TRACK, pipe, MSCKF, SLAM_DELAY, SLAM_UPDATE]) + "\n"
    )
    assert parsed["records"][0]["slam_delay"]["initialization"] == 1
    assert parsed["records"][0]["slam_update"]["chi2"] == 1


def test_parse_trace_aggregates_distinct_slam_updater_calls():
    from tools.benchmark.openvins_feature_trace import parse_trace

    pipe = (
        PIPE.replace("slam_update=0", "slam_update=3")
        .replace("slam_update_accepted=0", "slam_update_accepted=2")
    )
    second = SLAM_UPDATE.replace("input=2", "input=1").replace(
        "chi2=1 accepted=1", "chi2=0 accepted=1"
    )
    parsed = parse_trace(
        "\n".join([TRACK, pipe, MSCKF, SLAM_DELAY, SLAM_UPDATE, second]) + "\n"
    )
    assert parsed["records"][0]["slam_update"]["input"] == 3
    assert parsed["records"][0]["slam_update"]["accepted"] == 2


def test_compare_state_rows_excludes_clocks_but_binds_estimator_values():
    from tools.benchmark.openvins_feature_trace import compare_state_rows

    row = {
        "sequence": 10,
        "kind": "C",
        "sample_ns": 3_100_000_000,
        "receive_ns": 100,
        "start_ns": 110,
        "end_ns": 120,
        "acknowledged_ns": 130,
        "internal_initialized": True,
        "public_initialized": True,
        "has_moved_since_zupt": True,
        "zupt_flag_latched": False,
        "imu_state": [0.0] * 16,
        "fusion_eligible": False,
        "quality": None,
        "reset_counter": None,
    }
    candidate = copy.deepcopy(row)
    candidate.update(receive_ns=200, start_ns=220, end_ns=240, acknowledged_ns=260)
    result = compare_state_rows([row], [candidate], tolerance=1e-12)
    assert result["qualified"] is True
    candidate["imu_state"][15] = 1e-3
    with pytest.raises(ValueError, match="state mismatch"):
        compare_state_rows([row], [candidate], tolerance=1e-12)


def test_summarize_trace_preserves_all_rejection_categories():
    from tools.benchmark.openvins_feature_trace import parse_trace, summarize_trace

    parsed = parse_trace("\n".join([TRACK, PIPE, MSCKF, SLAM_DELAY]) + "\n")
    totals = summarize_trace(parsed)
    assert totals["track"]["klt_or_ransac"] == 8
    assert totals["msckf"]["insufficient"] == 1
    assert totals["slam_delay"]["initialization"] == 1


def test_audit_fixed_replay_rejects_binary_or_state_drift(tmp_path):
    from tools.benchmark.openvins_feature_trace import audit_fixed_replay

    control = tmp_path / "control"
    diagnostic = tmp_path / "diagnostic"
    control.mkdir()
    diagnostic.mkdir()
    binary = tmp_path / "probe"
    patch = tmp_path / "trace.patch"
    binary.write_bytes(b"probe-v1")
    patch.write_bytes(b"patch-v1")
    binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    common = {
        "qualified": True,
        "failure": None,
        "physical_replay": False,
        "truth_used": False,
        "fusion_eligible": False,
        "source_capture": "sealed/capture-v1",
        "source_requests_sha256": "a" * 64,
        "replayed_source_records": 3,
        "transport_accepted": 4,
        "initialized_sample_ns": 2,
        "effective_sim_ns": 3,
        "stop_sim_ns": 4,
    }
    (control / "summary.json").write_text(
        json.dumps({**common, "binary_sha256": "b" * 64}), encoding="utf-8"
    )
    (diagnostic / "summary.json").write_text(
        json.dumps({**common, "binary_sha256": binary_sha}), encoding="utf-8"
    )
    row = {"sequence": 1, "sample_ns": 2, "receive_ns": 10, "value": [1.0]}
    (control / "states.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (diagnostic / "states.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (diagnostic / "native.log").write_text(
        "\n".join([TRACK, PIPE, MSCKF, SLAM_DELAY]) + "\n", encoding="utf-8"
    )
    result = audit_fixed_replay(
        control,
        diagnostic,
        diagnostic_binary=binary,
        diagnostic_patch=patch,
        diagnostic_library_sha256="c" * 64,
    )
    assert result["qualified"] is True
    binary.write_bytes(b"probe-v2")
    with pytest.raises(ValueError, match="binary hash"):
        audit_fixed_replay(
            control,
            diagnostic,
            diagnostic_binary=binary,
            diagnostic_patch=patch,
            diagnostic_library_sha256="c" * 64,
        )


def test_audit_fixed_replay_requires_and_summarizes_geometry_detail(tmp_path):
    from tools.benchmark.openvins_feature_trace import audit_fixed_replay

    control = tmp_path / "control"
    diagnostic = tmp_path / "diagnostic"
    control.mkdir()
    diagnostic.mkdir()
    binary = tmp_path / "probe"
    patch = tmp_path / "geometry.patch"
    binary.write_bytes(b"geometry-probe-v1")
    patch.write_bytes(b"geometry-patch-v1")
    binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    common = {
        "qualified": True,
        "failure": None,
        "physical_replay": False,
        "truth_used": False,
        "fusion_eligible": False,
        "source_capture": "sealed/capture-v1",
        "source_requests_sha256": "a" * 64,
        "replayed_source_records": 3,
        "transport_accepted": 4,
        "initialized_sample_ns": 2,
        "effective_sim_ns": 3,
        "stop_sim_ns": 4,
    }
    (control / "summary.json").write_text(
        json.dumps({**common, "binary_sha256": "b" * 64}), encoding="utf-8"
    )
    (diagnostic / "summary.json").write_text(
        json.dumps({**common, "binary_sha256": binary_sha}), encoding="utf-8"
    )
    row = {"sequence": 1, "sample_ns": 2, "imu_state": [0.0] * 16}
    for directory in (control, diagnostic):
        (directory / "states.jsonl").write_text(
            json.dumps(row) + "\n", encoding="utf-8"
        )
    (diagnostic / "native.log").write_text(_detail_log(), encoding="utf-8")

    result = audit_fixed_replay(
        control,
        diagnostic,
        diagnostic_binary=binary,
        diagnostic_patch=patch,
        diagnostic_library_sha256="c" * 64,
        require_detail=True,
    )
    assert result["schema"] == "openvins-feature-history-geometry-audit-v1"
    assert result["mechanisms"]["history_classifications"]["msckf"] == {
        "clone_pruned": 1,
        "raw_short": 1,
        "sufficient": 1,
    }
    assert result["mechanisms"]["triangulation_rejections"]["slam_delay"][
        "reject_cond"
    ] == 1
    assert result["odometry_eligible"] is False
    assert result["arming_eligible"] is False
    assert result["ekf2_eligible"] is False

    summary = json.loads((diagnostic / "summary.json").read_text(encoding="utf-8"))
    summary["odometry_eligible"] = True
    (diagnostic / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="eligibility claim"):
        audit_fixed_replay(
            control,
            diagnostic,
            diagnostic_binary=binary,
            diagnostic_patch=patch,
            diagnostic_library_sha256="c" * 64,
            require_detail=True,
        )
