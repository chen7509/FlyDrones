"""Canonical file sequences reduced one frame at a time before training.

Keeps the complete small feature/label tensors, a row of each NPY member and
ZIP decompressor buffers. It does not bound total RSS or authenticate hostile
filesystem mutation. Noncanonical encodings are refused rather than eagerly
decoded through a fallback.
"""

from __future__ import annotations

import io
import json
import math
import struct
import sys
import zipfile
import zlib
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import torch

from .dataset import (
    INPUT_ARRAY_KEYS,
    SCHEMA,
    SCHEMA_V2,
    SCHEMA_V3,
    SequenceFrame,
    SequenceProvenance,
    TeacherTarget,
    TrainingSequence,
    _digest,
    _validate,
)
from .features import FEATURE_NAMES, MASKED_FEATURE_NAMES, SequenceFeatures, sequence_tensors


def _read_exact(stream, size):
    parts = bytearray()
    while len(parts) < size:
        block = stream.read(size - len(parts))
        if not block:
            raise ValueError("truncated sequence array")
        parts.extend(block)
    return parts


def _header(stream, info, count):
    version = np.lib.format.read_magic(stream)
    if version not in {(1, 0), (2, 0)}:
        raise ValueError("unsupported sequence NPY version")
    length_size = 2 if version == (1, 0) else 4
    length_bytes = _read_exact(stream, length_size)
    header_size = int.from_bytes(length_bytes, "little")
    if header_size > 10000:
        raise ValueError("sequence NPY header exceeds byte limit")
    # NumPy checks max_header_size only AFTER reading. Feed its public parser
    # an already bounded buffer, never the advertised-length archive stream.
    bounded = io.BytesIO(length_bytes + _read_exact(stream, header_size))
    parser = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
    shape, fortran, dtype = parser(bounded)
    if fortran or dtype.hasobject or not shape or any(type(n) is not int or n < 1 for n in shape) or shape[0] != count:
        raise ValueError("noncanonical sequence array header")
    limit = min(sys.maxsize, int(np.iinfo(np.intp).max))
    if any(n > limit for n in shape) or math.prod(shape) > limit or math.prod(shape) * dtype.itemsize > limit:
        raise ValueError("sequence array size is not representable")
    if stream.tell() + math.prod(shape) * dtype.itemsize != info.file_size:
        raise ValueError("sequence array payload length mismatch")
    return shape, dtype


def _member_integrity(source, info):
    """Check real decoded size, CRC and DEFLATE end without logical-size cropping.

    This extra bounded decompression pass precedes output allocations. It adds
    CPU/IO; neither raw compressed nor decoded chunks exceed 64KiB.
    """
    source.seek(info.header_offset)
    header = struct.unpack("<IHHHHHIIIHH", _read_exact(source, 30))
    signature, _, flags, method, _, _, _, _, _, name_size, extra_size = header
    if signature != 0x04034B50 or flags != info.flag_bits or method != info.compress_type or flags & 1:
        raise ValueError("noncanonical compressed member header")
    name = _read_exact(source, name_size).decode("utf-8" if flags & 0x800 else "cp437")
    if name != info.orig_filename:
        raise ValueError("compressed member name mismatch")
    _read_exact(source, extra_size)
    if method not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        raise ValueError("unsupported sequence compression method")
    decoder = zlib.decompressobj(-15) if method == zipfile.ZIP_DEFLATED else None
    remaining, decoded, crc = info.compress_size, 0, 0

    def account(block):
        nonlocal decoded, crc
        decoded += len(block)
        if decoded > info.file_size:
            raise ValueError("excess decoded member payload")
        crc = zlib.crc32(block, crc)

    while remaining:
        block = _read_exact(source, min(65536, remaining))
        remaining -= len(block)
        if decoder is None:
            account(block)
            continue
        while True:
            output = decoder.decompress(block, 65536)
            account(output)
            if decoder.unused_data or (decoder.eof and remaining):
                raise ValueError("trailing compressed member payload")
            block = decoder.unconsumed_tail
            if block or (len(output) == 65536 and not decoder.eof):
                continue
            break
    if decoder is not None and not decoder.eof:
        raise ValueError("incomplete compression terminator")
    if decoded != info.file_size:
        raise ValueError("decoded member payload length mismatch")
    if crc != info.CRC:
        raise zipfile.BadZipFile("Bad CRC in sequence member")


def load_feature_sequence(path: str | Path, *, profile: str = "legacy-v1") -> SequenceFeatures:
    width = {"legacy-v1": len(FEATURE_NAMES), "depth-mask-v3": len(MASKED_FEATURE_NAMES)}.get(profile)
    if width is None:
        raise ValueError("unsupported feature profile")
    path = Path(path)
    manifest_bytes = (path / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if set(manifest) != {"schema", "provenance", "samples", "samples_sha256"} or manifest["schema"] not in (
        SCHEMA,
        SCHEMA_V2,
        SCHEMA_V3,
    ):
        raise ValueError("unsupported training sequence schema")
    count = manifest["samples"]
    if type(count) is not int or count < 1:
        raise ValueError("sequence samples must be a positive integer")
    masked = manifest["schema"] == SCHEMA_V3
    if masked != (profile == "depth-mask-v3"):
        raise ValueError("sequence schema and feature profile mismatch")
    provenance = SequenceProvenance(**manifest["provenance"])
    samples = path / "samples.npz"
    before = _digest(samples)
    if before != manifest["samples_sha256"]:
        raise ValueError("samples.npz hash mismatch")
    required = set(INPUT_ARRAY_KEYS) | {
        "teacher_velocity_enu",
        "teacher_yaw_rate",
        "teacher_horizon_enu",
        "teacher_minimum_clearance_m",
        "teacher_terminal",
    }
    if manifest["schema"] != SCHEMA:
        required.add("teacher_horizon_valid")
    if masked:
        required.add("depth_valid")
    with zipfile.ZipFile(samples) as archive, ExitStack() as stack:
        infos = archive.infolist()
        if (
            len(infos) != len(required)
            or {i.filename for i in infos} != {name + ".npy" for name in required}
            or any(i.orig_filename != i.filename for i in infos)
        ):
            raise ValueError("sequence array membership mismatch or duplicate")
        if any(i.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} for i in infos):
            raise ValueError("unsupported sequence compression method")
        streams, headers = {}, {}
        for info in infos:
            name = info.filename[:-4]
            streams[name] = stack.enter_context(archive.open(info))
            headers[name] = _header(streams[name], info, count)
        depth_shape = headers["depth_m"][0]
        horizon_shape = headers["teacher_horizon_enu"][0]
        if len(depth_shape) != 3 or depth_shape[2] < 3 or len(horizon_shape) != 3 or horizon_shape[2] != 3:
            raise ValueError("sequence image or horizon geometry invalid")
        shapes = {name: (count,) for name in required}
        shapes.update({name: (count, 3) for name in ("position_enu", "velocity_enu", "goal_enu", "teacher_velocity_enu")})
        shapes.update(rgb=(*depth_shape, 3), depth_m=depth_shape, teacher_horizon_enu=horizon_shape)
        if "teacher_horizon_valid" in required:
            shapes["teacher_horizon_valid"] = horizon_shape[:2]
        if masked:
            shapes["depth_valid"] = depth_shape
        for name, (shape, dtype) in headers.items():
            expected = np.dtype(
                "int64"
                if name in {"sim_ns", "frame_ns"}
                else "uint8"
                if name == "rgb"
                else "bool"
                if name in {"depth_valid", "teacher_horizon_valid", "teacher_terminal"}
                else "float32"
            )
            if shape != shapes[name] or dtype != expected:
                raise ValueError(f"noncanonical sequence {name} shape or dtype")
        limit = min(sys.maxsize, int(np.iinfo(np.intp).max))
        if count * max(width, 4) * np.dtype("float32").itemsize > limit:
            raise ValueError("reduced output size is not representable")
        with samples.open("rb") as source:
            for info in infos:
                _member_integrity(source, info)
        features = np.empty((count, width), np.float32)
        commands = np.empty((count, 4), np.float32)
        clearance = np.empty(count, np.float32)
        previous = None
        for index in range(count):
            rows = {}
            for name, (shape, dtype) in headers.items():
                row_shape = shape[1:]
                rows[name] = np.frombuffer(
                    _read_exact(streams[name], math.prod(row_shape) * dtype.itemsize), dtype=dtype
                ).reshape(row_shape)
            frame = SequenceFrame(
                int(rows["sim_ns"]),
                int(rows["frame_ns"]),
                rows["rgb"],
                rows["depth_m"],
                rows["position_enu"],
                rows["velocity_enu"],
                float(rows["yaw"]),
                float(rows["yaw_rate"]),
                rows["goal_enu"],
                rows.get("depth_valid"),
            )
            target = TeacherTarget(
                rows["teacher_velocity_enu"],
                float(rows["teacher_yaw_rate"]),
                rows["teacher_horizon_enu"],
                float(rows["teacher_minimum_clearance_m"]),
                bool(rows["teacher_terminal"]),
                rows.get("teacher_horizon_valid", np.ones(horizon_shape[1], dtype=bool)),
            )
            if previous is not None and frame.sim_ns <= previous:
                raise ValueError("frames require strictly increasing sim_ns")
            previous = frame.sim_ns
            one = TrainingSequence(provenance, [frame], [target])
            _validate(one)
            x, y, c = sequence_tensors(one, profile=profile)
            features[index], commands[index], clearance[index] = x[0, 0].numpy(), y[0, 0].numpy(), c[0, 0].numpy()
            del one, frame, target, rows, x, y, c
        for stream in streams.values():
            if stream.read(1):
                raise ValueError("trailing sequence array payload")
    if _digest(samples) != before or (path / "manifest.json").read_bytes() != manifest_bytes:
        raise ValueError("sequence files changed during feature decode")
    return SequenceFeatures(
        provenance,
        profile,
        torch.from_numpy(features).unsqueeze(0),
        torch.from_numpy(commands).unsqueeze(0),
        torch.from_numpy(clearance).unsqueeze(0),
    )
