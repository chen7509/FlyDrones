import copy
import importlib.util

import numpy as np
import pytest
from scipy.spatial.transform import Rotation


def api():
    assert importlib.util.find_spec("tools.benchmark.openvins_odometry_contract"), "odometry contract is not implemented"
    from tools.benchmark import openvins_odometry_contract

    return openvins_odometry_contract


S = np.diag([1.0, -1.0, -1.0])


def native(rotation=None):
    rotation = np.eye(3) if rotation is None else rotation
    # Hamilton matrix equals transpose of JPL matrix: native Hamilton interpretation is S R_BL.
    q = Rotation.from_matrix(S @ rotation).as_quat()
    return np.r_[q, [1, 2, 3], [4, 5, 6], [0.1, 0.2, 0.3]], np.eye(12)


def row():
    x, p = native()
    return dict(
        target_ns=2_000_000_000,
        success=True,
        internal_initialized=True,
        public_initialized=False,
        state13=x.tolist(),
        covariance12=p.tolist(),
    )


def metadata(**changes):
    result = dict(session_id="test-session", clock_id="test-clock", observed_ns=2_004_000_000, reset_total=255, quality=0)
    result.update(changes)
    return result


def recorder():
    return api().ShadowSession("test-session", "test-clock", wire_offset_ns=1_000_000, max_age_ns=100_000_000)


@pytest.mark.parametrize("angles", [[0, 0, 0], [0, 0, 90], [90, 0, 0], [25, -30, 73], [-40, 20, -115]])
def test_analytic_pose_and_body_vectors(angles):
    rotation = Rotation.from_euler("xyz", angles, degrees=True).as_matrix()
    x, p = native(rotation)
    g = api().convert_native(x, p)
    q = g["q_wxyz"]
    np.testing.assert_allclose(Rotation.from_quat([*q[1:], q[0]]).as_matrix(), rotation, atol=1e-12)
    np.testing.assert_allclose(g["position"], [1, -2, -3])
    np.testing.assert_allclose(g["velocity_body"], [4, 5, 6])
    np.testing.assert_allclose(g["angular_velocity_body"], [0.1, 0.2, 0.3])
    x[:4] *= -1
    np.testing.assert_allclose(api().convert_native(x, p)["q_wxyz"], q)


def test_finite_difference_body_tangent_jacobian_and_cross_covariance():
    rotation = Rotation.from_euler("xyz", [0.4, -0.6, 0.8]).as_matrix()
    x, _ = native(rotation)
    rng = np.random.default_rng(492)
    a = rng.normal(size=(12, 12))
    p = a @ a.T * 0.01
    jac = np.zeros((12, 12))
    eps = 1e-6
    for k in range(12):
        dx = np.eye(12)[k] * eps
        # Actual JPL left update: R_GI' = Exp(-dtheta) R_GI.
        r_gi = rotation.T @ S
        perturbed = Rotation.from_rotvec(-dx[:3]).as_matrix() @ r_gi
        r_bl = S @ perturbed.T
        delta = np.r_[S @ dx[3:6], Rotation.from_matrix(rotation.T @ r_bl).as_rotvec(), dx[6:]]
        jac[:, k] = delta / eps
    g = api().convert_native(x, p)
    np.testing.assert_allclose(g["covariance12"], jac @ p @ jac.T, atol=1e-9)
    full = np.asarray(g["covariance12"])
    np.testing.assert_allclose(g["pose_covariance"], full[:6, :6][np.triu_indices(6)])
    np.testing.assert_allclose(g["velocity_covariance"], full[6:, 6:][np.triu_indices(6)])
    assert abs(full[0, 3]) > 1e-4  # cross term is preserved, not just diagonal copying
    roll, pitch, _ = Rotation.from_matrix(rotation).as_euler("xyz")
    euler_jac = np.array(
        [
            [1, np.sin(roll) * np.tan(pitch), np.cos(roll) * np.tan(pitch)],
            [0, np.cos(roll), -np.sin(roll)],
            [0, np.sin(roll) / np.cos(pitch), np.cos(roll) / np.cos(pitch)],
        ]
    )
    assert not np.allclose(np.diag(p[:3, :3]), np.diag(euler_jac @ p[:3, :3] @ euler_jac.T))


@pytest.mark.parametrize("bad", ["nan", "inf", "norm", "shape", "negative", "asymmetric", "overflow", "bool"])
def test_bad_native_values_fail_closed(bad):
    x, p = native()
    if bad == "nan":
        x[5] = np.nan
    if bad == "inf":
        p[0, 0] = np.inf
    if bad == "norm":
        x[:4] *= 1.001
    if bad == "shape":
        p = p[:11]
    if bad == "negative":
        p[0, 0] = -0.1
    if bad == "asymmetric":
        p[1, 3] = 1
    if bad == "overflow":
        x[4] = 1e40
    if bad == "bool":
        x = [True] * 13
    with pytest.raises(ValueError):
        api().convert_native(x, p)


def test_explicit_profile_only():
    x, p = native()
    with pytest.raises(ValueError):
        api().convert_native(x, p, profile="generic-euler")


def test_unknown_and_failed_quality_never_grants_fusion():
    for quality, reason in [(0, "quality_unknown"), (-1, "quality_failed"), (80, None)]:
        r = recorder().accept(row(), **metadata(quality=quality))
        assert r["fields"]["quality"] == quality
        assert r["fields"]["time_usec"] == 2_001_000
        assert not r["eligible_for_px4_fusion"]
        assert "public_not_initialized" in r["reasons"]
        if reason:
            assert reason in r["reasons"]
        assert "offline_only" in r["reasons"]
        assert "covariance_uncalibrated" in r["reasons"]


@pytest.mark.parametrize(
    "change",
    [
        dict(session_id="other"),
        dict(clock_id="other"),
        dict(reset_total=None),
        dict(reset_total=True),
        dict(reset_total=-1),
        dict(quality=None),
        dict(quality=101),
        dict(quality=True),
        dict(quality=-2),
        dict(observed_ns=1_999_999_999),
        dict(observed_ns=2_100_000_001),
    ],
)
def test_bad_metadata_rejected_without_consuming_sample(change):
    s = recorder()
    with pytest.raises(ValueError):
        s.accept(row(), **metadata(**change))
    assert s.accept(row(), **metadata())["fields"]["time_usec"] == 2_001_000


def test_reset_wrap_and_clock_rejections():
    s = recorder()
    assert s.accept(row(), **metadata())["fields"]["reset_counter"] == 255
    with pytest.raises(ValueError):
        s.accept(row(), **metadata())
    r = row()
    r["target_ns"] += 20_000_000
    m = metadata(observed_ns=2_024_000_000, reset_total=256)
    for reset in [254, 258]:
        with pytest.raises(ValueError):
            s.accept(r, **{**m, "reset_total": reset})
    assert s.accept(r, **m)["fields"]["reset_counter"] == 0
    r["target_ns"] += 1  # fresh ns cannot fabricate a fresh microsecond message
    with pytest.raises(ValueError):
        s.accept(r, **m)


@pytest.mark.parametrize(
    "change",
    [
        dict(success=False),
        dict(success=1),
        dict(public_initialized=1),
        dict(internal_initialized=False),
        dict(target_ns=True),
        dict(target_ns=2**80),
    ],
)
def test_bad_prediction_rejected(change):
    r = copy.deepcopy(row())
    r.update(change)
    with pytest.raises(ValueError):
        recorder().accept(r, **metadata())


@pytest.mark.parametrize(
    "args", [("", "clock", 0, 1), ("session", "", 0, 1), ("session", "clock", True, 1), ("session", "clock", 0, 0)]
)
def test_invalid_session_parameters(args):
    with pytest.raises(ValueError):
        api().ShadowSession(args[0], args[1], wire_offset_ns=args[2], max_age_ns=args[3])


def test_frozen_records_keep_unavailable_and_all_health_gaps():
    rows = [row(), {**row(), "success": False, "internal_initialized": False, "state13": None, "covariance12": None}]
    result = api().convert_frozen_records(rows)
    assert len(result) == 2 and result[0]["geometry"] is not None and result[1]["geometry"] is None
    assert "propagation_unavailable" in result[1]["reasons"]
    for r in result:
        assert not r["eligible_for_px4_fusion"] and r["wire_packet"] is None
        assert "live_clock_and_arrival_missing" in r["reasons"]
        assert "reset_evidence_missing" in r["reasons"] and "quality_evidence_missing" in r["reasons"]
