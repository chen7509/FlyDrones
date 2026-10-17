"""An owned PX4 logger file must be byte-bound before any PX4 spawn."""

import hashlib
import json
from pathlib import Path

import pytest

from tools.benchmark import px4_logger_runtime as logger_runtime
from tools.benchmark.capture_disarmed_sensors import prepare_capture_logger
from tools.benchmark.disarmed_sensor_provenance import CaptureJournal

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "config/px4/source-diagnostic-v1"


def source_copy(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("logger_topics.txt", "profile.json"):
        (source / name).write_bytes((FIXTURE / name).read_bytes())
    return source


def test_owned_runtime_copy_is_exact_and_post_checked(tmp_path):
    source = source_copy(tmp_path)
    record = logger_runtime.profile_record(source)
    runtime = tmp_path / "owned-runtime"
    runtime.mkdir()
    staged = logger_runtime.stage_profile(record, runtime)
    copied = runtime / "etc/logging/logger_topics.txt"
    assert copied.read_bytes() == (source / "logger_topics.txt").read_bytes()
    assert staged["copied_sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest()
    assert staged["px4_environment_override"] == {"PX4_PARAM_SDLOG_PROFILE": "0"}
    assert staged["runtime_topic_selection_verified"] is False
    assert logger_runtime.verify_profile(record, staged, runtime)["copy_stable"] is True
    copied.write_bytes(b"vehicle_odometry 0 0\n")
    with pytest.raises(ValueError, match="changed"):
        logger_runtime.verify_profile(record, staged, runtime)


@pytest.mark.parametrize("mutation", ["topics", "declaration", "duplicate_json"])
def test_modified_or_ambiguous_profile_is_refused_before_copy(tmp_path, mutation):
    source = source_copy(tmp_path)
    if mutation == "topics":
        (source / "logger_topics.txt").write_bytes(b"vehicle_odometry 0 0\n")
    elif mutation == "declaration":
        profile = json.loads((source / "profile.json").read_text())
        profile["sdlog_profile"] = 131
        (source / "profile.json").write_text(json.dumps(profile))
    else:
        (source / "profile.json").write_text('{"schema":"x","schema":"y"}')
    with pytest.raises(ValueError):
        logger_runtime.profile_record(source)


def test_staging_refuses_existing_or_linked_owned_target(tmp_path):
    record = logger_runtime.profile_record(source_copy(tmp_path))
    runtime = tmp_path / "runtime"
    (runtime / "etc/logging").mkdir(parents=True)
    target = runtime / "etc/logging/logger_topics.txt"
    target.write_bytes(b"preexisting")
    with pytest.raises((FileExistsError, ValueError)):
        logger_runtime.stage_profile(record, runtime)
    target.unlink()
    external = tmp_path / "external"
    external.write_bytes(b"external")
    try:
        target.symlink_to(external)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises((FileExistsError, ValueError)):
        logger_runtime.stage_profile(record, runtime)
    assert external.read_bytes() == b"external"


def test_capture_journal_checks_copy_after_owned_runtime_ends(tmp_path):
    source = source_copy(tmp_path)
    record = logger_runtime.profile_record(source)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    result = {"status": "capture_completed", "errors": []}
    with CaptureJournal(output, result) as journal:
        staged = prepare_capture_logger({"logger_diagnostic": record}, runtime, result, journal)
        assert staged["copied_sha256"] == record["topics_sha256"]
        assert result["logger_diagnostic"]["runtime_topic_selection_verified"] is False
    assert result["status"] == "capture_completed"
    assert result["logger_diagnostic_post"]["copy_stable"] is True


def test_capture_fails_if_logger_copy_changes_before_cleanup(tmp_path):
    record = logger_runtime.profile_record(source_copy(tmp_path))
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    result = {"status": "capture_completed", "errors": []}
    with CaptureJournal(output, result) as journal:
        prepare_capture_logger({"logger_diagnostic": record}, runtime, result, journal)
        (runtime / "etc/logging/logger_topics.txt").write_bytes(b"changed\n")
    assert result["status"] == "capture_failed"
    assert any("logger" in error for error in result["errors"])


def test_post_check_refuses_logger_parent_replaced_by_link(tmp_path, monkeypatch):
    source = source_copy(tmp_path)
    record = logger_runtime.profile_record(source)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    staged = logger_runtime.stage_profile(record, runtime)
    logging = runtime / "etc/logging"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == logging or original(path))
    with pytest.raises(ValueError, match="linked"):
        logger_runtime.verify_profile(record, staged, runtime)


def test_source_change_between_validation_and_copy_is_refused_before_px4(tmp_path, monkeypatch):
    source = source_copy(tmp_path)
    record = logger_runtime.profile_record(source)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    original = logger_runtime._stable_bytes
    reads = 0

    def changed_second_topics_read(path, limit):
        nonlocal reads
        if path == source / "logger_topics.txt":
            reads += 1
            if reads == 2:
                return b"vehicle_odometry 0 0\n"
        return original(path, limit)

    monkeypatch.setattr(logger_runtime, "_stable_bytes", changed_second_topics_read)
    with pytest.raises(ValueError, match="changed"):
        logger_runtime.stage_profile(record, runtime)
    assert not (runtime / "etc/logging/logger_topics.txt").exists()
