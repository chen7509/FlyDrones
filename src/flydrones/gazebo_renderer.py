"""Renderer profile selection and auditable Gazebo backend evidence."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RendererProfile:
    name: str
    environment: dict[str, str]
    required_adapter: str | None
    require_d3d12: bool


@dataclass(frozen=True)
class DepthObservation:
    width: int
    height: int
    frequency_hz: float
    message_count: int


_PROFILES = {
    "default": RendererProfile("default", {}, None, False),
    "d3d12-nvidia": RendererProfile(
        "d3d12-nvidia",
        {
            "GALLIUM_DRIVER": "d3d12",
            "MESA_D3D12_DEFAULT_ADAPTER_NAME": "NVIDIA",
        },
        "NVIDIA",
        True,
    ),
}


def resolve_renderer_profile(name: str) -> RendererProfile:
    try:
        profile = _PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unsupported Gazebo renderer profile: {name}") from exc
    return RendererProfile(
        profile.name,
        dict(profile.environment),
        profile.required_adapter,
        profile.require_d3d12,
    )


def parse_egl_renderer(text: str) -> str | None:
    prefixes = (
        "OpenGL renderer string:",
        "OpenGL core profile renderer:",
        "OpenGL compatibility profile renderer:",
    )
    for line in text.splitlines():
        stripped = line.strip()
        for prefix in prefixes:
            if stripped.startswith(prefix):
                return stripped[len(prefix):].strip() or None
    return None


def evaluate_renderer_attestation(
    *,
    profile: RendererProfile,
    egl_renderer: str | None,
    mapped_libraries: Collection[str],
    depth_observations: Mapping[str, DepthObservation],
    expected_depth_topics: int,
    expected_width: int = 160,
    expected_height: int = 120,
    expected_frequency_hz: float = 10.0,
    expected_render_engine: str | None = None,
) -> dict[str, object]:
    reasons: list[str] = []
    library_names = {Path(item).name for item in mapped_libraries}

    if expected_render_engine not in {None, "ogre", "ogre2"}:
        raise ValueError(f"unsupported Gazebo render engine: {expected_render_engine}")
    engine_library = None
    if expected_render_engine is not None:
        prefix = f"libgz-rendering8-{expected_render_engine}.so"
        engine_library = next(
            (name for name in sorted(library_names) if name.startswith(prefix)),
            None,
        )
        if engine_library is None:
            reasons.append("render_engine_mismatch")

    if egl_renderer is None:
        reasons.append("egl_renderer_missing")
    if profile.require_d3d12:
        if egl_renderer is not None and "D3D12" not in egl_renderer.upper():
            reasons.append("d3d12_not_active")
        if (
            egl_renderer is not None
            and profile.required_adapter is not None
            and profile.required_adapter.upper() not in egl_renderer.upper()
        ):
            reasons.append("required_adapter_missing")
        if not {"libd3d12.so", "libdxcore.so"}.issubset(library_names):
            reasons.append("d3d12_libraries_missing")

    if len(depth_observations) != expected_depth_topics:
        reasons.append("depth_topic_count_mismatch")
    if any(item.message_count < 1 for item in depth_observations.values()):
        reasons.append("depth_stream_missing")
    if any(
        item.width != expected_width or item.height != expected_height
        for item in depth_observations.values()
    ):
        reasons.append("depth_resolution_mismatch")
    frequency_lower = expected_frequency_hz * 0.9
    frequency_upper = expected_frequency_hz * 1.1
    if any(
        not frequency_lower <= item.frequency_hz <= frequency_upper
        for item in depth_observations.values()
    ):
        reasons.append("depth_frequency_out_of_range")

    return {
        "schema": "flydrones-gazebo-renderer-attestation-v1",
        "accepted": not reasons,
        "reasons": reasons,
        "requested_profile": profile.name,
        "requested_environment": dict(profile.environment),
        "requested_render_engine": expected_render_engine,
        "render_engine_library": engine_library,
        "render_engine_accepted": expected_render_engine is None or engine_library is not None,
        "egl_renderer": egl_renderer,
        "mapped_libraries": sorted(mapped_libraries),
        "expected_depth_topics": expected_depth_topics,
        "depth_observations": {
            topic: {
                "width": observation.width,
                "height": observation.height,
                "frequency_hz": observation.frequency_hz,
                "message_count": observation.message_count,
            }
            for topic, observation in sorted(depth_observations.items())
        },
    }
