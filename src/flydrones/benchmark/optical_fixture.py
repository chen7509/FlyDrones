"""Known-target check of Gazebo link-to-optical camera-axis convention."""

from __future__ import annotations

import numpy as np

OPTICAL_FROM_LINK_FLU = np.array([[0., -1., 0.], [0., 0., -1.], [1., 0., 0.]])


def _rotation_xyzw(quaternion: list[float]) -> np.ndarray:
    x, y, z, w = np.asarray(quaternion, dtype=float)
    norm = np.linalg.norm((x, y, z, w))
    if not np.isfinite(norm) or norm <= 0:
        raise ValueError("invalid camera-link quaternion")
    x, y, z, w = np.asarray((x, y, z, w)) / norm
    return np.array([
        [1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w)],
        [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w)],
        [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y)],
    ])


def _marker_mask(rgb: np.ndarray, target_color: list[float]) -> np.ndarray:
    red, green, blue = (rgb[..., axis].astype(float) for axis in range(3))
    color = tuple(int(value) for value in target_color)
    if color == (1, 0, 0):
        return (red > 70) & (red > 1.6 * green) & (red > 1.6 * blue)
    if color == (0, 1, 0):
        return (green > 70) & (green > 1.6 * red) & (green > 1.6 * blue)
    if color == (0, 0, 1):
        return (blue > 70) & (blue > 1.6 * red) & (blue > 1.6 * green)
    if color == (1, 1, 0):
        return (red > 70) & (green > 70) & (blue < .6 * np.minimum(red, green))
    raise ValueError("unsupported optical fixture target color")


def analyze_markers(
    rgb: np.ndarray, targets: list[dict], camera_pose: dict, intrinsics_k: list[float],
    *, max_residual_px: float = 2.,
) -> dict:
    """Project known world targets without relabeling truth as VIO output."""
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError("optical fixture requires uint8 RGB image")
    k = np.asarray(intrinsics_k, dtype=float)
    if k.shape != (9,) or not np.all(np.isfinite(k)) or k[0] <= 0 or k[4] <= 0:
        raise ValueError("invalid camera intrinsics")
    if not np.isfinite(max_residual_px) or max_residual_px <= 0:
        raise ValueError("max_residual_px must be positive")
    position = np.asarray(camera_pose["position_xyz_m"], dtype=float)
    world_from_link = _rotation_xyzw(camera_pose["quaternion_xyzw"])
    if position.shape != (3,) or not np.all(np.isfinite(position)):
        raise ValueError("invalid camera-link position")
    markers = []
    for target in targets:
        mask = _marker_mask(rgb, target["rgb"])
        rows, cols = np.nonzero(mask)
        if len(cols) < 10:
            raise ValueError(f"target {target['name']} not visibly detected")
        delta_world = np.asarray(target["world_xyz_m"], dtype=float) - position
        link = world_from_link.T @ delta_world
        optical = OPTICAL_FROM_LINK_FLU @ link
        if optical[2] <= 0:
            raise ValueError(f"target {target['name']} behind proposed optical camera")
        predicted = np.array([k[0] * optical[0] / optical[2] + k[2],
                              k[4] * optical[1] / optical[2] + k[5]])
        observed = np.array([float(np.mean(cols)), float(np.mean(rows))])
        markers.append({
            "name": target["name"], "pixel_count": len(cols),
            "observed_uv_px": observed.tolist(), "predicted_uv_px": predicted.tolist(),
            "residual_px": float(np.linalg.norm(observed - predicted)),
        })
    maximum = max(item["residual_px"] for item in markers)
    return {
        "schema": "flydrones-optical-fixture-analysis-v1",
        "candidate_optical_from_gazebo_link_flu": OPTICAL_FROM_LINK_FLU.tolist(),
        "markers": markers,
        "max_residual_px": maximum,
        "max_residual_limit_px": float(max_residual_px),
        "accepted": bool(maximum <= max_residual_px),
    }
