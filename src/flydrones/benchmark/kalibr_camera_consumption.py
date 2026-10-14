"""Apply byte-bound Kalibr artifacts; consumption never certifies calibration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from pathlib import Path, PurePosixPath

import numpy as np
import yaml

from .px4_camera_source import MAX_DOCUMENT, _array, _bound_bytes, _unique

IMU_CONTRACT = "px4-d6f12ad-sensor-combined-frd-interval-mean-v1"


def references(path, digest):
    """Read exact bundle/reference bytes for both consumer and CLI snapshots."""
    path = Path(path)
    raw = _bound_bytes(path, digest, MAX_DOCUMENT)
    doc = json.loads(raw, object_pairs_hook=_unique)
    fields = {"schema", "rig_sha256", "body_id", "camera_id", "imu_contract", "camera_key", "camchain", "results"}
    if type(doc) is not dict or set(doc) != fields or doc["schema"] != "flydrones-kalibr-artifact-binding-v1":
        raise ValueError("calibration artifact binding fields invalid")
    selected = {}
    for role in ("camchain", "results"):
        ref = doc[role]
        if type(ref) is not dict or set(ref) != {"path", "sha256"}:
            raise ValueError("calibration artifact reference invalid")
        name = ref["path"]
        if (
            type(name) is not str
            or not name
            or "\\" in name
            or ":" in name
            or PurePosixPath(name).is_absolute()
            or any(p in ("", ".", "..") for p in name.split("/"))
        ):
            raise ValueError("calibration artifact reference escapes bundle")
        file = path.parent.joinpath(*PurePosixPath(name).parts)
        if not file.resolve().is_relative_to(path.parent.resolve()):
            raise ValueError("calibration artifact reference escapes bundle")
        selected[role] = _bound_bytes(file, ref["sha256"], MAX_DOCUMENT)
    if doc["camchain"]["path"] == doc["results"]["path"] or not selected["results"]:
        raise ValueError("distinct nonempty calibration result reference required")
    return raw, doc, selected


def decimal(value):
    if type(value) is not str or len(value) > 128:
        raise ValueError("bounded calibration numeric literal required")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("calibration numeric literal invalid") from exc
    if not result.is_finite() or abs(result.as_tuple().exponent) > 128:
        raise ValueError("calibration number nonfinite")
    return result


def array(value, shape):
    raw = np.asarray(value)
    if raw.shape != shape:
        raise ValueError("calibration numeric shape invalid")
    return _array(np.array([float(decimal(v)) for v in raw.flatten().tolist()]).reshape(shape), shape)


def chain(raw):
    class Loader(yaml.BaseLoader):
        pass

    def mapping(loader, node):
        return _unique([(loader.construct_object(k), loader.construct_object(v)) for k, v in node.value])

    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        if any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for t in yaml.scan(raw)):
            raise ValueError("calibration YAML anchors/aliases forbidden")
        doc = yaml.load(raw, Loader=Loader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError("calibration YAML invalid") from exc
    if type(doc) is not dict or not 1 <= len(doc) <= 8 or any(re.fullmatch("cam[0-7]", k) is None for k in doc):
        raise ValueError("bounded calibration camera chain required")
    return doc


@dataclass(frozen=True, init=False)
class KalibrCameraArtifact:
    bundle_sha256: str
    rig_sha256: str
    intrinsics: tuple
    distortion: tuple
    camera_from_body: tuple
    timeshift_decimal_s: str
    timeshift_ns: int
    timeshift_rounding_error_ns: str
    evidence: tuple

    @classmethod
    def load(cls, path, digest, binding):
        _, doc, payload = references(path, digest)
        if (
            doc["rig_sha256"] != binding.sha256
            or doc["body_id"] != binding.body_id
            or doc["camera_id"] != binding.camera_id
            or doc["imu_contract"] != IMU_CONTRACT
        ):
            raise ValueError("calibration rig/IMU coordinate contract mismatch")
        cameras = chain(payload["camchain"])
        camera = cameras.get(doc["camera_key"])
        if type(camera) is not dict or camera.get("camera_model") != "pinhole" or camera.get("distortion_model") != "radtan":
            raise ValueError("supported pinhole/radtan calibration camera required")
        resolution = array(camera.get("resolution"), (2,))
        if not np.array_equal(resolution, [binding.width, binding.height]):
            raise ValueError("calibration camera resolution mismatch")
        intrinsic = array(camera.get("intrinsics"), (4,))
        distortion = array(camera.get("distortion_coeffs"), (4,))
        transform = array(camera.get("T_cam_imu"), (4, 4))
        rotation = transform[:3, :3]
        if (
            intrinsic[0] <= 0
            or intrinsic[1] <= 0
            or not np.array_equal(transform[3], [0.0, 0.0, 0.0, 1.0])
            or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8, rtol=0)
            or abs(np.linalg.det(rotation) - 1.0) > 1e-8
        ):
            raise ValueError("calibration projection/rigid transform invalid")
        value = camera.get("timeshift_cam_imu")
        shift = decimal(value)
        if shift.copy_abs() > 1:
            raise ValueError("calibration timeshift exceeds supported1s")
        with localcontext() as context:
            context.prec = 256
            exact = shift * Decimal(1_000_000_000)
            rounded = exact.to_integral_value(rounding=ROUND_HALF_EVEN)
            error = "0" if rounded == exact else str((rounded - exact).normalize())
        obj = cls()
        for name, result in dict(
            bundle_sha256=digest,
            rig_sha256=binding.sha256,
            intrinsics=tuple(intrinsic),
            distortion=tuple(distortion),
            camera_from_body=tuple(tuple(row) for row in transform),
            timeshift_decimal_s=value,
            timeshift_ns=int(rounded),
            timeshift_rounding_error_ns=error,
            evidence=tuple((role, doc[role]["sha256"]) for role in payload),
        ).items():
            object.__setattr__(obj, name, result)
        return obj

    def lookup_ns(self, frame_ns):
        if type(frame_ns) is not int or not 0 <= frame_ns <= 2**63 - 1:
            raise ValueError("integer camera boot timestamp required")
        result = frame_ns + self.timeshift_ns
        if not 0 <= result <= 2**63 - 1:
            raise ValueError("calibration lookup timestamp outside boot range")
        return result

    def body_from_camera(self):
        t = np.asarray(self.camera_from_body)
        r = t[:3, :3].T
        return r, -r @ t[:3, 3]

    def project_imu_point(self, point):
        point = _array(point, (3,))
        t = np.asarray(self.camera_from_body)
        p = t[:3, :3] @ point + t[:3, 3]
        if p[2] <= 0:
            raise ValueError("calibration projection requires point in front of camera")
        x, y = p[:2] / p[2]
        k1, k2, p1, p2 = self.distortion
        r2 = x * x + y * y
        radial = 1 + k1 * r2 + k2 * r2 * r2
        xd, yd = x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x * x), y * radial + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
        fx, fy, cx, cy = self.intrinsics
        result = np.array([fx * xd + cx, fy * yd + cy])
        if not np.isfinite(result).all():
            raise ValueError("calibration projected point nonfinite")
        return result

    def record(self):
        return {
            "bundle_sha256": self.bundle_sha256,
            "rig_sha256": self.rig_sha256,
            "artifact_sha256": dict(self.evidence),
            "timeshift_decimal_s": self.timeshift_decimal_s,
            "timeshift_ns": self.timeshift_ns,
            "timeshift_rounding_error_ns": self.timeshift_rounding_error_ns,
            "intrinsics": list(self.intrinsics),
            "distortion_model": "radtan",
            "distortion_coeffs": list(self.distortion),
            "T_cam_imu": [list(row) for row in self.camera_from_body],
            "artifact_parameters_loaded": True,
            "producer_authentication_verified": False,
            "camera_calibration_qualified": False,
            "clock_epoch_qualified": False,
            "training_eligible": False,
            "flight_eligible": False,
        }
