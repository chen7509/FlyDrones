import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.benchmark import openvins_lazy_runtime_closure as lazy


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


def historical(binary, allocator):
    identity = {"pid": 11, "pgrp": 11, "session": 11, "start_ticks": 7,
                "executable": str(binary.resolve()), "state": "S"}
    return {"phase": "ready", "role": "openvins", "observed_files_covered": False,
            "identity_before": identity, "identity_after": dict(identity),
            "mismatched": [], "unknown": [map_row(allocator)],
            "error": "ValueError('runtime process mappings are not covered')"}


def provenance_inputs(tmp_path):
    binary = write(tmp_path / "online_probe")
    config = write(tmp_path / "estimator_config.yaml")
    tbb = write(tmp_path / "libtbb.so.12.11")
    allocator = write(tmp_path / "libtbbmalloc.so.2.11")
    source = write(tmp_path / "allocator.cpp", '''
#define MALLOCLIB_NAME "libtbbmalloc" DEBUG_SUFFIX ".so.2"
bool success = dynamic_link(MALLOCLIB_NAME, MallocLinkTable, 4);
''')
    license_file = write(tmp_path / "LICENSE.txt", "Apache License\nVersion 2.0\n")
    return dict(
        binary=binary, config=config, tbb=tbb, allocator=allocator,
        allocator_source=source, license_file=license_file,
        upstream_commit="8b829acc65569019edb896c5150d427f288e8aba",
        historical=historical(binary, allocator),
        ldd_output=f"libtbb.so.12 => {tbb.resolve()} (0x7f00)\n",
        tbb_dynamic="0x0001 (NEEDED) Shared library: [libc.so.6]\n0x000e (SONAME) Library soname: [libtbb.so.12]\n",
        allocator_dynamic="0x0001 (NEEDED) Shared library: [libc.so.6]\n0x000e (SONAME) Library soname: [libtbbmalloc.so.2]\n",
        ldconfig_output=f"libtbbmalloc.so.2 (libc6,x86-64) => {allocator.resolve()}\n",
        tbb_status="Package: libtbb12\nStatus: install ok installed\nSource: onetbb\nVersion: 2021.11.0-2ubuntu2\nDepends: libtbbmalloc2 (= 2021.11.0-2ubuntu2), libc6\n",
        allocator_status="Package: libtbbmalloc2\nStatus: install ok installed\nSource: onetbb\nVersion: 2021.11.0-2ubuntu2\nDepends: libc6\n",
        tbb_owner=f"libtbb12:amd64: {tbb.resolve()}\n",
        allocator_owner=f"libtbbmalloc2:amd64: {allocator.resolve()}\n",
        ldd_parser=fake_ldd,
        ldconfig_parser=fake_ldconfig,
        config_validator=lambda _path: {"schema": "frozen-test-config"},
    )


def test_historical_failure_requires_one_exact_unknown_and_stable_owner(tmp_path):
    args = provenance_inputs(tmp_path)
    assert lazy.validate_historical_failure(args["historical"], args["binary"], args["allocator"])["inode"]
    for mutation in ("mismatch", "extra", "identity", "covered"):
        doc = copy.deepcopy(args["historical"])
        if mutation == "mismatch":
            doc["mismatched"] = [doc["unknown"][0]]
        elif mutation == "extra":
            doc["unknown"].append(dict(doc["unknown"][0], path="/other"))
        elif mutation == "identity":
            doc["identity_after"]["start_ticks"] += 1
        else:
            doc["observed_files_covered"] = True
        with pytest.raises(ValueError):
            lazy.validate_historical_failure(doc, args["binary"], args["allocator"])


def test_package_control_requires_exact_version_relation():
    tbb = "Package: libtbb12\nStatus: install ok installed\nSource: onetbb\nVersion: 1.2-3\nDepends: libc6, libtbbmalloc2 (= 1.2-3)\n"
    malloc = "Package: libtbbmalloc2\nStatus: install ok installed\nSource: onetbb\nVersion: 1.2-3\nDepends: libc6\n"
    assert lazy.validate_packages(tbb, malloc)["version"] == "1.2-3"
    for changed in (tbb.replace("= 1.2-3", ">= 1.2-3"), tbb.replace("1.2-3)\n", "9.0)\n")):
        with pytest.raises(ValueError):
            lazy.validate_packages(changed, malloc)


def test_package_owner_requires_one_exact_package_and_path(tmp_path):
    file = write(tmp_path / "lib.so")
    assert lazy.validate_owner(f"libtbb12:amd64: {file.resolve()}\n", file, "libtbb12") == "libtbb12:amd64"
    for text in ("", f"wrong:amd64: {file.resolve()}\n",
                 f"libtbb12:amd64: {file.resolve()}\nlibtbb12:amd64: {file.resolve()}\n"):
        with pytest.raises(ValueError):
            lazy.validate_owner(text, file, "libtbb12")


def test_build_provenance_binds_static_package_source_and_historical_layers(tmp_path):
    doc = lazy.build_provenance(**provenance_inputs(tmp_path))
    assert doc["schema"] == "openvins-lazy-runtime-provenance-v1"
    assert doc["predicted_mapping"]["resolved"].endswith("libtbbmalloc.so.2.11")
    assert doc["ordinary_elf_closure_contains_allocator"] is False
    assert doc["upstream"]["dynamic_load_name"] == "libtbbmalloc.so.2"
    assert doc["runtime_closure_qualified"] is False
    assert doc["fusion_eligible"] is False


@pytest.mark.parametrize("mutation", ["ldd-malloc", "no-tbb", "soname", "ldconfig", "source", "license", "commit", "owner"])
def test_build_provenance_rejects_ambiguity_drift_and_unsupported_source(tmp_path, mutation):
    args = provenance_inputs(tmp_path)
    if mutation == "ldd-malloc":
        args["ldd_output"] += f"libtbbmalloc.so.2 => {args['allocator'].resolve()} (0x7f02)\n"
    elif mutation == "no-tbb":
        args["ldd_output"] = f"{args['config'].resolve()} (0x7f01)\n"
    elif mutation == "soname":
        args["allocator_dynamic"] = args["allocator_dynamic"].replace("libtbbmalloc.so.2", "wrong.so.2")
    elif mutation == "ldconfig":
        args["ldconfig_output"] += "libtbbmalloc.so.2 (libc6,x86-64) => /tmp/ambiguous/libtbbmalloc.so.2\n"
    elif mutation == "source":
        args["allocator_source"].write_text("no dynamic allocator", encoding="utf-8")
    elif mutation == "license":
        args["license_file"].write_text("unknown", encoding="utf-8")
    elif mutation == "owner":
        args["allocator_owner"] = args["allocator_owner"].replace("libtbbmalloc2", "wrong")
    else:
        args["upstream_commit"] = "abc"
    with pytest.raises(ValueError):
        lazy.build_provenance(**args)


class FakeClient:
    def __init__(self, command, output, *, result=None, ack=None):
        self.process = SimpleNamespace(pid=77)
        self.command, self.output = command, output
        for name in ("states.jsonl", "fast.jsonl", "native.log", "native-requests.jsonl",
                     "native-acks.jsonl", "native-session.json"):
            (Path(output) / name).write_text("", encoding="utf-8")
        self._result = result or {"exit": 0, "accepted": 1, "failure": None,
                                  "fusion_eligible": False, "quality": None, "reset_counter": None}
        self._ack = ack or {"sequence": 0, "kind": "I", "sample_ns": 1_000_000,
                            "receive_ns": 10, "start_ns": 11, "end_ns": 12,
                            "acknowledged_ns": 13, "source_arrival_ns": 8, "dispatch_ns": 9,
                            "fusion_eligible": False, "quality": None, "reset_counter": None}
        self.actions = []

    def send(self, action):
        self.actions.append(action)
        return self._ack

    def finish(self):
        return self._result


def identity(binary):
    return {"pid": 77, "pgrp": 77, "session": 77, "start_ticks": 4,
            "state": "S", "executable": str(binary.resolve())}


def test_probe_requires_exact_single_lazy_addition_and_clean_exit(tmp_path):
    args = provenance_inputs(tmp_path)
    declaration = lazy.build_provenance(**args)
    before = [map_row(args["binary"]), map_row(args["tbb"])]
    after = before + [map_row(args["allocator"])]
    reads = iter([before, before, after, after])
    client = FakeClient([], tmp_path)
    result = lazy.run_probe(
        tmp_path / "probe", declaration,
        client_factory=lambda command, output: client,
        maps_reader=lambda _pid: next(reads),
        identity_reader=lambda _pid: identity(args["binary"]),
        sleeper=lambda _seconds: None,
        now=iter([8, 9]).__next__,
    )
    assert result["probe_qualified"] is True
    assert result["added"] == [map_row(args["allocator"])]
    assert result["accepted"] == 1
    assert client.actions[0]["am"] == [0.0, 0.0, 9.81]


@pytest.mark.parametrize("failure", ["extra", "missing", "identity", "exit", "ack", "unstable"])
def test_probe_fails_closed_and_retains_result(tmp_path, failure):
    args = provenance_inputs(tmp_path)
    declaration = lazy.build_provenance(**args)
    before = [map_row(args["binary"]), map_row(args["tbb"])]
    after = before + ([] if failure == "missing" else [map_row(args["allocator"])])
    if failure == "extra":
        other = write(tmp_path / "other.so")
        after.append(map_row(other))
    sequences = [before, before, after, after]
    if failure == "unstable":
        sequences = [[dict(before[0], inode=i)] for i in range(20)]
    reads = iter(sequences)
    result_doc = {"exit": 1 if failure == "exit" else 0, "accepted": 1, "failure": None,
                  "fusion_eligible": False, "quality": None, "reset_counter": None}
    ack = None
    if failure == "ack":
        ack = {"sequence": 2, "kind": "I", "sample_ns": 1_000_000,
               "receive_ns": 10, "start_ns": 11, "end_ns": 12,
               "acknowledged_ns": 13, "source_arrival_ns": 8, "dispatch_ns": 9,
               "fusion_eligible": False, "quality": None, "reset_counter": None}
    identities = [identity(args["binary"]), identity(args["binary"])]
    if failure == "identity":
        identities[-1] = dict(identities[-1], start_ticks=5)
    client = FakeClient([], tmp_path, result=result_doc, ack=ack)
    with pytest.raises((ValueError, TimeoutError)):
        lazy.run_probe(
            tmp_path / "probe", declaration,
            client_factory=lambda command, output: client,
            maps_reader=lambda _pid: next(reads),
            identity_reader=lambda _pid: identities.pop(0),
            sleeper=lambda _seconds: None,
            now=iter([8, 9]).__next__,
            max_map_attempts=20,
        )
    retained = json.loads((tmp_path / "probe" / "probe-result.json").read_text())
    assert retained["probe_qualified"] is False
    assert retained["fusion_eligible"] is False
    if failure in {"extra", "missing", "identity"}:
        assert (tmp_path / "probe" / "maps-before.json").exists()
        assert (tmp_path / "probe" / "maps-after.json").exists()

