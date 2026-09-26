import pytest

from flydrones.gazebo_renderer import (
    DepthObservation,
    evaluate_renderer_attestation,
    parse_egl_renderer,
    resolve_renderer_profile,
)
from tools.attest_gazebo_renderer_wsl import (
    parse_depth_messages,
    parse_depth_sim_frequency,
    parse_topic_frequency,
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
