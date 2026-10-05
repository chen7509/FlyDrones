"""Standalone check in existing WSL pymavlink 2.4.49 environment, no network.

Run from repository root: PYTHONPATH=. python3 tests/benchmark/check_openvins_odometry_packet.py
"""

import copy
import json

import numpy as np
from scipy.spatial.transform import Rotation

from tools.benchmark.openvins_odometry_contract import ShadowSession, encode_shadow


def run_checks():
    from pymavlink.dialects.v20 import common

    cases = []
    rng = np.random.default_rng(91)
    a = rng.normal(size=(12, 12))
    covariance = a @ a.T * 0.01
    for angles in [[0, 0, 0], [20, -35, 81], [-45, 15, -110]]:
        q = Rotation.from_matrix(
            np.diag([1.0, -1.0, -1.0]) @ Rotation.from_euler("xyz", angles, degrees=True).as_matrix()
        ).as_quat()
        for quality in [-1, 0, 80]:
            row = dict(
                target_ns=2_000_000_000,
                success=True,
                internal_initialized=True,
                public_initialized=False,
                state13=[*q, 1, 2, 3, 4, 5, 6, 0.1, 0.2, 0.3],
                covariance12=covariance.tolist(),
            )
            session = ShadowSession("synthetic", "clock", wire_offset_ns=1_000_000, max_age_ns=100_000_000)
            record = session.accept(
                row, session_id="synthetic", clock_id="clock", observed_ns=2_004_000_000, reset_total=256, quality=quality
            )
            packet = encode_shadow(record)
            parsed = common.MAVLink(None).parse_char(packet)
            assert parsed.get_type() == "ODOMETRY" and packet[0] == 0xFD
            assert parsed.frame_id == common.MAV_FRAME_LOCAL_FRD
            assert parsed.child_frame_id == common.MAV_FRAME_BODY_FRD
            assert parsed.estimator_type == common.MAV_ESTIMATOR_TYPE_VIO
            for key, value in record["fields"].items():
                np.testing.assert_allclose(getattr(parsed, key), value, rtol=1e-6, atol=1e-7)
            assert not record["eligible_for_px4_fusion"]
            cases.append(
                {
                    "angles_deg": angles,
                    "quality": quality,
                    "packet_hex": packet.hex(),
                    "decoded": parsed.to_dict(),
                    "reasons": record["reasons"],
                }
            )
    corruptions = [
        dict(frame_id=1),
        dict(child_frame_id=1),
        dict(estimator_type=0),
        dict(quality=101),
        dict(x=float("nan")),
        dict(q=[0, 0, 0, 0]),
        dict(reset_counter=True),
        dict(time_usec=0),
        dict(pose_covariance=[-1.0] * 21),
    ]
    for change in corruptions:
        bad = copy.deepcopy(record)
        bad["fields"].update(change)
        try:
            encode_shadow(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("corrupted file-only record accepted: " + repr(change))
    return {"synthetic_only": True, "roundtrips": len(cases), "wire_corruptions_rejected": len(corruptions), "cases": cases}


if __name__ == "__main__":
    print(json.dumps(run_checks(), indent=2))
