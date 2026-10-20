"""One owned WSL stdlib reader; retain all outputs on Windows, never launch build/resource checks."""

import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import threading
import time

OUT = Path(__file__).resolve().parent
selection = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))
caps = selection["caps"]
script = (OUT / "linux_reader.py").read_text(encoding="utf-8")
ast.parse(script)
script = "SELECTION = " + repr(selection) + "\n" + script
command = ["wsl", "-d", "Ubuntu", "--", "/usr/bin/python3", "-I", "-S", "-B", "-"]
start = time.monotonic()
result = dict(schema="native-linux-build-headers-readonly-parent-v1", command=command,
              utc_start=datetime.datetime.now(datetime.timezone.utc).isoformat(), errors=[],
              all_qualifications=False, dispatchable=False, resource_queries=False,
              compiler_or_target_executed=False, linux_file_writes=False, observed_files=[],
              stream_payload_bytes=0, stream_metadata_bytes=0, active_partial=None,
              stderr_bytes=0, linux_completion=None, bootstrap_identity_authenticated=False)
with (OUT / "start.json").open("x", encoding="utf-8") as stream:
    json.dump(dict(command=command, caps=caps, selected=len(selection["selected"]),
                   script_sha256=hashlib.sha256(script.encode()).hexdigest(),
                   utc_start=result["utc_start"]), stream, indent=2)
(OUT / "blobs").mkdir(exist_ok=False)


def exact(stream, count):
    data = bytearray()
    while len(data) < count:
        block = stream.read(count - len(data))
        if not block:
            raise EOFError("incomplete stdout frame")
        data.extend(block)
    return bytes(data)


def stdout_reader(stream):
    active = None
    try:
        with (OUT / "metadata.jsonl").open("xb") as metadata:
            while tag := stream.read(1):
                size = struct.unpack(">I", exact(stream, 4))[0]
                if tag == b"J":
                    if size > caps["metadata_bytes"] - result["stream_metadata_bytes"]:
                        raise ValueError("metadata stream cap")
                    raw = exact(stream, size)
                    result["stream_metadata_bytes"] += size
                    metadata.write(raw + b"\n")
                    metadata.flush()
                    row = json.loads(raw)
                    if row["type"] == "begin":
                        if active is not None:
                            raise ValueError("overlapping payload frames")
                        path = OUT / ("payload-" + str(row["id"]) + ".partial")
                        active = dict(row=row, path=path, stream=path.open("xb"), sha=hashlib.sha256(), size=0)
                        result["active_partial"] = str(path.name)
                    elif row["type"] == "end":
                        if active is None or active["row"]["id"] != row["id"]:
                            raise ValueError("unmatched payload completion")
                        active["stream"].flush()
                        os.fsync(active["stream"].fileno())
                        active["stream"].close()
                        if active["size"] != row["bytes"] or active["sha"].hexdigest() != row["sha256"]:
                            raise ValueError("new Linux/Windows payload transfer differs")
                        blob = OUT / "blobs" / row["sha256"]
                        if blob.exists():
                            # Keep the second actual-read temporary too; do not hide duplicate content acquisition.
                            row["duplicate_new_content_saved_as"] = active["path"].name
                        else:
                            active["path"].rename(blob)
                        result["observed_files"].append(dict(row, before=active["row"]["before"],
                                                            blob="blobs/" + row["sha256"]))
                        active = None
                        result["active_partial"] = None
                    elif row["type"] == "completion":
                        result["linux_completion"] = row
                elif tag == b"D":
                    if active is None or size > 1024**2:
                        raise ValueError("invalid bounded data frame")
                    if size > caps["total_payload_bytes"] - result["stream_payload_bytes"]:
                        raise ValueError("payload aggregate transport cap")
                    if size > caps["file_bytes"] - active["size"]:
                        raise ValueError("payload file transport cap")
                    raw = exact(stream, size)
                    active["stream"].write(raw)
                    active["sha"].update(raw)
                    active["size"] += size
                    result["stream_payload_bytes"] += size
                else:
                    raise ValueError("unknown stdout frame")
    except BaseException as exc:
        result["errors"].append("stdout: " + repr(exc))
    finally:
        if active is not None and not active["stream"].closed:
            active["stream"].close()
        stream.close()


def stderr_reader(stream):
    try:
        with (OUT / "stderr.bin").open("xb") as target:
            while block := stream.read(65536):
                if len(block) > caps["stderr_bytes"] - result["stderr_bytes"]:
                    remaining = caps["stderr_bytes"] - result["stderr_bytes"]
                    target.write(block[:remaining])
                    result["stderr_bytes"] += remaining
                    raise ValueError("2MiB stderr cap")
                result["stderr_bytes"] += len(block)
                target.write(block)
    except BaseException as exc:
        result["errors"].append("stderr: " + repr(exc))
    finally:
        stream.close()


process = None
readers = []
try:
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result["owned_windows_launcher_pid"] = process.pid
    readers = [threading.Thread(target=stdout_reader, args=(process.stdout,), daemon=True),
               threading.Thread(target=stderr_reader, args=(process.stderr,), daemon=True)]
    for reader in readers:
        reader.start()
    process.stdin.write(script.encode("utf-8"))
    process.stdin.close()
    try:
        remaining = caps["parent_wait_seconds"] - (time.monotonic() - start)
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, 30)
        result["exit"] = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        result["timed_out"] = True
        process.terminate()
        try:
            result["exit"] = process.wait(timeout=caps["terminate_seconds"])
        except subprocess.TimeoutExpired:
            process.kill()
            result["exit"] = process.wait(timeout=caps["kill_seconds"])
        result["linux_descendant_release"] = "unknown; no distro stop or competing-process control"
except BaseException as exc:
    result["errors"].append("parent: " + repr(exc))
    if process is not None and process.poll() is None:
        try:
            process.terminate()
            try:
                result["exit"] = process.wait(timeout=min(5, max(.001, 45 - (time.monotonic() - start))))
            except subprocess.TimeoutExpired:
                process.kill()
                result["exit"] = process.wait(timeout=min(5, max(.001, 45 - (time.monotonic() - start))))
            result["linux_descendant_release"] = "unknown after parent exception"
        except BaseException as cleanup:
            result["errors"].append("owned launcher cleanup: " + repr(cleanup))
finally:
    for reader in readers:
        reader.join(timeout=max(0, min(2, caps["outer_seconds"] - (time.monotonic() - start))))
    result["readers_closed"] = all(not t.is_alive() for t in readers)
    if process is not None and process.poll() is None:
        result["errors"].append("owned launcher still live; residual unknown")
    result["elapsed_s"] = time.monotonic() - start
    result["outer_exceeded"] = result["elapsed_s"] > caps["outer_seconds"]
    result["collection_complete"] = bool(result.get("exit") == 0 and result["readers_closed"]
                                         and not result["errors"] and not result["outer_exceeded"]
                                         and result["linux_completion"]
                                         and result["linux_completion"]["complete"] and result["active_partial"] is None)
    with (OUT / "collection-result.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
print(json.dumps({k: result[k] for k in ("collection_complete", "elapsed_s", "stream_payload_bytes",
                                        "stream_metadata_bytes", "stderr_bytes", "errors")}))
print(json.dumps(dict(new_observed_files=len(result["observed_files"]), linux_completion=result["linux_completion"])))
