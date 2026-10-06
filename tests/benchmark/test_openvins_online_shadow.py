import hashlib
import json
import math

import pytest

from tools.benchmark.openvins_online_shadow import SourceWatchdog, encode_packet, validate_ack


def imu():
    return dict(kind="imu", sample_ns=4_000_000, source_arrival_ns=100, wm=[1.0, 2.0, 3.0], am=[0.0, 0.0, -9.81])


def test_packet_has_owned_exact_rgb_bytes_and_no_paths():
    pixels = bytes([255, 0, 0]) * (160 * 120)
    action = dict(kind="camera", sample_ns=1000, source_arrival_ns=100)
    packet = encode_packet(action, sequence=2, dispatch_ns=200, pixels=pixels)
    header, raw = packet.split(b"\n", 1)
    assert header == b"C 2 1000 100 200 57600"
    assert raw == pixels
    with pytest.raises(ValueError):
        encode_packet(action, sequence=2, dispatch_ns=200, pixels="../../frame.ppm")
    with pytest.raises(ValueError):
        encode_packet(action, sequence=2, dispatch_ns=200, pixels=pixels[:-1])


@pytest.mark.parametrize("value", [math.nan, math.inf, 10**400, True])
def test_reject_nonfinite_and_non_numeric_imu(value):
    action = imu()
    action["wm"][0] = value
    with pytest.raises(ValueError):
        encode_packet(action, sequence=0, dispatch_ns=200)


@pytest.mark.parametrize("field,value", [("sample_ns", 2**63), ("sample_ns", 0), ("source_arrival_ns", True)])
def test_signed_clock_boundaries(field, value):
    action = imu()
    action[field] = value
    with pytest.raises(ValueError):
        encode_packet(action, sequence=0, dispatch_ns=200)


def test_dispatch_cannot_precede_arrival():
    with pytest.raises(ValueError):
        encode_packet(imu(), sequence=0, dispatch_ns=99)


def test_ack_checks_actual_cross_process_clock_interval():
    ack = dict(sequence=0, kind="I", receive_ns=201, start_ns=202, end_ns=205)
    assert validate_ack(ack, sequence=0, kind="I", dispatch_ns=200, acknowledged_ns=210) == ack
    for field, value in [("sequence", 1), ("receive_ns", 199), ("end_ns", 211), ("start_ns", 206)]:
        with pytest.raises(ValueError):
            validate_ack(dict(ack, **{field: value}), sequence=0, kind="I", dispatch_ns=200, acknowledged_ns=210)


def test_watchdog_detects_total_silence_without_pending_images():
    guard = SourceWatchdog(timeout_ns=200)
    guard.start(1000)
    guard.check(1199)
    with pytest.raises(TimeoutError, match="imu.*rgb.*info"):
        guard.check(1201)


def test_watchdog_each_source_and_clock_regression():
    guard = SourceWatchdog(timeout_ns=200)
    guard.start(1000)
    for kind in ["imu", "rgb", "info"]:
        guard.observe(kind, 1100)
    guard.observe("imu", 1290)
    with pytest.raises(TimeoutError, match="rgb.*info"):
        guard.check(1301)
    with pytest.raises(ValueError):
        guard.observe("imu", 1200)


def test_cold_start_is_separate_from_operational_source_loss():
    guard = SourceWatchdog(timeout_ns=200, startup_timeout_ns=1000)
    guard.start(1000)
    guard.observe("imu", 1010)
    guard.check(1500)  # Renderer has not produced first RGB/info yet.
    guard.observe("imu", 1600)
    guard.observe("rgb", 1601)
    guard.observe("info", 1602)
    guard.check(1700)
    assert guard.snapshot()["ready_ns"] == 1602
    with pytest.raises(TimeoutError, match="source silence"):
        guard.check(1803)
    missing = SourceWatchdog(timeout_ns=200, startup_timeout_ns=1000)
    missing.start(1000)
    missing.observe("imu", 1500)
    with pytest.raises(TimeoutError, match="startup.*rgb.*info"):
        missing.check(2001)


def test_synthetic_results_serializable():
    assert json.loads(json.dumps({"fusion_eligible": False, "quality": None, "reset_counter": None}))["quality"] is None


def event(kind, sample, arrival):
    from tools.benchmark.openvins_causal_input import raw_profile

    base = dict(kind=kind, sample_ns=sample, arrival_monotonic_ns=arrival, observed_sim_ns=sample)
    if kind == "imu":
        base.update(gyro_flu=[1.0, 2.0, 3.0], accel_flu=[0.0, 0.0, 9.81])
    elif kind == "rgb":
        base.update(width=160, height=120)
    else:
        base["camera_info"] = raw_profile()["camera_info"]
    return base


class FakeNative:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, action, pixels=None):
        if self.fail:
            raise TimeoutError("blocked native")
        self.sent.append((action, pixels))


def test_causal_handoff_real_pixels_and_final_unreleased_frame(tmp_path):
    from tools.benchmark.openvins_online_shadow import ShadowInput

    client = FakeNative()
    shadow = ShadowInput(client, tmp_path, session_id="test", now=lambda: 2000)
    pixels = bytes([255, 0, 0]) * 19200
    shadow.on_record(event("imu", 1_000_000, 1000), None)
    shadow.on_record(event("rgb", 1_000_000, 1010), pixels)
    shadow.on_record(event("info", 1_000_000, 1020), b"PB")
    assert len(client.sent) == 1
    shadow.on_record(event("imu", 4_000_000, 1030), None)
    assert [a[0]["kind"] for a in client.sent] == ["imu", "imu", "camera"]
    assert client.sent[-1][1] == pixels
    assert client.sent[0][0]["wm"] == [1.0, -2.0, -3.0]
    shadow.on_record(event("rgb", 4_000_000, 1040), pixels)
    shadow.on_record(event("info", 4_000_000, 1050), b"PB")
    result = shadow.finish()
    assert result["pending"][0]["reason"] == "later_imu_missing"
    assert result["fusion_eligible"] is False


def test_study_v8_queued_later_imu_is_not_expired_by_local_service_time(tmp_path):
    """Exact retained clocks: source arrival passes 250 ms, post-service wall time does not."""
    from tools.benchmark.openvins_online_shadow import ShadowInput

    client = FakeNative()
    after_record = iter([65_524_453_701, 66_698_382_096, 66_947_892_850, 66_949_524_266])
    shadow = ShadowInput(client, tmp_path, session_id="study-v8-fixed", now=lambda: next(after_record))
    pixels = b"\xff" * 57600
    shadow.on_record(event("imu", 1_000_000, 65_491_832_354), None)
    shadow.on_record(event("info", 2_000_000, 66_678_238_723), b"PB")
    shadow.on_record(event("rgb", 2_000_000, 66_905_573_764), pixels)
    shadow.on_record(event("imu", 4_000_000, 66_906_522_485), None)
    result = shadow.finish()
    assert result["failure"] is None
    assert [action[0]["kind"] for action in client.sent] == ["imu", "imu", "camera"]
    assert client.sent[-1][0]["sample_ns"] == 2_000_000
    assert client.sent[-1][0]["imu_boundary_ns"] == 4_000_000


def test_online_adapter_accepts_slow_wall_pair_with_fresh_simulation_time(tmp_path):
    from tools.benchmark.openvins_online_shadow import ShadowInput

    after_record = iter([1_000_000_000, 1_001_000_000, 1_002_000_000, 1_251_000_001])
    shadow = ShadowInput(FakeNative(), tmp_path, session_id="stale-source", now=lambda: next(after_record))
    pixels = b"\xff" * 57600
    shadow.on_record(event("imu", 1_000_000, 1_000_000_000), None)
    shadow.on_record(event("info", 2_000_000, 1_001_000_000), b"PB")
    shadow.on_record(event("rgb", 2_000_000, 1_002_000_000), pixels)
    shadow.on_record(event("imu", 4_000_000, 1_252_000_001), None)
    result = shadow.finish()
    assert result["failure"] is None
    assert [item[0]["kind"] for item in shadow.client.sent] == ["imu", "imu", "camera"]
    assert result["fusion_eligible"] is False


def test_online_adapter_wall_idle_does_not_advance_simulation_dependency_age(tmp_path):
    from tools.benchmark.openvins_online_shadow import ShadowInput

    shadow = ShadowInput(FakeNative(), tmp_path, session_id="silent-source", now=lambda: 9_000_000_000)
    shadow.on_record(event("info", 2_000_000, 1_000_000_000), b"PB")
    shadow.tick_idle(1_250_000_000)
    assert shadow.failure is None
    shadow.tick_idle(9_000_000_000)
    result = shadow.finish()
    assert result["failure"] is None
    assert result["pending"][0]["reason"] == "rgb_missing"


def test_online_adapter_rejects_missing_pair_after_simulation_advance(tmp_path):
    from tools.benchmark.openvins_online_shadow import ShadowInput

    shadow = ShadowInput(FakeNative(), tmp_path, session_id="sim-stale", now=lambda: 2_000_000_000)
    shadow.on_record(event("info", 2_000_000, 1_000_000_000), b"PB")
    shadow.on_record(event("rgb", 253_000_001, 1_000_000_001), b"\xff" * 57600)
    result = shadow.finish()
    assert result["failure"] == "InputRefusal('pending input exceeded simulation wait')"
    assert result["pending"][0]["reason"] == "pending input exceeded simulation wait"


def test_consumer_failure_latches_but_raw_writer_still_retains_inputs(tmp_path):
    from tools.benchmark.disarmed_sensor_provenance import CaptureWriter
    from tools.benchmark.openvins_online_shadow import ShadowInput

    client = FakeNative(fail=True)
    shadow = ShadowInput(client, tmp_path, session_id="failed", now=lambda: 2000)
    writer = CaptureWriter(tmp_path, on_record=shadow.on_record)
    writer.submit(event("imu", 1_000_000, 1000))
    writer.submit(event("imu", 4_000_000, 1010))
    summary = writer.finish()
    result = shadow.finish()
    assert summary["written"]["imu"] == 2
    assert "blocked native" in result["failure"]
    assert result["skipped_after_failure"] == 1
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 2


def test_pixels_rejected_and_failure_evidence_retained(tmp_path):
    from tools.benchmark.openvins_online_shadow import ShadowInput

    shadow = ShadowInput(FakeNative(), tmp_path, session_id="bad", now=lambda: 2000)
    shadow.on_record(event("rgb", 1_000_000, 1000), b"truncated")
    result = shadow.finish()
    assert "RGB" in result["failure"]
    assert json.loads((tmp_path / "shadow-failures.jsonl").read_text())["event"]["kind"] == "rgb"


@pytest.mark.parametrize("fail_on", [2, 3])
def test_released_actions_retain_failure_and_not_attempted_dispositions(tmp_path, fail_on):
    from tools.benchmark.openvins_online_shadow import ShadowInput

    class FailNth(FakeNative):
        calls = 0

        def send(self, action, pixels=None):
            self.calls += 1
            if self.calls == fail_on:
                raise TimeoutError("delivery interrupted")
            super().send(action, pixels)

    shadow = ShadowInput(FailNth(), tmp_path, session_id="batch", now=lambda: 2000)
    pixels = b"\xff" * 57600
    shadow.on_record(event("imu", 1_000_000, 1000), None)
    shadow.on_record(event("rgb", 1_000_000, 1010), pixels)
    shadow.on_record(event("info", 1_000_000, 1020), b"PB")
    shadow.on_record(event("imu", 4_000_000, 1030), None)
    result = shadow.finish()
    camera = result["released_unacknowledged"][-1]
    assert camera["action"]["kind"] == "camera"
    assert camera["action"]["rgb_sequence"] == 1
    assert camera["action"]["info_sequence"] == 2
    assert camera["action"]["imu_boundary_sequence"] == 3
    assert camera["status"] == ("never_attempted" if fail_on == 2 else "delivery_failed")
    assert camera["rgb_sha256"] == hashlib.sha256(pixels).hexdigest()
    assert result["retained_pixel_stamps"] == [1_000_000]
    if fail_on == 2:
        assert result["released_unacknowledged"][0]["action"]["kind"] == "imu"
        assert result["released_unacknowledged"][0]["status"] == "delivery_failed"
    failure = json.loads((tmp_path / "shadow-failures.jsonl").read_text())
    assert failure["input_sequence"] == 3


def frozen_fixture(directory):
    files = {
        "estimator_config.yaml": b'relative_config_imu: "kalibr_imu_chain.yaml"\nrelative_config_imucam: "kalibr_imucam_chain.yaml"\n',
        "kalibr_imu_chain.yaml": b"imu0: {}\n",
        "kalibr_imucam_chain.yaml": b"cam0: {}\n",
    }
    for name, data in files.items():
        (directory / name).write_bytes(data)
    manifest = dict(
        name="raw-model-zero-bias-diffusion-v1", sha256={name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    )
    (directory / "freeze.json").write_text(json.dumps(manifest))
    return directory / "estimator_config.yaml", manifest


@pytest.mark.parametrize("mutation", ["unlisted_selected", "empty", "missing_calibration", "changed_reference", "path_escape"])
def test_frozen_config_rejects_unverified_selected_or_references(tmp_path, mutation):
    from tools.benchmark.openvins_online_shadow import validate_frozen_config

    config, manifest = frozen_fixture(tmp_path)
    if mutation == "unlisted_selected":
        config = tmp_path / "other.yaml"
        config.write_text("unverified: true\n")
    elif mutation == "empty":
        manifest["sha256"] = {}
    elif mutation == "missing_calibration":
        del manifest["sha256"]["kalibr_imu_chain.yaml"]
    elif mutation == "path_escape":
        manifest["sha256"]["../elsewhere.yaml"] = "0" * 64
    else:
        config.write_text(config.read_text().replace('"kalibr_imu_chain.yaml"', '"other.yaml"'))
        manifest["sha256"][config.name] = hashlib.sha256(config.read_bytes()).hexdigest()
    (tmp_path / "freeze.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        validate_frozen_config(config)


def test_frozen_config_accepts_exact_selected_and_calibration_set(tmp_path):
    from tools.benchmark.openvins_online_shadow import validate_frozen_config

    config, manifest = frozen_fixture(tmp_path)
    assert validate_frozen_config(config) == manifest
