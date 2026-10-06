"""Read-only audit for the prospective OpenVINS lazy allocator closure."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import file_record
from tools.benchmark.openvins_lazy_runtime_closure import (
    PROBE_SCHEMA,
    SCHEMA,
    UPSTREAM_COMMIT,
    mapping_record,
    parse_dynamic,
    parse_ldconfig_allocator,
    parse_ldd,
    validate_historical_failure,
    validate_owner,
    validate_packages,
    validate_upstream_source,
)
from tools.benchmark.openvins_online_shadow import encode_packet


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _require(condition, failures, label):
    if not condition:
        failures.append(label)


def _single_json_line(path):
    text = Path(path).read_text(encoding="utf-8")
    if not text.endswith("\n") or len(text.splitlines()) != 1:
        raise ValueError("expected exactly one newline-terminated JSON record")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=pairs)


def audit(output):
    output = Path(output)
    failures = []
    try:
        _require({path.name for path in output.iterdir()} == {"provenance.json", "probe"}, failures,
                 "unexpected or missing study member")
        probe_members = {
            "states.jsonl", "fast.jsonl", "native.log", "native-requests.jsonl",
            "native-acks.jsonl", "native-session.json", "maps-before.json",
            "maps-after.json", "probe-result.json",
        }
        _require({path.name for path in (output / "probe").iterdir()} == probe_members, failures,
                 "unexpected or missing probe member")
        provenance = _read(output / "provenance.json")
        probe = _read(output / "probe" / "probe-result.json")
        before = _read(output / "probe" / "maps-before.json")
        after = _read(output / "probe" / "maps-after.json")
        _require(provenance.get("schema") == SCHEMA, failures, "provenance schema")
        _require(probe.get("schema") == PROBE_SCHEMA, failures, "probe schema")
        _require(provenance.get("upstream", {}).get("commit") == UPSTREAM_COMMIT, failures,
                 "upstream commit")
        files = provenance.get("files")
        _require(type(files) is dict and set(files) == {
            "binary", "config", "tbb", "allocator", "allocator_source", "license"
        }, failures, "declared file roles")
        if type(files) is dict:
            for role, record in files.items():
                try:
                    _require(file_record(record["requested"]) == record, failures, "file drift: " + role)
                except Exception:
                    failures.append("file unavailable: " + role)
        outputs = provenance.get("command_outputs")
        expected_outputs = {"ldd", "readelf_tbb", "readelf_allocator", "ldconfig",
                            "dpkg_status_tbb", "dpkg_status_allocator",
                            "dpkg_owner_tbb", "dpkg_owner_allocator"}
        _require(type(outputs) is dict and set(outputs) == expected_outputs, failures,
                 "command output set")
        if type(outputs) is dict and expected_outputs <= outputs.keys() and type(files) is dict:
            try:
                packages = validate_packages(outputs["dpkg_status_tbb"], outputs["dpkg_status_allocator"])
                _require(packages["version"] == provenance.get("package_relation", {}).get("version"),
                         failures, "package relation")
                validate_owner(outputs["dpkg_owner_tbb"], files["tbb"]["resolved"], "libtbb12")
                validate_owner(outputs["dpkg_owner_allocator"], files["allocator"]["resolved"],
                               "libtbbmalloc2")
                _require(parse_dynamic(outputs["readelf_tbb"]) == provenance.get("elf", {}).get("tbb"),
                         failures, "tbb ELF evidence")
                _require(parse_dynamic(outputs["readelf_allocator"]) == provenance.get("elf", {}).get("allocator"),
                         failures, "allocator ELF evidence")
                _require(parse_ldconfig_allocator(outputs["ldconfig"]) == files["allocator"]["resolved"],
                         failures, "loader selection evidence")
                validate_upstream_source(Path(files["allocator_source"]["resolved"]).read_text(encoding="utf-8"))
                validate_historical_failure(provenance.get("historical_evidence"),
                                            files["binary"]["resolved"], files["allocator"]["resolved"])
                if os.name == "posix":
                    dependencies = [str(Path(path).resolve(strict=True))
                                    for path in parse_ldd(outputs["ldd"], 0)]
                    _require(dependencies == provenance.get("elf", {}).get("ordinary_dependencies"),
                             failures, "ordinary ELF dependency evidence")
            except Exception as exc:
                failures.append("provenance recomputation: " + repr(exc))
        predicted = provenance.get("predicted_mapping")
        try:
            _require(mapping_record(predicted["resolved"]) == {
                "path": predicted["resolved"],
                "device": probe.get("added", [{}])[0].get("device"),
                "inode": probe.get("added", [{}])[0].get("inode"),
            }, failures, "predicted mapping identity")
        except Exception:
            failures.append("predicted mapping unavailable")
        _require(provenance.get("ordinary_elf_closure_contains_allocator") is False, failures,
                 "ordinary closure scope")
        _require(provenance.get("lazy_mapping_qualified") is False, failures,
                 "provenance overclaim")
        _require(probe.get("probe_qualified") is True and probe.get("lazy_mapping_qualified") is True,
                 failures, "probe qualification")
        _require(probe.get("accepted") == 1 and probe.get("failure") is None, failures,
                 "single acknowledged input")
        _require(probe.get("client", {}).get("exit") == 0
                 and probe.get("client", {}).get("accepted") == 1
                 and probe.get("client", {}).get("failure") is None, failures, "clean native exit")
        try:
            request = _single_json_line(output / "probe" / "native-requests.jsonl")
            acknowledgement = _single_json_line(output / "probe" / "native-acks.jsonl")
            session = _read(output / "probe" / "native-session.json")
            action = request.get("action")
            _require(type(request) is dict and set(request) == {
                "sequence", "action", "dispatch_ns", "bytes", "packet_sha256", "rgb_sha256"
            }, failures, "request schema")
            _require(type(action) is dict and set(action) == {
                "kind", "sample_ns", "source_arrival_ns", "wm", "am"
            } and action.get("kind") == "imu" and action.get("sample_ns") == 1_000_000
                     and action.get("wm") == [0.0, 0.0, 0.0]
                     and action.get("am") == [0.0, 0.0, 9.81], failures, "request action")
            packet = encode_packet(action, sequence=request.get("sequence"),
                                   dispatch_ns=request.get("dispatch_ns"))
            _require(request.get("sequence") == 0 and request.get("bytes") == len(packet)
                     and request.get("packet_sha256") == hashlib.sha256(packet).hexdigest()
                     and request.get("rgb_sha256") is None, failures, "request packet evidence")
            _require(acknowledgement == probe.get("acknowledgement"), failures,
                     "acknowledgement evidence")
            _require(acknowledgement.get("sequence") == 0
                     and acknowledgement.get("kind") == "I"
                     and acknowledgement.get("sample_ns") == 1_000_000
                     and acknowledgement.get("source_arrival_ns") == action.get("source_arrival_ns")
                     and acknowledgement.get("dispatch_ns") == request.get("dispatch_ns")
                     and acknowledgement.get("fusion_eligible") is False
                     and acknowledgement.get("quality") is None
                     and acknowledgement.get("reset_counter") is None, failures,
                     "acknowledgement scope")
            clocks = [request.get("dispatch_ns"), acknowledgement.get("receive_ns"),
                      acknowledgement.get("start_ns"), acknowledgement.get("end_ns"),
                      acknowledgement.get("acknowledged_ns")]
            _require(all(type(value) is int and 0 < value < 2**63 for value in clocks)
                     and clocks == sorted(clocks), failures, "acknowledgement clocks")
            expected_command = [
                files["binary"]["resolved"], files["config"]["resolved"],
                str(output / "probe" / "states.jsonl"),
                str(output / "probe" / "fast.jsonl"),
            ]
            _require(type(session) is dict and set(session) == {
                "pid", "command", "started_monotonic_ns", "reset_counter", "quality",
                "fusion_eligible"
            } and session.get("pid") == probe.get("before_identity", {}).get("pid")
                     and session.get("command") == expected_command
                     and type(session.get("started_monotonic_ns")) is int
                     and 0 < session.get("started_monotonic_ns") < 2**63
                     and session.get("reset_counter") is None
                     and session.get("quality") is None
                     and session.get("fusion_eligible") is False, failures, "native session evidence")
            _require((output / "probe" / "states.jsonl").read_bytes() == b""
                     and (output / "probe" / "fast.jsonl").read_bytes() == b"", failures,
                     "one-IMU output scope")
            _require(b"native_refusal:" not in (output / "probe" / "native.log").read_bytes(),
                     failures, "native refusal log")
        except Exception as exc:
            failures.append("native protocol evidence: " + repr(exc))
        _require(probe.get("before_identity") == before.get("identity"), failures, "before identity evidence")
        _require(probe.get("after_identity") == after.get("identity"), failures, "after identity evidence")
        immutable = ("pid", "pgrp", "session", "start_ticks", "executable")
        before_identity, after_identity = probe.get("before_identity"), probe.get("after_identity")
        _require(type(before_identity) is dict and type(after_identity) is dict
                 and all(before_identity.get(key) == after_identity.get(key) for key in immutable),
                 failures, "stable probe identity")
        before_keys = {(r["path"], r["device"], r["inode"]) for r in before.get("maps", [])}
        after_keys = {(r["path"], r["device"], r["inode"]) for r in after.get("maps", [])}
        added = [{"path": path, "device": device, "inode": inode}
                 for path, device, inode in sorted(after_keys - before_keys)]
        removed = [{"path": path, "device": device, "inode": inode}
                   for path, device, inode in sorted(before_keys - after_keys)]
        _require(probe.get("added") == added and len(added) == 1, failures, "mapping delta")
        _require(probe.get("removed") == removed, failures, "removed mapping evidence")
        _require(added and added[0]["path"] == predicted.get("resolved"), failures,
                 "predicted allocator delta")
        for doc, prefix in ((provenance, "provenance"), (probe, "probe")):
            for key in ("runtime_closure_qualified", "estimator_health_qualified",
                        "physical_execution_qualified", "fusion_eligible", "flight_ready"):
                _require(doc.get(key) is False, failures, f"{prefix} overclaim: {key}")
    except Exception as exc:
        failures.append("audit exception: " + repr(exc))
    return {
        "schema": "openvins-lazy-runtime-closure-audit-v1",
        "failures": failures,
        "lazy_mapping_qualified": not failures,
        "runtime_closure_qualified": False,
        "estimator_health_qualified": False,
        "physical_execution_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
        "scope": "one first-IMU lazy allocator mapping only",
    }


__all__ = ["audit"]
