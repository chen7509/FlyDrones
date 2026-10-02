import numpy as np

from flydrones.benchmark.optical_fixture import analyze_markers


def _case(mirrored=False):
    rgb = np.zeros((120, 160, 3), dtype=np.uint8)
    positions = {
        "negative_y_red": (107, 59, (255, 0, 0), [-3.88, -1, .482]),
        "center_green": (80, 59, (0, 255, 0), [-3.88, 0, .482]),
        "positive_y_blue": (53, 59, (0, 0, 255), [-3.88, 1, .482]),
        "high_yellow": (80, 32, (255, 255, 0), [-3.88, 0, 1.482]),
    }
    targets = []
    for name, (x, y, color, world) in positions.items():
        if mirrored:
            x = 160 - x
        rgb[y-2:y+3, x-2:x+3] = color
        targets.append({"name": name, "rgb": [v / 255 for v in color], "world_xyz_m": world})
    pose = {"position_xyz_m": [-7.88, 0, .43246], "quaternion_xyzw": [0, 0, 0, 1]}
    k = [108.124, 0, 80, 0, 108.124, 60, 0, 0, 1]
    return rgb, targets, pose, k


def test_optical_fixture_projects_left_right_and_high_marker():
    rgb, targets, pose, k = _case()
    result = analyze_markers(rgb, targets, pose, k, max_residual_px=2)
    assert result["accepted"] is True
    assert result["max_residual_px"] < 1
    by_name = {m["name"]: m for m in result["markers"]}
    assert by_name["positive_y_blue"]["observed_uv_px"][0] < 80
    assert by_name["negative_y_red"]["observed_uv_px"][0] > 80
    assert by_name["high_yellow"]["observed_uv_px"][1] < 60


def test_optical_fixture_rejects_mirrored_image():
    rgb, targets, pose, k = _case(mirrored=True)
    result = analyze_markers(rgb, targets, pose, k, max_residual_px=2)
    assert result["accepted"] is False
    assert result["max_residual_px"] > 50
