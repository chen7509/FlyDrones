"""PR48 heartbeat projection with virtual clocks and a non-estimator sink."""

import argparse
import copy
import hashlib
import json
import zipfile
from pathlib import Path

from tools.benchmark.journaled_heartbeat_lane import JournaledHeartbeatFanout
from tools.benchmark.readiness_anchor import JournaledReadiness

PIN = "07a2a247b87ff43304ec4c0fe787640264772ad12c272b354d5a5116cdecaeb2"
PREFIX = "results/supported-online-vio-dev-1701/"


class Sink:
    failure = None

    def __init__(self):
        self.rows = []

    def on_record(self, row, payload):
        assert row["kind"] == "heartbeat" and payload is None
        self.rows.append(copy.deepcopy(row))


def run(archive, output):
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == PIN
    consumed = {}
    with zipfile.ZipFile(archive) as z:

        def read(name):
            data = z.read(PREFIX + name)
            consumed[name] = hashlib.sha256(data).hexdigest()
            return data

        events = [json.loads(x) for x in read("capture-v1/events.jsonl").splitlines()]
        result = json.loads(read("capture-v1/result.json"))
    heartbeats = [r for r in events if r["kind"] == "heartbeat"]
    assert len(heartbeats) == 6
    output.mkdir(exist_ok=False)
    now = [heartbeats[0]["arrival_monotonic_ns"]]
    clock = lambda: now[0]
    readiness, baseline, sink = JournaledReadiness(clock=clock), JournaledReadiness(clock=clock), Sink()
    f = JournaledHeartbeatFanout(output, readiness, sink, clock=clock)
    mapping = []
    for i, row in enumerate(heartbeats):
        raw = {k: v for k, v in row.items() if k not in {"source_sequence", "writer_begin_monotonic_ns", "recorded_monotonic_ns"}}
        now[0] = raw["arrival_monotonic_ns"]
        f.observe_heartbeat(raw)
        mapping.append(
            dict(
                original_source_sequence=row["source_sequence"],
                projected_sequence=i,
                original_record_sha256=hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest(),
            )
        )
        if i != 5:
            now[0] = row["recorded_monotonic_ns"] + 1
            f.on_record(dict(row, source_sequence=i), None)
            assert not f.failure
    # Preserve old committed sensors; do not invent replayed native processing.
    now[0] = result["readiness"]["clock_high_water_ns"]
    for kind, row in result["readiness"]["records"].items():
        baseline.on_record(copy.deepcopy(row), None)
        if kind != "heartbeat":
            readiness.on_record(copy.deepcopy(row), None)
    assert baseline.proof() is None
    proof = f.proof()
    assert proof is not None
    callbacks = []
    assert f.pre_step(lambda: callbacks.append("synthetic only"), lambda: None)
    now[0] = heartbeats[-1]["recorded_monotonic_ns"] + 1
    f.on_record(dict(heartbeats[-1], source_sequence=5), None)
    assert f.committed == 6 and f.reconciled == 6 and not f.failure
    sink.failure = "synthetic downstream fault after reconciliation"
    assert not f.pre_step(lambda: callbacks.append("must not run"), lambda: None)
    terminal = f.finish()
    assert len(callbacks) == 1 and terminal["failure"]
    report = dict(
        archive_sha256=PIN,
        consumed_members=consumed,
        mapping=mapping,
        source_heartbeats=6,
        projected_commits=f.committed,
        baseline_ready=False,
        independent_observation_ready_at_fixed_check=True,
        downstream_fault_refused=True,
        proof=proof,
        result=terminal,
        virtual_clock=True,
        estimator_run=False,
        sensor_processing_replayed=False,
        physical_run=False,
        online_latency_measured=False,
        eligible_for_px4_fusion=False,
    )
    (output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    summary = run(args.archive, args.output)
    print(json.dumps({k: v for k, v in summary.items() if k not in ["mapping", "proof", "result"]}))
