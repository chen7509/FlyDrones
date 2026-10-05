import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from tools.benchmark.supported_vio_metrics import FixedGauge


def test_real_producer_state16_schema():
    # Pinned producer appends three gyro and three acceleration biases.
    actual = state()
    assert len(actual) == 16
    gauge = FixedGauge(actual, truth())
    assert gauge.compare(actual, truth())["position_error_m"] == 0


def test_nonfinite_bias_is_not_silently_discarded():
    actual = state()
    actual[-1] = float("nan")
    with pytest.raises(ValueError):
        FixedGauge(actual, truth())


def test_noncommuting_nonidentity_origin_direction():
    rn = Rotation.from_euler("xyz", [20, 30, 40], degrees=True)
    a = Rotation.from_euler("xyz", [-10, 15, 75], degrees=True)
    rt = a * rn
    flu_frd = Rotation.from_euler("x", 180, degrees=True)
    origin = truth(q=(rt * flu_frd).as_quat(), p=[5, 6, 7])
    gauge = FixedGauge(state(q=rn.as_quat(), p=[1, 2, 3]), origin)
    next_r = rn * Rotation.from_euler("y", 23, degrees=True)
    delta, velocity = np.array([0.2, -0.1, 0.4]), np.array([0.3, 0.4, -0.2])
    row = gauge.compare(
        state(q=next_r.as_quat(), p=np.array([1, 2, 3]) + delta, v=velocity),
        truth(q=(a * next_r * flu_frd).as_quat(), p=np.array([5, 6, 7]) + a.apply(delta), v=a.apply(velocity)),
    )
    assert max(row[k] for k in ["position_error_m", "velocity_error_m_s", "attitude_error_deg"]) < 1e-10


def state(q=None, p=None, v=None):
    return np.r_[
        q if q is not None else [0, 0, 0, 1], p if p is not None else [0, 0, 0], v if v is not None else [0, 0, 0], np.zeros(6)
    ]


def truth(q=None, p=None, v=None):
    return dict(
        quaternion_xyzw=q if q is not None else [1, 0, 0, 0],
        position=p if p is not None else [0, 0, 0],
        velocity_world=v if v is not None else [0, 0, 0],
    )


def test_yaw_gauge_and_global_velocity():
    q = Rotation.from_euler("z", 90, degrees=True)
    ref = truth(q=(q * Rotation.from_euler("x", 180, degrees=True)).as_quat(), p=[3, 2, 1])
    gauge = FixedGauge(state(), ref)
    actual = truth(q=ref["quaternion_xyzw"], p=[3, 3, 1], v=[0, 2, 0])
    row = gauge.compare(state(p=[1, 0, 0], v=[2, 0, 0]), actual)
    assert row["position_error_m"] < 1e-12
    assert row["velocity_error_m_s"] < 1e-12
    assert row["attitude_error_deg"] < 1e-12


def test_drift_and_attitude_are_not_realigned():
    gauge = FixedGauge(state(), truth())
    row = gauge.compare(
        state(q=Rotation.from_euler("y", 20, degrees=True).as_quat(), p=[3, 0, 0], v=[2, 0, 0]), truth(p=[1, 0, 0])
    )
    assert row["position_error_m"] == pytest.approx(2)
    assert row["displacement_error_lower_bound_m"] == pytest.approx(2)
    assert row["velocity_error_m_s"] == pytest.approx(2)
    assert row["attitude_error_deg"] == pytest.approx(20)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1e300, True])
def test_invalid_state_refused(value):
    bad = list(state())
    bad[4] = value
    with pytest.raises(ValueError):
        FixedGauge(bad, truth())


def test_invalid_quaternion_refused():
    with pytest.raises(ValueError):
        FixedGauge(state(q=[0, 0, 0, 2]), truth())


def test_truth_nonfinite_refused():
    with pytest.raises(ValueError):
        FixedGauge(state(), truth(v=[0, float("nan"), 0]))


def test_gravity_tilt_not_hidden():
    gauge = FixedGauge(state(q=Rotation.from_euler("y", 15, degrees=True).as_quat()), truth())
    assert gauge.gravity_axis_error_deg == pytest.approx(15)
