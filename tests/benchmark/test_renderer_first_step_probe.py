import hashlib
import json
import os

import pytest

from tools.benchmark.renderer_first_step_probe import (
    baseline_mapping_identities,
    expected_renderer_mappings,
    persist_then_parse_maps,
    read_maps_snapshot,
    validate_mapping_delta,
    validate_probe_environment,
    write_json_exclusive,
)


def historical(tmp_path):
    cache = tmp_path / "cache-index"
    cache.write_text("mutable")
    libs = []
    for name in ("libA.so.1", "libB.so.2"):
        path = tmp_path / name
        path.write_text(name)
        libs.append(path)
    doc = {
        "phase": "postfirststep",
        "unknown": [
            {"path": str(libs[0]), "device": "08:30", "inode": 10},
            {"path": str(cache), "device": "08:30", "inode": 11},
            {"path": str(libs[1]), "device": "08:30", "inode": 12},
        ],
        "mismatched": [],
        "observed_files_covered": False,
        "runtime_closure_qualified": False,
    }
    path = tmp_path / "historical.json"
    path.write_text(json.dumps(doc))
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), cache, libs


def test_expected_mappings_excludes_only_declared_mutable_cache(tmp_path):
    path, sha, cache, libs = historical(tmp_path)
    result = expected_renderer_mappings(path, sha, str(cache))
    assert result["cache_path"] == str(cache.resolve())
    assert [row["path"] for row in result["libraries"]] == sorted(str(p.resolve()) for p in libs)
    assert result["historical_failure_retained"] is True
    assert result["runtime_closure_qualified"] is False


@pytest.mark.parametrize("mutation", ["hash", "phase", "covered", "missing_cache", "duplicate", "relative"])
def test_expected_mapping_contract_refuses_invalid_history(tmp_path, mutation):
    path, sha, cache, _ = historical(tmp_path)
    doc = json.loads(path.read_text())
    if mutation == "hash":
        sha = "0" * 64
    elif mutation == "phase":
        doc["phase"] = "postfinalize"
    elif mutation == "covered":
        doc["observed_files_covered"] = True
    elif mutation == "missing_cache":
        doc["unknown"] = [row for row in doc["unknown"] if row["path"] != str(cache)]
    elif mutation == "duplicate":
        doc["unknown"].append(dict(doc["unknown"][0]))
    elif mutation == "relative":
        doc["unknown"][0]["path"] = "libA.so"
    if mutation != "hash":
        path.write_text(json.dumps(doc))
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        expected_renderer_mappings(path, sha, str(cache))


def test_mapping_delta_requires_exact_expected_identity_and_no_cache(tmp_path):
    cache = "/tmp/cache"
    a = "/tmp/a.so"
    b = "/tmp/b.so"
    before = [{"path": "/usr/bin/python3", "device": "08:30", "inode": 1}]
    after = before + [
        {"path": a, "device": "08:30", "inode": 2},
        {"path": b, "device": "08:30", "inode": 3},
    ]
    expected = [
        {"path": a, "device": "08:30", "inode": 2},
        {"path": b, "device": "08:30", "inode": 3},
    ]
    result = validate_mapping_delta(before, after, expected, cache)
    assert result["exact_delta"] is True
    assert result["cache_absent"] is True
    assert result["runtime_closure_qualified"] is True


def test_mapping_delta_allows_only_identity_matched_frozen_baseline(tmp_path):
    before = [{"path": "/usr/bin/python3", "device": "08:30", "inode": 1}]
    expected = [{"path": "/tmp/new.so", "device": "08:30", "inode": 2}]
    baseline = [{"path": "/tmp/known.so", "device": "08:30", "inode": 3}]
    after = before + [dict(expected[0]), dict(baseline[0])]
    result = validate_mapping_delta(before, after, expected, "/tmp/cache", baseline)
    assert result["historical_additions"] == expected
    assert result["baseline_additions"] == baseline

    after[-1]["inode"] = 4
    with pytest.raises(ValueError, match="differs"):
        validate_mapping_delta(before, after, expected, "/tmp/cache", baseline)


def test_baseline_mapping_identities_require_stable_declared_files(tmp_path):
    library = tmp_path / "lib.so"
    library.write_text("binary")
    info = library.stat()
    doc = {
        "schema": "declared-files-v1",
        "files": [{
            "resolved": "/tmp/lib.so",
            "identity": {"device": info.st_dev, "inode": info.st_ino},
        }],
    }
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(doc))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = baseline_mapping_identities(path, sha)
    assert rows[0]["path"] == "/tmp/lib.so"

    doc["files"].append(dict(doc["files"][0]))
    path.write_text(json.dumps(doc))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert baseline_mapping_identities(path, sha) == rows

    doc["files"][-1] = json.loads(json.dumps(doc["files"][-1]))
    doc["files"][-1]["identity"]["inode"] += 1
    path.write_text(json.dumps(doc))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="conflicting"):
        baseline_mapping_identities(path, sha)


@pytest.mark.parametrize("fault", ["extra", "missing", "identity", "cache"])
def test_mapping_delta_refuses_every_deviation(tmp_path, fault):
    cache = "/tmp/cache"
    a = "/tmp/a.so"
    before = [{"path": "/usr/bin/python3", "device": "08:30", "inode": 1}]
    expected = [{"path": a, "device": "08:30", "inode": 2}]
    after = before + [dict(expected[0])]
    if fault == "extra":
        after.append({"path": "/tmp/x.so", "device": "08:30", "inode": 4})
    elif fault == "missing":
        after.pop()
    elif fault == "identity":
        after[-1]["inode"] = 99
    else:
        after.append({"path": cache, "device": "08:30", "inode": 5})
    with pytest.raises(ValueError):
        validate_mapping_delta(before, after, expected, cache)


class BadStream:
    def __init__(self, fault):
        self.fault = fault

    def write(self, value):
        if self.fault == "write":
            return len(value) - 1
        return len(value)

    def flush(self):
        if self.fault == "flush":
            raise OSError("flush")

    def close(self):
        if self.fault == "close":
            raise OSError("close")


@pytest.mark.parametrize("fault", ["write", "flush", "close"])
def test_exclusive_writer_propagates_all_io_failures(tmp_path, fault):
    with pytest.raises(OSError):
        write_json_exclusive(tmp_path / "out.json", {"ok": True}, opener=lambda *_args, **_kwargs: BadStream(fault))


def test_raw_maps_are_persisted_before_parser_failure(tmp_path):
    path = tmp_path / "maps.txt"

    def reject(_text):
        raise ValueError("deleted mapping")

    with pytest.raises(ValueError, match="deleted mapping"):
        persist_then_parse_maps("raw mapping evidence\n", path, parser=reject)
    assert path.read_text() == "raw mapping evidence\n"


def test_map_source_and_evidence_destination_cannot_alias(tmp_path):
    source = tmp_path / "proc-maps"
    evidence = tmp_path / "evidence-maps"
    raw = "1000-2000 r--p 00000000 08:30 7 /tmp/lib.so\n"
    source.write_text(raw)
    returned, rows = read_maps_snapshot(evidence, source_path=source)
    assert returned == raw
    assert evidence.read_text() == raw
    assert rows == [{"path": "/tmp/lib.so", "device": "08:30", "inode": 7}]


def test_probe_environment_requires_exact_process_environment(tmp_path, monkeypatch):
    doc = {
        "schema": "renderer-probe-environment-v1",
        "base_environment_sha256": "a" * 64,
        "materialized": {"HOME": "/home/test", "MESA_SHADER_CACHE_DISABLE": "true"},
        "ambient_inherited": False,
    }
    path = tmp_path / "environment.json"
    path.write_text(json.dumps(doc))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(os, "environ", dict(doc["materialized"]))
    assert validate_probe_environment(path, sha)["ambient_inherited"] is False

    monkeypatch.setitem(os.environ, "DISPLAY", ":0")
    with pytest.raises(ValueError, match="environment differs"):
        validate_probe_environment(path, sha)


@pytest.mark.parametrize("mutation", ["schema", "mesa", "ambient", "hash", "type"])
def test_probe_environment_rejects_invalid_declaration(tmp_path, monkeypatch, mutation):
    doc = {
        "schema": "renderer-probe-environment-v1",
        "base_environment_sha256": "a" * 64,
        "materialized": {"HOME": "/home/test", "MESA_SHADER_CACHE_DISABLE": "true"},
        "ambient_inherited": False,
    }
    if mutation == "schema":
        doc["schema"] = "other"
    elif mutation == "mesa":
        doc["materialized"]["MESA_SHADER_CACHE_DISABLE"] = "false"
    elif mutation == "ambient":
        doc["ambient_inherited"] = True
    elif mutation == "type":
        doc["materialized"]["HOME"] = None
    path = tmp_path / "environment.json"
    path.write_text(json.dumps(doc))
    sha = "0" * 64 if mutation == "hash" else hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(os, "environ", dict(doc["materialized"]))
    with pytest.raises(ValueError):
        validate_probe_environment(path, sha)
