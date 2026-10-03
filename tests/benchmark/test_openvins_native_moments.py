import csv
import hashlib

import numpy as np
import pytest

from tools.benchmark.audit_openvins_native_moments import audit


def fixture_files(tmp_path, *, matrices=None, times=(33.5, 33.6, 33.7),
                  state_times=None, velocity=None):
    states = tmp_path / "states.csv"
    moments = tmp_path / "moments.csv"
    if matrices is None:
        matrices = [np.eye(15) * .01 for _ in times]
    if velocity is None:
        velocity = [(0., 0., 0.) for _ in times]
    if state_times is None:
        state_times = times
    with states.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["image_ns", "initialized", "state_timestamp_s", "qx", "qy", "qz", "qw", "px", "py", "pz"])
        for time in times:
            writer.writerow([round(time * 1e9), 1, time, 0, 0, 0, 1, 0, 0, 0])
    with moments.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["image_ns", "state_timestamp_s", "vx", "vy", "vz"]
                        + [f"cov_{row}_{col}" for row in range(15) for col in range(15)])
        for time, state_time, vec, matrix in zip(times, state_times, velocity, matrices, strict=True):
            writer.writerow([round(time * 1e9), state_time, *vec, *matrix.reshape(-1)])
    return states, moments


def audit_fixture(states, moments):
    frozen_sha = hashlib.sha256(states.read_bytes()).hexdigest()
    return audit(states, moments, expected_states_sha256=frozen_sha,
                 required_event_image_ns=())


def test_audit_reads_native_order_and_matches_old_states(tmp_path):
    states, moments = fixture_files(tmp_path)
    report = audit_fixture(states, moments)
    assert report["initialized_frames"] == 3
    assert report["native_error_order"] == ["dtheta", "dposition", "dvelocity", "gyro_bias", "accel_bias"]
    assert report["position_variance_m2_range"] == [0.01, 0.01]
    assert report["velocity_variance_m2ps2_range"] == [0.01, 0.01]
    assert report["covariance_structure_valid"] is True
    assert report["px4_fusion_eligible"] is False
    assert report["truth_used"] is False


@pytest.mark.parametrize("mutation,reason", [
    ("timestamp", "timestamp"),
    ("nan_velocity", "non-finite"),
    ("asymmetric", "symmetric"),
    ("negative_eigenvalue", "positive semidefinite"),
    ("zero_position_variance", "positive"),
])
def test_audit_rejects_invalid_moments(tmp_path, mutation, reason):
    matrices = [np.eye(15) * .01 for _ in range(3)]
    state_times = None
    velocity = None
    if mutation == "timestamp":
        state_times = (33.5, 33.61, 33.7)
    elif mutation == "nan_velocity":
        velocity = [(0., 0., 0.), (float("nan"), 0., 0.), (0., 0., 0.)]
    elif mutation == "asymmetric":
        matrices[1][3, 4] = .1
    elif mutation == "negative_eigenvalue":
        matrices[1][3, 3] = -.1
    else:
        matrices[1][3, 3] = 0
    states, moments = fixture_files(tmp_path, matrices=matrices,
                                    state_times=state_times, velocity=velocity)
    with pytest.raises(ValueError, match=reason):
        audit_fixture(states, moments)


def test_audit_rejects_missing_initialized_frame(tmp_path):
    states, moments = fixture_files(tmp_path)
    lines = moments.read_text(encoding="utf-8").splitlines()
    moments.write_text("\n".join([lines[0], lines[1], lines[3]]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frame count"):
        audit_fixture(states, moments)


def test_audit_rejects_invalid_state_flag_even_when_moments_match(tmp_path):
    states, moments = fixture_files(tmp_path)
    lines = states.read_text(encoding="utf-8").splitlines()
    lines.insert(1, "33400000000,2,-1,,,,,,,")
    states.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="initialization flag"):
        audit_fixture(states, moments)


@pytest.mark.parametrize("corruption", ["duplicate_header", "extra_cell"])
def test_audit_rejects_broken_moments_csv_width(tmp_path, corruption):
    states, moments = fixture_files(tmp_path)
    lines = moments.read_text(encoding="utf-8").splitlines()
    if corruption == "duplicate_header":
        lines[0] += ",vx"
        lines[1:] = [line + ",0" for line in lines[1:]]
    else:
        lines[2] += ",0"
    moments.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns|malformed"):
        audit_fixture(states, moments)


def test_audit_rejects_changed_pose_with_same_timestamps(tmp_path):
    states, moments = fixture_files(tmp_path)
    frozen_sha = hashlib.sha256(states.read_bytes()).hexdigest()
    lines = states.read_text(encoding="utf-8").splitlines()
    cells = lines[2].split(",")
    cells[7] = "9"
    lines[2] = ",".join(cells)
    states.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen baseline"):
        audit(states, moments, expected_states_sha256=frozen_sha,
              required_event_image_ns=())


def test_audit_requires_all_declared_anomaly_frames(tmp_path):
    states, moments = fixture_files(tmp_path)
    frozen_sha = hashlib.sha256(states.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="required anomaly"):
        audit(states, moments, expected_states_sha256=frozen_sha,
              required_event_image_ns=(46_100_000_000,))


def test_audit_rejects_small_negative_covariance_eigenvalue(tmp_path):
    matrices = [np.eye(15) * .01 for _ in range(3)]
    matrices[1][0, 0] = -1e-9
    states, moments = fixture_files(tmp_path, matrices=matrices)
    with pytest.raises(ValueError, match="positive semidefinite"):
        audit_fixture(states, moments)
