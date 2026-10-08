"""Bounded offline CPU microbenchmark. Parent imports only the standard library."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FULL_MINIMUM_BYTES = 4 * 1024**3


@dataclass(frozen=True)
class ProbeSpec:
    model: str
    parameters: str
    mode: str = "full-male-cns"
    checkpoint: str | None = None
    checkpoint_sha256: str | None = None
    config_digest: str | None = None
    dataset_sha256: str | None = None
    threads: int = 14
    warmup: int = 5
    samples: int = 30
    seed: int = 20260922
    timeout_s: float = 180.

    def __post_init__(self):
        if any(type(x) is not str or not x.strip() for x in (self.model, self.parameters)):
            raise ValueError("model and parameter paths required")
        if self.mode not in {"full-male-cns", "tiny-fixture"}:
            raise ValueError("unknown model mode")
        for value, low, high in ((self.threads, 1, 64), (self.warmup, 0, 100),
                                 (self.samples, 1, 1000), (self.seed, 0, 2**63 - 1)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("invalid integer probe limit")
        if (type(self.timeout_s) not in (int, float) or not math.isfinite(self.timeout_s)
                or not 0 < self.timeout_s <= 300):
            raise ValueError("timeout must be finite in (0,300]")
        fields = (self.checkpoint, self.checkpoint_sha256, self.config_digest, self.dataset_sha256)
        if any(x is not None for x in fields):
            if (type(self.checkpoint) is not str or not self.checkpoint.strip()
                    or any(type(x) is not str or re.fullmatch(r"[0-9a-f]{64}", x) is None for x in fields[1:])):
                raise ValueError("checkpoint path and three SHA256 identities required together")


def _write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def available_memory_bytes():
    if sys.platform != "win32":
        raise OSError("this probe has no qualified available-memory observer for this platform")
    from ctypes import wintypes
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong) for name in (
                "total_physical", "available_physical", "total_pagefile", "available_pagefile",
                "total_virtual", "available_virtual", "available_extended_virtual",
            )
        ]
    value = MemoryStatus()
    value.length = ctypes.sizeof(value)
    api = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
    api.argtypes = [ctypes.POINTER(MemoryStatus)]
    api.restype = wintypes.BOOL
    if not api(ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(value.available_physical)


def _resource_check(mode):
    result = {"required_bytes": FULL_MINIMUM_BYTES if mode == "full-male-cns" else 0,
              "available_bytes": None, "allowed": False, "error": None}
    try:
        available = available_memory_bytes()
        if type(available) is not int or available <= 0:
            raise ValueError("available memory must be a positive integer")
        result.update(available_bytes=available, allowed=available >= result["required_bytes"])
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    return result


def _input_hashes(spec):
    paths = {"model": Path(spec.model), "parameters": Path(spec.parameters) / "parameters.npz",
             "parameter_manifest": Path(spec.parameters) / "manifest.json"}
    if spec.checkpoint is not None:
        paths.update(checkpoint=Path(spec.checkpoint) / "checkpoint.pt",
                     checkpoint_manifest=Path(spec.checkpoint) / "manifest.json")
    selected = [Path(__file__).resolve(), ROOT / "tools/connectome_training/profile_baseline.py"]
    selected += [ROOT / "src/flydrones/connectome_training" / name for name in (
        "profiling.py", "inference.py", "inference_artifact.py", "model.py", "features.py",
        "parameters.py", "checkpoint.py", "curriculum_session.py",
    )]
    for path in selected:
        paths[f"implementation:{path.relative_to(ROOT).as_posix()}"] = path
    return {role: {"path": str(path.resolve()), "sha256": _hash(path)} for role, path in paths.items()}


def _verify_inputs(spec, expected):
    if _input_hashes(spec) != expected:
        raise ValueError("input files changed relative to declared request")


def _read_request(output, digest):
    path = Path(output) / "request.json"
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("request hash changed")
    request = json.loads(data)
    if set(request) != {"schema", "spec", "input_hashes"} or request["schema"] != "connectome-probe-request-v1":
        raise ValueError("request schema invalid")
    return request, ProbeSpec(**request["spec"])


def _run_child(command, output, timeout_s, *, on_start=None):
    """Own just this direct worker; it has no child-launching model code."""
    output = Path(output)
    started = time.perf_counter()
    result = {"pid": None, "returncode": None, "timed_out": False, "kill_sent": False, "reaped": False}
    with (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                   cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        result["pid"] = process.pid
        try:
            try:
                if on_start is not None:
                    on_start(process.pid)
                process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                result["timed_out"] = True
                process.kill()
                result["kill_sent"] = True
                process.wait(timeout=10)
            except BaseException:
                if process.poll() is None:
                    process.kill()
                    result["kill_sent"] = True
                    process.wait(timeout=10)
                raise
        finally:
            result.update(returncode=process.returncode, reaped=process.returncode is not None,
                          elapsed_wall_s=time.perf_counter() - started)
            _write_json(output / "child.json", result)
    return result


def run_probe(spec: ProbeSpec, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    spec = replace(spec, model=str(Path(spec.model).resolve()), parameters=str(Path(spec.parameters).resolve()),
                   checkpoint=None if spec.checkpoint is None else str(Path(spec.checkpoint).resolve()))
    request = {"schema": "connectome-probe-request-v1", "spec": asdict(spec), "input_hashes": None}
    result = {"schema": "connectome-probe-parent-v1", "status": "failed", "worker_started": False,
              "flight_eligible": False, "training_success_verified": False}
    try:
        result["resource"] = _resource_check(spec.mode)
        if result["resource"]["allowed"]:
            request["input_hashes"] = _input_hashes(spec)
        _write_json(output / "request.json", request)
        if not result["resource"]["allowed"]:
            result["status"] = "resource_refused"
        else:
            digest = _hash(output / "request.json")
            result["request_sha256"] = digest
            result["child"] = _run_child([
                sys.executable, str(Path(__file__).resolve()), "--worker", str(output), "--request-sha256", digest,
            ], output, spec.timeout_s, on_start=lambda pid: result.update(worker_started=True, worker_pid=pid))
            child = result["child"]
            if child["timed_out"]:
                result["status"] = "timed_out"
            elif child["returncode"] == 0 and child["reaped"]:
                worker = json.loads((output / "worker-result.json").read_text(encoding="utf-8"))
                if worker["status"] not in {"completed", "resource_refused"} or worker["request_sha256"] != digest:
                    raise ValueError("worker report identity or status mismatch")
                result["status"] = worker["status"]
            if (output / "worker-result.json").is_file():
                result["worker_result_sha256"] = _hash(output / "worker-result.json")
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        if not (output / "request.json").exists():
            _write_json(output / "request.json", request)
        _write_json(output / "result.json", result)
        if not isinstance(error, Exception):
            raise
        return result
    _write_json(output / "result.json", result)
    return result


def _frames(start, count):
    import numpy as np

    from flydrones.connectome_training.dataset import SequenceFrame
    rgb = np.zeros((120, 160, 3), np.uint8)
    depth = np.full((120, 160), 8., np.float32)
    for index in range(start, start + count):
        yield SequenceFrame((index + 1) * 50_000_000, (index // 2 * 2 + 1) * 50_000_000,
                            rgb, depth, np.array([0., 0., 1.]), np.zeros(3), 0., 0., np.array([8., 0., 1.]))


def _worker(output, digest):
    output = Path(output)
    result = {"schema": "connectome-probe-worker-v1", "status": "failed", "request_sha256": digest,
              "flight_eligible": False, "training_success_verified": False}
    controller = None
    try:
        request, spec = _read_request(output, digest)
        result["resource"] = _resource_check(spec.mode)
        if not result["resource"]["allowed"]:
            result["status"] = "resource_refused"
        else:
            _verify_inputs(spec, request["input_hashes"])
            import torch

            from flydrones.connectome_training.curriculum_session import _peak_process_memory_bytes
            from flydrones.connectome_training.inference import ConnectomeInferenceController
            from flydrones.connectome_training.inference_artifact import CheckpointIdentity, load_inference_core
            from flydrones.connectome_training.profiling import profile_controller
            from tools.connectome_training.profile_baseline import evaluate_latency_gate
            torch.set_num_threads(spec.threads)
            # Imports may consume memory; repeat immediately before core construction.
            result["resource_before_model"] = _resource_check(spec.mode)
            if not result["resource_before_model"]["allowed"]:
                result["status"] = "resource_refused"
            else:
                identity = None if spec.checkpoint is None else CheckpointIdentity(
                    spec.checkpoint_sha256, spec.config_digest, spec.dataset_sha256,
                )
                started = time.perf_counter()
                loaded = load_inference_core(spec.model, spec.parameters, mode=spec.mode,
                                             checkpoint_path=spec.checkpoint, checkpoint_identity=identity)
                result["load_wall_s"] = time.perf_counter() - started
                if result["load_wall_s"] > 60:
                    raise TimeoutError("model load exceeded 60 seconds on return")
                controller = ConnectomeInferenceController(loaded)
                controller.reset(spec.seed)
                with (output / "samples.jsonl").open("x", encoding="utf-8") as journal:
                    def record(phase):
                        def append(row):
                            journal.write(json.dumps({"phase": phase, **row}, sort_keys=True, allow_nan=False) + "\n")
                            journal.flush()
                            if row["outer_wall_s"] > 5:
                                raise TimeoutError("step exceeded 5 seconds on return")
                        return append
                    if spec.warmup:
                        profile_controller(controller, _frames(0, spec.warmup), on_sample=record("warmup"))
                    latency = profile_controller(controller, _frames(spec.warmup, spec.samples), on_sample=record("measured"))
                _verify_inputs(spec, request["input_hashes"])
                gate = evaluate_latency_gate(latency, identity=loaded.provenance["mode"], model={
                    "neurons": loaded.provenance["neurons"], "connections": loaded.provenance["connections"],
                    "sha256": loaded.provenance["model_sha256"],
                }, maximum_p95_s=.035, minimum_samples=30)
                if spec.warmup < 5:
                    gate.update(eligible=False, passed=False)
                    gate["reasons"].append("insufficient_warmup")
                result.update(status="completed", model=loaded.provenance, latency=latency, latency_gate=gate,
                              inputs_unchanged=True, input_profile="synthetic-static-rgbd-10hz-policy20hz-v1",
                              peak_process_memory_bytes=_peak_process_memory_bytes(), threads=torch.get_num_threads(),
                              torch_version=torch.__version__, torch_git_version=torch.version.git_version,
                              python_version=sys.version, timing_scope="CPU synthetic-input step return only")
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        traceback.print_exc()
    finally:
        if controller is not None:
            controller.close()
    _write_json(output / "worker-result.json", result)
    return 0 if result["status"] in {"completed", "resource_refused"} else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--request-sha256", help=argparse.SUPPRESS)
    parser.add_argument("--model")
    parser.add_argument("--parameters")
    parser.add_argument("--output")
    parser.add_argument("--mode", default="full-male-cns", choices=["full-male-cns", "tiny-fixture"])
    for name in ("checkpoint", "checkpoint-sha256", "config-digest", "dataset-sha256"):
        parser.add_argument(f"--{name}")
    for name, default in (("threads", 14), ("warmup", 5), ("samples", 30), ("seed", 20260922)):
        parser.add_argument(f"--{name}", type=int, default=default)
    parser.add_argument("--timeout", type=float, default=180.)
    args = parser.parse_args()
    if args.worker:
        return _worker(args.worker, args.request_sha256)
    if not args.model or not args.parameters or not args.output:
        parser.error("model, parameters and output are required")
    fields = vars(args).copy()
    for key in ("worker", "request_sha256", "output"):
        fields.pop(key)
    fields["timeout_s"] = fields.pop("timeout")
    result = run_probe(ProbeSpec(**fields), args.output)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
