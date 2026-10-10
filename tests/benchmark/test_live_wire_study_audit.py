"""Offline reader tests; synthetic journal events never prove PX4 delivery."""

import copy
import hashlib
import importlib.util
import json
import socket
import subprocess

import pytest

from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal


def api():
    assert importlib.util.find_spec("tools.benchmark.audit_live_wire_study") is not None, "raw auditor missing"
    from tools.benchmark import audit_live_wire_study

    return audit_live_wire_study


def journal_fixture(tmp_path):
    directory = tmp_path / "wire-segments"
    store = SegmentedWireJournal(directory)
    wire, cold = store.channel("wire"), store.channel("cold")
    wire.append({"kind": "synthetic-request", "value": 1})
    cold.append({"kind": "synthetic-status", "value": 2})
    store.phase("maintenance")
    wire.append({"kind": "synthetic-maintenance", "value": 3})
    store.phase("stopping")
    terminal = store.close()
    return directory, terminal


def replace_records(directory, terminal, rows):
    payload = b"".join((json.dumps(row) + "\n").encode() for row in rows)
    member = terminal["segments"][0]
    (directory / member["name"]).write_bytes(payload)
    member.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    terminal["bytes"] = len(payload)
    index = copy.deepcopy(terminal)
    index.update(complete_retention=False, manifest_scope="member_index_not_completion_grant")
    (directory / "manifest.json").write_text(json.dumps(index))


def test_reads_real_producer_segments_without_claiming_delivery(tmp_path, monkeypatch):
    module = api()
    directory, terminal = journal_fixture(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("reader started a runtime")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = module.read_segmented_wire_records(directory, terminal)
    assert [row["index"] for row in result["records"]] == [0, 1, 2]
    assert result["channels"] == {"wire": 2, "cold": 1}
    assert result["integrity_verified"] is True
    assert result["live_qualified"] is False
    assert result["fusion_qualified"] is False
    assert json.loads((directory / "manifest.json").read_text())["complete_retention"] is False
    assert terminal["complete_retention"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "bytes",
        "missing",
        "unlisted",
        "terminal_failure",
        "unsealed",
        "incomplete",
        "traversal",
        "manifest_disagreement",
        "bool_count",
        "index_gap",
        "channel_gap",
        "phase_regression",
        "unknown_source",
        "extra_row_field",
        "nonfinite",
        "duplicate_key",
    ],
)
def test_reader_refuses_incomplete_tampered_or_inconsistent_raw_evidence(tmp_path, mutation):
    module = api()
    directory, terminal = journal_fixture(tmp_path)
    member = directory / terminal["segments"][0]["name"]
    rows = [json.loads(line) for line in member.read_bytes().splitlines()]
    if mutation == "bytes":
        member.write_bytes(member.read_bytes() + b" ")
    elif mutation == "missing":
        member.unlink()
    elif mutation == "unlisted":
        (directory / "segment-0001.jsonl").write_text("hidden failed input")
    elif mutation == "terminal_failure":
        terminal["failure"] = "close failed"
    elif mutation == "unsealed":
        terminal["unsealed"] = [terminal["segments"][0]]
    elif mutation == "incomplete":
        terminal["complete_retention"] = False
    elif mutation == "traversal":
        terminal["segments"][0]["name"] = "../outside.jsonl"
    elif mutation == "manifest_disagreement":
        terminal["channels"]["cold"] = 2
    elif mutation == "bool_count":
        terminal["channels"]["cold"] = True
    elif mutation == "index_gap":
        rows[1]["index"] = 2
        replace_records(directory, terminal, rows)
    elif mutation == "channel_gap":
        rows[2]["source_index"] = 2
        replace_records(directory, terminal, rows)
    elif mutation == "phase_regression":
        rows[0]["phase"] = "stopping"
        replace_records(directory, terminal, rows)
    elif mutation == "unknown_source":
        rows[0]["source"] = "unrecorded-source"
        replace_records(directory, terminal, rows)
    elif mutation == "extra_row_field":
        rows[0]["delivered"] = True
        replace_records(directory, terminal, rows)
    elif mutation == "nonfinite":
        rows[0]["event"]["value"] = float("inf")
        replace_records(directory, terminal, rows)
    elif mutation == "duplicate_key":
        path = directory / "manifest.json"
        path.write_text(path.read_text()[:-1] + ',"closed":true}')
    with pytest.raises((ValueError, FileNotFoundError)):
        module.read_segmented_wire_records(directory, terminal)


def test_reader_refuses_json_numeric_overflow_even_with_matching_hashes(tmp_path):
    module = api()
    directory, terminal = journal_fixture(tmp_path)
    member = terminal["segments"][0]
    path = directory / member["name"]
    data = path.read_bytes().replace(b'"value":1', b'"value":1e999')
    assert b"1e999" in data
    path.write_bytes(data)
    member.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    terminal["bytes"] = len(data)
    index = copy.deepcopy(terminal)
    index.update(complete_retention=False, manifest_scope="member_index_not_completion_grant")
    (directory / "manifest.json").write_text(json.dumps(index))
    with pytest.raises(ValueError, match="nonfinite"):
        module.read_segmented_wire_records(directory, terminal)


def test_reader_preserves_channel_sequences_across_real_segment_boundary(tmp_path):
    module = api()
    directory = tmp_path / "segmented"
    store = SegmentedWireJournal(directory)
    wire, receiver = store.channel("wire"), store.channel("receiver")
    for index in range(8200):
        (wire if index % 2 == 0 else receiver).append({"kind": "synthetic", "ordinal": index})
    terminal = store.close()
    result = module.read_segmented_wire_records(directory, terminal)
    assert [row["event"]["ordinal"] for row in result["records"]] == list(range(8200))
    assert [member["records"] for member in terminal["segments"]] == [8192, 8]
    assert result["channels"] == {"wire": 4100, "receiver": 4100}
    assert result["live_qualified"] is False
