"""Fixed sealed-source adapter exercise. No native estimator or simulator is started."""

import argparse
import hashlib
import json
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from tools.benchmark.openvins_online_shadow import ShadowInput, encode_packet
from tools.benchmark.readiness_anchor import JournaledReadiness
from tools.benchmark.ready_shadow_fanout import ReadyShadowFanout


def run(archive, output):
    expected = "17923eceadcd5aa47af882380388b8fede38f74a2992fca00a5e97a85b12aa46"
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("fixed PR43 archive changed")
    output.mkdir(parents=True, exist_ok=False)
    now, inputs = [1], []
    prefix = "results/native-reference-probe-dev-1701/capture-v1/"
    with zipfile.ZipFile(archive) as z, tempfile.TemporaryDirectory(prefix="fly-fanout-fixed-") as tmp:
        source = Path(tmp)
        consumed = []

        def consume(name):
            data = z.read(prefix + name)
            consumed.append(dict(member=prefix + name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
            return data

        rows = [json.loads(line) for line in consume("events.jsonl").splitlines()]
        packet_stream = (output / "packet-sink.jsonl").open("x")

        class RecordingOnlySink:
            sequence = 0
            counts = Counter()

            def send(self, action, pixels=None):
                packet = encode_packet(action, sequence=self.sequence, dispatch_ns=now[0], pixels=pixels)
                packet_stream.write(
                    json.dumps(
                        dict(
                            sequence=self.sequence,
                            action=action,
                            bytes=len(packet),
                            packet_sha256=hashlib.sha256(packet).hexdigest(),
                        )
                    )
                    + "\n"
                )
                self.sequence += 1
                self.counts[action["kind"]] += 1

        sink = RecordingOnlySink()
        shadow = ShadowInput(sink, output, session_id="fixed-pr43-adapter-only", now=lambda: now[0])
        ready = JournaledReadiness(clock=lambda: now[0])
        fan = ReadyShadowFanout(source, ready, shadow, clock=lambda: now[0], stream=(output / "source-fanout.jsonl").open("x"))
        ready_proofs = 0
        for seq, row in enumerate(rows):
            payload = None
            if row["kind"] in ("rgb", "info"):
                relative = "rgb-frames/" + str(row["sample_ns"]) + ".ppm" if row["kind"] == "rgb" else row["payload_path"]
                data = consume(relative)
                path = source / relative
                if not path.resolve().is_relative_to(source):
                    raise ValueError("fixed source path escape")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(data)
                payload = data[len(b"P6\n160 120\n255\n") :] if row["kind"] == "rgb" else data
            now[0] = row["recorded_monotonic_ns"] + 1
            derived = dict(row, source_sequence=seq)
            inputs.append(
                dict(sequence=seq, original_row_sha256=hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest())
            )
            fan.on_record(derived, payload)
            if fan.failure:
                raise ValueError(fan.failure)
            if fan.proof() is not None:
                ready_proofs += 1
        summary = fan.finish()
        shadow_result = shadow.finish()
        packet_stream.close()
        result = dict(
            fanout=summary,
            shadow=shadow_result,
            source_rows=len(rows),
            source_counts=dict(Counter(r["kind"] for r in rows)),
            packet_counts=dict(sink.counts),
            packet_count=sink.sequence,
            ready_proofs=ready_proofs,
            archive_sha256=actual,
            consumed_members=consumed,
            input_mapping=inputs,
            estimator_run=False,
            simulation_run=False,
            online_latency_measured=False,
            clock="virtual replay wall time = original recorded_monotonic_ns +1; not observed processing time",
            truth_input=False,
            fusion_eligible=False,
        )
        with (output / "result.json").open("x") as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps({k: v for k, v in result.items() if k not in {"consumed_members", "input_mapping", "shadow", "fanout"}}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.archive, args.output)
