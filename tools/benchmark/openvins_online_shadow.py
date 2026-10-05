"""Research-only bounded native transport; no network, commands or fusion grant."""

from __future__ import annotations

import hashlib
import json
import math
import os
import select
import subprocess
import threading
import time

from tools.benchmark.openvins_causal_input import CausalInput, InputRefusal


def _integer(value, *, minimum=1):
    if type(value) is not int or not minimum <= value < 2**63:
        raise ValueError("invalid signed clock/sequence")
    return value


def encode_packet(action, *, sequence, dispatch_ns, pixels=None):
    _integer(sequence, minimum=0)
    sample = _integer(action["sample_ns"])
    arrival = _integer(action["source_arrival_ns"])
    if _integer(dispatch_ns) < arrival:
        raise ValueError("dispatch precedes arrival")
    prefix = f"{sequence} {sample} {arrival} {dispatch_ns}"
    if action["kind"] == "imu":
        values = list(action["wm"]) + list(action["am"])
        try:
            valid = len(action["wm"]) == len(action["am"]) == 3 and all(
                type(v) in (int, float) and math.isfinite(v) for v in values
            )
        except OverflowError:
            valid = False
        if not valid or pixels is not None:
            raise ValueError("invalid IMU payload")
        packet = (f"I {prefix} " + " ".join(format(v, ".17g") for v in values) + "\n").encode("ascii")
        if len(packet) > 512:
            raise ValueError("oversized header")
        return packet
    if action["kind"] != "camera" or type(pixels) is not bytes or len(pixels) != 57600:
        raise ValueError("invalid owned RGB bytes")
    return f"C {prefix} 57600\n".encode("ascii") + pixels


def validate_ack(ack, *, sequence, kind, dispatch_ns, acknowledged_ns):
    if ack.get("sequence") != sequence or ack.get("kind") != kind:
        raise ValueError("native acknowledgement mismatch")
    clocks = [_integer(ack[k]) for k in ["receive_ns", "start_ns", "end_ns"]]
    if not dispatch_ns <= clocks[0] <= clocks[1] <= clocks[2] <= acknowledged_ns:
        raise ValueError("cross-process monotonic clock ordering invalid")
    return ack


class SourceWatchdog:
    """Independent of pending images: missing whole sources are failures."""

    def __init__(self, *, timeout_ns=2_000_000_000, startup_timeout_ns=None):
        self.timeout_ns = _integer(timeout_ns)
        self.startup_timeout_ns = _integer(startup_timeout_ns if startup_timeout_ns is not None else timeout_ns)
        self.started = None
        self.ready_ns = None
        self.last = {}
        self.lock = threading.Lock()

    def start(self, now):
        with self.lock:
            if self.started is not None:
                raise ValueError("source watchdog already started")
            self.started = _integer(now)

    def observe(self, kind, now):
        if kind not in {"imu", "rgb", "info"}:
            return
        with self.lock:
            _integer(now)
            if now <= self.last.get(kind, 0):
                raise ValueError("source arrival clock regressed")
            self.last[kind] = now
            if self.ready_ns is None and set(self.last) == {"imu", "rgb", "info"}:
                self.ready_ns = max(self.last.values())

    def snapshot(self):
        with self.lock:
            return dict(
                started_ns=self.started,
                ready_ns=self.ready_ns,
                last_arrivals=dict(self.last),
                startup_timeout_ns=self.startup_timeout_ns,
                operational_timeout_ns=self.timeout_ns,
            )

    def check(self, now):
        with self.lock:
            if self.started is None:
                return
            if _integer(now) < self.started:
                raise ValueError("watchdog clock regressed")
            if self.ready_ns is None:
                if now - self.started > self.startup_timeout_ns:
                    raise TimeoutError("source startup: " + ",".join(k for k in ["imu", "rgb", "info"] if k not in self.last))
                return
            missing = [k for k in ["imu", "rgb", "info"] if now - self.last.get(k, self.started) > self.timeout_ns]
            if missing:
                raise TimeoutError("source silence: " + ",".join(missing))


class NativeClient:
    """POSIX one-in-flight byte channel with a single wall deadline for write+ack."""

    def __init__(self, command, output, *, timeout_s=2.0):
        if os.name != "posix" or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("POSIX bounded transport required")
        self.timeout_s, self.sequence, self.failed = timeout_s, 0, None
        self.output, self.buffer, self.closed = output, b"", False
        self.log = (output / "native.log").open("xb")
        self.requests = (output / "native-requests.jsonl").open("x")
        self.acks = (output / "native-acks.jsonl").open("x")
        self.ack_fd, child_ack = os.pipe()
        try:
            self.process = subprocess.Popen(
                command + [str(child_ack)],
                stdin=subprocess.PIPE,
                stdout=self.log,
                stderr=subprocess.STDOUT,
                pass_fds=(child_ack,),
                bufsize=0,
            )
        except BaseException:
            os.close(self.ack_fd)
            self.log.close()
            self.requests.close()
            self.acks.close()
            raise
        finally:
            os.close(child_ack)
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.ack_fd, False)
        with (output / "native-session.json").open("x") as stream:
            json.dump(
                dict(
                    pid=self.process.pid,
                    command=command,
                    started_monotonic_ns=time.monotonic_ns(),
                    reset_counter=None,
                    quality=None,
                    fusion_eligible=False,
                ),
                stream,
                indent=2,
            )

    def send(self, action, pixels=None):
        if self.closed or self.failed:
            raise RuntimeError("native client unavailable")
        dispatch = time.monotonic_ns()
        packet = encode_packet(action, sequence=self.sequence, dispatch_ns=dispatch, pixels=pixels)
        request = dict(
            sequence=self.sequence,
            action=action,
            dispatch_ns=dispatch,
            bytes=len(packet),
            packet_sha256=hashlib.sha256(packet).hexdigest(),
            rgb_sha256=hashlib.sha256(pixels).hexdigest() if pixels is not None else None,
        )
        self.requests.write(json.dumps(request, allow_nan=False) + "\n")
        self.requests.flush()
        deadline, written = time.monotonic() + self.timeout_s, 0
        try:
            while written < len(packet) or b"\n" not in self.buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("native write/processing acknowledgement deadline")
                reads, writes, _ = select.select(
                    [self.ack_fd], [self.process.stdin] if written < len(packet) else [], [], remaining
                )
                if writes:
                    written += os.write(self.process.stdin.fileno(), packet[written:])
                if reads:
                    data = os.read(self.ack_fd, 8192)
                    if not data:
                        raise RuntimeError("native acknowledgement EOF")
                    self.buffer += data
                    if len(self.buffer) > 8192:
                        raise ValueError("oversized native acknowledgement")
            line, self.buffer = self.buffer.split(b"\n", 1)
            acknowledged = time.monotonic_ns()
            ack = json.loads(line)
            validate_ack(ack, sequence=self.sequence, kind=chr(packet[0]), dispatch_ns=dispatch, acknowledged_ns=acknowledged)
            row = dict(ack, acknowledged_ns=acknowledged, source_arrival_ns=action["source_arrival_ns"], dispatch_ns=dispatch)
            self.acks.write(json.dumps(row, allow_nan=False) + "\n")
            self.acks.flush()
            self.sequence += 1
            return row
        except BaseException as exc:
            self.failed = repr(exc)
            self.acks.write(
                json.dumps(
                    dict(
                        sequence=self.sequence,
                        refusal=self.failed,
                        refused_monotonic_ns=time.monotonic_ns(),
                        bytes_written=written,
                    )
                )
                + "\n"
            )
            self.acks.flush()
            raise

    def finish(self):
        if self.closed:
            raise RuntimeError("native client already closed")
        self.closed = True
        self.process.stdin.close()
        try:
            if self.failed:
                self.process.terminate()
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.failed = self.failed or "native exit deadline"
            self.process.kill()
            self.process.wait(timeout=3)
        finally:
            os.close(self.ack_fd)
            self.log.close()
            self.requests.close()
            self.acks.close()
        return dict(
            exit=self.process.returncode,
            accepted=self.sequence,
            failure=self.failed,
            fusion_eligible=False,
            quality=None,
            reset_counter=None,
        )


class ShadowInput:
    """Recorder-thread-only adapter. On failure, stop native delivery but retain raw recording."""

    def __init__(self, client, output, *, session_id, now=time.monotonic_ns):
        self.client, self.output, self.now = client, output, now
        self.causal = CausalInput(session_id=session_id, clock_id="gazebo-sim+linux-monotonic")
        self.sequence, self.skipped, self.delivered = 0, 0, 0
        self.pixels, self.failure = {}, None
        self.failures = (output / "shadow-failures.jsonl").open("x")

    def on_record(self, row, payload):
        kind = row["kind"]
        if kind not in {"imu", "rgb", "info"}:
            return
        if self.failure:
            self.skipped += 1
            return
        keys = {"kind", "sample_ns", "arrival_monotonic_ns", "observed_sim_ns"}
        keys |= {"imu": {"gyro_flu", "accel_flu"}, "rgb": {"width", "height"}, "info": {"camera_info"}}[kind]
        base = {key: row[key] for key in keys}
        try:
            if kind == "rgb":
                if type(payload) is not bytes or len(payload) != 57600:
                    raise ValueError("invalid RGB bytes")
                if len(self.pixels) >= 8 or row["sample_ns"] in self.pixels:
                    raise ValueError("RGB buffer capacity/duplicate")
                self.pixels[row["sample_ns"]] = payload
            actions = self.causal.accept(
                base, sequence=self.sequence, session_id=self.causal.session_id, clock_id=self.causal.clock_id
            )
            self.sequence += 1
            for action in actions:
                pixels = self.pixels.pop(action["sample_ns"]) if action["kind"] == "camera" else None
                self.client.send(action, pixels)
                self.delivered += 1
            self.causal.tick(self.now())
        except Exception as exc:
            self.failure = repr(exc)
            self.failures.write(
                json.dumps(
                    dict(
                        event=base,
                        input_sequence=self.sequence,
                        failure=self.failure,
                        wall_ns=self.now(),
                        input_refusal=exc.disposition if isinstance(exc, InputRefusal) else None,
                    ),
                    allow_nan=False,
                )
                + "\n"
            )
            self.failures.flush()

    def finish(self):
        result = dict(
            failure=self.failure,
            inputs_accepted=self.sequence,
            delivered=self.delivered,
            skipped_after_failure=self.skipped,
            pending=self.causal.finish(),
            retained_pixel_stamps=list(self.pixels),
            fusion_eligible=False,
            quality=None,
            reset_counter=None,
        )
        self.failures.close()
        with (self.output / "shadow-input-result.json").open("x") as stream:
            json.dump(result, stream, indent=2)
        return result
