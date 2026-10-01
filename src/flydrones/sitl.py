"""Repeatable PX4 SITL acceptance trial.

This deliberately exercises the flight-controller boundary without the fly
brain.  Once the boundary is known-good, learned policies can be compared on
the same takeoff/hover/land envelope instead of mixing controller and MAVLink
failures together.
"""

from __future__ import annotations

import csv
import json
import math
import time
from pathlib import Path

from .drones.mavlink import MavlinkDrone
from .motor.command import FlightCommand


def evaluate_px4_trial(
    trace: list[dict], target_alt_m: float, geofence_m: float = 5.0, landed_alt_m: float = 0.15
) -> dict:
    if not trace:
        return {"accepted": False, "checks": {}, "metrics": {"samples": 0}, "reason": "empty trace"}

    altitudes = [float(row["alt_m"]) for row in trace if row.get("alt_m") is not None]
    hover_altitudes = [float(row["alt_m"]) for row in trace if row.get("phase") == "hover" and row.get("alt_m") is not None]
    radii = [
        math.hypot(float(row["x_m"]), float(row["y_m"]))
        for row in trace
        if row.get("x_m") is not None and row.get("y_m") is not None
    ]
    final_alt = altitudes[-1] if altitudes else math.inf
    max_alt = max(altitudes, default=-math.inf)
    max_hover_error = max((abs(a - target_alt_m) for a in hover_altitudes), default=math.inf)
    max_radius = max(radii, default=math.inf)
    checks = {
        "reached_altitude": max_alt >= target_alt_m - 0.15,
        "hover_altitude_stable": bool(hover_altitudes) and max_hover_error <= 0.30,
        "inside_geofence": max_radius <= geofence_m,
        "landed": trace[-1].get("phase") == "land" and final_alt <= landed_alt_m,
    }
    return {
        "accepted": all(checks.values()),
        "checks": checks,
        "metrics": {
            "samples": len(trace),
            "max_alt_m": round(max_alt, 4) if altitudes else None,
            "max_hover_error_m": round(max_hover_error, 4) if hover_altitudes else None,
            "max_radius_m": round(max_radius, 4) if radii else None,
            "final_alt_m": round(final_alt, 4) if altitudes else None,
        },
    }


def run_px4_trial(
    connection: str = "udpin:0.0.0.0:14540",
    target_alt_m: float = 1.8,
    hover_s: float = 5.0,
    rate_hz: float = 20.0,
    land_timeout_s: float = 20.0,
) -> tuple[list[dict], dict]:
    drone = MavlinkDrone(
        connection=connection,
        autopilot="px4",
        takeoff_alt=target_alt_m,
        offboard_rate_hz=rate_hz,
    )
    trace: list[dict] = []
    period = 1.0 / rate_hz
    start = time.monotonic()

    def sample(phase: str) -> None:
        tel = drone.telemetry()
        trace.append(
            {
                "t_s": round(time.monotonic() - start, 4),
                "phase": phase,
                "alt_m": tel.alt_m,
                "x_m": tel.x_m,
                "y_m": tel.y_m,
                "vz_mps": tel.vz_mps,
                "yaw_deg": tel.yaw_deg,
                "battery_pct": tel.battery_pct,
            }
        )

    drone.connect()
    sample("connected")
    try:
        drone.takeoff()
        deadline = time.monotonic() + hover_s
        while time.monotonic() < deadline:
            drone.send(FlightCommand.hover("SITL acceptance hover"))
            sample("hover")
            time.sleep(period)
    finally:
        drone.land()

    deadline = time.monotonic() + land_timeout_s
    while time.monotonic() < deadline:
        sample("land")
        if trace[-1]["alt_m"] is not None and trace[-1]["alt_m"] <= 0.15:
            break
        time.sleep(period)
    return trace, evaluate_px4_trial(trace, target_alt_m=target_alt_m)


def write_px4_trial_artifacts(output_dir: str | Path, trace: list[dict], summary: dict) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fields = ["t_s", "phase", "alt_m", "x_m", "y_m", "vz_mps", "yaw_deg", "battery_pct"]
    with (out / "flight.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(trace)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    report = [
        "# PX4 单机 SITL 验收报告",
        "",
        f"结论：{'通过' if summary['accepted'] else '未通过'}",
        "",
        "## 检查项",
        "",
    ]
    report.extend(f"- {name}: {'通过' if passed else '失败'}" for name, passed in summary.get("checks", {}).items())
    report.extend(["", "## 指标", ""])
    report.extend(f"- {name}: {value}" for name, value in summary.get("metrics", {}).items())
    (out / "报告.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return out
