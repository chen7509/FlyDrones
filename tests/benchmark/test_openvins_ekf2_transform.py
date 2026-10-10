import importlib.util

import numpy as np
import pytest
from scipy.spatial.transform import Rotation


def api():
    assert importlib.util.find_spec("tools.benchmark.openvins_ekf2_transform"), "EKF2 transform is not implemented"
    from tools.benchmark import openvins_ekf2_transform

    return openvins_ekf2_transform


S = np.diag([1.0, -1.0, -1.0])


def native_state(r_gi=None, *, position=(1.0, 2.0, 3.0), velocity=(4.0, -2.0, 1.5)):
    r_gi = Rotation.from_euler("xyz", [31.0, -22.0, 67.0], degrees=True).as_matrix() if r_gi is None else r_gi
    # OpenVINS stores JPL q_GtoI; scipy interprets the same coefficients as
    # Hamilton and therefore returns R_GI.T.
    q_jpl_xyzw = Rotation.from_matrix(r_gi.T).as_quat()
    return np.r_[q_jpl_xyzw, position, velocity, [0.01, -0.02, 0.03], [-0.1, 0.2, -0.3]]


def spd15(seed=1509):
    rng = np.random.default_rng(seed)
    factors = rng.normal(size=(15, 15))
    return factors @ factors.T * 1e-3 + np.eye(15) * 1e-4


def skew(value):
    x, y, z = value
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])


@pytest.mark.parametrize(
    "angles",
    ([0.0, 0.0, 0.0], [0.0, 0.0, 90.0], [90.0, 0.0, 0.0], [31.0, -22.0, 67.0], [-47.0, 28.0, -113.0]),
)
def test_analytic_jpl_to_hamilton_geometry_and_quaternion_sign(angles):
    r_gi = Rotation.from_euler("xyz", angles, degrees=True).as_matrix()
    state = native_state(r_gi)
    result = api().convert_imu15(state, spd15())

    np.testing.assert_allclose(result["position_local_frd"], [1.0, -2.0, -3.0], atol=1e-12)
    np.testing.assert_allclose(result["velocity_body_frd"], r_gi @ state[7:10], atol=1e-12)
    q_wxyz = result["q_body_to_local_frd_wxyz"]
    assert q_wxyz[0] > 0 or next(value for value in q_wxyz[1:] if value != 0) > 0
    np.testing.assert_allclose(
        Rotation.from_quat([*q_wxyz[1:], q_wxyz[0]]).as_matrix(), S @ r_gi.T, atol=1e-12
    )

    state[:4] *= -1
    np.testing.assert_allclose(api().convert_imu15(state, spd15())["q_body_to_local_frd_wxyz"], q_wxyz)


def test_finite_difference_9_by_15_jacobian_including_velocity_skew_sign():
    r_gi = Rotation.from_euler("xyz", [38.0, -27.0, 71.0], degrees=True).as_matrix()
    state = native_state(r_gi, velocity=(4.5, -3.25, 2.0))
    result = api().convert_imu15(state, spd15())
    numeric = np.zeros((9, 15))
    epsilon = 1e-7
    base_r_bl = S @ r_gi.T
    base_position = S @ state[4:7]
    base_velocity = r_gi @ state[7:10]

    for column in range(15):
        delta = np.eye(15)[column] * epsilon
        perturbed_r_gi = Rotation.from_rotvec(-delta[:3]).as_matrix() @ r_gi
        perturbed_position = S @ (state[4:7] + delta[3:6])
        perturbed_velocity = perturbed_r_gi @ (state[7:10] + delta[6:9])
        perturbed_r_bl = S @ perturbed_r_gi.T
        output_delta = np.r_[
            perturbed_position - base_position,
            Rotation.from_matrix(base_r_bl.T @ perturbed_r_bl).as_rotvec(),
            perturbed_velocity - base_velocity,
        ]
        numeric[:, column] = output_delta / epsilon

    analytic = np.asarray(result["jacobian9x15"])
    np.testing.assert_allclose(analytic, numeric, atol=5e-7)
    np.testing.assert_allclose(analytic[6:9, :3], skew(base_velocity), atol=1e-12)
    np.testing.assert_allclose(analytic[:, 9:15], 0.0, atol=0.0)


def test_full_cross_covariance_is_preserved_and_px4_diagonals_are_exact():
    state = native_state()
    covariance = spd15(1701)
    result = api().convert_imu15(state, covariance)
    jacobian = np.asarray(result["jacobian9x15"])
    transformed = np.asarray(result["covariance9x9"])
    np.testing.assert_allclose(transformed, jacobian @ covariance @ jacobian.T, atol=1e-12)
    assert np.count_nonzero(np.abs(transformed - np.diag(np.diag(transformed))) > 1e-12) > 20
    np.testing.assert_allclose(result["position_variance"], np.diag(transformed)[0:3])
    np.testing.assert_allclose(result["attitude_variance_body_tangent"], np.diag(transformed)[3:6])
    np.testing.assert_allclose(result["velocity_variance_body"], np.diag(transformed)[6:9])


def test_new_global_velocity_covariance_is_not_the_old_body_velocity_contract():
    r_gi = Rotation.from_euler("xyz", [27.0, 19.0, -63.0], degrees=True).as_matrix()
    state = native_state(r_gi, velocity=(8.0, -3.0, 2.0))
    covariance = np.eye(15) * 1e-3
    covariance[:3, :3] = np.diag([0.03, 0.02, 0.01])
    result = api().convert_imu15(state, covariance)
    transformed = np.asarray(result["covariance9x9"])

    # The old 12x12 fast-state contract already held velocity in the body frame
    # and used an identity velocity block. The new global velocity must couple
    # attitude uncertainty into BODY_FRD velocity.
    old_identity_velocity = covariance[6:9, 6:9]
    assert not np.allclose(transformed[6:9, 6:9], old_identity_velocity)
    assert np.linalg.norm(transformed[6:9, 3:6]) > 1e-4


@pytest.mark.parametrize(
    "mutator",
    [
        lambda state, covariance: (state[:15], covariance),
        lambda state, covariance: (state, covariance[:14]),
        lambda state, covariance: (np.where(np.arange(16) == 5, np.nan, state), covariance),
        lambda state, covariance: (state, np.where(np.eye(15, dtype=bool), np.inf, covariance)),
        lambda state, covariance: (np.r_[state[:4] * 1.01, state[4:]], covariance),
        lambda state, covariance: (state, covariance + np.triu(np.ones((15, 15)), 1) * 0.1),
        lambda state, covariance: (state, covariance - np.eye(15) * (np.linalg.eigvalsh(covariance)[0] + 0.1)),
        lambda state, covariance: ([True] * 16, covariance),
        lambda state, covariance: (np.where(np.arange(16) == 4, 1e40, state), covariance),
        lambda state, covariance: (np.where((np.arange(16) >= 7) & (np.arange(16) < 10), 1e20, state), np.eye(15)),
    ],
)
def test_invalid_or_float32_unrepresentable_inputs_fail_closed(mutator):
    state, covariance = mutator(native_state(), spd15())
    with pytest.raises(ValueError):
        api().convert_imu15(state, covariance)


def test_profile_is_exact_and_outputs_are_float32_representable():
    state = native_state(position=(1e18, -2e18, 3e18), velocity=(4e18, -5e18, 6e18))
    result = api().convert_imu15(state, spd15())
    for key in (
        "position_local_frd",
        "q_body_to_local_frd_wxyz",
        "velocity_body_frd",
        "covariance9x9",
    ):
        assert np.max(np.abs(np.asarray(result[key], dtype=float))) <= np.finfo(np.float32).max
    with pytest.raises(ValueError):
        api().convert_imu15(state, spd15(), profile="generic-or-unpinned")
