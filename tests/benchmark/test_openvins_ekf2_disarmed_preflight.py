from __future__ import annotations

import importlib.util
import json

import pytest


def api():
    assert importlib.util.find_spec("tools.benchmark.openvins_ekf2_disarmed_preflight")
    from tools.benchmark import openvins_ekf2_disarmed_preflight

    return openvins_ekf2_disarmed_preflight


def exchange(index: int, *, offset_ns: int = 2_000_000, rtt_ns: int = 2_000_000):
    px4_request_ns = 1_000_000_000 + index * 100_000_000
    px4_receive_ns = px4_request_ns + rtt_ns
    remote_response_ns = (px4_request_ns + px4_receive_ns) // 2 - offset_ns
    return api().TimesyncExchange(px4_request_ns, remote_response_ns, px4_receive_ns)


def test_frozen_endpoint_matches_retained_instance_eight_evidence():
    profile = api().frozen_receiver_profile()
    assert profile.target_system == 9
    assert profile.target_component == 1
    assert profile.sender_system == 254
    assert profile.sender_component == 191
    assert profile.px4_udp_port == 14588
    assert profile.companion_udp_port == 14548
    assert profile.px4_instance == 8
    assert profile.model == "gz_x500_benchmark"
    assert profile.network_enabled is False


def test_timesync_matches_pinned_px4_filter_and_needs_500_accepted_samples():
    sync = api().BoundedTimesyncVerifier("clock-a")
    for index in range(499):
        result = sync.observe(exchange(index))
        assert result["accepted"] is True
        assert result["converged"] is False
    result = sync.observe(exchange(499))
    assert result["converged"] is True
    assert result["sequence"] == 500
    assert abs(result["offset_ns"] - 2_000_000) <= 1_000


def test_remote_monotonic_clock_is_shared_by_odometry_and_timesync():
    clock = api().RemoteMonotonicClock("clock-a", sim_origin_ns=1_000_000, remote_origin_ns=9_000_000)
    sample = clock.map_odometry_sample(1_020_000)
    response = clock.respond_to_px4_request(tc1_ns=0, ts1_ns=3_000_000, observed_sim_ns=1_040_000)
    assert sample == 9_020_000
    assert response == {"tc1_ns": 9_040_000, "ts1_ns": 3_000_000, "clock_session_id": "clock-a"}
    assert clock.map_odometry_sample(1_040_000) == 9_040_000
    with pytest.raises(ValueError, match="clock"):
        clock.map_odometry_sample(1_040_000)
    with pytest.raises(ValueError, match="replacement"):
        clock.map_odometry_sample(1_060_000)
    clock.replace_session("clock-b", sim_origin_ns=1_060_000, remote_origin_ns=10_000_000)
    assert clock.map_odometry_sample(1_080_000) == 10_020_000


def test_timesync_rejects_high_rtt_and_resets_on_jump_or_session_replacement():
    sync = api().BoundedTimesyncVerifier("clock-a")
    assert sync.observe(exchange(0, rtt_ns=10_000_000))["accepted"] is False
    for index in range(500):
        sync.observe(exchange(index + 1))
    assert sync.converged
    for index in range(10):
        assert sync.observe(exchange(600 + index, offset_ns=202_000_000))["reset"] is False
    reset = sync.observe(exchange(610, offset_ns=202_000_000))
    assert reset["reset"] is True
    assert reset["requires_session_replacement"] is True
    assert sync.converged is False
    assert sync.sequence == 0
    with pytest.raises(ValueError, match="clock"):
        sync.observe(exchange(611))
    sync.replace_session("clock-b")
    assert sync.session_id == "clock-b"
    assert sync.sequence == 0
    with pytest.raises(ValueError, match="session"):
        sync.replace_session("clock-b")


class FakeParameters:
    def __init__(
        self,
        values,
        *,
        fail_write=None,
        fail_verify=None,
        fail_restore=None,
        raise_write=None,
        missing_after_write=None,
    ):
        self.values = dict(values)
        self.baseline = dict(values)
        self.fail_write = fail_write
        self.fail_verify = fail_verify
        self.fail_restore = fail_restore
        self.raise_write = raise_write
        self.missing_after_write = missing_after_write
        self.events = []

    def read(self, name):
        if name not in self.values:
            return []
        value = self.values[name]
        if self.missing_after_write == name and any(event[:2] == ("write", name) for event in self.events):
            return []
        if isinstance(value, list):
            return value
        if self.fail_verify == name and any(event[:2] == ("write", name) for event in self.events):
            return [value + 1]
        return [value]

    def write(self, name, value):
        self.events.append(("write", name, value))
        if self.raise_write == name:
            raise OSError("intentional transport write error")
        if self.fail_write == name:
            return False
        if self.fail_restore == name and value == self.baseline[name]:
            return False
        self.values[name] = value
        return True


def baseline():
    return {name: 0 for name in api().required_parameter_names()}


def test_parameter_snapshot_rejects_missing_or_ambiguous_values():
    values = baseline()
    values.pop("EKF2_EV_DELAY")
    with pytest.raises(ValueError, match="EKF2_EV_DELAY"):
        api().ParameterTransaction(FakeParameters(values)).snapshot()
    values = baseline()
    values["EKF2_EV_DELAY"] = [0.0, 1.0]
    with pytest.raises(ValueError, match="ambiguous"):
        api().ParameterTransaction(FakeParameters(values)).snapshot()


def test_successful_parameter_transaction_is_verified_then_restored():
    values = baseline()
    transport = FakeParameters(values)
    result = api().ParameterTransaction(transport).apply_verify_restore(
        {"EKF2_EV_CTRL": 0, "EKF2_EV_QMIN": 1}
    )
    assert result["qualified"] is True
    assert result["primary_failure"] is None
    assert result["rollback_failures"] == []
    assert transport.values == values


@pytest.mark.parametrize("fault", ["write", "verify"])
def test_parameter_transaction_latches_primary_failure_and_restores_baseline(fault):
    values = baseline()
    values["EKF2_EV_QMIN"] = 0
    transport = FakeParameters(
        values,
        fail_write="EKF2_EV_QMIN" if fault == "write" else None,
        fail_verify="EKF2_EV_QMIN" if fault == "verify" else None,
    )
    result = api().ParameterTransaction(transport).apply_verify_restore(
        {"EKF2_EV_CTRL": 0, "EKF2_EV_QMIN": 1}
    )
    assert result["qualified"] is False
    assert result["primary_failure"].startswith(fault)
    assert result["rollback_attempted"] is True
    assert transport.values == values


def test_restore_failure_is_reported_without_hiding_apply_failure():
    values = baseline()
    transport = FakeParameters(values, fail_verify="EKF2_EV_QMIN", fail_restore="EKF2_EV_QMIN")
    result = api().ParameterTransaction(transport).apply_verify_restore(
        {"EKF2_EV_CTRL": 0, "EKF2_EV_QMIN": 1}
    )
    assert result["primary_failure"].startswith("verify")
    assert result["rollback_failures"]
    assert result["qualified"] is False


@pytest.mark.parametrize(
    ("kwargs", "prefix"),
    [
        ({"raise_write": "EKF2_EV_QMIN"}, "write_exception"),
        ({"missing_after_write": "EKF2_EV_QMIN"}, "verify_read_failed"),
    ],
)
def test_transport_exceptions_still_return_auditable_rollback(kwargs, prefix):
    values = baseline()
    transport = FakeParameters(values, **kwargs)
    result = api().ParameterTransaction(transport).apply_verify_restore(
        {"EKF2_EV_CTRL": 0, "EKF2_EV_QMIN": 1}
    )
    assert result["primary_failure"].startswith(prefix)
    assert result["rollback_attempted"] is True
    assert result["qualified"] is False


def test_receiver_only_profile_and_ulog_rules_are_fail_closed():
    profile = api().receiver_only_parameter_profile()
    assert profile["EKF2_EV_CTRL"] == 0
    assert "EKF2_EV_QMIN" not in profile
    rules = api().ulog_acceptance_profile()
    assert "vehicle_visual_odometry" in rules["required_topics"]
    assert "timesync_status" in rules["required_topics"]
    assert "estimator_status_flags" in rules["required_topics"]
    assert rules["require_unarmed"] is True
    assert rules["require_ev_fusion_false"] is True
    assert rules["network_odometry"] is False


def test_module_has_no_transport_or_process_surface():
    module = api()
    assert not hasattr(module, "socket")
    assert not hasattr(module, "subprocess")


def runtime_binding():
    records = []
    for role, path, digest in (
        ("runtime-root:px4", "/home/PX4/build/px4_sitl_default/bin/px4", "1" * 64),
        ("runtime:px4-startup", "/home/PX4/build/px4_sitl_default/rootfs/gz_env.sh", "2" * 64),
        ("runtime:px4-startup", "/home/PX4/build/px4_sitl_default/etc/init.d-posix/rcS", "3" * 64),
        ("declared:resources", "/repo/assets/gazebo/models/x500_benchmark/model.sdf", "4" * 64),
        ("generated:world.sdf", "/run/world.sdf", "5" * 64),
    ):
        records.append({"role": role, "requested": path, "resolved": path, "bytes": 10, "sha256": digest})
    return {"schema": "declared-files-v1", "files": records}


def retained_parameter_baseline():
    values = baseline()
    values.update(
        {
            "MAV_SYS_ID": 9,
            "EKF2_HGT_REF": 1,
            "EKF2_GPS_CTRL": 7,
            "EKF2_OF_CTRL": 1,
            "EKF2_BARO_CTRL": 1,
            "EKF2_RNG_CTRL": 1,
        }
    )
    return {
        "schema": "px4-ulog-parameter-baseline-v1",
        "parameters": values,
        "source_ulog": {"path": "run.ulg", "bytes": 100, "sha256": "6" * 64},
    }


def test_preflight_binds_runtime_baseline_topics_and_keeps_destination_absent():
    evidence = api().build_preflight_evidence(runtime_binding(), retained_parameter_baseline())
    assert evidence["baseline"]["EKF2_EV_CTRL"] == 0
    assert evidence["baseline"]["MAV_SYS_ID"] == 9
    assert evidence["ev_and_imu_reference_equal"] is True
    assert evidence["resources"]["px4_binary"]["sha256"] == "1" * 64
    assert evidence["resources"]["rootfs_environment"]["sha256"] == "2" * 64
    assert evidence["resources"]["vehicle_model"]["sha256"] == "4" * 64
    assert evidence["physical_destination_present"] is False
    assert evidence["network_odometry"] is False
    assert evidence["px4_parameter_access"] is False


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda binding, baseline: binding["files"].pop(), "world_sdf"),
        (lambda binding, baseline: baseline["parameters"].pop("EKF2_EV_QMIN"), "EKF2_EV_QMIN"),
        (lambda binding, baseline: baseline["parameters"].__setitem__("MAV_SYS_ID", 10), "MAV_SYS_ID"),
        (lambda binding, baseline: baseline["parameters"].__setitem__("EKF2_EV_POS_X", 0.1), "reference"),
    ],
)
def test_preflight_rejects_incomplete_or_inconsistent_evidence(mutate, expected):
    binding = runtime_binding()
    parameters = retained_parameter_baseline()
    mutate(binding, parameters)
    with pytest.raises(ValueError, match=expected):
        api().build_preflight_evidence(binding, parameters)


def test_one_shot_prepare_refuses_to_overwrite(tmp_path):
    from tools.benchmark.prepare_openvins_ekf2_disarmed_preflight import main

    runtime = tmp_path / "runtime.json"
    parameters = tmp_path / "parameters.json"
    output = tmp_path / "preflight.json"
    runtime.write_text(json.dumps(runtime_binding()), encoding="utf-8")
    parameters.write_text(json.dumps(retained_parameter_baseline()), encoding="utf-8")
    implementation = tmp_path / "implementation.py"
    implementation.write_text("VALUE = 1\n", encoding="utf-8")
    args = [
        "--runtime-binding",
        str(runtime),
        "--parameter-baseline",
        str(parameters),
        "--implementation-commit",
        "a" * 40,
        "--implementation-file",
        str(implementation),
        "--output",
        str(output),
    ]
    assert main(args) == 0
    result = json.loads(output.read_text())
    assert result["physical_destination_present"] is False
    assert result["implementation"]["commit"] == "a" * 40
    assert result["implementation"]["files"][0]["bytes"] == implementation.stat().st_size
    with pytest.raises(FileExistsError):
        main(args)
