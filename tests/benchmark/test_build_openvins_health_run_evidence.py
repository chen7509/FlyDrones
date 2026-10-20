import numpy as np

from tools.benchmark.build_openvins_health_run_evidence import error_vectors
from tools.benchmark.trajectory_gauge_contract import YawTranslationGauge


def native_state(position=(1.0, 2.0, 3.0), velocity=(0.1, 0.2, 0.3)):
    return [1.0, 0.0, 0.0, 0.0, *position, *velocity, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def truth(position=(1.0, 2.0, 3.0), velocity=(0.1, 0.2, 0.3)):
    return {
        "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0],
        "position": list(position),
        "velocity_world": list(velocity),
        "truth_for_fixture_audit_only": True,
    }


def test_error_vectors_preserve_component_order_for_covariance_audit():
    gauge = YawTranslationGauge(native_state(), truth())
    vectors = error_vectors(gauge, native_state(), truth())
    assert np.allclose(vectors["position_error_xyz_m"], [0.0, 0.0, 0.0], atol=1e-12)
    assert np.allclose(vectors["velocity_error_xyz_m_s"], [0.0, 0.0, 0.0], atol=1e-12)
    assert np.allclose(vectors["attitude_error_tangent_xyz_rad"], [0.0, 0.0, 0.0], atol=1e-12)
