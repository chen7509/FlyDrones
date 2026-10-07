import copy
import importlib.util
import inspect
import socket

import numpy as np
import pytest

from tools.benchmark.openvins_health_contract import CovarianceProfile, OpenVinsHealthContract


def api():
    assert importlib.util.find_spec("tools.benchmark.openvins_ekf2_integration"), "integration contract is not implemented"
    from tools.benchmark import openvins_ekf2_integration

    return openvins_ekf2_integration


def health(*, session="estimator-a", reset_total=0, qualified=True):
    return OpenVinsHealthContract(
        session,
        reset_total=reset_total,
        profile=CovarianceProfile(sim_domain_qualified=qualified),
    )


def camera(sample_ns=3_000_000_000, *, session="estimator-a", public=True, regular_age_ns=100_000_000):
    covariance = np.eye(15) * 1e-3
    return {
        "kind": "C",
        "session_id": session,
        "sample_ns": sample_ns,
        "internal_initialized": True,
        "public_initialized": public,
        "state_time_s": sample_ns * 1e-9,
        "last_regular_update_s": (sample_ns - regular_age_ns) * 1e-9,
        "imu_state16": [0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 3.0, 4.0, -2.0, 1.5, 0.01, -0.02, 0.03, -0.1, 0.2, -0.3],
        "imu_covariance15": covariance.tolist(),
    }


def source_health(**changes):
    result = {
        "source_healthy": True,
        "native_healthy": True,
        "source_failure": None,
        "native_failure": None,
    }
    result.update(changes)
    return result


def clock(observed_ns=3_006_000_000, **changes):
    result = {
        "clock_session_id": "clock-a",
        "publisher_session_id": "publisher-a",
        "observed_remote_ns": observed_ns,
    }
    result.update(changes)
    return result


def composer(contract=None, *, sink=None, max_age_ns=100_000_000):
    return api().OfflineEkf2Composer(
        contract if contract is not None else health(),
        clock_session_id="clock-a",
        publisher_session_id="publisher-a",
        sample_to_remote_offset_ns=1_000_000,
        max_age_ns=max_age_ns,
        sink=sink,
    )


def test_positive_health_is_composed_once_without_override_arguments():
    compose_signature = inspect.signature(api().OfflineEkf2Composer.compose)
    for forbidden in ("quality", "reset_total", "reset_counter", "covariance_profile"):
        assert forbidden not in compose_signature.parameters

    result = composer().compose(camera(), source_health(), clock())
    assert result["status"] == "candidate" and result["refusal"] is None
    assert result["candidate"]["fields"]["quality"] == 1
    assert result["candidate"]["fields"]["reset_counter"] == 0
    assert result["candidate"]["health"]["reset_total"] == 0
    assert result["candidate"]["health"]["covariance_profile"] == "px4-d6f12ad-gate-floor-v1"
    assert result["candidate"]["identities"] == {
        "estimator_session_id": "estimator-a",
        "clock_session_id": "clock-a",
        "publisher_session_id": "publisher-a",
    }
    assert result["candidate"]["fields"]["time_usec"] == 3_001_000
    assert result["candidate"]["fields"]["frame_id"] == 20
    assert result["candidate"]["fields"]["child_frame_id"] == 12
    assert result["candidate"]["fields"]["estimator_type"] == 3
    assert not result["fusion_eligible"] and not result["candidate"]["fusion_eligible"]


def test_full_covariance_and_upper_triangle_indices_are_exact():
    candidate = composer().compose(camera(), source_health(), clock())["candidate"]
    full = np.asarray(candidate["covariance9x9"])
    pose = candidate["fields"]["pose_covariance"]
    velocity = candidate["fields"]["velocity_covariance"]
    np.testing.assert_allclose(pose, full[:6, :6][np.triu_indices(6)])
    assert [velocity[index] for index in (0, 6, 11)] == pytest.approx(np.diag(full)[6:9])
    assert all(velocity[index] is None for index in range(21) if index not in (0, 1, 2, 6, 7, 11))
    assert candidate["fields"]["rollspeed"] is None
    assert candidate["fields"]["pitchspeed"] is None
    assert candidate["fields"]["yawspeed"] is None


@pytest.mark.parametrize(
    ("contract", "row_change", "health_change", "expected"),
    [
        (health(qualified=False), {}, {}, "covariance_profile_unqualified"),
        (health(), {"public_initialized": False}, {}, "public_unavailable"),
        (health(), {"regular_age_ns": 200_000_001}, {}, "regular_update_stale"),
        (health(), {}, {"source_healthy": False, "source_failure": "lost"}, "source_failure"),
        (health(), {}, {"native_healthy": False, "native_failure": "dead"}, "native_failure"),
    ],
)
def test_nonpositive_health_never_produces_candidate(contract, row_change, health_change, expected):
    row = camera(public=row_change.get("public_initialized", True), regular_age_ns=row_change.get("regular_age_ns", 100_000_000))
    result = composer(contract).compose(row, source_health(**health_change), clock())
    assert result["status"] == "refused" and result["candidate"] is None
    assert expected in result["refusal"]["reasons"]
    assert result["health"]["quality"] in (-1, 0)
    assert not result["fusion_eligible"]


@pytest.mark.parametrize("field", ["quality", "reset_total", "reset_counter", "covariance_profile", "session_id_override"])
def test_caller_override_fields_are_rejected_and_latched(field):
    row = camera()
    row[field] = 100
    first = composer().compose(row, source_health(), clock())
    assert first["status"] == "refused" and first["refusal"]["latched"]
    assert first["refusal"]["reason"] == "camera_record_invalid"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda row: row.update(imu_covariance15=[[0.0] * 15 for _ in range(14)]), "covariance_invalid"),
        (lambda row: row["imu_covariance15"][0].__setitem__(0, -1.0), "covariance_invalid"),
        (lambda row: row["imu_state16"].__setitem__(4, float("nan")), "transform_invalid"),
    ],
)
def test_invalid_covariance_or_state_is_refused_before_candidate(mutation, reason):
    row = camera()
    mutation(row)
    result = composer().compose(row, source_health(), clock())
    assert result["candidate"] is None and result["refusal"]["reason"] == reason
    assert result["refusal"]["latched"]


@pytest.mark.parametrize(
    ("clock_change", "reason"),
    [
        ({"clock_session_id": "old-clock"}, "clock_session_mismatch"),
        ({"publisher_session_id": "other-publisher"}, "publisher_session_mismatch"),
        ({"observed_ns": 3_101_000_001}, "sample_too_old"),
    ],
)
def test_clock_identity_publisher_identity_and_delay_fail_closed(clock_change, reason):
    observed = clock_change.pop("observed_ns", 3_006_000_000)
    result = composer().compose(camera(), source_health(), clock(observed, **clock_change))
    assert result["candidate"] is None and result["refusal"]["reason"] == reason
    assert result["refusal"]["latched"]


@pytest.mark.parametrize("second_sample", [3_000_000_000, 2_900_000_000])
def test_duplicate_and_reordered_samples_latch_after_first_candidate(second_sample):
    instance = composer()
    assert instance.compose(camera(), source_health(), clock())["status"] == "candidate"
    rejected = instance.compose(camera(second_sample), source_health(), clock(3_007_000_000))
    assert rejected["refusal"]["reason"] == "sample_time_regressed"
    assert rejected["refusal"]["latched"]
    later = instance.compose(camera(3_100_000_000), source_health(), clock(3_106_000_000))
    assert later["candidate"] is None and later["refusal"]["latched"]


def test_estimator_replacement_is_the_only_reset_authority_and_wraps_wire_counter():
    instance = composer(health(reset_total=255))
    first = instance.compose(camera(), source_health(), clock())
    assert first["candidate"]["fields"]["reset_counter"] == 255
    transition = instance.replace_estimator("estimator-b")
    assert transition["reset_total"] == 256 and transition["reset_counter"] == 0
    second = instance.compose(camera(3_100_000_000, session="estimator-b"), source_health(), clock(3_106_000_000))
    assert second["candidate"]["fields"]["reset_counter"] == 0
    old = instance.compose(camera(3_200_000_000, session="estimator-a"), source_health(), clock(3_206_000_000))
    assert old["candidate"] is None and old["refusal"]["reason"] == "estimator_session_mismatch"


class RecordingSink:
    def __init__(self, *, fail_write=False, fail_close=False):
        self.records = []
        self.fail_write = fail_write
        self.fail_close = fail_close

    def write(self, record):
        if self.fail_write:
            raise OSError("write failed")
        self.records.append(copy.deepcopy(record))

    def close(self):
        if self.fail_close:
            raise OSError("close failed")


def test_journal_write_and_close_faults_are_returned_as_structured_refusals():
    write = composer(sink=RecordingSink(fail_write=True))
    write_result = write.compose(camera(), source_health(), clock())
    assert write_result["candidate"] is None and write_result["refusal"]["reason"] == "journal_write_failed"
    assert write_result["refusal"]["latched"]

    close = composer(sink=RecordingSink(fail_close=True))
    assert close.compose(camera(), source_health(), clock())["status"] == "candidate"
    close_result = close.finish()
    assert close_result["status"] == "refused" and close_result["refusal"]["reason"] == "journal_close_failed"


def test_journal_retains_candidate_and_nonfatal_and_latched_refusals():
    unknown_sink = RecordingSink()
    unknown = composer(health(qualified=False), sink=unknown_sink)
    refusal = unknown.compose(camera(), source_health(), clock())
    assert unknown_sink.records == [refusal]
    assert refusal["refusal"]["latched"] is False

    failure_sink = RecordingSink()
    failure = composer(sink=failure_sink)
    lost = failure.compose(camera(), source_health(source_healthy=False, source_failure="lost"), clock())
    assert failure_sink.records == [lost]
    assert lost["refusal"]["latched"] is True

    candidate_sink = RecordingSink()
    success = composer(sink=candidate_sink)
    candidate = success.compose(camera(), source_health(), clock())
    assert candidate_sink.records == [candidate]


def test_composition_never_opens_a_socket(monkeypatch):
    def forbidden_socket(*_args, **_kwargs):
        raise AssertionError("network transport attempted")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    assert composer().compose(camera(), source_health(), clock())["status"] == "candidate"
