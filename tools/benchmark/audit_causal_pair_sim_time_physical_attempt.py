"""Audit study-v16's camera-pair wall/simulation clock-domain refusal."""

from __future__ import annotations

import json
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import write_manifest
from tools.benchmark.openvins_causal_input import CausalInput

CLASSIFICATION = "camera-pair-wall-age-slow-simulation-refusal"


def _read(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("object required")
    return value


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def _replay(events, idle_wall_ns):
    scheduler = CausalInput(session_id="study-v16-fixed", clock_id="gazebo-sim+linux-monotonic")
    actions = []
    for sequence, row in enumerate(events[:4]):
        if sequence == 2:
            scheduler.tick(idle_wall_ns)
        keys = {"kind", "sample_ns", "arrival_monotonic_ns", "observed_sim_ns"}
        keys |= {
            "imu": {"gyro_flu", "accel_flu"},
            "rgb": {"width", "height"},
            "info": {"camera_info"},
        }[row["kind"]]
        base = {key: row[key] for key in keys}
        actions.extend(scheduler.accept(base, sequence=sequence, session_id=scheduler.session_id, clock_id=scheduler.clock_id))
    return scheduler, actions


def audit(capture, dispatch, completion):
    capture = Path(capture).resolve(strict=True)
    failures = []

    def require(value, label):
        if not value:
            failures.append(label)

    pair_wall_age = pair_sim_age = idle_wall_age = None
    replay_camera = counterfactual_refused = False
    try:
        result = _read(capture / "result.json")
        supervisor = _read(capture / "supervisor.json")
        dispatched = _read(dispatch)
        completed = _read(completion)
        events = _rows(capture / "events.jsonl")
        fanout = _rows(capture / "source-fanout.jsonl")
        require(result.get("status") == "capture_failed" and result.get("end_sim_ns") == 10_000_000, "capture terminal")
        require(result.get("source_fanout", {}).get("failure") == "ValueError(\"shadow failed during source idle: ValueError('pending input exceeded wall wait')\")", "source refusal")
        require(result.get("shadow", {}).get("failure") == "ValueError('pending input exceeded wall wait')", "shadow refusal")
        require(result.get("heartbeat-observations") is None and result.get("source_fanout", {}).get("heartbeat", {}).get("observed") == 0, "heartbeat not causal")
        require(result.get("motion", {}).get("recorded_commands") == 0 and result.get("motion", {}).get("anchor_ns") is None, "motion not started")
        require(result.get("readiness", {}).get("first_internal") is None, "estimator not initialized")
        require(result.get("px4_ulogs") == [], "no ULog")
        require(result.get("eligible_for_vio_input") is False and result.get("eligible_for_px4_fusion") is False, "gates closed")
        require(len(events) >= 4 and [row.get("kind") for row in events[:4]] == ["imu", "info", "depth", "rgb"], "source prefix")
        info, rgb = events[1], events[3]
        require(info.get("sample_ns") == rgb.get("sample_ns") == 2_000_000, "pair sample")
        require(info.get("observed_sim_ns") == rgb.get("observed_sim_ns") == 3_000_000, "pair simulation time")
        pair_wall_age = rgb["arrival_monotonic_ns"] - info["arrival_monotonic_ns"]
        pair_sim_age = rgb["observed_sim_ns"] - info["observed_sim_ns"]
        idle = next(row for row in fanout if row.get("event") == "source_idle_refusal")
        idle_wall_age = idle["wall_monotonic_ns"] - info["arrival_monotonic_ns"]
        require(pair_wall_age == 355_099_344 and idle_wall_age == 294_079_878 and pair_sim_age == 0, "clock-domain ages")

        replay_events = [events[0], events[1], events[3], events[4]]
        scheduler, actions = _replay(replay_events, idle["wall_monotonic_ns"])
        replay_camera = [row["kind"] for row in actions] == ["imu", "imu", "camera"] and scheduler.failure is None
        require(replay_camera, "fixed replay")
        stale = CausalInput(session_id="counterfactual", clock_id="gazebo-sim+linux-monotonic")
        base = {key: value for key, value in events[1].items() if key in {"kind", "sample_ns", "arrival_monotonic_ns", "observed_sim_ns", "camera_info"}}
        stale.accept(base, sequence=0, session_id=stale.session_id, clock_id=stale.clock_id)
        later = dict(events[3], sample_ns=253_000_001, observed_sim_ns=253_000_001, arrival_monotonic_ns=base["arrival_monotonic_ns"] + 1)
        later = {key: value for key, value in later.items() if key in {"kind", "sample_ns", "arrival_monotonic_ns", "observed_sim_ns", "width", "height"}}
        try:
            stale.accept(later, sequence=1, session_id=stale.session_id, clock_id=stale.clock_id)
        except ValueError as exc:
            counterfactual_refused = "simulation wait" in str(exc)
        require(counterfactual_refused, "simulation silence refusal")

        cleanup = supervisor.get("cleanup", {})
        require(cleanup.get("group_absent") is True and cleanup.get("no_executing_members") is True, "owned cleanup")
        require(completed.get("returncode") == 2 and completed.get("resources_after") == [], "completion resources")
        require(dispatched.get("single_actual_attempt") is True and dispatched.get("physical_run") is True, "single attempt")
    except Exception as exc:
        failures.append("audit:" + repr(exc))
    return {
        "schema": "causal-pair-simulation-time-physical-attempt-audit-v1",
        "failures": failures,
        "failure_evidence_qualified": not failures,
        "classification": CLASSIFICATION,
        "pair_wall_age_ns": pair_wall_age,
        "idle_wall_age_ns": idle_wall_age,
        "pair_sim_age_ns": pair_sim_age,
        "fixed_replay_camera_released": replay_camera,
        "simulation_silence_refused": counterfactual_refused,
        "physical_retry_performed": True,
        "complete_physical_execution_qualified": False,
        "runtime_mapping_coverage_verified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
        "fruit_fly_policy_failure": False,
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--dispatch", required=True, type=Path)
    parser.add_argument("--completion", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.capture, args.dispatch, args.completion)
    if args.output:
        write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["failure_evidence_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
