import json
from pathlib import Path

import numpy as np
import pytest

CONFIG = """%YAML:1.0
use_klt: true
num_pts: 200
fast_threshold: 20
grid_x: 5
grid_y: 5
min_px_dist: 10
track_frequency: 21.0
downsample_cameras: false
histogram_method: \"HISTOGRAM\"
"""


def ppm(path: Path, image):
    path.write_bytes(b"P6\n160 120\n255\n" + image.tobytes())


def fixed_frames(directory):
    directory.mkdir()
    rng = np.random.default_rng(7)
    base = rng.integers(0, 256, size=(120, 160, 3), dtype=np.uint8)
    for index in range(4):
        image = np.roll(base, index, axis=1)
        ppm(directory / f"{(index + 1) * 100_000_000}.ppm", image)


def log_text():
    return "\n".join(
        [
            "VioManager.cpp:615 [TIME]: 0.0001 seconds for MSCKF update (0 feats)",
            "VioManager.cpp:617 [TIME]: 0.0000 seconds for SLAM update (0 feats)",
            "UpdaterZeroVelocity.cpp:233 [ZUPT]: passed disparity (0.238 < 0.500, 36 features)",
            "VioManager.cpp:615 [TIME]: 0.0001 seconds for MSCKF update (1 feats)",
            "VioManager.cpp:617 [TIME]: 0.0000 seconds for SLAM update (0 feats)",
        ]
    )


def test_fixed_frames_report_texture_and_proxy_tracks_without_claiming_vio(tmp_path):
    from tools.benchmark.diagnose_visual_feature_starvation import diagnose

    frames = tmp_path / "rgb"
    fixed_frames(frames)
    config = tmp_path / "estimator.yaml"
    config.write_text(CONFIG)
    log = tmp_path / "native.log"
    log.write_text(log_text())
    result = diagnose(frames, config, log)
    assert result["frame_count"] == 4
    assert result["unique_frame_hashes"] == 4
    assert [row["sample_ns"] for row in result["frame_details"]] == [
        100_000_000,
        200_000_000,
        300_000_000,
        400_000_000,
    ]
    assert result["pairwise_translation_proxy"]["details"][0]["from_sample_ns"] == 100_000_000
    assert result["pairwise_translation_proxy"]["details"][0]["to_sample_ns"] == 200_000_000
    assert result["proxy_corners"]["minimum"] >= 20
    assert result["pairwise_translation_proxy"]["minimum_retained"] >= 20
    assert result["openvins_log"]["msckf_updates"] == 2
    assert result["openvins_log"]["msckf_nonzero_updates"] == 1
    assert result["openvins_log"]["slam_features_total"] == 0
    assert result["classification"] == "raw-texture-and-pairwise-trackability-present; internal-update-starvation-unresolved"
    assert result["openvins_replayed"] is False
    assert result["proxy_is_openvins_internal_tracker"] is False
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("mutation", ["config", "shape", "duplicate", "log"])
def test_rejects_config_image_sequence_and_log_ambiguity(tmp_path, mutation):
    from tools.benchmark.diagnose_visual_feature_starvation import diagnose

    frames = tmp_path / "rgb"
    fixed_frames(frames)
    config = tmp_path / "estimator.yaml"
    config.write_text(CONFIG.replace("fast_threshold: 20", "fast_threshold: 10") if mutation == "config" else CONFIG)
    log = tmp_path / "native.log"
    log.write_text("unrelated" if mutation == "log" else log_text())
    if mutation == "shape":
        (frames / "200000000.ppm").write_bytes(b"P6\n10 10\n255\n" + bytes(300))
    elif mutation == "duplicate":
        (frames / "0100000000.ppm").write_bytes((frames / "100000000.ppm").read_bytes())
    with pytest.raises(ValueError):
        diagnose(frames, config, log)


def test_identical_low_information_frames_are_retained_as_failure(tmp_path):
    from tools.benchmark.diagnose_visual_feature_starvation import diagnose

    frames = tmp_path / "rgb"
    frames.mkdir()
    blank = np.zeros((120, 160, 3), np.uint8)
    ppm(frames / "100000000.ppm", blank)
    ppm(frames / "200000000.ppm", blank)
    config = tmp_path / "estimator.yaml"
    config.write_text(CONFIG)
    log = tmp_path / "native.log"
    log.write_text(log_text())
    result = diagnose(frames, config, log)
    assert result["unique_frame_hashes"] == 1
    assert result["classification"] == "raw-frame-front-end-capacity-not-established"
