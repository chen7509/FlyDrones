#!/usr/bin/env python3
"""Audit diagnostic-only OpenVINS feature stage logs on frozen offline data.

Reason logs from active-track visualization outside the MSCKF updater are
intentionally excluded. This only locates rejection stages; it does not prove
an estimator is accurate or safe for PX4 fusion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _fields(line: str) -> dict[str, str]:
    return dict(re.findall(r"([a-z_][a-z0-9_]*)=([^ ]+)", line))


def _tri_reason(line: str) -> str:
    values = _fields(line)
    flags = []
    if abs(float(values["cond"])) > float(values["max_cond"]):
        flags.append("condition_number")
    if float(values["depth"]) < float(values["min_dist"]):
        flags.append("depth_below_min")
    if float(values["depth"]) > float(values["max_dist"]):
        flags.append("depth_above_max")
    if int(values["nan"]):
        flags.append("nan_position")
    return "+".join(flags) or "unclassified"


def _refine_reason(line: str) -> str:
    values = _fields(line)
    flags = []
    if float(values["depth"]) < float(values["min_dist"]):
        flags.append("depth_below_min")
    if float(values["depth"]) > float(values["max_dist"]):
        flags.append("depth_above_max")
    if float(values["ratio"]) > float(values["max_ratio"]):
        flags.append("baseline_ratio")
    if int(values["nan"]):
        flags.append("nan_position")
    return "+".join(flags) or "unclassified"


def analyze(upstream_log: Path, reference_states: Path, replay_states: Path) -> dict:
    reference_hash = _sha(reference_states)
    replay_hash = _sha(replay_states)
    if reference_hash != replay_hash:
        raise ValueError("diagnostic replay changed state CSV")
    totals = Counter()
    tri_reasons: Counter[str] = Counter()
    refine_reasons: Counter[str] = Counter()
    secondary_refine_reasons: Counter[str] = Counter()
    windows = 0
    outside_reject_logs = 0
    active: dict | None = None
    for line in upstream_log.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("FD_VIO_STAGE "):
            if active is not None:
                raise ValueError("unfinished MSCKF diagnostic window")
            active = {"manager": _fields(line), "tri": [], "refine": [],
                      "secondary_refine": [], "tri_pending": False}
        elif line.startswith("FD_TRI_REJECT "):
            if active is None:
                outside_reject_logs += 1
            else:
                active["tri"].append(_tri_reason(line))
                active["tri_pending"] = True
        elif line.startswith("FD_REFINE_REJECT "):
            if active is None:
                outside_reject_logs += 1
            else:
                # Upstream runs refinement even when linear triangulation
                # failed. That result uses an unset feature position and is
                # secondary to the prior failure, not another rejected track.
                if active["tri_pending"]:
                    active["secondary_refine"].append(_refine_reason(line))
                else:
                    active["refine"].append(_refine_reason(line))
                active["tri_pending"] = False
        elif line.startswith("FD_MSCKF_STAGE "):
            if active is None:
                raise ValueError("MSCKF stage without manager marker")
            manager = active["manager"]
            stage = _fields(line)
            if manager["t"] != stage["t"]:
                raise ValueError("diagnostic timestamps disagree")
            numbers = {key: int(stage[key]) for key in (
                "input", "clean", "tri", "chi2", "tri_fail", "refine_fail", "chi2_fail")}
            if int(manager["candidate"]) != numbers["input"]:
                raise ValueError("candidate and updater input disagree")
            if (numbers["input"] < numbers["clean"]
                    or numbers["clean"] != numbers["tri"] + numbers["tri_fail"]
                    + numbers["refine_fail"]
                    or numbers["tri"] != numbers["chi2"] + numbers["chi2_fail"]):
                raise ValueError("inconsistent MSCKF stage totals")
            if (len(active["tri"]) != numbers["tri_fail"]
                    or len(active["refine"]) != numbers["refine_fail"]):
                raise ValueError("reason count disagrees with stage totals")
            totals.update(numbers)
            totals.update({key: int(manager[key]) for key in ("lost", "marg", "maxtracks")})
            tri_reasons.update(active["tri"])
            refine_reasons.update(active["refine"])
            secondary_refine_reasons.update(active["secondary_refine"])
            active = None
            windows += 1
    if active is not None or not windows:
        raise ValueError("missing or unfinished MSCKF diagnostic windows")
    return {
        "schema": "flydrones-openvins-rejection-audit-v1",
        "scope": "offline textured development fixture; no EKF2 visual fusion",
        "upstream_log_sha256": _sha(upstream_log),
        "reference_state_sha256": reference_hash,
        "replay_state_sha256": replay_hash,
        "state_csv_identical": True,
        "windows": windows,
        "totals": dict(totals),
        "tri_reason_combinations": dict(sorted(tri_reasons.items())),
        "refine_reason_combinations": dict(sorted(refine_reasons.items())),
        "secondary_refine_after_failed_tri": dict(sorted(secondary_refine_reasons.items())),
        "outside_reject_logs": outside_reject_logs,
        "status": "no_visual_features_past_triangulation" if totals["tri"] == 0
                  else "visual_candidates_past_triangulation_unvalidated",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-log", type=Path, required=True)
    parser.add_argument("--reference-states", type=Path, required=True)
    parser.add_argument("--replay-states", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refusing to overwrite rejection audit")
    report = analyze(args.upstream_log, args.reference_states, args.replay_states)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
