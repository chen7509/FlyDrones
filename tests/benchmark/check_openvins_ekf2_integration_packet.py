"""Standalone pymavlink 2.4.49 packet check; no socket or transport."""

import copy
import json
import math
import socket
from unittest import mock

import numpy as np
from scipy.spatial.transform import Rotation

from tools.benchmark.openvins_ekf2_integration import OfflineEkf2Composer, decode_candidate, encode_candidate
from tools.benchmark.openvins_health_contract import CovarianceProfile, OpenVinsHealthContract


def camera(r_gi, sample_ns):
    return {
        "kind": "C",
        "session_id": "estimator-a",
        "sample_ns": sample_ns,
        "internal_initialized": True,
        "public_initialized": True,
        "state_time_s": sample_ns * 1e-9,
        "last_regular_update_s": (sample_ns - 100_000_000) * 1e-9,
        "imu_state16": [
            *Rotation.from_matrix(r_gi.T).as_quat(),
            1.0,
            2.0,
            3.0,
            4.0,
            -2.0,
            1.5,
            0.01,
            -0.02,
            0.03,
            -0.1,
            0.2,
            -0.3,
        ],
        "imu_covariance15": (np.eye(15) * 1e-3).tolist(),
    }


def healthy():
    return {"source_healthy": True, "native_healthy": True, "source_failure": None, "native_failure": None}


def clock(observed_remote_ns):
    return {
        "clock_session_id": "clock-a",
        "publisher_session_id": "publisher-a",
        "observed_remote_ns": observed_remote_ns,
    }


def _run_checks():
    contract = OpenVinsHealthContract(
        "estimator-a",
        reset_total=255,
        profile=CovarianceProfile(sim_domain_qualified=True),
    )
    composer = OfflineEkf2Composer(
        contract,
        clock_session_id="clock-a",
        publisher_session_id="publisher-a",
        sample_to_remote_offset_ns=1_000_000,
        max_age_ns=100_000_000,
    )
    cases = []
    for index, angles in enumerate(([0, 0, 0], [31, -22, 67], [-47, 28, -113])):
        sample_ns = 3_000_000_000 + index * 100_000_000
        r_gi = Rotation.from_euler("xyz", angles, degrees=True).as_matrix()
        result = composer.compose(camera(r_gi, sample_ns), healthy(), clock(sample_ns + 6_000_000))
        candidate = result["candidate"]
        packet = encode_candidate(candidate)
        decoded = decode_candidate(packet)
        fields = candidate["fields"]
        for name in ("time_usec", "frame_id", "child_frame_id", "reset_counter", "estimator_type", "quality"):
            assert decoded[name] == fields[name]
        for name in ("x", "y", "z", "vx", "vy", "vz"):
            np.testing.assert_allclose(decoded[name], fields[name], rtol=1e-6, atol=1e-7)
        np.testing.assert_allclose(decoded["q"], fields["q"], rtol=1e-6, atol=1e-7)
        np.testing.assert_allclose(decoded["pose_covariance"], fields["pose_covariance"], rtol=1e-6, atol=1e-7)
        for position, value in enumerate(fields["velocity_covariance"]):
            if value is None:
                assert math.isnan(decoded["velocity_covariance"][position])
            else:
                np.testing.assert_allclose(decoded["velocity_covariance"][position], value, rtol=1e-6, atol=1e-7)
        assert all(math.isnan(decoded[name]) for name in ("rollspeed", "pitchspeed", "yawspeed"))
        cases.append({"angles_deg": angles, "packet_hex": packet.hex(), "decoded": decoded})

    corruptions = [
        {"frame_id": 1},
        {"child_frame_id": 1},
        {"estimator_type": 0},
        {"quality": 0},
        {"reset_counter": True},
        {"time_usec": 0},
        {"x": float("nan")},
        {"q": [0.0, 0.0, 0.0, 0.0]},
        {"pose_covariance": [-1.0] * 21},
        {"velocity_covariance": [-1.0 if i in (0, 1, 2, 6, 7, 11) else None for i in range(21)]},
        {"pose_covariance": [True] + candidate["fields"]["pose_covariance"][1:]},
        {"velocity_covariance": [0.0] * 21},
        {"pose_covariance": [candidate["fields"]["pose_covariance"][0] + 0.001] + candidate["fields"]["pose_covariance"][1:]},
        {
            "velocity_covariance": [
                candidate["fields"]["velocity_covariance"][0] + 0.001,
                *candidate["fields"]["velocity_covariance"][1:],
            ]
        },
    ]
    rejected = 0
    for change in corruptions:
        bad = copy.deepcopy(candidate)
        bad["fields"].update(change)
        try:
            encode_candidate(bad)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError("corrupted candidate encoded: " + repr(change))
    try:
        decode_candidate(b"not-mavlink")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid packet decoded")
    for extra in (packet, b"\x00"):
        try:
            decode_candidate(packet + extra)
        except ValueError:
            pass
        else:
            raise AssertionError("multiple or trailing packet bytes decoded")
    return {
        "schema": "openvins-ekf2-integration-pymavlink-check-v1",
        "pymavlink_version": "2.4.49",
        "roundtrips": len(cases),
        "wire_corruptions_rejected": rejected,
        "socket_forbidden": True,
        "network_odometry": False,
        "fusion_eligible": False,
        "cases": cases,
    }


def run_checks():
    with mock.patch.object(socket, "socket", side_effect=AssertionError("network attempted")):
        return _run_checks()


if __name__ == "__main__":
    print(json.dumps(run_checks(), indent=2, allow_nan=True))
