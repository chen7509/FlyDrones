"""Bounded status journal build admission/result tests; never launch Docker."""

import pytest

from tools.connectome import run_status_journal_build as subject


def _passing_result():
    return {
        "build_started": True, "docker_exit": 0, "timed_out": False,
        "source_after_verified": True, "launch_error": None,
        "postflight_error": None, "daemon_id_before": "daemon-fixed",
        "daemon_id_after": "daemon-fixed", "owned_container_remaining": "",
        "container_inspection_error": None,
        "installed_status_sha256": subject.PX4_STATUS_SHA256,
        "collector_binary_sha256": "a" * 64,
        "generated_struct_sha256": "b" * 64,
        "generated_type_support_sha256": "c" * 64,
        "generated_type_support_library_sha256": "d" * 64,
    }


def test_qualification_needs_binary_type_source_and_cleanup():
    assert subject._qualifies(_passing_result())
    for key, replacement in (
        ("docker_exit", 1), ("timed_out", True), ("source_after_verified", False),
        ("collector_binary_sha256", None), ("installed_status_sha256", "0" * 64),
        ("daemon_id_after", "another"), ("owned_container_remaining", "alive"),
        ("postflight_error", "missing"),
    ):
        result = _passing_result()
        result[key] = replacement
        assert not subject._qualifies(result), key


def test_run_profile_is_bounded_offline_and_disclaims_live_source():
    profile = subject._profile()
    assert profile["image_id"].startswith("sha256:")
    assert profile["cpus"] == 1
    assert profile["memory_mib"] == profile["memory_swap_mib"] == 768
    assert profile["network"] == "none"
    assert profile["minimum_host_free_kib"] == 900_000
    assert profile["run_count_limit"] == 1
    assert profile["firmware_compiled_verified"] is False
    assert profile["live_source_authenticated"] is False
    assert profile["training_eligible"] is False
    assert "px4_msgs flydrones_px4_status_ros2_source" in profile["command"]


def test_existing_one_shot_result_cannot_be_restarted(tmp_path, monkeypatch):
    result = tmp_path / "existing"
    result.mkdir()
    monkeypatch.setattr(subject, "RESULT", result)
    monkeypatch.setattr(subject.subprocess, "Popen", lambda *_a, **_k: pytest.fail("launched"))
    with pytest.raises(FileExistsError):
        subject.main()
