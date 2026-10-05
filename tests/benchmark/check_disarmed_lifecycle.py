"""Standalone WSL process/payload check. No simulator or flight process is started."""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from flydrones.benchmark.camera_info_capture import camera_info_fields  # noqa: E402
from tools.benchmark.disarmed_sensor_provenance import CaptureWriter, audit_event_records, supervise_worker  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=False)
    child_code = """
import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
Path(sys.argv[1]).write_text(str(child.pid))
class Server:
    def run(self):
        time.sleep(30)  # injected blocked simulation call
Server().run()
"""
    started = time.monotonic()
    outcome = supervise_worker([sys.executable, "-c", child_code, str(output / "child.pid")], output / "blocked", timeout_s=1)
    elapsed = time.monotonic() - started
    assert outcome["status"] == "supervisor_timeout" and elapsed < 10
    child_pid = int((output / "child.pid").read_text())
    stat = Path(f"/proc/{child_pid}/stat")
    # An orphan zombie awaiting init reap consumes no execution resources.
    child_state = stat.read_text().split(") ", 1)[1].split()[0] if stat.exists() else "gone"
    assert child_state in {"gone", "Z"}, child_state
    from gz.msgs10.camera_info_pb2 import CameraInfo

    directory = output / "camera-info"
    directory.mkdir()
    writer = CaptureWriter(directory)
    for stamp in [2_000_000, 100_000_000]:
        message = CameraInfo()
        message.header.stamp.nsec = stamp
        entry = message.header.data.add()
        entry.key = "frame_id"
        entry.value.append("camera")
        message.width, message.height = 160, 120
        message.intrinsics.k.extend([1, 0, 0, 0, 1, 0, 0, 0, 1])
        message.projection.p.extend([1.0] * 12)
        writer.submit(
            dict(
                kind="info",
                sample_ns=stamp,
                observed_sim_ns=stamp,
                arrival_monotonic_ns=time.monotonic_ns(),
                camera_info=camera_info_fields(message),
            ),
            message.SerializeToString(),
        )
    writer.finish()
    rows = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    assert audit_event_records(rows, required_kinds={"info"}) == {"info": 2}
    for row in rows:
        decoded = CameraInfo()
        decoded.ParseFromString((directory / row["payload_path"]).read_bytes())
        assert decoded.header.stamp.nsec == row["sample_ns"]
    result = {
        "blocked_worker_stopped": True,
        "child_state": child_state,
        "elapsed_wall_s": elapsed,
        "distinct_camera_info_protobufs_verified": 2,
        "physical_capture_rerun": False,
    }
    with (output / "check.json").open("x") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
