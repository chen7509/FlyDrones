"""Synthetic source/native evidence; no simulator, sockets or estimator process."""

import copy
import importlib.util

import pytest

from tests.benchmark.live_wire_source_fixture import build_chain


def api():
    name = "tools.benchmark.audit_live_wire_workload"
    assert importlib.util.find_spec(name) is not None, "raw workload audit missing"
    return __import__(name, fromlist=["audit_source_native_records"]).audit_source_native_records


@pytest.fixture(scope="module")
def chain():
    return build_chain()


def test_callback_clock_is_not_sensor_sample_time():
    out = api()(**build_chain(callback_clock_lag_ns=1_000_000))
    assert out["source_native_records_consistent"] is True


def test_full_synthetic_source_native_chain(chain):
    out = api()(**chain)
    assert out["source_native_records_consistent"] is True
    assert out["counts"] == {"imu": 6251, "rgb": 251, "info": 251, "depth": 251, "heartbeat": 24}
    assert out["native_sensor_acknowledgements"] == 6501
    assert out["public_camera_states"] == 0
    assert out["live_qualified"] is out["fusion_qualified"] is out["vio_accuracy_qualified"] is False


@pytest.mark.parametrize("field", ["failure", "quality", "reset_counter"])
def test_missing_null_terminal_fields_refuse(chain, field):
    data = copy.deepcopy(chain)
    del data["terminal"][field]
    with pytest.raises(ValueError):
        api()(**data)


def test_unknown_native_imu_field_refuses(chain):
    data = copy.deepcopy(chain)
    data["acknowledgements"][0]["truth_correction"] = True
    with pytest.raises(ValueError):
        api()(**data)


@pytest.mark.parametrize(
    "fault",
    [
        "source_gap",
        "reduced_load",
        "armed",
        "imu_transform",
        "arrival",
        "image_truncated",
        "image_hash",
        "missing_info_payload",
        "source_hash",
        "fanout_missing",
        "partial_delivery",
        "fanout_timeout",
        "ack_missing",
        "request_action",
        "packet_hash",
        "short_packet",
        "ack_sample",
        "ack_sequence_bool",
        "ack_timeout",
        "native_gap",
        "state_mismatch",
        "pending_hidden",
        "failure_hidden",
        "unlisted_payload",
        "native_extra",
    ],
)
def test_corrupted_raw_chain_refuses(chain, fault):
    data = copy.deepcopy(chain)
    if fault == "source_gap":
        data["sources"][2]["source_sequence"] += 1
    elif fault == "reduced_load":
        data["sources"].pop()
    elif fault == "armed":
        next(r for r in data["sources"] if r["kind"] == "heartbeat")["base_mode"] |= 128
    elif fault == "imu_transform":
        data["sources"][0]["accel_frd"][2] *= -1
    elif fault == "arrival":
        data["sources"][0]["recorded_monotonic_ns"] = 1
    elif fault in ("image_truncated", "image_hash"):
        seq = next(r["source_sequence"] for r in data["sources"] if r["kind"] == "rgb")
        data["payloads"][seq] = b"a" if fault == "image_truncated" else b"a" * 57600
    elif fault == "missing_info_payload":
        del data["payloads"][next(r["source_sequence"] for r in data["sources"] if r["kind"] == "info")]
    elif fault == "source_hash":
        data["fanout"][0]["source_sha256"] = "0" * 64
    elif fault == "fanout_missing":
        data["fanout"].pop()
    elif fault == "partial_delivery":
        data["fanout"][1]["dispositions"]["readiness"] = "not_attempted"
    elif fault == "fanout_timeout":
        data["fanout"][1]["end_ns"] += 2_000_000_001
    elif fault == "ack_missing":
        data["acknowledgements"].pop()
    elif fault == "request_action":
        data["requests"][0]["action"]["am"][0] += 1
    elif fault == "packet_hash":
        data["requests"][0]["packet_sha256"] = "0" * 64
    elif fault == "short_packet":
        data["requests"][0]["bytes"] -= 1
    elif fault == "ack_sample":
        data["acknowledgements"][0]["sample_ns"] += 1
    elif fault == "ack_sequence_bool":
        data["acknowledgements"][0]["sequence"] = False
    elif fault == "ack_timeout":
        data["acknowledgements"][0]["acknowledged_ns"] += 2_000_000_001
    elif fault == "native_gap":
        data["requests"].pop(0)
        data["acknowledgements"].pop(0)
    elif fault == "state_mismatch":
        data["states"][0]["public_initialized"] = True
    elif fault == "pending_hidden":
        data["terminal"]["pending"] = []
    elif fault == "failure_hidden":
        data["terminal"]["failure"] = "source failure"
    elif fault == "unlisted_payload":
        data["payloads"][99999] = b"extra"
    elif fault == "native_extra":
        data["requests"].append(data["requests"][-1])
        data["acknowledgements"].append(data["acknowledgements"][-1])
    with pytest.raises(ValueError):
        api()(**data)
