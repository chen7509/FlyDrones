import hashlib
import json
import subprocess

import pytest

from flydrones.gazebo_renderer import (
    DepthObservation,
    evaluate_renderer_attestation,
    parse_egl_renderer,
    resolve_renderer_profile,
)
from tools.attest_gazebo_renderer_wsl import (
    evaluate_expected_plugin,
    evaluate_expected_process_environment,
    evaluate_expected_server_config,
    evaluate_forbidden_mapped_libraries,
    finalize_renderer_attestation,
    load_phase_depth_observations,
    parse_depth_messages,
    parse_depth_sim_frequency,
    parse_mapped_libraries,
    parse_topic_frequency,
    probe_egl_renderer,
)


def test_d3d12_profile_pins_nvidia_without_changing_default_environment():
    default = resolve_renderer_profile("default")
    d3d12 = resolve_renderer_profile("d3d12-nvidia")

    assert default.environment == {}
    assert default.required_adapter is None
    assert not default.require_d3d12
    assert d3d12.environment == {
        "GALLIUM_DRIVER": "d3d12",
        "MESA_D3D12_DEFAULT_ADAPTER_NAME": "NVIDIA",
    }
    assert d3d12.required_adapter == "NVIDIA"
    assert d3d12.require_d3d12


def test_unknown_renderer_profile_is_rejected():
    with pytest.raises(ValueError, match="unsupported Gazebo renderer profile"):
        resolve_renderer_profile("vulkan-maybe")


def test_resolved_profile_environment_cannot_mutate_profile_registry():
    first = resolve_renderer_profile("d3d12-nvidia")
    first.environment["GALLIUM_DRIVER"] = "llvmpipe"

    assert resolve_renderer_profile("d3d12-nvidia").environment["GALLIUM_DRIVER"] == "d3d12"


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("OpenGL renderer string: D3D12 (NVIDIA GeForce RTX 3070 Ti Laptop GPU)\n", "D3D12 (NVIDIA GeForce RTX 3070 Ti Laptop GPU)"),
        ("OpenGL renderer string: D3D12 (Intel(R) Iris(R) Xe Graphics)\n", "D3D12 (Intel(R) Iris(R) Xe Graphics)"),
        ("OpenGL renderer string: llvmpipe (LLVM 20.1.2, 256 bits)\n", "llvmpipe (LLVM 20.1.2, 256 bits)"),
        ("EGL vendor string: Mesa Project\n", None),
    ],
)
def test_egl_parser_extracts_renderer(output, expected):
    assert parse_egl_renderer(output) == expected


def _observations(count=5, *, width=160, height=120, frequency_hz=10.0, message_count=2):
    return {
        f"/world/fly/model/x500_depth_fly_{index}/sensor/StereoOV7251/depth_image": DepthObservation(
            width=width,
            height=height,
            frequency_hz=frequency_hz,
            message_count=message_count,
        )
        for index in range(count)
    }


@pytest.mark.parametrize(
    ("renderer", "reason"),
    [
        ("llvmpipe (LLVM 20.1.2, 256 bits)", "d3d12_not_active"),
        ("D3D12 (Intel(R) Iris(R) Xe Graphics)", "required_adapter_missing"),
        (None, "egl_renderer_missing"),
    ],
)
def test_d3d12_attestation_rejects_wrong_backend_or_adapter(renderer, reason):
    result = evaluate_renderer_attestation(
        profile=resolve_renderer_profile("d3d12-nvidia"),
        egl_renderer=renderer,
        mapped_libraries={"/usr/lib/wsl/lib/libd3d12.so", "/usr/lib/wsl/lib/libdxcore.so"},
        depth_observations=_observations(),
        expected_depth_topics=5,
    )

    assert not result["accepted"]
    assert reason in result["reasons"]


@pytest.mark.parametrize(
    ("libraries", "observations", "reason"),
    [
        ({"/usr/lib/wsl/lib/libd3d12.so"}, _observations(), "d3d12_libraries_missing"),
        (
            {"/usr/lib/wsl/lib/libd3d12.so", "/usr/lib/wsl/lib/libdxcore.so"},
            _observations(4),
            "depth_topic_count_mismatch",
        ),
        (
            {"/usr/lib/wsl/lib/libd3d12.so", "/usr/lib/wsl/lib/libdxcore.so"},
            _observations(message_count=0),
            "depth_stream_missing",
        ),
        (
            {"/usr/lib/wsl/lib/libd3d12.so", "/usr/lib/wsl/lib/libdxcore.so"},
            _observations(width=80, height=60),
            "depth_resolution_mismatch",
        ),
        (
            {"/usr/lib/wsl/lib/libd3d12.so", "/usr/lib/wsl/lib/libdxcore.so"},
            _observations(frequency_hz=8.9),
            "depth_frequency_out_of_range",
        ),
    ],
)
def test_d3d12_attestation_requires_process_libraries_and_every_depth_stream(libraries, observations, reason):
    result = evaluate_renderer_attestation(
        profile=resolve_renderer_profile("d3d12-nvidia"),
        egl_renderer="D3D12 (NVIDIA GeForce RTX 3070 Ti Laptop GPU)",
        mapped_libraries=libraries,
        depth_observations=observations,
        expected_depth_topics=5,
    )

    assert not result["accepted"]
    assert reason in result["reasons"]


def test_default_attestation_records_backend_without_requiring_d3d12():
    result = evaluate_renderer_attestation(
        profile=resolve_renderer_profile("default"),
        egl_renderer="llvmpipe (LLVM 20.1.2, 256 bits)",
        mapped_libraries=set(),
        depth_observations=_observations(),
        expected_depth_topics=5,
    )

    assert result["accepted"]
    assert result["egl_renderer"] == "llvmpipe (LLVM 20.1.2, 256 bits)"
    assert result["reasons"] == []


@pytest.mark.parametrize(
    ("engine", "libraries", "accepted"),
    (
        ("ogre2", {"/usr/lib/gz-rendering/libgz-rendering8-ogre2.so.8"}, True),
        ("ogre", {"/usr/lib/gz-rendering/libgz-rendering8-ogre.so.8"}, True),
        ("ogre", {"/usr/lib/gz-rendering/libgz-rendering8-ogre2.so.8"}, False),
    ),
)
def test_attestation_proves_requested_render_engine(engine, libraries, accepted):
    result = evaluate_renderer_attestation(
        profile=resolve_renderer_profile("d3d12-nvidia"),
        egl_renderer="D3D12 (NVIDIA GeForce RTX 3070 Ti Laptop GPU)",
        mapped_libraries={
            "/usr/lib/wsl/lib/libd3d12.so",
            "/usr/lib/wsl/lib/libdxcore.so",
            *libraries,
        },
        depth_observations=_observations(),
        expected_depth_topics=5,
        expected_render_engine=engine,
    )

    assert result["requested_render_engine"] == engine
    assert result["render_engine_accepted"] is accepted
    assert result["accepted"] is accepted
    assert ("render_engine_mismatch" in result["reasons"]) is (not accepted)


def test_expected_sensors_plugin_requires_exact_mapped_file_and_hash(tmp_path):
    plugin = tmp_path / "libgz-sim8-sensors-system.so"
    plugin.write_bytes(b"development sensor plugin")
    expected_sha = "073a89a2367a7f57da57a8576ab96e0a5e75dafbc6aa5098db2e7fded9f2cbe7"

    accepted = evaluate_expected_plugin(
        plugin,
        expected_sha256=expected_sha,
        mapped_libraries={str(plugin.resolve())},
    )
    missing = evaluate_expected_plugin(
        plugin,
        expected_sha256=expected_sha,
        mapped_libraries=set(),
    )

    assert accepted["accepted"] is True
    assert accepted["sha256"] == expected_sha
    assert accepted["mapped_path"] == str(plugin.resolve())
    assert missing["accepted"] is False
    assert "plugin_not_mapped" in missing["reasons"]


def test_expected_server_config_binds_hash_and_exact_sensors_plugin(tmp_path):
    plugin = (tmp_path / "libgz-sim8-sensors-system.so").resolve()
    config = tmp_path / "custom-server.config"
    config.write_text(
        '<plugin entity_name="*" entity_type="world" '
        f'filename="{plugin}" name="gz::sim::systems::Sensors">\n'
        "  <render_engine>ogre2</render_engine>\n"
        "</plugin>\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(config.read_bytes()).hexdigest()

    accepted = evaluate_expected_server_config(
        config,
        expected_sha256=digest,
        expected_plugin_path=plugin,
        process_environment={"GZ_SIM_SERVER_CONFIG_PATH": str(config)},
    )
    wrong_plugin = evaluate_expected_server_config(
        config,
        expected_sha256=digest,
        expected_plugin_path=tmp_path / "different.so",
        process_environment={"GZ_SIM_SERVER_CONFIG_PATH": str(config)},
    )
    unused_config = evaluate_expected_server_config(
        config,
        expected_sha256=digest,
        expected_plugin_path=plugin,
        process_environment={"GZ_SIM_SERVER_CONFIG_PATH": str(tmp_path / "other.config")},
    )

    assert accepted["accepted"] is True
    assert accepted["sha256"] == digest
    assert accepted["sensors_plugin_entry_count"] == 1
    assert wrong_plugin["accepted"] is False
    assert "sensors_plugin_entry_mismatch" in wrong_plugin["reasons"]
    assert unused_config["accepted"] is False
    assert "process_server_config_mismatch" in unused_config["reasons"]


def test_expected_server_config_proves_forbidden_plugin_is_absent(tmp_path):
    config = tmp_path / "custom-server.config"
    config.write_text(
        '<server_config><plugins><plugin filename="gz-sim-physics-system" '
        'name="gz::sim::systems::Physics"/></plugins></server_config>\n',
        encoding="utf-8",
    )
    digest = hashlib.sha256(config.read_bytes()).hexdigest()

    accepted = evaluate_expected_server_config(
        config,
        expected_sha256=digest,
        expected_plugin_path=None,
        forbidden_plugin_names=("custom::GstCameraSystem",),
        process_environment={"GZ_SIM_SERVER_CONFIG_PATH": str(config)},
    )
    config.write_text(
        '<server_config><plugins><plugin filename="libGstCameraSystem.so" '
        'name="custom::GstCameraSystem"/></plugins></server_config>\n',
        encoding="utf-8",
    )
    rejected_digest = hashlib.sha256(config.read_bytes()).hexdigest()
    rejected = evaluate_expected_server_config(
        config,
        expected_sha256=rejected_digest,
        expected_plugin_path=None,
        forbidden_plugin_names=("custom::GstCameraSystem",),
        process_environment={"GZ_SIM_SERVER_CONFIG_PATH": str(config)},
    )

    assert accepted["accepted"] is True
    assert accepted["forbidden_plugin_counts"] == {"custom::GstCameraSystem": 0}
    assert rejected["accepted"] is False
    assert rejected["forbidden_plugin_counts"] == {"custom::GstCameraSystem": 1}
    assert "forbidden_server_plugin_present" in rejected["reasons"]


def test_forbidden_mapped_library_requires_runtime_absence():
    accepted = evaluate_forbidden_mapped_libraries(
        ("libGstCameraSystem.so",),
        mapped_libraries={"/usr/lib/libgz-sim8.so.8"},
    )
    rejected = evaluate_forbidden_mapped_libraries(
        ("libGstCameraSystem.so",),
        mapped_libraries={"/opt/px4/libGstCameraSystem.so"},
    )

    assert accepted["accepted"] is True
    assert accepted["matches"] == {"libGstCameraSystem.so": []}
    assert rejected["accepted"] is False
    assert rejected["matches"] == {
        "libGstCameraSystem.so": ["/opt/px4/libGstCameraSystem.so"]
    }
    assert "forbidden_mapped_library_present" in rejected["reasons"]


def test_process_maps_parser_preserves_spaces_and_deleted_library_identity():
    maps = (
        "7f00-7f10 r-xp 00000000 08:01 10 /opt/PX4 Plugins/libGstCameraSystem.so (deleted)\n"
        "7f20-7f30 r-xp 00000000 08:01 11 /usr/lib/libgz-sim8.so.8\n"
        "7f40-7f50 rw-p 00000000 00:00 0 [heap]\n"
    )

    assert parse_mapped_libraries(maps) == {
        "/opt/PX4 Plugins/libGstCameraSystem.so",
        "/usr/lib/libgz-sim8.so.8",
    }


def test_expected_process_environment_binds_gazebo_to_loopback():
    accepted = evaluate_expected_process_environment(
        {"GZ_IP": "127.0.0.1"}, expected_gz_ip="127.0.0.1"
    )
    rejected = evaluate_expected_process_environment(
        {"GZ_IP": "172.28.0.10"}, expected_gz_ip="127.0.0.1"
    )

    assert accepted == {
        "accepted": True,
        "expected_gz_ip": "127.0.0.1",
        "process_gz_ip": "127.0.0.1",
        "reasons": [],
    }
    assert rejected["accepted"] is False
    assert rejected["reasons"] == ["process_gz_ip_mismatch"]


def test_eglinfo_nonzero_exit_keeps_a_parseable_renderer():
    output = "OpenGL core profile renderer: llvmpipe (LLVM 20.1.2, 256 bits)\n"

    renderer = probe_egl_renderer(
        {},
        run=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 3, output),
    )

    assert renderer == "llvmpipe (LLVM 20.1.2, 256 bits)"


def test_optional_wall_frequency_failure_is_recorded_without_rejecting_core_attestation():
    result = {"accepted": True, "reasons": []}

    finalize_renderer_attestation(
        result,
        probe_errors=[],
        wall_frequency_errors={"/depth": "timed out"},
    )

    assert result["accepted"]
    assert result["wall_frequency_errors"] == {"/depth": "timed out"}


def test_phase_ready_marker_supplies_depth_evidence_without_temporary_subscriptions(tmp_path):
    marker = tmp_path / "camera-phase-ready.json"
    topic = (
        "/world/flydrones_forest/model/x500_depth_fly_0"
        "/link/camera_link/sensor/StereoOV7251/depth_image"
    )
    marker.write_text(
        json.dumps(
            {
                "schema": "flydrones-camera-phase-ready-v1",
                "vehicle_count": 1,
                "depth_topics": [topic],
                "depth_observations": {
                    topic: {
                        "width": 160,
                        "height": 120,
                        "frequency_hz": 10.0,
                        "message_count": 11,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    observations = load_phase_depth_observations(
        marker,
        expected_topics=[topic],
        minimum_message_count=11,
    )

    assert observations[topic].width == 160
    assert observations[topic].height == 120
    assert observations[topic].frequency_hz == pytest.approx(10.0)
    assert observations[topic].message_count == 11


def test_phase_ready_marker_rejects_incomplete_stream_evidence(tmp_path):
    marker = tmp_path / "camera-phase-ready.json"
    marker.write_text(
        json.dumps(
            {
                "schema": "flydrones-camera-phase-ready-v1",
                "vehicle_count": 1,
                "depth_topics": ["/depth"],
                "depth_observations": {
                    "/depth": {
                        "width": 160,
                        "height": 120,
                        "frequency_hz": 10.0,
                        "message_count": 10,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="message_count"):
        load_phase_depth_observations(
            marker,
            expected_topics=["/depth"],
            minimum_message_count=11,
        )


def test_depth_message_parser_counts_concatenated_json_messages():
    output = '{"width":160,"height":120,"data":"AA=="}\n{"width":160,"height":120,"data":"AQ=="}\n'

    assert parse_depth_messages(output) == (160, 120, 2)


def test_depth_frequency_uses_message_simulation_timestamps_instead_of_wall_rate():
    output = "\n".join([
        '{"width":160,"height":120,"header":{"stamp":{"sec":7,"nsec":0}}}',
        '{"width":160,"height":120,"header":{"stamp":{"sec":7,"nsec":100000000}}}',
        '{"width":160,"height":120,"header":{"stamp":{"sec":7,"nsec":200000000}}}',
    ])

    assert parse_depth_sim_frequency(output) == pytest.approx(10.0)


def test_longer_depth_window_averages_gazebo_step_quantization():
    intervals_ns = [88_000_000, 112_000_000] * 5
    stamps = [7_000_000_000]
    for interval in intervals_ns:
        stamps.append(stamps[-1] + interval)
    output = "\n".join(
        json.dumps({
            "width": 160,
            "height": 120,
            "header": {"stamp": {"sec": stamp // 1_000_000_000,
                                   "nsec": stamp % 1_000_000_000}},
        })
        for stamp in stamps
    )

    assert parse_depth_sim_frequency(output) == pytest.approx(10.0)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("Hz: 9.997\n", 9.997),
        ("Mean frequency: 10.02 Hz\n", 10.02),
        ("No messages received\n", 0.0),
    ],
)
def test_topic_frequency_parser_accepts_gz_output_variants(output, expected):
    assert parse_topic_frequency(output) == expected
