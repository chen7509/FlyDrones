import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.benchmark import openvins_lazy_runtime_closure as lazy
from tools.benchmark.audit_openvins_lazy_runtime_closure import audit
from tools.benchmark.declared_runtime_snapshot import write_manifest
from tools.benchmark.openvins_online_shadow import encode_packet


def write(path, text="x"):
    path.write_text(text, encoding="utf-8")
    return path


def fake_ldd(output, returncode):
    assert returncode == 0
    return [line.split(" => ")[-1].rsplit(" (", 1)[0] for line in output.splitlines() if line.strip()]


def fake_ldconfig(output):
    matches = [line.split(" => ", 1)[1] for line in output.splitlines()
               if line.startswith("libtbbmalloc.so.2 ")]
    if len(matches) != 1:
        raise ValueError("ambiguous")
    return str(Path(matches[0]).resolve(strict=True))


def map_row(path):
    return lazy.mapping_record(path)


def identity(binary):
    return {"pid": 77, "pgrp": 77, "session": 77, "start_ticks": 4,
            "state": "S", "executable": str(binary.resolve())}


class FakeClient:
    def __init__(self, command, output):
        self.process = SimpleNamespace(pid=77)
        self.output, self.command = Path(output), command
        for name in ("states.jsonl", "fast.jsonl", "native-requests.jsonl", "native-acks.jsonl"):
            (self.output / name).write_text("", encoding="utf-8")
        (self.output / "native.log").write_text("fixture\n", encoding="utf-8")
        (self.output / "native-session.json").write_text(json.dumps({
            "pid": 77, "command": command, "started_monotonic_ns": 7,
            "reset_counter": None, "quality": None, "fusion_eligible": False,
        }), encoding="utf-8")

    def send(self, action):
        packet = encode_packet(action, sequence=0, dispatch_ns=9)
        request = {"sequence": 0, "action": action, "dispatch_ns": 9, "bytes": len(packet),
                   "packet_sha256": hashlib.sha256(packet).hexdigest(), "rgb_sha256": None}
        ack = {"sequence": 0, "kind": "I", "sample_ns": 1_000_000,
               "receive_ns": 10, "start_ns": 11, "end_ns": 12,
               "acknowledged_ns": 13, "source_arrival_ns": action["source_arrival_ns"],
               "dispatch_ns": 9, "fusion_eligible": False, "quality": None,
               "reset_counter": None}
        (self.output / "native-requests.jsonl").write_text(json.dumps(request) + "\n", encoding="utf-8")
        (self.output / "native-acks.jsonl").write_text(json.dumps(ack) + "\n", encoding="utf-8")
        return ack

    def finish(self):
        return {"exit": 0, "accepted": 1, "failure": None,
                "fusion_eligible": False, "quality": None, "reset_counter": None}


def historical(binary, allocator):
    owner = {"pid": 11, "pgrp": 11, "session": 11, "start_ticks": 7,
             "executable": str(binary.resolve()), "state": "S"}
    return {"phase": "ready", "role": "openvins", "observed_files_covered": False,
            "identity_before": owner, "identity_after": dict(owner), "mismatched": [],
            "unknown": [map_row(allocator)],
            "error": "ValueError('runtime process mappings are not covered')"}


def provenance_inputs(tmp_path):
    binary = write(tmp_path / "online_probe")
    config = write(tmp_path / "estimator_config.yaml")
    tbb = write(tmp_path / "libtbb.so.12.11")
    allocator = write(tmp_path / "libtbbmalloc.so.2.11")
    source = write(tmp_path / "allocator.cpp", '#define MALLOCLIB_NAME "libtbbmalloc" DEBUG_SUFFIX ".so.2"\nbool success = dynamic_link(MALLOCLIB_NAME, MallocLinkTable, 4);\n')
    license_file = write(tmp_path / "LICENSE.txt", "Apache License\nVersion 2.0\n")
    return dict(binary=binary, config=config, tbb=tbb, allocator=allocator,
                allocator_source=source, license_file=license_file,
                upstream_commit=lazy.UPSTREAM_COMMIT, historical=historical(binary, allocator),
                ldd_output=f"libtbb.so.12 => {tbb.resolve()} (0x7f00)\n",
                tbb_dynamic="0x1 (NEEDED) Shared library: [libc.so.6]\n0xe (SONAME) Library soname: [libtbb.so.12]\n",
                allocator_dynamic="0x1 (NEEDED) Shared library: [libc.so.6]\n0xe (SONAME) Library soname: [libtbbmalloc.so.2]\n",
                ldconfig_output=f"libtbbmalloc.so.2 (libc6,x86-64) => {allocator.resolve()}\n",
                tbb_status="Package: libtbb12\nStatus: install ok installed\nSource: onetbb\nVersion: 2021.11.0-2ubuntu2\nDepends: libtbbmalloc2 (= 2021.11.0-2ubuntu2), libc6\n",
                allocator_status="Package: libtbbmalloc2\nStatus: install ok installed\nSource: onetbb\nVersion: 2021.11.0-2ubuntu2\nDepends: libc6\n",
                tbb_owner=f"libtbb12:amd64: {tbb.resolve()}\n",
                allocator_owner=f"libtbbmalloc2:amd64: {allocator.resolve()}\n",
                ldd_parser=fake_ldd, ldconfig_parser=fake_ldconfig,
                config_validator=lambda _path: {"schema": "frozen-test-config"})


def package(tmp_path):
    args = provenance_inputs(tmp_path)
    declaration = lazy.build_provenance(**args)
    output = tmp_path / "study"
    output.mkdir()
    write_manifest(output / "provenance.json", declaration)
    before = [map_row(args["binary"]), map_row(args["tbb"])]
    after = before + [map_row(args["allocator"])]
    reads = iter([before, before, after, after])
    identities = iter([identity(args["binary"]), dict(identity(args["binary"]), state="R")])
    probe = lazy.run_probe(
        output / "probe", declaration,
        client_factory=lambda command, target: FakeClient(command, target),
        maps_reader=lambda _pid: next(reads),
        identity_reader=lambda _pid: next(identities),
        sleeper=lambda _seconds: None,
        now=iter([8, 9]).__next__,
    )
    return output, declaration, probe


def test_audit_accepts_exact_prospective_closure_without_overclaim(tmp_path):
    output, _, _ = package(tmp_path)
    result = audit(output)
    assert result["lazy_mapping_qualified"] is True
    assert result["runtime_closure_qualified"] is False
    assert result["physical_execution_qualified"] is False
    assert result["fusion_eligible"] is False


@pytest.mark.parametrize("mutation", [
    "provenance", "probe", "extra", "probe-extra", "overclaim", "drift",
    "ack", "request", "session",
])
def test_audit_rejects_tampering_missing_scope_and_file_drift(tmp_path, mutation):
    output, declaration, probe = package(tmp_path)
    if mutation == "provenance":
        doc = copy.deepcopy(declaration)
        doc["upstream"]["commit"] = "0" * 40
        (output / "provenance.json").write_text(json.dumps(doc))
    elif mutation == "probe":
        doc = copy.deepcopy(probe)
        doc["added"] = []
        (output / "probe" / "probe-result.json").write_text(json.dumps(doc))
    elif mutation == "extra":
        (output / "unexpected.txt").write_text("x")
    elif mutation == "probe-extra":
        (output / "probe" / "unexpected.txt").write_text("x")
    elif mutation == "overclaim":
        doc = copy.deepcopy(probe)
        doc["runtime_closure_qualified"] = True
        (output / "probe" / "probe-result.json").write_text(json.dumps(doc))
    elif mutation == "ack":
        (output / "probe" / "native-acks.jsonl").write_text(json.dumps({"sequence": 9}) + "\n")
    elif mutation == "request":
        row = json.loads((output / "probe" / "native-requests.jsonl").read_text())
        row["packet_sha256"] = "0" * 64
        (output / "probe" / "native-requests.jsonl").write_text(json.dumps(row) + "\n")
    elif mutation == "session":
        row = json.loads((output / "probe" / "native-session.json").read_text())
        row["command"][0] = "wrong"
        (output / "probe" / "native-session.json").write_text(json.dumps(row))
    else:
        predicted = declaration["predicted_mapping"]["resolved"]
        with open(predicted, "a", encoding="utf-8") as stream:
            stream.write("drift")
    result = audit(output)
    assert result["lazy_mapping_qualified"] is False
    assert result["failures"]
