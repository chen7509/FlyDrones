import copy

import numpy as np
import pytest

from tools.benchmark.build_openvins_ekf2_fast_file_candidates import compose_fast_file_candidate


def camera_record():
    health = {
        "schema": "openvins-health-evidence-v1",
        "session_id": "session-a",
        "quality": 1,
        "reset_counter": 2,
        "failed_latched": False,
        "covariance_sim_domain_qualified": True,
        "fusion_eligible": False,
    }
    return {
        "timing": {"capture_sample_ns": 2_800_000_000},
        "composition": {
            "status": "candidate",
            "health": health,
            "candidate": {
                "identities": {
                    "estimator_session_id": "session-a",
                    "clock_session_id": "clock-a",
                    "publisher_session_id": "publisher-a",
                },
                "fusion_eligible": False,
            },
        },
    }


def fast_row():
    covariance = np.eye(12) * 1e-3
    return {
        "target_ns": 2_820_000_000,
        "last_camera_ns": 2_800_000_000,
        "available_imu_ns": 2_824_000_000,
        "success": True,
        "public_initialized": True,
        "state13": [0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 3.0, 0.1, -0.2, 0.3, 0.0, 0.0, 0.0],
        "covariance12": covariance.tolist(),
        "fusion_eligible": False,
        "quality": None,
        "reset_counter": None,
    }


def test_fast_file_candidate_uses_authoritative_health_and_unique_native_state():
    result = compose_fast_file_candidate(fast_row(), camera_record())
    assert result["target_ns"] == 2_820_000_000
    assert result["fields"]["time_usec"] == 2_820_000
    assert result["fields"]["quality"] == 1
    assert result["fields"]["reset_counter"] == 2
    assert result["fields"]["frame_id"] == 20 and result["fields"]["child_frame_id"] == 12
    assert len(result["fields"]["pose_covariance"]) == 21
    assert len(result["fields"]["velocity_covariance"]) == 21
    assert result["network_odometry"] is False and result["fusion_eligible"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        ("quality", 0),
        ("failed_latched", True),
        ("covariance_sim_domain_qualified", False),
        ("fusion_eligible", True),
    ],
)
def test_fast_file_candidate_rejects_nonpositive_or_unqualified_health(mutation):
    camera = camera_record()
    camera["composition"]["health"][mutation[0]] = mutation[1]
    with pytest.raises(ValueError, match="authoritative"):
        compose_fast_file_candidate(fast_row(), camera)


def test_fast_file_candidate_rejects_stale_camera_or_caller_quality():
    stale = fast_row()
    stale["target_ns"] = 2_901_000_000
    with pytest.raises(ValueError, match="timing"):
        compose_fast_file_candidate(stale, camera_record())
    spoofed = copy.deepcopy(fast_row())
    spoofed["quality"] = 1
    with pytest.raises(ValueError, match="timing"):
        compose_fast_file_candidate(spoofed, camera_record())
