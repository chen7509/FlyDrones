from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verify_camera_phase_native_parity.py"
FIXTURE = ROOT / "tests" / "fixtures" / "camera_phase_vectors.json"


def _verifier():
    assert SCRIPT.is_file(), "native parity verifier is missing"
    spec = importlib.util.spec_from_file_location("camera_phase_native_parity", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_native_fixture(path: Path, executable: Path, events: list[dict[str, object]]) -> None:
    identity = {
        "event": "native-build",
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
    }
    shuffled = [identity, *events[::2], *events[1::2]]
    path.write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in shuffled),
        encoding="utf-8",
    )


def test_verifier_accepts_shuffled_native_jsonl_with_identical_canonical_fields(tmp_path: Path):
    verifier = _verifier()
    executable = tmp_path / "native-probe"
    executable.write_bytes(b"native executable fixture")
    native_jsonl = tmp_path / "native.jsonl"
    events = verifier.build_reference_events(FIXTURE)
    _write_native_fixture(native_jsonl, executable, events)

    result = verifier.verify_native_parity(
        native_executable=executable,
        native_jsonl=native_jsonl,
        vector_fixture=FIXTURE,
    )

    assert result["matched"] is True
    assert result["canonical"]["vehicle_count"] == 5
    assert result["canonical"]["max_simultaneous_cameras_10ms"] == 1
    assert result["canonical"]["unmatched_image_count"] == 0


def test_verifier_rejects_malformed_jsonl(tmp_path: Path):
    verifier = _verifier()
    executable = tmp_path / "native-probe"
    executable.write_bytes(b"native executable fixture")
    native_jsonl = tmp_path / "native.jsonl"
    _write_native_fixture(native_jsonl, executable, verifier.build_reference_events(FIXTURE))
    with native_jsonl.open("a", encoding="utf-8") as handle:
        handle.write("{\n")

    with pytest.raises(verifier.ParityError, match="malformed JSONL"):
        verifier.verify_native_parity(
            native_executable=executable,
            native_jsonl=native_jsonl,
            vector_fixture=FIXTURE,
        )


def test_verifier_rejects_one_unmatched_native_image(tmp_path: Path):
    verifier = _verifier()
    executable = tmp_path / "native-probe"
    executable.write_bytes(b"native executable fixture")
    native_jsonl = tmp_path / "native.jsonl"
    events = verifier.build_reference_events(FIXTURE)
    events.append(
        {
            "event": "image",
            "vehicle_id": 0,
            "topic": verifier.depth_topic(0),
            "sim_ns": 3_000_000_000,
            "sequence": 999,
        }
    )
    _write_native_fixture(native_jsonl, executable, events)

    with pytest.raises(verifier.ParityError, match="canonical mismatch"):
        verifier.verify_native_parity(
            native_executable=executable,
            native_jsonl=native_jsonl,
            vector_fixture=FIXTURE,
        )


def test_verifier_rejects_native_executable_hash_mismatch(tmp_path: Path):
    verifier = _verifier()
    executable = tmp_path / "native-probe"
    executable.write_bytes(b"native executable fixture")
    native_jsonl = tmp_path / "native.jsonl"
    _write_native_fixture(native_jsonl, executable, verifier.build_reference_events(FIXTURE))
    executable.write_bytes(b"changed after fixture export")

    with pytest.raises(verifier.ParityError, match="hash mismatch"):
        verifier.verify_native_parity(
            native_executable=executable,
            native_jsonl=native_jsonl,
            vector_fixture=FIXTURE,
        )
