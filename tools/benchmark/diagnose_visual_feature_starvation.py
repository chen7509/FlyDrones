"""Read-only raw-frame proxy and OpenVINS update-count diagnosis."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter

EXPECTED_CONFIG = {
    "use_klt": "true",
    "num_pts": "200",
    "fast_threshold": "20",
    "grid_x": "5",
    "grid_y": "5",
    "min_px_dist": "10",
    "track_frequency": "21.0",
    "downsample_cameras": "false",
    "histogram_method": '"HISTOGRAM"',
}


def _config(path):
    text = Path(path).read_text(encoding="utf8")
    selected = {}
    for key, expected in EXPECTED_CONFIG.items():
        matches = re.findall(r"^" + re.escape(key) + r":\s*([^#\r\n]+)", text, re.MULTILINE)
        if len(matches) != 1 or matches[0].strip() != expected:
            raise ValueError("frozen front-end config mismatch: " + key)
        selected[key] = expected.strip('"')
    return selected


def _ppm(path):
    data = Path(path).read_bytes()
    parts = data.split(b"\n", 3)
    if len(parts) != 4 or parts[:3] != [b"P6", b"160 120", b"255"] or len(parts[3]) != 160 * 120 * 3:
        raise ValueError("invalid fixed RGB PPM")
    return np.frombuffer(parts[3], dtype=np.uint8).reshape(120, 160, 3)


def _equalized_gray(rgb):
    gray = np.rint(rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114).astype(np.uint8)
    counts = np.bincount(gray.ravel(), minlength=256)
    cdf = counts.cumsum()
    nonzero = cdf[cdf > 0]
    if len(nonzero) == 0 or cdf[-1] == nonzero[0]:
        return gray
    table = np.floor((cdf - nonzero[0]) * 255 / (cdf[-1] - nonzero[0])).clip(0, 255).astype(np.uint8)
    return table[gray]


def _corners(gray, *, maximum=200, minimum_distance=10):
    image = gray.astype(np.float64) / 255.0
    gx = np.gradient(image, axis=1)
    gy = np.gradient(image, axis=0)
    xx, yy, xy = gaussian_filter(gx * gx, 1), gaussian_filter(gy * gy, 1), gaussian_filter(gx * gy, 1)
    response = xx * yy - xy * xy - 0.04 * (xx + yy) ** 2
    local = (response == maximum_filter(response, size=3)) & (response > max(float(np.quantile(response, 0.95)), 0.0))
    candidates = np.argwhere(local)
    candidates = sorted(candidates, key=lambda point: response[tuple(point)], reverse=True)
    selected = []
    distance2 = minimum_distance**2
    for y, x in candidates:
        if 3 <= x < 157 and 3 <= y < 117 and all((x - px) ** 2 + (y - py) ** 2 >= distance2 for py, px in selected):
            selected.append((int(y), int(x)))
            if len(selected) == maximum:
                break
    return selected


def _phase_shift(before, after):
    a = before.astype(np.float64) - float(before.mean())
    b = after.astype(np.float64) - float(after.mean())
    cross = np.fft.fft2(a) * np.conj(np.fft.fft2(b))
    magnitude = np.abs(cross)
    cross /= np.where(magnitude > 1e-12, magnitude, 1.0)
    peak = np.unravel_index(np.argmax(np.abs(np.fft.ifft2(cross))), before.shape)
    shift = [int(value) for value in peak]
    for index, size in enumerate(before.shape):
        if shift[index] > size // 2:
            shift[index] -= size
    candidates = [tuple(shift), tuple(-value for value in shift)]
    return min(candidates, key=lambda item: float(np.mean(np.abs(np.roll(before, item, axis=(0, 1)).astype(float) - after))))


def _pair(before, after, points):
    dy, dx = _phase_shift(before, after)
    retained, errors = 0, []
    for y, x in points:
        target_y, target_x = y + dy, x + dx
        if not (3 <= target_x < 157 and 3 <= target_y < 117):
            continue
        source = before[y - 2 : y + 3, x - 2 : x + 3].astype(float)
        target = after[target_y - 2 : target_y + 3, target_x - 2 : target_x + 3].astype(float)
        error = float(np.mean(np.abs(source - target)))
        if error <= 32.0:
            retained += 1
            errors.append(error)
    return {"shift_y": dy, "shift_x": dx, "retained": retained, "patch_error_mean": float(np.mean(errors)) if errors else None}


def _summary(values):
    return {"minimum": min(values), "median": float(np.median(values)), "maximum": max(values)}


def _log(path):
    text = Path(path).read_text(encoding="utf8", errors="strict")
    msckf = [int(value) for value in re.findall(r"MSCKF update \((\d+) feats\)", text)]
    slam = [int(value) for value in re.findall(r"SLAM update \((\d+) feats\)", text)]
    disparity = [int(value) for value in re.findall(r"\[ZUPT\]: (?:passed|failed) disparity \([^\r\n]*, (\d+) features\)", text)]
    if not msckf or not slam or len(msckf) != len(slam):
        raise ValueError("missing/ambiguous OpenVINS update log")
    return {
        "msckf_updates": len(msckf),
        "msckf_nonzero_updates": sum(value > 0 for value in msckf),
        "msckf_features_total": sum(msckf),
        "msckf_features_max": max(msckf),
        "slam_updates": len(slam),
        "slam_nonzero_updates": sum(value > 0 for value in slam),
        "slam_features_total": sum(slam),
        "zupt_disparity_observations": len(disparity),
        "zupt_disparity_features": disparity,
    }


def diagnose(frame_directory, config_path, log_path):
    config = _config(config_path)
    files = list(Path(frame_directory).glob("*.ppm"))
    stamps = []
    for path in files:
        if not path.stem.isascii() or not path.stem.isdigit():
            raise ValueError("non-numeric frame timestamp")
        stamps.append((int(path.stem), path))
    stamps.sort(key=lambda item: item[0])
    if len(stamps) < 2 or len({stamp for stamp, _ in stamps}) != len(stamps) or any(
        right <= left for (left, _), (right, _) in zip(stamps, stamps[1:])
    ):
        raise ValueError("missing/duplicate/regressed frame sequence")
    frames, hashes, corners = [], [], []
    for _, path in stamps:
        data = path.read_bytes()
        hashes.append(hashlib.sha256(data).hexdigest())
        frame = _equalized_gray(_ppm(path))
        frames.append(frame)
        corners.append(_corners(frame))
    pairs = []
    for index, (before, after, points) in enumerate(zip(frames, frames[1:], corners)):
        pair = _pair(before, after, points)
        pair.update(from_sample_ns=stamps[index][0], to_sample_ns=stamps[index + 1][0])
        pairs.append(pair)
    counts = [len(value) for value in corners]
    retained = [value["retained"] for value in pairs]
    log = _log(log_path)
    capacity = len(set(hashes)) > 1 and min(counts) >= 20 and min(retained) >= 20
    classification = (
        "raw-texture-and-pairwise-trackability-present; internal-update-starvation-unresolved"
        if capacity and log["msckf_nonzero_updates"] <= 2 and log["slam_features_total"] == 0
        else "raw-frame-front-end-capacity-not-established"
    )
    return {
        "schema": "visual-feature-starvation-fixed-frame-diagnosis-v1",
        "frame_count": len(frames),
        "first_sample_ns": stamps[0][0],
        "last_sample_ns": stamps[-1][0],
        "frame_sha256": hashes,
        "unique_frame_hashes": len(set(hashes)),
        "frame_details": [
            {"sample_ns": stamp, "sha256": digest, "proxy_corner_count": len(points)}
            for (stamp, _), digest, points in zip(stamps, hashes, corners)
        ],
        "config": config,
        "proxy_corners": _summary(counts),
        "pairwise_translation_proxy": {
            "pairs": len(pairs),
            "minimum_retained": min(retained),
            "median_retained": float(np.median(retained)),
            "maximum_retained": max(retained),
            "maximum_absolute_shift_px": max(max(abs(value["shift_x"]), abs(value["shift_y"])) for value in pairs),
            "details": pairs,
        },
        "openvins_log": log,
        "classification": classification,
        "fixed_capture_read_only": True,
        "openvins_replayed": False,
        "proxy_is_openvins_internal_tracker": False,
        "threshold_tuning_authorized": False,
        "vio_qualified": False,
        "fusion_eligible": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("frames", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("log", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = diagnose(args.frames, args.config, args.log)
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    with args.output.open("x", encoding="utf8") as stream:
        if stream.write(encoded) != len(encoded):
            raise OSError("short visual diagnosis write")
        stream.flush()
    print(encoded, end="")


if __name__ == "__main__":
    main()
