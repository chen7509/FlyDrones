"""Status synthetic admission/result checks; tests never launch Docker."""

import pytest

from tools.connectome import run_status_journal_synthetic as subject


def passing():
    source = {"file_count": 263, "profile_sha256": subject.SOURCE_PROFILE_SHA256,
              "verified": True}
    result = {
        "docker_exit": 0, "timed_out": False, "launch_error": None,
        "daemon_id_after": "fixed", "owned_container_remaining": "",
        "source_after": source, "harness_after": subject.HARNESS,
        "cdr_parity": {"independent_cdr_parity": True, "samples": 3,
                       "unavailable_ratios": ["vel_test_ratio"]},
        "cases": {
            "normal": {"writer_exit": 0, "publisher_exit": 0,
                       "audit_completed": True, "samples": 3, "training_eligible": False},
            "fsync_eio": {"writer_exit": 2, "publisher_exit": 0,
                          "audit_completed": False, "training_eligible": False,
                          "injection_marker": True},
            "close_eio": {"writer_exit": 2, "publisher_exit": 0,
                          "audit_completed": False, "training_eligible": False,
                          "injection_marker": True},
            "partial_then_eio": {"writer_exit": 2, "publisher_exit": 0,
                                 "audit_error": "truncated", "training_eligible": False,
                                 "injection_marker": True},
        },
    }
    preflight = {"daemon_id": "fixed", "source": source}
    return result, preflight


def test_qualification_needs_parity_exit_failure_and_owned_cleanup():
    result, preflight = passing()
    assert subject._qualifies(result, preflight)
    mutations = (
        ("docker_exit", 1), ("timed_out", True),
        ("daemon_id_after", "changed"), ("owned_container_remaining", "alive"),
        ("harness_after", {}), ("cdr_parity", {}),
    )
    for key, value in mutations:
        changed, before = passing()
        changed[key] = value
        assert not subject._qualifies(changed, before), key
    for mode, field, value in (
        ("normal", "samples", 2), ("normal", "audit_completed", False),
        ("fsync_eio", "writer_exit", 0), ("close_eio", "audit_completed", True),
        ("partial_then_eio", "training_eligible", True),
        ("fsync_eio", "injection_marker", False),
    ):
        changed, before = passing()
        changed["cases"][mode][field] = value
        assert not subject._qualifies(changed, before), (mode, field)


def test_existing_result_refuses_second_launch(tmp_path, monkeypatch):
    result = tmp_path / "existing"
    result.mkdir()
    monkeypatch.setattr(subject, "RESULT", result)
    monkeypatch.setattr(subject.subprocess, "run", lambda *_a, **_k: pytest.fail("launched"))
    with pytest.raises(FileExistsError):
        subject.main()
