"""Audit one immutable estimator-aware physical attempt and classify its refusal."""

from __future__ import annotations

import json
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import write_manifest

WALL_WAIT_NS = 250_000_000


FALSE_CLAIMS = (
    "physical_execution_qualified",
    "runtime_mapping_coverage_verified",
    "runtime_closure_qualified",
    "vio_accuracy_qualified",
    "estimator_health_qualified",
    "fusion_eligible",
    "flight_ready",
    "fruit_fly_policy_failure",
)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def audit(capture, completion):
    capture = Path(capture).resolve(strict=True)
    completion = Path(completion).resolve(strict=True)
    failures = []

    def require(value, label):
        if not value:
            failures.append(label)

    try:
        result = _read(capture / "result.json")
        ulogs = _read(capture / "px4-ulog-manifest.json")
        supervisor = _read(capture / "supervisor.json")
        completed = _read(completion)
        events = _jsonl(capture / "events.jsonl")
        fanout = _jsonl(capture / "source-fanout.jsonl")

        require(result.get("status") == "capture_failed", "capture status")
        require(result.get("end_sim_ns") == 10_000_000, "failure simulation time")
        require(result.get("estimator_run") is True, "estimator started")
        cause = "pending input exceeded wall wait"
        require(cause in result.get("source_fanout", {}).get("failure", ""), "source fanout cause")
        require(result.get("shadow", {}).get("failure") == "ValueError('pending input exceeded wall wait')",
                "shadow cause")
        motion = result.get("motion", {})
        require(motion.get("active_steps") == 0 and motion.get("support_steps") == 0, "motion remained zero")
        require(motion.get("absolute_impulse_ns") == 0.0 and motion.get("anchor_ns") is None,
                "force remained zero")
        require((capture / "motion-force.jsonl").stat().st_size == 0, "force log empty")
        require(result.get("eligible_for_vio_input") is False, "VIO input closed")
        require(result.get("eligible_for_px4_fusion") is False, "fusion closed")
        require(result.get("source_fanout", {}).get("fusion_eligible") is False, "fanout fusion closed")
        require(result.get("px4_ulogs") == [] and ulogs.get("logs") == [], "no ULog")
        require(result.get("px4_exit_code") == -9 and "owned PX4 required SIGKILL" in result.get("errors", []),
                "PX4 SIGKILL retained")

        binding = result.get("runtime_binding", {})
        require(binding.get("phases") == ["postgraph", "bootstrap", "postimports", "postfinalize", "postfirststep"],
                "self runtime phases")
        require(binding.get("owned_phases", {}).get("openvins") == ["ready", "prestop"],
                "OpenVINS owned phases")
        require(binding.get("owned_phases", {}).get("px4") == [], "PX4 owned phases absent")
        require(binding.get("runtime_mapping_coverage_verified") is False, "runtime mapping remains false")

        cleanup = supervisor.get("cleanup", {})
        require(supervisor.get("capture_status") == "capture_failed" and supervisor.get("worker_exit") == 2,
                "supervisor retained failure")
        require(cleanup.get("no_executing_members") is True and cleanup.get("group_absent") is True,
                "supervisor group drained")
        require(cleanup.get("sigkill_dispatched") is False, "supervisor did not SIGKILL group")
        require(cleanup.get("final_snapshot", {}).get("members") == [], "supervisor final members empty")
        require(completed.get("returncode") == 2 and completed.get("destination_exists") is True,
                "dispatch completion")
        require(completed.get("resources_after") == [], "post-run resources empty")

        by_sequence = {row.get("source_sequence"): row for row in events}
        require(set(by_sequence) == set(range(6)), "source sequence evidence")
        info, rgb, later_imu = by_sequence[1], by_sequence[3], by_sequence[4]
        require(info.get("kind") == "info" and rgb.get("kind") == "rgb" and later_imu.get("kind") == "imu",
                "source kind evidence")
        require(info.get("sample_ns") == rgb.get("sample_ns") == 2_000_000, "camera pair stamp")
        require(later_imu.get("sample_ns") == 4_000_000, "later IMU boundary stamp")

        failed = [row for row in fanout if row.get("event") == "source_delivery" and row.get("failure")]
        require(len(failed) == 1 and failed[0].get("source_sequence") == 3, "single RGB fanout failure")
        failure_ns = result.get("source_fanout", {}).get("failure_latched_ns")
        require(type(failure_ns) is int and failed and failed[0].get("failure_latched_ns") == failure_ns,
                "failure latch identity")
        deadline = WALL_WAIT_NS
        timing = {
            "deadline_ns": deadline,
            "info_arrival_ns": info["arrival_monotonic_ns"],
            "rgb_arrival_ns": rgb["arrival_monotonic_ns"],
            "rgb_fanout_begin_ns": failed[0]["begin_ns"] if failed else None,
            "later_imu_arrival_ns": later_imu["arrival_monotonic_ns"],
            "later_imu_writer_begin_ns": later_imu["writer_begin_monotonic_ns"],
            "failure_latched_ns": failure_ns,
        }
        timing.update(
            info_to_rgb_arrival_ns=timing["rgb_arrival_ns"] - timing["info_arrival_ns"],
            info_to_failure_ns=failure_ns - timing["info_arrival_ns"],
            rgb_arrival_to_failure_ns=failure_ns - timing["rgb_arrival_ns"],
            rgb_fanout_begin_to_failure_ns=failure_ns - timing["rgb_fanout_begin_ns"],
            later_imu_arrival_after_rgb_ns=timing["later_imu_arrival_ns"] - timing["rgb_arrival_ns"],
            failure_after_later_imu_arrival_ns=failure_ns - timing["later_imu_arrival_ns"],
            later_imu_writer_begin_after_failure_ns=timing["later_imu_writer_begin_ns"] - failure_ns,
        )
        require(timing["info_to_rgb_arrival_ns"] < deadline < timing["info_to_failure_ns"],
                "deadline crossing interval")
        require(timing["later_imu_arrival_after_rgb_ns"] >= 0, "later IMU arrived after RGB")
        require(timing["failure_after_later_imu_arrival_ns"] > 0, "later IMU arrived before failure")
        require(timing["later_imu_writer_begin_after_failure_ns"] > 0, "later IMU processed after failure")
    except Exception as exc:
        failures.append("audit:" + repr(exc))
        timing = {}

    return {
        "schema": "estimator-physical-attempt-audit-v1",
        "failures": failures,
        "failure_evidence_qualified": not failures,
        "classification": "causal-input-wall-deadline-platform-scheduling-refusal",
        "scope": (
            "development transport refusal before motion/VIO accuracy; not a fruit-fly learning, "
            "OpenVINS accuracy, or swarm-policy result"
        ),
        "timing": timing,
        **{key: False for key in FALSE_CLAIMS},
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--completion", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.capture, args.completion)
    if args.output:
        write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["failure_evidence_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
