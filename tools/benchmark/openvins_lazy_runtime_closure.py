"""Prospective proof for one OpenVINS lazy oneTBB allocator mapping.

This module never grants whole-runtime, estimator-health, fusion, or flight
qualification.  Its active probe sends one synthetic IMU packet only to expose
the allocator mapping before a later physical study is declared.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import (
    file_record,
    parse_ldd,
    write_manifest,
)
from tools.benchmark.openvins_online_shadow import NativeClient, validate_frozen_config
from tools.benchmark.owned_group_evidence import parse_stat
from tools.benchmark.owned_runtime_maps import parse_maps

SCHEMA = "openvins-lazy-runtime-provenance-v1"
PROBE_SCHEMA = "openvins-lazy-runtime-probe-v1"
UPSTREAM_COMMIT = "8b829acc65569019edb896c5150d427f288e8aba"
ALLOCATOR_SONAME = "libtbbmalloc.so.2"


def _device_parts(value):
    if hasattr(os, "major"):
        return os.major(value), os.minor(value)
    return value >> 8 & 0xFFF, value & 0xFF | value >> 12 & 0xFFF00


def mapping_record(path):
    path = Path(path).resolve(strict=True)
    info = path.stat()
    major, minor = _device_parts(info.st_dev)
    return {"path": str(path), "device": f"{major:02x}:{minor:02x}", "inode": info.st_ino}


def _same_process(before, after):
    keys = ("pid", "pgrp", "session", "start_ticks", "executable")
    return all(before.get(key) == after.get(key) for key in keys)


def validate_historical_failure(doc, binary, allocator):
    if type(doc) is not dict or doc.get("role") != "openvins" or doc.get("phase") != "ready":
        raise ValueError("historical mapping role/phase")
    if doc.get("observed_files_covered") is not False or doc.get("mismatched") != []:
        raise ValueError("historical mapping was not one unknown-only refusal")
    before, after = doc.get("identity_before"), doc.get("identity_after")
    if type(before) is not dict or type(after) is not dict or not _same_process(before, after):
        raise ValueError("historical OpenVINS identity changed")
    if before.get("executable") != str(Path(binary).resolve(strict=True)):
        raise ValueError("historical OpenVINS executable mismatch")
    unknown = doc.get("unknown")
    expected = mapping_record(allocator)
    if type(unknown) is not list or unknown != [expected]:
        raise ValueError("historical lazy mapping is not exact")
    if "runtime process mappings are not covered" not in str(doc.get("error")):
        raise ValueError("historical refusal reason")
    return expected


def parse_control(text):
    if type(text) is not str or not text.strip() or "\n\n" in text.strip():
        raise ValueError("one package control paragraph required")
    fields, current = {}, None
    for raw in text.splitlines():
        if raw.startswith((" ", "\t")):
            if current is None:
                raise ValueError("orphan package continuation")
            fields[current] += " " + raw.strip()
            continue
        if ": " not in raw:
            raise ValueError("malformed package control field")
        current, value = raw.split(": ", 1)
        if current in fields or not current:
            raise ValueError("duplicate package control field")
        fields[current] = value.strip()
    return fields


def validate_packages(tbb_text, allocator_text):
    tbb, allocator = parse_control(tbb_text), parse_control(allocator_text)
    required = {"Package", "Status", "Source", "Version", "Depends"}
    if not required <= tbb.keys() or not required <= allocator.keys():
        raise ValueError("incomplete package metadata")
    if (tbb["Package"] != "libtbb12" or allocator["Package"] != "libtbbmalloc2"
            or tbb["Status"] != allocator["Status"] != "install ok installed"):
        raise ValueError("unexpected or unavailable oneTBB packages")
    if tbb["Status"] != "install ok installed" or allocator["Status"] != "install ok installed":
        raise ValueError("oneTBB package not installed")
    if tbb["Source"] != "onetbb" or allocator["Source"] != "onetbb" or tbb["Version"] != allocator["Version"]:
        raise ValueError("oneTBB package source/version mismatch")
    dependency = re.compile(r"(?:^|,\s*)libtbbmalloc2\s*\(=\s*" + re.escape(tbb["Version"]) + r"\)(?:,|$)")
    if dependency.search(tbb["Depends"]) is None:
        raise ValueError("libtbb12 lacks exact allocator package dependency")
    return {"source": "onetbb", "version": tbb["Version"],
            "tbb_package": "libtbb12", "allocator_package": "libtbbmalloc2",
            "exact_allocator_dependency": True}


def validate_owner(text, path, expected_package):
    if type(text) is not str or not text.strip() or type(expected_package) is not str:
        raise ValueError("package owner output required")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != 1 or ": " not in lines[0]:
        raise ValueError("one exact package owner required")
    owner, selected = lines[0].rsplit(": ", 1)
    if owner.split(":", 1)[0] != expected_package:
        raise ValueError("unexpected package owner")
    try:
        resolved = str(Path(selected).resolve(strict=True))
    except OSError as exc:
        raise ValueError("package-owned file unavailable") from exc
    if resolved != str(Path(path).resolve(strict=True)):
        raise ValueError("package owner path mismatch")
    return owner


def parse_dynamic(text):
    if type(text) is not str or not text.strip():
        raise ValueError("empty ELF dynamic section")
    needed, sonames = [], []
    for line in text.splitlines():
        if "(NEEDED)" in line:
            match = re.search(r"Shared library: \[([^\]]+)\]", line)
            if match is None:
                raise ValueError("malformed ELF needed entry")
            needed.append(match.group(1))
        if "(SONAME)" in line:
            match = re.search(r"Library soname: \[([^\]]+)\]", line)
            if match is None:
                raise ValueError("malformed ELF soname entry")
            sonames.append(match.group(1))
    if len(sonames) != 1 or len(needed) != len(set(needed)):
        raise ValueError("ambiguous ELF dynamic section")
    return {"soname": sonames[0], "needed": needed}


def parse_ldconfig_allocator(text):
    if type(text) is not str or not text.strip():
        raise ValueError("empty loader cache listing")
    matches = []
    pattern = re.compile(r"^\s*libtbbmalloc\.so\.2\s+\([^\n)]+\)\s+=>\s+(\S+)\s*$")
    for line in text.splitlines():
        match = pattern.fullmatch(line)
        if match:
            candidate = Path(match.group(1))
            if not candidate.is_absolute():
                raise ValueError("allocator loader candidate is not absolute")
            try:
                matches.append(str(candidate.resolve(strict=True)))
            except OSError as exc:
                raise ValueError("allocator loader candidate unavailable") from exc
    if len(matches) != 1:
        raise ValueError("allocator loader candidate missing or ambiguous")
    return matches[0]


def validate_upstream_source(text):
    if type(text) is not str:
        raise ValueError("invalid allocator source")
    name = re.search(r'#define\s+MALLOCLIB_NAME\s+"libtbbmalloc"\s+DEBUG_SUFFIX\s+"\.so\.2"', text)
    load = re.search(r"dynamic_link\s*\(\s*MALLOCLIB_NAME\s*,\s*MallocLinkTable\s*,\s*4\s*\)", text)
    if name is None or load is None:
        raise ValueError("upstream source does not prove lazy allocator load")
    return {"dynamic_load_name": ALLOCATOR_SONAME,
            "mechanism": "first-use dynamic_link of scalable allocator handlers"}


def build_provenance(*, binary, config, tbb, allocator, allocator_source, license_file,
                     upstream_commit, historical, ldd_output, tbb_dynamic, allocator_dynamic,
                     ldconfig_output, tbb_status, allocator_status, tbb_owner, allocator_owner,
                     ldd_parser=parse_ldd, ldconfig_parser=parse_ldconfig_allocator,
                     config_validator=validate_frozen_config):
    paths = {name: Path(value).resolve(strict=True) for name, value in {
        "binary": binary, "config": config, "tbb": tbb, "allocator": allocator,
        "allocator_source": allocator_source, "license": license_file,
    }.items()}
    if not re.fullmatch(r"[0-9a-f]{40}", upstream_commit) or upstream_commit != UPSTREAM_COMMIT:
        raise ValueError("unexpected upstream oneTBB commit")
    license_text = paths["license"].read_text(encoding="utf-8")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        raise ValueError("upstream license is not Apache-2.0")
    source_proof = validate_upstream_source(paths["allocator_source"].read_text(encoding="utf-8"))
    packages = validate_packages(tbb_status, allocator_status)
    packages["tbb_owner"] = validate_owner(tbb_owner, paths["tbb"], "libtbb12")
    packages["allocator_owner"] = validate_owner(
        allocator_owner, paths["allocator"], "libtbbmalloc2"
    )
    config_manifest = config_validator(paths["config"])
    if type(config_manifest) is not dict or not config_manifest:
        raise ValueError("frozen estimator configuration evidence required")
    ldd_paths = [str(Path(path).resolve(strict=True)) for path in ldd_parser(ldd_output, 0)]
    if str(paths["tbb"]) not in ldd_paths or str(paths["allocator"]) in ldd_paths:
        raise ValueError("ordinary ELF closure does not show the expected lazy boundary")
    tbb_elf, allocator_elf = parse_dynamic(tbb_dynamic), parse_dynamic(allocator_dynamic)
    if tbb_elf["soname"] != "libtbb.so.12" or ALLOCATOR_SONAME in tbb_elf["needed"]:
        raise ValueError("unexpected oneTBB general-library dynamic section")
    if allocator_elf["soname"] != ALLOCATOR_SONAME:
        raise ValueError("unexpected allocator SONAME")
    if ldconfig_parser(ldconfig_output) != str(paths["allocator"]):
        raise ValueError("loader cache did not select the declared allocator")
    historical_mapping = validate_historical_failure(historical, paths["binary"], paths["allocator"])
    records = {name: file_record(path) for name, path in paths.items()}
    return {
        "schema": SCHEMA,
        "files": records,
        "config_manifest": config_manifest,
        "historical_evidence": historical,
        "command_outputs": {
            "ldd": ldd_output,
            "readelf_tbb": tbb_dynamic,
            "readelf_allocator": allocator_dynamic,
            "ldconfig": ldconfig_output,
            "dpkg_status_tbb": tbb_status,
            "dpkg_status_allocator": allocator_status,
            "dpkg_owner_tbb": tbb_owner,
            "dpkg_owner_allocator": allocator_owner,
        },
        "package_relation": packages,
        "elf": {"ordinary_dependencies": ldd_paths, "tbb": tbb_elf, "allocator": allocator_elf},
        "upstream": {"repository": "https://github.com/uxlfoundation/oneTBB",
                     "tag": "v2021.11.0", "commit": upstream_commit,
                     "license": "Apache-2.0", **source_proof},
        "historical_mapping": historical_mapping,
        "predicted_mapping": records["allocator"],
        "ordinary_elf_closure_contains_allocator": False,
        "lazy_mapping_qualified": False,
        "runtime_closure_qualified": False,
        "estimator_health_qualified": False,
        "physical_execution_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
        "scope": "one predicted first-IMU lazy mapping only; later and whole-runtime mappings unqualified",
    }


def _read_maps(pid):
    return parse_maps(Path(f"/proc/{pid}/maps").read_text(encoding="utf-8"))


def _read_identity(pid):
    row = parse_stat(Path(f"/proc/{pid}/stat").read_text(encoding="utf-8"))
    row["executable"] = str(Path(f"/proc/{pid}/exe").resolve(strict=True))
    return row


def stable_mapping_snapshot(pid, reader, *, max_attempts=40, interval_s=0.05, sleeper=time.sleep):
    if type(max_attempts) is not int or max_attempts < 2 or not math.isfinite(interval_s) or interval_s < 0:
        raise ValueError("invalid stable-map limits")
    previous = None
    for _ in range(max_attempts):
        try:
            rows = reader(pid)
            normalized = sorted(parse_maps(rows) if isinstance(rows, str) else rows,
                                key=lambda row: (row["path"], row["device"], row["inode"]))
            if len(normalized) != len({(row["path"], row["device"], row["inode"]) for row in normalized}):
                raise ValueError("duplicate runtime mapping identity")
        except Exception as exc:
            raise ValueError("runtime mapping read failed") from exc
        if normalized == previous:
            return normalized
        previous = normalized
        sleeper(interval_s)
    raise TimeoutError("runtime mapping set did not stabilize")


def _validate_probe_ack(ack, arrival):
    if (type(ack) is not dict or ack.get("sequence") != 0 or ack.get("kind") != "I"
            or ack.get("sample_ns") != 1_000_000 or ack.get("source_arrival_ns") != arrival
            or ack.get("fusion_eligible") is not False or ack.get("quality") is not None
            or ack.get("reset_counter") is not None):
        raise ValueError("unexpected single-IMU acknowledgement")
    return ack


def run_probe(output, declaration, *, client_factory=NativeClient, maps_reader=_read_maps,
              identity_reader=_read_identity, sleeper=time.sleep, now=time.monotonic_ns,
              max_map_attempts=40):
    if type(declaration) is not dict or declaration.get("schema") != SCHEMA:
        raise ValueError("lazy-runtime provenance required")
    output = Path(output)
    output.mkdir(parents=False, exist_ok=False)
    result = {
        "schema": PROBE_SCHEMA,
        "probe_qualified": False,
        "lazy_mapping_qualified": False,
        "runtime_closure_qualified": False,
        "estimator_health_qualified": False,
        "physical_execution_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
        "accepted": 0,
        "failure": None,
        "scope": "single synthetic first-IMU mapping trigger; no VIO initialization or physical simulation",
    }
    error, client = None, None
    try:
        binary = declaration["files"]["binary"]["resolved"]
        config = declaration["files"]["config"]["resolved"]
        predicted = mapping_record(declaration["predicted_mapping"]["resolved"])
        if file_record(binary) != declaration["files"]["binary"] or file_record(config) != declaration["files"]["config"]:
            raise ValueError("probe binary/config drift")
        command = [binary, config, str(output / "states.jsonl"), str(output / "fast.jsonl")]
        client = client_factory(command, output)
        before_identity = identity_reader(client.process.pid)
        if before_identity.get("executable") != binary:
            raise ValueError("probe executable identity mismatch")
        before = stable_mapping_snapshot(client.process.pid, maps_reader,
                                         max_attempts=max_map_attempts, sleeper=sleeper)
        if predicted in before:
            raise ValueError("predicted lazy mapping was already present before trigger")
        arrival = now()
        if type(arrival) is not int or not 0 < arrival < 2**63:
            raise ValueError("invalid probe arrival clock")
        action = {"kind": "imu", "sample_ns": 1_000_000, "source_arrival_ns": arrival,
                  "wm": [0.0, 0.0, 0.0], "am": [0.0, 0.0, 9.81]}
        ack = _validate_probe_ack(client.send(action), arrival)
        after = stable_mapping_snapshot(client.process.pid, maps_reader,
                                        max_attempts=max_map_attempts, sleeper=sleeper)
        after_identity = identity_reader(client.process.pid)
        if not _same_process(before_identity, after_identity):
            raise ValueError("probe process identity changed")
        before_keys = {(row["path"], row["device"], row["inode"]) for row in before}
        after_keys = {(row["path"], row["device"], row["inode"]) for row in after}
        added = [{"path": path, "device": device, "inode": inode}
                 for path, device, inode in sorted(after_keys - before_keys)]
        removed = [{"path": path, "device": device, "inode": inode}
                   for path, device, inode in sorted(before_keys - after_keys)]
        if added != [predicted]:
            raise ValueError("first-IMU lazy mapping delta is not exact")
        write_manifest(output / "maps-before.json", {"identity": before_identity, "maps": before})
        write_manifest(output / "maps-after.json", {"identity": after_identity, "maps": after})
        result.update(before_identity=before_identity, after_identity=after_identity,
                      added=added, removed=removed, acknowledgement=ack)
    except BaseException as exc:
        error = exc
        result["failure"] = repr(exc)
    finally:
        if client is not None:
            try:
                client_result = client.finish()
                result["client"] = client_result
                result["accepted"] = client_result.get("accepted")
                if (client_result.get("exit") != 0 or client_result.get("accepted") != 1
                        or client_result.get("failure") is not None):
                    raise ValueError("single-IMU native client did not close cleanly")
            except BaseException as exc:
                if error is None:
                    error = exc
                    result["failure"] = repr(exc)
                else:
                    result.setdefault("cleanup_failures", []).append(repr(exc))
        if error is None:
            result["probe_qualified"] = result["lazy_mapping_qualified"] = True
        try:
            write_manifest(output / "probe-result.json", result)
        except BaseException as exc:
            if error is None:
                error = exc
            else:
                result.setdefault("evidence_failures", []).append(repr(exc))
    if error is not None:
        raise error
    return result


def run_command(command, *, timeout, runner=subprocess.run):
    completed = runner(command, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0 or not completed.stdout.strip():
        raise ValueError("dependency command failed: " + repr(command))
    return {"command": command, "returncode": completed.returncode,
            "stdout": completed.stdout, "stderr": completed.stderr}


def load_strict_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def collect_and_probe(output, *, binary, config, tbb, allocator, allocator_source,
                      license_file, historical_file, runner=subprocess.run):
    output = Path(output)
    if output.exists():
        raise FileExistsError(str(output))
    commands = {
        "ldd": run_command(["/usr/bin/ldd", str(Path(binary).resolve(strict=True))], timeout=10, runner=runner),
        "readelf_tbb": run_command(["/usr/bin/readelf", "-d", str(Path(tbb).resolve(strict=True))], timeout=10, runner=runner),
        "readelf_allocator": run_command(["/usr/bin/readelf", "-d", str(Path(allocator).resolve(strict=True))], timeout=10, runner=runner),
        "ldconfig": run_command(["/sbin/ldconfig", "-p"], timeout=10, runner=runner),
        "dpkg_status_tbb": run_command(["/usr/bin/dpkg-query", "-s", "libtbb12"], timeout=10, runner=runner),
        "dpkg_status_allocator": run_command(["/usr/bin/dpkg-query", "-s", "libtbbmalloc2"], timeout=10, runner=runner),
        "dpkg_owner_tbb": run_command(["/usr/bin/dpkg-query", "-S", str(Path(tbb).resolve(strict=True))], timeout=10, runner=runner),
        "dpkg_owner_allocator": run_command(["/usr/bin/dpkg-query", "-S", str(Path(allocator).resolve(strict=True))], timeout=10, runner=runner),
    }
    historical = load_strict_json(historical_file)
    declaration = build_provenance(
        binary=binary, config=config, tbb=tbb, allocator=allocator,
        allocator_source=allocator_source, license_file=license_file,
        upstream_commit=UPSTREAM_COMMIT, historical=historical,
        ldd_output=commands["ldd"]["stdout"],
        tbb_dynamic=commands["readelf_tbb"]["stdout"],
        allocator_dynamic=commands["readelf_allocator"]["stdout"],
        ldconfig_output=commands["ldconfig"]["stdout"],
        tbb_status=commands["dpkg_status_tbb"]["stdout"],
        allocator_status=commands["dpkg_status_allocator"]["stdout"],
        tbb_owner=commands["dpkg_owner_tbb"]["stdout"],
        allocator_owner=commands["dpkg_owner_allocator"]["stdout"],
    )
    declaration["commands"] = commands
    output.mkdir()
    write_manifest(output / "provenance.json", declaration)
    result = run_probe(output / "probe", declaration)
    return {"provenance": declaration, "probe": result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tbb", type=Path, required=True)
    parser.add_argument("--allocator", type=Path, required=True)
    parser.add_argument("--allocator-source", type=Path, required=True)
    parser.add_argument("--license-file", type=Path, required=True)
    parser.add_argument("--historical-file", type=Path, required=True)
    args = parser.parse_args(argv)
    result = collect_and_probe(**vars(args))
    print(json.dumps({"probe_qualified": result["probe"]["probe_qualified"],
                      "predicted_mapping": result["probe"]["added"]}, indent=2))


__all__ = [
    "ALLOCATOR_SONAME", "PROBE_SCHEMA", "SCHEMA", "UPSTREAM_COMMIT",
    "build_provenance", "collect_and_probe", "load_strict_json", "mapping_record",
    "parse_control", "parse_dynamic", "parse_ldconfig_allocator", "run_command", "run_probe",
    "stable_mapping_snapshot",
    "validate_historical_failure", "validate_owner", "validate_packages", "validate_upstream_source",
]


if __name__ == "__main__":
    main()
