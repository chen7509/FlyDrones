from __future__ import annotations

import json
from pathlib import Path

import pytest

from flydrones.camera_render_capacity import capacity_schedule
from tools.run_camera_render_capacity_trial_wsl import (
    _atomic_text,
    _auxiliary_closed_cleanly,
    _capacity_phase_summary,
    _capacity_run_directory,
    _capacity_startup_commands,
    _depth_topic,
    _renderer_witness_accepted,
    _renderer_witness_command,
    _scored_resource_summary,
    capacity_auxiliary_commands,
    capacity_telemetry_ready,
    run_capacity_trial,
    validate_depth_topic_connections,
    wait_for_capacity_telemetry,
)


@pytest.mark.parametrize(
    "implementation,events,exit_code,accepted",
    (
        ("scheduler", [{"event": "stop", "exit_code": 0}], 0, True),
        ("scheduler", [{"event": "stop", "exit_code": 1}], 0, False),
        ("scheduler", [{"event": "stop", "exit_code": 0}] * 2, 0, False),
        ("python", [{"event": "stop", "exit_code": 0, "completed": True}], 0, True),
        ("python", [{"event": "stop", "exit_code": 0, "completed": False}], 0, False),
        ("python", [{"event": "stop", "exit_code": 0}], 0, False),
        ("native-cpp", [{"event": "stop"}], 0, True),
        ("native-cpp", [{"event": "stop"}], 1, False),
        ("native-cpp", [{"event": "malformed-native-jsonl"}], 0, False),
    ),
)
def test_auxiliary_clean_close_requires_one_complete_success_record(
    implementation: str,
    events: list[dict[str, object]],
    exit_code: int,
    accepted: bool,
):
    assert _auxiliary_closed_cleanly(
        events, exit_code=exit_code, implementation=implementation
    ) is accepted


def test_scored_resource_summary_pins_gazebo_cpu_rss_and_gpu(tmp_path: Path):
    (tmp_path / "resource-probe.csv").write_text(
        "monotonic_s,pid,cpu_user_s,cpu_system_s,rss_bytes,threads\n"
        "49.0,12,1.0,0.5,1000,4\n"
        "50.0,12,2.0,1.0,2000,5\n"
        "65.0,12,4.0,2.0,3500,6\n"
        "81.0,12,8.0,3.0,3000,5\n"
        "82.0,12,9.0,4.0,5000,7\n",
        encoding="utf-8",
    )
    (tmp_path / "gpu-probe.csv").write_text(
        "monotonic_s,gpu_utilization_percent,memory_used_mib\n"
        "50.0,25,100\n65.0,75,150\n81.0,unavailable,unavailable\n",
        encoding="utf-8",
    )

    result = _scored_resource_summary(tmp_path, start_monotonic_s=50.0, end_monotonic_s=81.0)

    assert result["accepted"] is True
    assert result["gazebo"]["cpu_seconds_delta"] == 8.0
    assert result["gazebo"]["rss_peak_bytes"] == 3500
    assert result["gazebo"]["threads_peak"] == 6
    assert result["gpu"]["utilization_peak_percent"] == 75.0


def test_atomic_text_never_leaves_the_temporary_file(tmp_path: Path):
    destination = tmp_path / "observer.pid"

    _atomic_text(destination, "4321\n")

    assert destination.read_text(encoding="utf-8") == "4321\n"
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize(
    "estimator_healthy,armed,landed,accepted",
    (
        (True, False, True, True),
        (False, False, True, False),
        (None, False, True, False),
        (True, True, False, False),
        (True, False, None, False),
    ),
)
def test_capacity_telemetry_waits_for_the_complete_safe_state(
    estimator_healthy, armed, landed, accepted
):
    telemetry = type(
        "Telemetry",
        (),
        {
            "estimator_healthy": estimator_healthy,
            "armed": armed,
            "landed": landed,
        },
    )()

    assert capacity_telemetry_ready(telemetry) is accepted


def test_capacity_telemetry_wait_allows_slow_five_vehicle_ekf_convergence():
    class Drone:
        def __init__(self) -> None:
            self.now = 0.0

        def telemetry(self):
            return type(
                "Telemetry",
                (),
                {
                    "estimator_healthy": self.now >= 25.0,
                    "armed": False,
                    "landed": True,
                },
            )()

    drone = Drone()

    result = wait_for_capacity_telemetry(
        drone,
        monotonic=lambda: drone.now,
        sleep=lambda duration: setattr(drone, "now", drone.now + duration),
    )

    assert result.estimator_healthy is True
    assert drone.now >= 25.0


def test_capacity_run_directory_is_stable_per_output_and_unique_across_campaigns(tmp_path: Path):
    run = _run("native-1")
    first = _capacity_run_directory(run, tmp_path / "campaign-a" / run.name)
    repeated = _capacity_run_directory(run, tmp_path / "campaign-a" / run.name)
    second = _capacity_run_directory(run, tmp_path / "campaign-b" / run.name)

    assert first == repeated
    assert first != second
    assert first.parent == Path("/tmp")
    assert first.name.startswith(f"flydrones-capacity-{run.name}-")


def _run(cell: str):
    return next(run for run in capacity_schedule() if run.cell.name == cell)


def _config() -> dict[str, object]:
    return {
        "scored_duration_s": 30.0,
        "wall_timeout_s": 120.0,
        "readiness_timeout_s": 45.0,
        "renderer_profile": "d3d12-nvidia",
        "world": "flydrones_forest",
        "vehicle_count": 5,
        "px4_build_name": "px4_sitl_nolockstep",
        "px4_revision": "d6f12ad1c4f70ad3230afd7d86e971421e02fef4",
        "thresholds": {
            "min_rtf": 0.95,
            "min_image_hz": 9.5,
            "max_image_hz": 10.5,
            "max_phase_error_p95_ns": 8_000_000,
            "max_spacing_median_error_ns": 8_000_000,
            "scored_duration_s": 30.0,
            "wall_timeout_s": 120.0,
            "repeatability_rtf_range_max": 0.03,
            "native_improvement_min": 0.05,
        },
    }


def _phase_events() -> list[dict[str, object]]:
    epoch = 1_000_000_000
    topics = [
        f"/world/flydrones_forest/model/x500_depth_fly_{vehicle}"
        "/link/camera_link/sensor/StereoOV7251/depth_image"
        for vehicle in range(5)
    ]
    events: list[dict[str, object]] = [
        {"event": "start", "epoch_ns": epoch},
        {"event": "topology", "depth_topics": topics},
        {"event": "ready", "epoch_ns": epoch},
    ]
    for cycle in range(320):
        for vehicle in range(5):
            planned = epoch + cycle * 100_000_000 + vehicle * 20_000_000
            events.extend(
                (
                    {
                        "event": "trigger",
                        "vehicle_id": vehicle,
                        "cycle": cycle,
                        "planned_sim_ns": planned,
                        "published_sim_ns": planned + 4_000_000,
                    },
                    {
                        "event": "image",
                        "vehicle_id": vehicle,
                        "topic": topics[vehicle],
                        "sim_ns": planned,
                        "sequence": cycle,
                        "width": 160,
                        "height": 120,
                        "format": "R_FLOAT32",
                    },
                )
            )
    events.append({"event": "stop"})
    return events


def test_capacity_phase_summary_uses_only_scored_window_scheduler_epoch_and_metadata():
    scheduler_epoch = 1_000_000_000
    scored_start = 2_000_000_000
    scored_end = 32_000_000_000
    topic = _depth_topic(0)
    events: list[dict[str, object]] = [
        {"event": "start", "epoch_ns": 1_600_000_000},
        {"event": "topology", "depth_topics": [_depth_topic(i) for i in range(5)]},
        {"event": "ready", "epoch_ns": 1_600_000_000},
    ]
    for cycle in range(320):
        planned = scheduler_epoch + cycle * 100_000_000
        events.extend(
            (
                {
                    "event": "trigger",
                    "vehicle_id": 0,
                    "cycle": cycle,
                    "planned_sim_ns": planned,
                    "published_sim_ns": planned + 4_000_000,
                },
                {
                    "event": "image",
                    "vehicle_id": 0,
                    "topic": topic,
                    "sim_ns": planned + 4_000_000,
                    "sequence": cycle,
                    "width": 160,
                    "height": 120,
                    "format": "R_FLOAT32",
                },
            )
        )
    events.append({"event": "stop"})

    summary = _capacity_phase_summary(
        events,
        subscriber_count=1,
        scored_window={"start_sim_ns": scored_start, "end_sim_ns": scored_end},
        scheduler_epoch_ns=scheduler_epoch,
    )

    assert summary["accepted"] is True
    assert summary["epoch_ns"] == scheduler_epoch
    assert summary["unmatched_trigger_count"] == 0
    assert summary["unmatched_image_count"] == 0
    assert summary["vehicles"]["0"] == {
        **summary["vehicles"]["0"],
        "frequency_hz": 10.0,
        "width": 160,
        "height": 120,
        "format": "R_FLOAT32",
    }
    assert summary["vehicles"]["0"]["image_count"] == 300


def test_renderer_witness_accepts_setup_phase_jitter_but_rejects_integrity_errors():
    summary = {
        "schema": "flydrones-camera-phase-summary-v1",
        "vehicle_count": 5,
        "accepted": False,
        "reasons": ["phase_error_p95_exceeded"],
        "vehicles": {
            str(vehicle): {"mean_frequency_hz": 10.0} for vehicle in range(5)
        },
        "missed_trigger_count": 0,
        "queue_overflow_count": 0,
        "duplicate_trigger_count": 0,
        "duplicate_image_count": 0,
        "unmatched_trigger_count": 0,
        "unmatched_image_count": 0,
        "cross_model_error_count": 0,
    }

    assert _renderer_witness_accepted(summary, exit_code=2) is True
    summary["unmatched_trigger_count"] = 1
    assert _renderer_witness_accepted(summary, exit_code=2) is False


def test_renderer_witness_uses_native_five_camera_warmup(tmp_path: Path):
    executable = tmp_path / "flydrones_camera_phase_native"

    command = _renderer_witness_command(output=tmp_path, native_executable=executable)

    assert command[:2] == [str(executable), "observe"]
    assert command[command.index("--vehicle-count") + 1] == "5"
    assert command[command.index("--subscriber-count") + 1] == "5"
    assert command[command.index("--warmup-image-count-min") + 1] == "11"
    assert command[command.index("--observe-triggers") + 1] == "0"
    assert command[command.index("--readiness-timeout-s") + 1] == "150"
    assert command[command.index("--ready-marker") + 1].endswith(
        "renderer-phase-ready.json"
    )


def test_capacity_selected_observer_starts_before_renderer_witness_handoff(
    tmp_path: Path,
):
    commands = capacity_auxiliary_commands(
        run=_run("native-5"),
        output=tmp_path,
        completion_marker=tmp_path / "complete.marker",
        native_executable=tmp_path / "flydrones_camera_phase_native",
    )

    startup = _capacity_startup_commands(
        commands=commands,
        output=tmp_path,
        native_executable=tmp_path / "flydrones_camera_phase_native",
    )

    assert [role for role, _command in startup] == [
        "scheduler",
        "renderer-witness",
        "observer",
    ]
    assert startup[2][1] is commands[1]


def test_capacity_observers_allow_sequential_px4_startup(tmp_path: Path):
    run = _run("native-1")
    scheduler, _observer = capacity_auxiliary_commands(
        run=run,
        output=tmp_path,
        completion_marker=tmp_path / "complete.marker",
        native_executable=tmp_path / "flydrones_camera_phase_native",
    )

    assert scheduler[scheduler.index("--topology-timeout-s") + 1] == "150"
    assert _observer[_observer.index("--readiness-timeout-s") + 1] == "150"


class FakeBackend:
    def __init__(self, *, failure: str | None = None, busy: bool = False):
        self.failure = failure
        self.busy = busy
        self.calls: list[str] = []
        self.commands: list[list[str]] = []
        self.environment: dict[str, str] = {}

    def occupied_resources(self) -> list[str]:
        self.calls.append("occupied_resources")
        return ["gz sim"] if self.busy else []

    def start(self, *, commands, **_kwargs):
        self.calls.append("start")
        self.commands = commands
        self.environment = dict(_kwargs["environment"])
        if self.failure == "start":
            raise RuntimeError("launcher failed")

    def wait_ready(self, **_kwargs):
        self.calls.append("wait_ready")
        if self.failure == "readiness_timeout":
            raise TimeoutError("capacity readiness timed out")
        if self.failure == "completion_before_readiness":
            raise RuntimeError("completion before readiness")
        if self.failure == "observer_early_exit":
            raise RuntimeError("observer exited before readiness")
        if self.failure == "runtime_probe_early_exit":
            raise RuntimeError("runtime probe exited before readiness")
        return {
            "schema": "flydrones-camera-capacity-ready-v1",
            "renderer_attestation_accepted": self.failure != "renderer_rejected",
            "px4_vehicle_count": 5,
            "px4_all_healthy": self.failure != "px4_unhealthy",
            "px4_all_disarmed": self.failure != "px4_armed",
            "px4_all_landed": self.failure != "px4_armed",
            "px4_build": {
                "build_name": "px4_sitl_nolockstep",
                "nolockstep": True,
                "px4_revision": "d6f12ad1c4f70ad3230afd7d86e971421e02fef4",
                "binary_sha256": "a" * 64,
            },
            "observer_pid": 4321,
        }

    def capture_connections(self, *, stage: str, subscriber_count: int):
        self.calls.append(f"connections:{stage}")
        selected = set(range(subscriber_count))
        if self.failure == "wrong_subscriber_count":
            selected.add(4 if subscriber_count < 5 else 0)
        return {
            vehicle: f"Subscribers: {2 if self.failure == 'wrong_subscriber_count' and vehicle in selected else int(vehicle in selected)}"
            for vehicle in range(5)
        }

    def run_scored_window(self, **_kwargs):
        self.calls.append("run_scored_window")
        if self.failure == "wall_timeout":
            raise TimeoutError("120 second wall timeout")
        return {
            "start_sim_ns": 2_000_000_000,
            "end_sim_ns": 32_000_000_000,
            "start_monotonic_s": 50.0,
            "end_monotonic_s": 81.0,
            "rtf": 30.0 / 31.0,
        }

    def collect(self, **_kwargs):
        self.calls.append("collect")
        return {
            "phase_events": _phase_events(),
            "scheduler_epoch_ns": 1_000_000_000,
            "observer_exit_code": 0,
            "scheduler_exit_code": 0,
            "runtime_probe_exit_code": 0,
            "launcher_exit_code": 0,
            "observer_closed_cleanly": True,
            "scheduler_closed_cleanly": True,
            "native_metrics": {
                "callback_cpu_ns": 100,
                "writer_cpu_ns": 200,
                "queue_high_watermark": 3,
                "image_payload_bytes_seen": 1234,
            },
            "resource_metrics": {
                "accepted": True,
                "gazebo": {
                    "samples": 3,
                    "cpu_seconds_delta": 8.0,
                    "rss_peak_bytes": 3500,
                },
                "gpu": {"numeric_samples": 2, "utilization_peak_percent": 75.0},
            },
        }

    def preserve_artifacts(self, **_kwargs):
        self.calls.append("preserve_artifacts")
        return {
            "ulog_artifacts": [
                {
                    "vehicle_id": vehicle_id,
                    "path": f"px4-ulogs/agent-{vehicle_id}.ulg",
                    "bytes": 100 + vehicle_id,
                    "sha256": f"{vehicle_id}" * 64,
                }
                for vehicle_id in range(5)
            ],
            "copied_evidence": ["renderer-attestation.json", "cleanup-evidence.json"],
        }

    def stop(self, **_kwargs) -> int:
        self.calls.append("stop")
        return 1 if self.failure == "stopper_failure" else 0

    def shared_files_restored(self, **_kwargs) -> bool:
        self.calls.append("shared_files_restored")
        return self.failure != "restoration_failure"

    def cleanup_verified(self, **_kwargs) -> bool:
        self.calls.append("cleanup_verified")
        return self.failure != "cleanup_failure"


@pytest.mark.parametrize(
    "cell,subscriber_count,implementation",
    (
        ("idle-0", "0", "native"),
        ("native-1", "1", "native"),
        ("python-5", "5", "python"),
        ("native-5", "5", "native"),
    ),
)
def test_auxiliary_commands_are_exact_and_never_construct_worker(
    tmp_path: Path, cell: str, subscriber_count: str, implementation: str
):
    commands = capacity_auxiliary_commands(
        run=_run(cell),
        output=tmp_path,
        completion_marker=tmp_path / "complete.marker",
        native_executable=tmp_path / "flydrones_camera_phase_native",
    )

    assert len(commands) == 2
    scheduler, observer = commands
    assert scheduler[1].endswith("run_camera_phase_scheduler_wsl.py")
    assert "--formal" in scheduler
    assert "--dispatch-delay-ns" in scheduler and "4000000" in scheduler
    if implementation == "native":
        assert observer[0].endswith("flydrones_camera_phase_native")
        assert observer[1] == "observe"
        assert observer[observer.index("--subscriber-count") + 1] == subscriber_count
    else:
        assert observer[1].endswith("probe_camera_phase_wsl.py")
        assert observer[observer.index("--vehicle-count") + 1] == "5"
    assert all("worker" not in part and "distributed_agent" not in part for cmd in commands for part in cmd)


def test_depth_topic_connection_validation_rejects_duplicates_and_unexpected_subscribers():
    zero = {vehicle: "Subscribers: 0" for vehicle in range(5)}
    one = {vehicle: f"Subscribers: {int(vehicle == 0)}" for vehicle in range(5)}
    five = {vehicle: "Subscribers: 1" for vehicle in range(5)}
    assert validate_depth_topic_connections(zero, subscriber_count=0)["accepted"] is True
    assert validate_depth_topic_connections(one, subscriber_count=1)["accepted"] is True
    assert validate_depth_topic_connections(five, subscriber_count=5)["accepted"] is True
    duplicate = dict(five)
    duplicate[0] = "Subscribers: 2"
    assert validate_depth_topic_connections(duplicate, subscriber_count=5)["accepted"] is False
    unexpected = dict(zero)
    unexpected[4] = "Subscribers: 1"
    assert validate_depth_topic_connections(unexpected, subscriber_count=0)["accepted"] is False
    with pytest.raises(ValueError, match="subscriber count"):
        validate_depth_topic_connections({0: "malformed"}, subscriber_count=1)


def test_depth_topic_connection_validation_accepts_gazebo_no_subscribers_text():
    no_subscribers = {
        vehicle: (
            "Publishers [Address, Message Type]:\n"
            f"  tcp://127.0.0.1:{42000 + vehicle}, gz.msgs.Image\n"
            f"No subscribers on topic [{_depth_topic(vehicle)}]\n"
        )
        for vehicle in range(5)
    }

    evidence = validate_depth_topic_connections(no_subscribers, subscriber_count=0)

    assert evidence["accepted"] is True
    assert evidence["actual"] == {str(vehicle): 0 for vehicle in range(5)}


def test_capacity_launcher_uses_temporary_attestation_and_stable_gazebo_identity():
    launcher = (Path(__file__).parents[1] / "tools/launch_px4_depth_swarm_wsl.sh").read_text(
        encoding="utf-8"
    )
    runner = (
        Path(__file__).parents[1] / "tools/run_camera_render_capacity_trial_wsl.py"
    ).read_text(encoding="utf-8")
    assert "renderer-phase-ready.json" in runner
    assert "renderer-phase-complete.marker" in runner
    assert "renderer-phase.jsonl" in runner
    assert "renderer-phase-summary.json" in runner
    assert '--phase-ready-marker "$camera_phase_ready_marker"' in launcher
    assert "camera-phase-selected-ready.json" in runner
    assert "Gazebo launcher did not reach stable gz sim argv" in launcher
    assert launcher.index("Gazebo launcher did not reach stable gz sim argv") < launcher.index(
        'record_process "$gazebo_pid" "gazebo-server"'
    )
    assert 'gazebo_run_args=(-s "$world_target")' in launcher
    assert '--preload-vehicles "$vehicle_count"' in launcher
    assert 'PX4_GZ_MODEL_NAME="x500_depth_fly_$instance_id"' in launcher
    assert 'px4_build_name="${PX4_BUILD_NAME:-px4_sitl_default}"' in launcher
    assert 'build="$px4_root/build/$px4_build_name"' in launcher
    assert 'PX4_BUILD_NAME must be px4_sitl_nolockstep in capacity mode' in launcher
    assert '#define CONFIG_BOARD_NOLOCKSTEP 1' in launcher
    assert 'px4-build-evidence.json' in launcher
    assert 'px4-capacity-platform-ready.json' in launcher
    assert 'if [[ "$capacity_mode" != 1 ]]; then gazebo_run_args=(-r "${gazebo_run_args[@]}"); fi' in launcher
    assert 'px4-sensor-source-warmup.json' in launcher
    assert 'gz service -s "/world/flydrones_forest/control"' in launcher
    assert '"pause: false"' in launcher
    final_resume = launcher.index('>"$run_dir/capacity-world-resume.log"')
    first_px4 = launcher.index('record_process "$(cat "$instance_dir/pid")" "px4-$instance_id"')
    assert first_px4 < final_resume
    source_warmup = launcher.index('"$run_dir/px4-sensor-source-warmup.json"')
    assert 'echo "PX4 instance $instance_id sensor publisher registration timed out"' in launcher
    serial_sensor_gate = launcher.index(
        'echo "PX4 instance $instance_id sensor publisher registration timed out"'
    )
    assert first_px4 < serial_sensor_gate < final_resume
    assert 'echo "PX4 pre-resume bridge barrier timed out"' in launcher
    barrier = launcher.index('echo "PX4 pre-resume bridge barrier timed out"')
    sensor_topology = launcher.index('"$run_dir/px4-sensor-topic-connections.json"')
    assert final_resume < source_warmup < barrier < sensor_topology
    assert 'capacity-world-instance-$instance_id-resume.log' not in launcher
    assert 'capacity-world-instance-$instance_id-pause.log' not in launcher
    assert 'echo "PX4 concurrent sensor readiness failed"' in launcher
    startup_health = launcher.index('"startup-health.json"')
    assert sensor_topology < startup_health
    platform_ready = launcher.index('"$run_dir/px4-capacity-platform-ready.json"')
    capacity_aux_wait = launcher.index(
        'echo "capacity camera auxiliaries did not start after platform readiness"'
    )
    assert startup_health < platform_ready < capacity_aux_wait
    backend_platform_wait = runner.index(
        'run_dir / "px4-capacity-platform-ready.json"'
    )
    backend_scheduler_start = runner.index(
        "startup_commands = _capacity_startup_commands"
    )
    assert backend_platform_wait < backend_scheduler_start
    assert 'px4-gz_bridge" --instance "$instance_id" stop' not in launcher
    assert 'item["publisher_count"] == 1 and item["subscriber_count"] == 1' in launcher
    assert "px4-sensor-topic-connections.json" in launcher
    assert "px4-sensor-topic-connections.json" in runner
    assert 'f"capacity-world-instance-{vehicle_id}-{action}.log"' not in runner
    assert 'f"px4-console/agent-{vehicle_id}-startup-health.json"' in runner
    assert '"px4-console/agent-{vehicle_id}-{stream}.log"' in runner
    assert '"gazebo.stdout.log"' in runner
    assert '"gazebo.stderr.log"' in runner
    assert '"px4-sensor-source-warmup.json"' in runner
    assert '"px4-build-evidence.json"' in runner
    assert '"px4-capacity-platform-ready.json"' in runner
    assert '"capacity-world-warmup-resume.log"' not in runner
    assert '"capacity-world-warmup-pause.log"' not in runner
    assert '"capacity-world-warmup-reset.log"' not in runner
    assert final_resume < launcher.index("  running=0", final_resume)


def test_capacity_trial_freezes_official_nolockstep_px4_build(tmp_path: Path):
    backend = FakeBackend()
    native_executable = tmp_path / "flydrones_camera_phase_native"
    native_executable.write_bytes(b"native capacity test executable")

    run_capacity_trial(
        run=_run("native-1"),
        config=_config(),
        output_root=tmp_path,
        native_executable=native_executable,
        _backend=backend,
    )

    assert backend.environment["PX4_BUILD_NAME"] == "px4_sitl_nolockstep"
    assert backend.environment["FLYDRONES_CAMERA_AUX_TIMEOUT_S"] == "150"
    assert backend.environment["FLYDRONES_EXPECTED_PX4_REVISION"] == (
        "d6f12ad1c4f70ad3230afd7d86e971421e02fef4"
    )


def test_capacity_trial_rejects_lockstep_px4_build_before_start(tmp_path: Path):
    config = _config()
    config["px4_build_name"] = "px4_sitl_default"
    native_executable = tmp_path / "flydrones_camera_phase_native"
    native_executable.write_bytes(b"native capacity test executable")

    with pytest.raises(ValueError, match="px4_sitl_nolockstep"):
        run_capacity_trial(
            run=_run("native-1"),
            config=config,
            output_root=tmp_path,
            native_executable=native_executable,
            _backend=FakeBackend(),
        )


@pytest.mark.parametrize("cell", ("idle-0", "native-1", "python-5", "native-5"))
def test_successful_trial_writes_manifest_summary_epoch_and_no_worker(tmp_path: Path, cell: str):
    backend = FakeBackend()
    native_executable = tmp_path / "flydrones_camera_phase_native"
    native_executable.write_bytes(b"native capacity test executable")
    result = run_capacity_trial(
        run=_run(cell),
        config=_config(),
        output_root=tmp_path,
        native_executable=native_executable,
        _backend=backend,
    )

    output = tmp_path / _run(cell).name
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    epoch = json.loads((output / "scored-epoch.json").read_text(encoding="utf-8"))
    assert result["manifest"] == manifest
    assert manifest["schema"] == "flydrones-camera-render-capacity-manifest-v1"
    assert summary["schema"] == "flydrones-camera-render-capacity-summary-v1"
    assert epoch["target_sim_duration_s"] == 30.0
    assert epoch["wall_timeout_s"] == 120.0
    assert manifest["worker_command_constructed"] is False
    assert manifest["stop_exit_code"] == 0
    assert manifest["trial_cleanup_verified"] is True
    assert manifest["launcher_exit_code"] == 0
    assert manifest["frozen_hashes"]["native_executable"]
    assert manifest["frozen_hashes"]["runner"]
    assert manifest["source_hashes_match"] is True
    assert manifest["native_executable_hash_match"] is True
    assert len(manifest["ulog_artifacts"]) == 5
    assert manifest["config_artifact"] == "trial-config.json"
    assert (output / "trial-config.json").is_file()
    assert (output / "depth-topic-connections.json").is_file()
    assert summary["native_metrics"]["queue_high_watermark"] == 3
    assert summary["runtime"]["resources"]["gazebo"]["rss_peak_bytes"] == 3500
    assert result["score"]["evidence_valid"] is True
    assert result["score"]["performance_pass"] is True
    assert json.loads((output / "score.json").read_text(encoding="utf-8")) == result["score"]
    assert "stop" in backend.calls
    assert "preserve_artifacts" in backend.calls
    if cell == "idle-0":
        assert summary["camera_phase"]["depth_subscription_absent"] is True
    else:
        assert summary["camera_phase"]["accepted"] is True


@pytest.mark.parametrize(
    "failure,reason",
    (
        ("renderer_rejected", "renderer attestation rejected"),
        ("px4_unhealthy", "PX4 health/disarmed/landed gate failed"),
        ("px4_armed", "PX4 health/disarmed/landed gate failed"),
        ("wrong_subscriber_count", "depth subscriber topology rejected"),
        ("readiness_timeout", "capacity readiness timed out"),
        ("completion_before_readiness", "completion before readiness"),
        ("observer_early_exit", "observer exited before readiness"),
        ("runtime_probe_early_exit", "runtime probe exited before readiness"),
        ("wall_timeout", "120 second wall timeout"),
        ("stopper_failure", "stopper exited 1"),
        ("restoration_failure", "shared PX4 files were not restored"),
        ("cleanup_failure", "owned process cleanup was not verified"),
    ),
)
def test_trial_preserves_failures_and_always_runs_cleanup(
    tmp_path: Path, failure: str, reason: str
):
    backend = FakeBackend(failure=failure)
    result = run_capacity_trial(
        run=_run("native-5"),
        config=_config(),
        output_root=tmp_path,
        native_executable=tmp_path / "native",
        _backend=backend,
    )

    assert result["manifest"]["evidence_accepted"] is False
    assert any(reason in error for error in result["manifest"]["errors"])
    assert "stop" in backend.calls
    assert "shared_files_restored" in backend.calls
    assert "cleanup_verified" in backend.calls


def test_occupied_resources_abort_before_output_or_process_start(tmp_path: Path):
    backend = FakeBackend(busy=True)
    with pytest.raises(RuntimeError, match="resources are in use"):
        run_capacity_trial(
            run=_run("idle-0"),
            config=_config(),
            output_root=tmp_path,
            native_executable=tmp_path / "native",
            _backend=backend,
        )
    assert not (tmp_path / _run("idle-0").name).exists()
    assert "start" not in backend.calls
