from __future__ import annotations

import numpy as np
import pytest

from flydrones.connectome_training.px4_reset_epoch import audit_reset_epochs


def _topics(times=(10, 20, 30)):
    stamps = np.asarray(times, np.int64)
    local = {"timestamp": stamps, "timestamp_sample": stamps.copy()}
    for name in ("xy_reset_counter", "z_reset_counter", "vxy_reset_counter",
                 "vz_reset_counter", "heading_reset_counter"):
        local[name] = np.zeros(len(stamps), np.uint8)
    attitude = {"timestamp": stamps.copy(), "timestamp_sample": stamps.copy(),
                "quat_reset_counter": np.zeros(len(stamps), np.uint8)}
    return {"vehicle_local_position": local, "vehicle_attitude": attitude}


def test_nonfuture_selection_preserves_missing_frames_and_never_grants_capture():
    result = audit_reset_epochs([0, 10_000, 19_000, 30_000], _topics())
    assert result["eligible_for_live_capture"] is False
    assert result["transitions"] == []
    assert result["records"][0]["reasons"] == [
        "vehicle_attitude_missing", "vehicle_local_position_missing"]
    assert [row["selected"]["vehicle_local_position"]["index"] for row in result["records"][1:]] == [0, 0, 2]
    assert all(row["selected"]["vehicle_local_position"]["publication_us"] <= row["frame_ns"] // 1000
               for row in result["records"][1:])


def test_between_frame_reset_and_return_to_same_value_stays_latched():
    topics = _topics()
    topics["vehicle_local_position"]["xy_reset_counter"] = np.array([0, 1, 0], np.uint8)
    result = audit_reset_epochs([15_000, 35_000, 50_000], topics)
    assert result["records"][0]["reset_epoch_unresolved"] is False
    assert result["records"][1]["selected"]["vehicle_local_position"]["counters"]["xy_reset_counter"] == 0
    assert all(row["reset_epoch_unresolved"] for row in result["records"][1:])
    assert all("reset_epoch_unresolved" in row["reasons"] for row in result["records"][1:])
    assert [(row["before"], row["after"], row["publication_us"]) for row in result["transitions"]] == [
        (0, 1, 20), (1, 0, 30)]


def test_attitude_counter_wrap_is_a_reset_not_a_new_session():
    topics = _topics()
    topics["vehicle_attitude"]["quat_reset_counter"] = np.array([255, 0, 0], np.uint8)
    result = audit_reset_epochs([15_000, 25_000, 35_000], topics)
    assert result["records"][0]["reset_epoch_unresolved"] is False
    assert result["records"][1]["reset_epoch_unresolved"] is True
    assert result["transitions"][0]["before"] == 255
    assert result["transitions"][0]["after"] == 0
    assert result["transitions"][0]["topic"] == "vehicle_attitude"


@pytest.mark.parametrize("field,value", [
    ("timestamp", np.array([10, 10, 30])),
    ("timestamp", np.array([10.0, 20.0, 30.0])),
    ("timestamp_sample", np.array([10, 25, 30])),
    ("timestamp_sample", np.array([10, 10, 30])),
    ("timestamp_sample", np.array([True, True, True])),
    ("xy_reset_counter", np.array([0, 256, 0])),
    ("xy_reset_counter", np.array([0, -1, 0])),
    ("xy_reset_counter", np.array([False, False, False])),
    ("xy_reset_counter", np.array([0, 0])),
])
def test_malformed_topic_is_refused(field, value):
    topics = _topics()
    topics["vehicle_local_position"][field] = value
    with pytest.raises(ValueError):
        audit_reset_epochs([15_000, 25_000], topics)


def test_malformed_frames_or_missing_topic_are_refused():
    for frames in ([15_000, 15_000], [True, 20_000], [-1, 20_000], []):
        with pytest.raises(ValueError):
            audit_reset_epochs(frames, _topics())
    with pytest.raises(ValueError):
        audit_reset_epochs([15_000], {"vehicle_local_position": _topics()["vehicle_local_position"]})
