"""Strict parser and semantic comparator for GPL OpenVINS trace evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCHEMAS = {
    "FD_TRACK": (
        "t",
        "cam",
        "initial",
        "previous",
        "topped",
        "klt_or_ransac",
        "out_of_bounds",
        "masked",
        "accepted",
        "reset",
    ),
    "FD_PIPE": (
        "t",
        "db",
        "lost",
        "marg",
        "maxtracks",
        "msckf_selected",
        "msckf_accepted",
        "slam_delayed",
        "slam_delayed_accepted",
        "slam_update",
        "slam_update_accepted",
    ),
    "FD_MSCKF": (
        "t",
        "input",
        "insufficient",
        "triangulation",
        "refinement",
        "chi2",
        "accepted",
    ),
    "FD_SLAM_DELAY": (
        "t",
        "input",
        "insufficient",
        "triangulation",
        "refinement",
        "initialization",
        "accepted",
    ),
    "FD_SLAM_UPDATE": (
        "t",
        "input",
        "no_measurements",
        "representation_insufficient",
        "chi2",
        "accepted",
    ),
}
TIMING_FIELDS = {"receive_ns", "start_ns", "end_ns", "acknowledged_ns"}


def _parse_line(line):
    tokens = line.split()
    marker_index = next(
        (index for index, token in enumerate(tokens) if token in SCHEMAS),
        None,
    )
    if marker_index is None:
        return None
    tokens = tokens[marker_index:]
    kind = tokens[0]
    fields = {}
    for token in tokens[1:]:
        if token.count("=") != 1:
            raise ValueError("invalid trace token")
        key, value = token.split("=", 1)
        if not key or key in fields:
            raise ValueError("duplicate trace field")
        fields[key] = value
    if tuple(fields) != SCHEMAS[kind]:
        raise ValueError("invalid trace schema")
    try:
        timestamp = Decimal(fields.pop("t"))
    except InvalidOperation as exc:
        raise ValueError("invalid trace timestamp") from exc
    if not timestamp.is_finite() or timestamp < 0:
        raise ValueError("invalid trace timestamp")
    parsed = {"t": str(timestamp)}
    for key, value in fields.items():
        if not value.isascii() or not value.isdecimal():
            raise ValueError("invalid trace count")
        parsed[key] = int(value)
    return kind, timestamp, parsed


def parse_trace(text):
    records = {}
    for raw_line in text.splitlines():
        parsed = _parse_line(raw_line.strip())
        if parsed is None:
            continue
        kind, timestamp, fields = parsed
        slot = records.setdefault(timestamp, {})
        name = kind.removeprefix("FD_").lower()
        if name in slot:
            if name not in {"slam_delay", "slam_update"}:
                raise ValueError("duplicate trace stage")
            for key, value in fields.items():
                if key != "t":
                    slot[name][key] += value
            continue
        slot[name] = fields

    for timestamp, slot in records.items():
        track = slot.get("track")
        pipe = slot.get("pipe")
        msckf = slot.get("msckf")
        slam_delay = slot.get("slam_delay")
        slam_update = slot.get("slam_update")
        if track is not None:
            if track["initial"] not in (0, 1) or track["reset"] not in (0, 1):
                raise ValueError("invalid trace boolean")
            if track["topped"] != sum(
                track[key]
                for key in ("klt_or_ransac", "out_of_bounds", "masked", "accepted")
            ):
                raise ValueError("track count mismatch")
        if pipe is not None:
            if track is None or msckf is None:
                raise ValueError("missing trace stage")
            if pipe["msckf_selected"] != msckf["input"]:
                raise ValueError("pipeline/updater input mismatch")
            if pipe["msckf_accepted"] != msckf["accepted"]:
                raise ValueError("pipeline/updater output mismatch")
            for prefix in ("msckf", "slam_delayed", "slam_update"):
                if pipe[f"{prefix}_accepted"] > pipe[
                    "msckf_selected" if prefix == "msckf" else prefix
                ]:
                    raise ValueError("accepted count exceeds input")
            if pipe["slam_delayed"]:
                if slam_delay is None:
                    raise ValueError("missing delayed SLAM trace stage")
                if (
                    pipe["slam_delayed"] != slam_delay["input"]
                    or pipe["slam_delayed_accepted"] != slam_delay["accepted"]
                ):
                    raise ValueError("pipeline/delayed SLAM mismatch")
            elif slam_delay is not None:
                raise ValueError("unexpected delayed SLAM trace stage")
            if pipe["slam_update"]:
                if slam_update is None:
                    raise ValueError("missing SLAM update trace stage")
                if (
                    pipe["slam_update"] != slam_update["input"]
                    or pipe["slam_update_accepted"] != slam_update["accepted"]
                ):
                    raise ValueError("pipeline/SLAM update mismatch")
            elif slam_update is not None:
                raise ValueError("unexpected SLAM update trace stage")
        if msckf is not None:
            if pipe is None:
                raise ValueError("missing trace stage")
            if msckf["input"] != sum(
                msckf[key]
                for key in ("insufficient", "triangulation", "refinement", "chi2", "accepted")
            ):
                raise ValueError("MSCKF count mismatch")
        if pipe is None and msckf is not None:
            raise ValueError("missing trace stage")
        if slam_delay is not None and slam_delay["input"] != sum(
            slam_delay[key]
            for key in (
                "insufficient",
                "triangulation",
                "refinement",
                "initialization",
                "accepted",
            )
        ):
            raise ValueError("delayed SLAM count mismatch")
        if slam_update is not None and slam_update["input"] != sum(
            slam_update[key]
            for key in (
                "no_measurements",
                "representation_insufficient",
                "chi2",
                "accepted",
            )
        ):
            raise ValueError("SLAM update count mismatch")
        if timestamp < 0:
            raise ValueError("invalid timestamp")

    update_records = [
        {"timestamp": str(timestamp), **slot}
        for timestamp, slot in sorted(records.items())
        if "pipe" in slot
    ]
    if not update_records:
        raise ValueError("missing update trace")
    return {"frames": len(update_records), "records": update_records}


def _compare_value(expected, actual, tolerance, path):
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        if actual != expected:
            raise ValueError(f"state mismatch at {path}")
        return
    if isinstance(expected, (int, float)):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise ValueError(f"state mismatch at {path}")
        if not math.isfinite(float(expected)) or not math.isfinite(float(actual)):
            raise ValueError(f"state mismatch at {path}")
        if abs(float(expected) - float(actual)) > tolerance:
            raise ValueError(f"state mismatch at {path}")
        return
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping) or set(actual) != set(expected):
            raise ValueError(f"state mismatch at {path}")
        for key in expected:
            _compare_value(expected[key], actual[key], tolerance, f"{path}.{key}")
        return
    if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        if not isinstance(actual, Sequence) or isinstance(actual, (str, bytes)) or len(actual) != len(expected):
            raise ValueError(f"state mismatch at {path}")
        for index, value in enumerate(expected):
            _compare_value(value, actual[index], tolerance, f"{path}[{index}]")
        return
    raise ValueError(f"unsupported state value at {path}")


def compare_state_rows(control, diagnostic, *, tolerance):
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0:
        raise ValueError("invalid state tolerance")
    if len(control) != len(diagnostic):
        raise ValueError("state row count mismatch")
    for index, (expected, actual) in enumerate(zip(control, diagnostic, strict=True)):
        if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
            raise ValueError("invalid state row")
        expected_stable = {key: value for key, value in expected.items() if key not in TIMING_FIELDS}
        actual_stable = {key: value for key, value in actual.items() if key not in TIMING_FIELDS}
        _compare_value(expected_stable, actual_stable, tolerance, f"row[{index}]")
    return {"qualified": True, "rows": len(control), "tolerance": float(tolerance)}


def _json_lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def summarize_trace(parsed):
    totals = {}
    for stage in ("track", "pipe", "msckf", "slam_delay", "slam_update"):
        stage_totals = {}
        for record in parsed["records"]:
            for key, value in record.get(stage, {}).items():
                if key != "t":
                    stage_totals[key] = stage_totals.get(key, 0) + value
        totals[stage] = stage_totals
    return totals


def audit_fixed_replay(
    control_dir,
    diagnostic_dir,
    *,
    diagnostic_binary,
    diagnostic_patch,
    diagnostic_library_sha256,
    tolerance=1e-12,
):
    control_dir = Path(control_dir)
    diagnostic_dir = Path(diagnostic_dir)
    control_summary = json.loads((control_dir / "summary.json").read_text(encoding="utf-8"))
    diagnostic_summary = json.loads((diagnostic_dir / "summary.json").read_text(encoding="utf-8"))
    for name, summary in (("control", control_summary), ("diagnostic", diagnostic_summary)):
        if summary.get("qualified") is not True or summary.get("failure") is not None:
            raise ValueError(f"{name} replay not qualified")
        if summary.get("physical_replay") is not False or summary.get("truth_used") is not False:
            raise ValueError(f"{name} replay scope mismatch")
        if summary.get("fusion_eligible") is not False:
            raise ValueError(f"{name} replay made a fusion claim")
    stable_summary_fields = (
        "source_capture",
        "source_requests_sha256",
        "replayed_source_records",
        "transport_accepted",
        "initialized_sample_ns",
        "effective_sim_ns",
        "stop_sim_ns",
    )
    for field in stable_summary_fields:
        if control_summary.get(field) != diagnostic_summary.get(field):
            raise ValueError(f"replay summary mismatch at {field}")
    binary_sha = _sha256(diagnostic_binary)
    if binary_sha != diagnostic_summary.get("binary_sha256"):
        raise ValueError("diagnostic binary hash mismatch")
    if not isinstance(diagnostic_library_sha256, str) or len(diagnostic_library_sha256) != 64:
        raise ValueError("invalid diagnostic library hash")
    trace = parse_trace((diagnostic_dir / "native.log").read_text(encoding="utf-8"))
    state_comparison = compare_state_rows(
        _json_lines(control_dir / "states.jsonl"),
        _json_lines(diagnostic_dir / "states.jsonl"),
        tolerance=tolerance,
    )
    totals = summarize_trace(trace)
    return {
        "schema": "openvins-feature-rejection-trace-audit-v1",
        "qualified": True,
        "physical_replay": False,
        "fusion_eligible": False,
        "truth_used": False,
        "control_binary_sha256": control_summary["binary_sha256"],
        "diagnostic_binary_sha256": binary_sha,
        "diagnostic_library_sha256": diagnostic_library_sha256,
        "diagnostic_patch_sha256": _sha256(diagnostic_patch),
        "source_capture": control_summary["source_capture"],
        "source_requests_sha256": control_summary["source_requests_sha256"],
        "replayed_source_records": control_summary["replayed_source_records"],
        "trace_frames": trace["frames"],
        "state_comparison": state_comparison,
        "totals": totals,
        "dominant_observed_rejections": {
            "msckf_insufficient": totals["msckf"].get("insufficient", 0),
            "slam_delayed_triangulation": totals["slam_delay"].get("triangulation", 0),
            "slam_update_chi2": totals["slam_update"].get("chi2", 0),
        },
        "root_cause_qualified": False,
        "online_latency_qualified": False,
    }
