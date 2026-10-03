import csv
from pathlib import Path

import pytest

from tools.benchmark.audit_vio_fusion_readiness import audit, main

HEADER = ["image_ns", "initialized", "state_timestamp_s", "qx", "qy", "qz", "qw", "px", "py", "pz"]


def write_states(path: Path, *, positions=(0.0, 0.04, 0.08, 0.56, 1.12),
                 timestamps=None, bad_quaternion=False):
    times = timestamps or [33.5 + 0.1 * i for i in range(len(positions))]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADER)
        for i, (time, x) in enumerate(zip(times, positions, strict=True)):
            writer.writerow([round(time * 1e9), 1, time, 0, 0, 0,
                             0.5 if bad_quaternion and i == 2 else 1,
                             x, 0, 0])


def test_audit_locates_both_consecutive_spikes_and_rejects_fusion(tmp_path):
    states = tmp_path / "states.csv"
    write_states(states)
    result = audit(states, speed_limit_mps=0.8)
    assert result["total_image_frames"] == 5
    assert result["initialized_frames"] == 5
    assert result["speed_screen_threshold_mps"] == 1.6
    assert [(item["from_image_ns"], item["to_image_ns"])
            for item in result["speed_screen_events"]] == [
                (33700000000, 33800000000), (33800000000, 33900000000)]
    assert all(item["apparent_speed_mps"] > 1.6 for item in result["speed_screen_events"])
    assert "pose_covariance" in result["missing_fusion_fields"]
    assert "arrival_time_ns" in result["missing_fusion_fields"]
    assert result["eligible_for_px4_fusion"] is False
    assert result["truth_used"] is False


@pytest.mark.parametrize("timestamps,bad_quaternion,reason", [
    ([33.5, 33.6, 33.59, 33.8, 33.9], False, "nonmonotonic"),
    (None, True, "quaternion"),
])
def test_audit_rejects_corrupt_state(tmp_path, timestamps, bad_quaternion, reason):
    states = tmp_path / "states.csv"
    write_states(states, timestamps=timestamps, bad_quaternion=bad_quaternion)
    with pytest.raises(ValueError, match=reason):
        audit(states, speed_limit_mps=0.8)


def test_audit_rejects_nonfinite_and_missing_state(tmp_path):
    states = tmp_path / "states.csv"
    write_states(states, positions=(0.0, float("nan"), 0.08, 0.56, 1.12))
    with pytest.raises(ValueError, match="non-finite"):
        audit(states, speed_limit_mps=0.8)
    states.write_text("image_ns,initialized\n1,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns"):
        audit(states, speed_limit_mps=0.8)


@pytest.mark.parametrize("corruption", [
    "duplicate_header", "extra_cell", "uninitialized_nan", "uninitialized_pose",
])
def test_audit_rejects_malformed_csv_records(tmp_path, corruption):
    states = tmp_path / "states.csv"
    write_states(states)
    lines = states.read_text(encoding="utf-8").splitlines()
    if corruption == "duplicate_header":
        lines[0] += ",px"
        lines[1:] = [line + ",999" for line in lines[1:]]
    elif corruption == "extra_cell":
        lines[2] += ",999"
    elif corruption == "uninitialized_nan":
        lines[1] = "33500000000,0,nan,,,,,,,"
    else:
        lines[1] = "33500000000,0,-1,0,0,0,1,0,0,0"
    states.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns|unexpected|uninitialized"):
        audit(states, speed_limit_mps=0.8)


def test_audit_rejects_arithmetic_overflow(tmp_path):
    states = tmp_path / "states.csv"
    write_states(states, positions=(0.0, 1e308, -1e308, 0.0, 0.1))
    with pytest.raises(ValueError, match="non-finite|overflow"):
        audit(states, speed_limit_mps=0.8)
    write_states(states)
    with pytest.raises(ValueError, match="non-finite|overflow"):
        audit(states, speed_limit_mps=1e308)


def test_audit_accepts_uninitialized_older_finite_timestamp(tmp_path):
    states = tmp_path / "states.csv"
    write_states(states, positions=(0, .01, .02, .03, .04))
    lines = states.read_text(encoding="utf-8").splitlines()
    lines.insert(1, "33400000000,0,30.004,,,,,,,")
    states.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = audit(states, speed_limit_mps=0.8)
    assert result["total_image_frames"] == 6
    assert result["initialized_frames"] == 5


def test_audit_rejects_bad_limit_and_cli_refuses_overwrite(tmp_path, monkeypatch):
    states = tmp_path / "states.csv"
    output = tmp_path / "audit.json"
    write_states(states, positions=(0, .01, .02, .03, .04))
    with pytest.raises(ValueError, match="speed limit"):
        audit(states, speed_limit_mps=0)
    monkeypatch.setattr("sys.argv", ["audit", "--states", str(states),
                                      "--speed-limit-mps", "0.8", "--output", str(output)])
    assert main() == 0
    before = output.read_bytes()
    with pytest.raises(FileExistsError, match="overwrite"):
        main()
    assert output.read_bytes() == before
