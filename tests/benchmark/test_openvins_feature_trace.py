import copy
import hashlib
import json

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
