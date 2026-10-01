import hashlib

import pytest

from flydrones.benchmark.gateway import NativeGazeboPx4Backend
from flydrones.benchmark.ulog_capture import (
    collect_ulogs,
    episode_exit_code,
    ulog_evidence_failures,
    verify_episode_ulog_evidence,
)

ULOG_HEADER = b"ULog\x01\x12\x35" + b"\0" * 9


def test_collect_ulogs_copies_only_this_runtime_and_hashes_each_file(tmp_path):
    runtime = tmp_path / "runtime" / "episode-a"
    source = runtime / "log/2026-09-22/01_00_00.ulg"
    source.parent.mkdir(parents=True)
    source.write_bytes(ULOG_HEADER + b"flight-data")
    unrelated = tmp_path / "runtime" / "episode-b/log/other.ulg"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(ULOG_HEADER + b"other-flight")

    records = collect_ulogs(runtime, tmp_path / "output")

    assert len(records) == 1
    assert records[0]["valid_header"]
    assert records[0]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (tmp_path / "output" / records[0]["path"]).read_bytes() == source.read_bytes()


def test_collect_ulogs_reports_missing_and_preserves_invalid_log(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    assert collect_ulogs(runtime, tmp_path / "missing-output") == []

    source = runtime / "log/broken.ulg"
    source.parent.mkdir()
    source.write_bytes(b"not-a-ulog")
    records = collect_ulogs(runtime, tmp_path / "invalid-output")
    assert len(records) == 1
    assert not records[0]["valid_header"]
    assert (tmp_path / "invalid-output" / records[0]["path"]).read_bytes() == source.read_bytes()


def test_collect_ulogs_refuses_to_overwrite_existing_episode_evidence(tmp_path):
    runtime = tmp_path / "runtime"
    source = runtime / "log/a.ulg"
    source.parent.mkdir(parents=True)
    source.write_bytes(ULOG_HEADER)
    output = tmp_path / "output"
    collect_ulogs(runtime, output)

    with pytest.raises(FileExistsError):
        collect_ulogs(runtime, output)


def test_backend_captures_ulog_only_after_px4_exit(tmp_path):
    output = tmp_path / "episode"
    output.mkdir()
    backend = NativeGazeboPx4Backend(tmp_path, output, {"goal": [0, 0, 1]})
    backend.runtime_path = tmp_path / "runtime"
    backend.runtime_path.mkdir()

    class FinishedPx4:
        def poll(self):
            return 0

        def wait(self, timeout):
            source = backend.runtime_path / "log/flight.ulg"
            source.parent.mkdir()
            source.write_bytes(ULOG_HEADER + b"flight")

    backend.processes = [FinishedPx4()]
    backend.close()

    assert len(backend.ulog_evidence) == 1
    assert backend.ulog_evidence[0]["valid_header"]
    assert (output / backend.ulog_evidence[0]["path"]).is_file()


def test_episode_ulog_gate_rejects_missing_corrupt_or_failed_capture():
    good = [{"valid_header": True}]
    bad = [{"valid_header": False}]

    assert ulog_evidence_failures(good, None) == []
    assert ulog_evidence_failures([], None) == ["px4_ulog_missing"]
    assert ulog_evidence_failures(bad, None) == ["px4_ulog_invalid_header"]
    assert ulog_evidence_failures(good, "copy failed") == ["px4_ulog_capture_error"]
    assert episode_exit_code("success", []) == 0
    assert episode_exit_code("collision", ["px4_ulog_missing"]) == 2
    assert episode_exit_code("controller_error", []) == 2


def test_report_gate_rechecks_saved_ulog_and_rejects_tampering(tmp_path):
    runtime = tmp_path / "runtime"
    source = runtime / "log/flight.ulg"
    source.parent.mkdir(parents=True)
    source.write_bytes(ULOG_HEADER + b"flight")
    episode = tmp_path / "episode"
    records = collect_ulogs(runtime, episode)
    result = {"px4_ulog_capture_accepted": True, "px4_ulogs": records}

    verify_episode_ulog_evidence(episode, result)
    (episode / records[0]["path"]).write_bytes(ULOG_HEADER + b"changed")
    with pytest.raises(ValueError, match="changed PX4 ULog"):
        verify_episode_ulog_evidence(episode, result)


def test_report_gate_rejects_legacy_result_without_ulog(tmp_path):
    with pytest.raises(ValueError, match="missing validated PX4 ULog"):
        verify_episode_ulog_evidence(tmp_path, {"status": "success"})
