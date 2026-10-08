"""Read-only resource/calibration joins, never creates Gazebo transport objects."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from flydrones.benchmark.camera_info_capture import camera_info_fields
from tools.benchmark.audit_live_wire_study import _equal, _integer, _shape
from tools.benchmark.openvins_causal_input import raw_profile


def audit_resource_graph_records(*, declaration, pre, after_queries, graph, context, queries, documents):
    """Re-run the production XML traversal against retained native replies only.

    Does not query today's SDK or search filesystem. Declared snapshots/mappings
    need the preceding runtime audit. Every original XML byte string is hashed;
    selected resources are joined to those snapshots, not re-resolved by Python.
    """
    from tools.benchmark.bound_resource_graph import _build_graph
    from tools.benchmark.capture_contract import _unique_pairs
    from tools.benchmark.native_resource_client import _reject_constant, validate_response

    _equal(pre["resource_graph"], graph, "runtime/graph mirror")
    _equal(after_queries["files"], pre["files"], "graph-query file stability")
    selection = declaration["graph"]
    _equal(context, selection["expected_context"], "prospective SDK context")
    if type(queries) is not list or not 1 <= len(queries) <= 512 or type(documents) is not dict:
        raise ValueError("bounded resource evidence required")
    roots = [r for r in pre["files"] if r["role"] == "generated:world.sdf"]
    if len(roots) != 1:
        raise ValueError("one generated world required")
    resolver = declaration["inventory"]["graph:resolver"]
    if type(resolver) is not list or len(resolver) != 1 or not any(r["requested"] == resolver[0] for r in pre["files"]):
        raise ValueError("declared graph resolver absent")

    class RecordedClient:
        count = 0
        started = None
        last = 0.0

        def check_budget(self):
            # Original wall-time samples are checked by query(), not recreated
            # with current wall time or presented as observations of every call.
            return self.last

        def query(self, *args):
            if self.count >= len(queries):
                raise ValueError("missing original graph query")
            row = queries[self.count]
            self.count += 1
            _shape(
                row,
                (
                    "command",
                    "cwd",
                    "environment",
                    "started_monotonic",
                    "ended_monotonic",
                    "stdout",
                    "stderr",
                    "stdout_hex",
                    "stderr_hex",
                    "returncode",
                    "error",
                    "output_limit_exceeded",
                    "collection_errors",
                ),
                "native query record",
            )
            _equal(row["command"], [resolver[0], *args], "native query arguments")
            _equal(row["cwd"], selection["cwd"], "native query working directory")
            _equal(row["environment"], selection["environment"], "native query search environment")
            for key, expected in (
                ("returncode", 0),
                ("error", None),
                ("output_limit_exceeded", False),
                ("collection_errors", []),
            ):
                _equal(row[key], expected, "query " + key)
            begin, end = row["started_monotonic"], row["ended_monotonic"]
            for value in (begin, end):
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError("invalid native query clock")
            if self.started is None:
                self.started = begin
            if not self.last <= begin <= end or end - self.started >= 60:
                raise ValueError("native query clock/budget")
            self.last = end
            outputs = {}
            for key in ("stdout", "stderr"):
                try:
                    raw = bytes.fromhex(row[key + "_hex"])
                    text = raw.decode("utf8")
                except (TypeError, ValueError, UnicodeError) as exc:
                    raise ValueError("invalid retained native output") from exc
                _equal(text, row[key], "raw native output/text mirror")
                outputs[key] = raw
            if len(outputs["stdout"]) + len(outputs["stderr"]) > 1024 * 1024:
                raise ValueError("retained native output exceeded bound")
            answer = json.loads(outputs["stdout"], object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
            return validate_response(answer, args, Path(selection["cwd"]), selection["environment"])

    client = RecordedClient()
    _equal(client.query("context"), context, "original SDK context reply")
    consumed, recorded = set(), []

    def read_source(path):
        if path not in documents or type(documents[path]) is not bytes:
            raise ValueError("missing original graph document")
        consumed.add(path)
        return documents[path]

    rebuilt = _build_graph(roots[0]["requested"], client, pre["files"], read_source, recorded.append)
    _equal(rebuilt, graph, "original-byte graph traversal")
    _equal(recorded, [graph], "single completed graph")
    _equal(client.count, len(queries), "all retained queries consumed")
    _equal(consumed, set(documents), "all retained source documents consumed")
    return dict(
        raw_graph_records_consistent=True,
        documents=len(consumed),
        edges=len(graph["edges"]),
        queries=client.count,
        current_sdk_executed=False,
        decoding_or_rendering_verified=False,
        runtime_closure_qualified=False,
        live_qualified=False,
        fusion_qualified=False,
    )


def audit_camera_info_records(*, sources, payloads, manifest, first_payload):
    """Decode each raw CameraInfo with the installed official message class.

    Fixed simulation-camera profile only. No hardware/extrinsic calibration or
    accuracy claim; producer/config/runtime identities are separate audit gates.
    Payloads can also include RGB bytes for the preceding full workload check.
    """
    try:
        from google.protobuf.message import DecodeError
        from gz.msgs10.camera_info_pb2 import CameraInfo
    except ImportError as exc:
        raise ValueError("installed Gazebo CameraInfo decoder unavailable") from exc

    _shape(
        manifest,
        ("schema", "topic", "message_count", "changed_stable_fields", "first_message_sha256", "camera_info"),
        "CameraInfo manifest",
    )
    _equal(manifest["schema"], "flydrones-camera-info-v1", "CameraInfo schema")
    _equal(manifest["topic"], "/benchmark/rgbd/camera_info", "CameraInfo topic")
    _equal(manifest["message_count"], 251, "CameraInfo count")
    _equal(manifest["changed_stable_fields"], 0, "CameraInfo stable fields")
    expected = raw_profile()["camera_info"]
    _equal(manifest["camera_info"], expected, "frozen CameraInfo profile")
    if type(sources) is not list or type(payloads) is not dict or any(type(k) is not int for k in payloads):
        raise ValueError("invalid CameraInfo source inputs")
    info = [r for r in sources if r["kind"] == "info"]
    _equal(len(info), 251, "raw CameraInfo count")
    stamps = [r["sample_ns"] for r in info]
    _integer(stamps[0], 1, 99_999_999, "first camera sample")
    _equal(stamps[1:], list(range(100_000_000, 25_000_000_001, 100_000_000)), "CameraInfo cadence")
    _equal(stamps, [r["sample_ns"] for r in sources if r["kind"] == "rgb"], "CameraInfo RGB sample identity")
    previous_seq = -1
    for row in info:
        seq = row["source_sequence"]
        _integer(seq, previous_seq + 1, 30000, "CameraInfo source sequence")
        previous_seq = seq
        _equal(row["payload_path"], f"camera-info-messages/{row['sample_ns']}.pb", "CameraInfo member path")
        payload = payloads.get(seq)
        if type(payload) is not bytes or not 0 < len(payload) <= 1024 * 1024:
            raise ValueError("missing or oversized CameraInfo bytes")
        _equal(hashlib.sha256(payload).hexdigest(), row["payload_sha256"], "raw CameraInfo hash")
        message = CameraInfo()
        try:
            consumed = message.ParseFromString(payload)
        except DecodeError as exc:
            raise ValueError("malformed CameraInfo protobuf") from exc
        _equal(consumed, len(payload), "complete CameraInfo decode")
        if not message.HasField("header") or not message.header.HasField("stamp"):
            raise ValueError("missing CameraInfo timestamp")
        _integer(message.header.stamp.sec, 0, 25, "CameraInfo seconds")
        _integer(message.header.stamp.nsec, 0, 999_999_999, "CameraInfo nanoseconds")
        _equal(message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nsec, row["sample_ns"], "CameraInfo raw sample")
        # Unknown fields cannot silently expand this fixed profile. Comparing
        # parsed serialization allows protobuf field ordering without requiring
        # raw bytes to be in one serializer's canonical order.
        parsed = message.SerializeToString()
        message.DiscardUnknownFields()
        _equal(message.SerializeToString(), parsed, "unknown CameraInfo fields")
        _equal(
            [(r.key, list(r.value)) for r in message.header.data], [("frame_id", ["camera_link"])], "CameraInfo frame metadata"
        )
        _equal(list(message.rectification_matrix), [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0], "unrectified fixed camera")
        fields = camera_info_fields(message)
        _equal(fields, row["camera_info"], "CameraInfo decoded/event fields")
        _equal(fields, expected, "CameraInfo frozen calibration fields")
    _equal(first_payload, payloads[info[0]["source_sequence"]], "first CameraInfo bytes")
    _equal(hashlib.sha256(first_payload).hexdigest(), manifest["first_message_sha256"], "first CameraInfo manifest hash")
    return dict(
        decoded_messages=len(info),
        decoder="gz.msgs10.camera_info_pb2.CameraInfo",
        raw_calibration_records_consistent=True,
        hardware_calibrated=False,
        extrinsic_calibration_verified=False,
        live_qualified=False,
        fusion_qualified=False,
    )
