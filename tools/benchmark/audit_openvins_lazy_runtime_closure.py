"""Read-only audit for the prospective OpenVINS lazy allocator closure."""

from __future__ import annotations

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


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _require(condition, failures, label):
    if not condition:
        failures.append(label)


def audit(output):
    output = Path(output)
    failures = []
    try:
        _require({path.name for path in output.iterdir()} == {"provenance.json", "probe"}, failures,
                 "unexpected or missing study member")
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
        _require(probe.get("before_identity") == before.get("identity"), failures, "before identity evidence")
        _require(probe.get("after_identity") == after.get("identity"), failures, "after identity evidence")
        _require(probe.get("before_identity") is not None
                 and probe.get("before_identity") == probe.get("after_identity"), failures,
                 "stable probe identity")
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
