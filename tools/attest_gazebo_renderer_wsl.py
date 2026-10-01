"""Attest the renderer and depth streams of an already-running Gazebo server."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from flydrones.gazebo_renderer import (
    DepthObservation,
    evaluate_renderer_attestation,
    parse_egl_renderer,
    resolve_renderer_profile,
)


def evaluate_expected_plugin(
    expected_path: Path,
    *,
    expected_sha256: str,
    mapped_libraries: set[str],
) -> dict[str, object]:
    resolved = expected_path.resolve()
    reasons: list[str] = []
    try:
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError:
        digest = None
        reasons.append("plugin_file_unreadable")
    if digest is not None and digest != expected_sha256:
        reasons.append("plugin_hash_mismatch")
    resolved_maps = {str(Path(item).resolve()) for item in mapped_libraries}
    if str(resolved) not in resolved_maps:
        reasons.append("plugin_not_mapped")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "expected_path": str(resolved),
        "expected_sha256": expected_sha256,
        "sha256": digest,
        "mapped_path": str(resolved) if str(resolved) in resolved_maps else None,
    }


def evaluate_expected_server_config(
    expected_path: Path,
    *,
    expected_sha256: str,
    expected_plugin_path: Path | None,
    forbidden_plugin_names: Sequence[str] = (),
    process_environment: Mapping[str, str],
) -> dict[str, object]:
    resolved = expected_path.resolve()
    expected_plugin = (
        expected_plugin_path.resolve() if expected_plugin_path is not None else None
    )
    reasons: list[str] = []
    contents: bytes | None = None
    try:
        contents = resolved.read_bytes()
    except OSError:
        reasons.append("server_config_unreadable")
    digest = hashlib.sha256(contents).hexdigest() if contents is not None else None
    if digest is not None and digest != expected_sha256:
        reasons.append("server_config_hash_mismatch")
    process_config_value = process_environment.get("GZ_SIM_SERVER_CONFIG_PATH")
    process_config_path = (
        Path(process_config_value).resolve() if process_config_value else None
    )
    if process_config_path != resolved:
        reasons.append("process_server_config_mismatch")

    sensors_entries: list[str] = []
    plugin_names: list[str] = []
    forbidden_plugin_counts = {name: 0 for name in forbidden_plugin_names}
    if contents is not None:
        try:
            root = ET.fromstring(contents)
        except ET.ParseError:
            reasons.append("server_config_xml_invalid")
        else:
            plugin_names = [
                str(element.get("name", "")) for element in root.iter("plugin")
            ]
            sensors_entries = [
                str(element.get("filename", ""))
                for element in root.iter("plugin")
                if element.get("name") == "gz::sim::systems::Sensors"
            ]
            if expected_plugin is not None and (
                len(sensors_entries) != 1
                or Path(sensors_entries[0]).resolve() != expected_plugin
            ):
                reasons.append("sensors_plugin_entry_mismatch")
            forbidden_plugin_counts = {
                name: plugin_names.count(name) for name in forbidden_plugin_names
            }
            if any(forbidden_plugin_counts.values()):
                reasons.append("forbidden_server_plugin_present")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "expected_path": str(resolved),
        "expected_sha256": expected_sha256,
        "sha256": digest,
        "process_server_config_path": (
            str(process_config_path) if process_config_path is not None else None
        ),
        "expected_sensors_plugin": (
            str(expected_plugin) if expected_plugin is not None else None
        ),
        "sensors_plugin_entry_count": len(sensors_entries),
        "sensors_plugin_filename": sensors_entries[0] if len(sensors_entries) == 1 else None,
        "plugin_names": plugin_names,
        "forbidden_plugin_counts": forbidden_plugin_counts,
    }


def evaluate_forbidden_mapped_libraries(
    forbidden_basenames: Sequence[str],
    *,
    mapped_libraries: set[str],
) -> dict[str, object]:
    matches = {
        basename: sorted(
            library for library in mapped_libraries if Path(library).name == basename
        )
        for basename in forbidden_basenames
    }
    reasons = ["forbidden_mapped_library_present"] if any(matches.values()) else []
    return {"accepted": not reasons, "reasons": reasons, "matches": matches}


def evaluate_expected_process_environment(
    process_environment: Mapping[str, str],
    *,
    expected_gz_ip: str,
) -> dict[str, object]:
    process_gz_ip = process_environment.get("GZ_IP")
    reasons = [] if process_gz_ip == expected_gz_ip else ["process_gz_ip_mismatch"]
    return {
        "accepted": not reasons,
        "expected_gz_ip": expected_gz_ip,
        "process_gz_ip": process_gz_ip,
        "reasons": reasons,
    }


def parse_mapped_libraries(maps: str) -> set[str]:
    """Return shared-library paths without losing spaces or deleted identity."""
    libraries: set[str] = set()
    for line in maps.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) != 6:
            continue
        pathname = fields[5].removesuffix(" (deleted)")
        if ".so" in pathname:
            libraries.add(pathname)
    return libraries


def read_process_environment(pid: int) -> dict[str, str]:
    raw = Path(f"/proc/{pid}/environ").read_bytes()
    environment: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        environment[key.decode(errors="replace")] = value.decode(errors="replace")
    return environment


def _json_messages(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    index = 0
    messages: list[dict] = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        value, index = decoder.raw_decode(text, index)
        if isinstance(value, dict):
            messages.append(value)
    return messages


def parse_depth_messages(text: str) -> tuple[int, int, int]:
    messages = _json_messages(text)
    widths = {int(message.get("width", 0)) for message in messages}
    heights = {int(message.get("height", 0)) for message in messages}
    width = widths.pop() if len(widths) == 1 else 0
    height = heights.pop() if len(heights) == 1 else 0
    return width, height, len(messages)


def parse_depth_sim_frequency(text: str) -> float:
    timestamps = []
    for message in _json_messages(text):
        stamp = message.get("header", {}).get("stamp", {})
        try:
            timestamps.append(float(stamp["sec"]) + float(stamp["nsec"]) / 1_000_000_000)
        except (KeyError, TypeError, ValueError):
            continue
    if len(timestamps) < 2 or timestamps[-1] <= timestamps[0]:
        return 0.0
    return (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])


def parse_topic_frequency(text: str) -> float:
    for line in text.splitlines():
        if "hz" not in line.lower():
            continue
        values = re.findall(r"(?:^|[^\w.])([0-9]+(?:\.[0-9]+)?)", line)
        if values:
            return float(values[-1])
    return 0.0


def load_phase_depth_observations(
    marker: Path,
    *,
    expected_topics: Sequence[str],
    minimum_message_count: int,
) -> dict[str, DepthObservation]:
    """Load depth evidence from the permanent phase observer readiness marker."""

    payload = json.loads(marker.read_text(encoding="utf-8"))
    if payload.get("schema") != "flydrones-camera-phase-ready-v1":
        raise ValueError("phase ready marker schema is invalid")
    topics = payload.get("depth_topics")
    raw_observations = payload.get("depth_observations")
    if topics != list(expected_topics) or not isinstance(raw_observations, dict):
        raise ValueError("phase ready marker depth topics do not match topology")
    observations: dict[str, DepthObservation] = {}
    for topic in expected_topics:
        raw = raw_observations.get(topic)
        if not isinstance(raw, dict):
            raise ValueError(f"depth observation missing for {topic}")
        width = raw.get("width")
        height = raw.get("height")
        frequency_hz = raw.get("frequency_hz")
        message_count = raw.get("message_count")
        if (
            isinstance(width, bool)
            or not isinstance(width, int)
            or isinstance(height, bool)
            or not isinstance(height, int)
            or isinstance(frequency_hz, bool)
            or not isinstance(frequency_hz, (int, float))
            or isinstance(message_count, bool)
            or not isinstance(message_count, int)
            or message_count < minimum_message_count
        ):
            raise ValueError(f"depth observation message_count or dimensions invalid for {topic}")
        observations[topic] = DepthObservation(
            width=width,
            height=height,
            frequency_hz=float(frequency_hz),
            message_count=message_count,
        )
    return observations


def _run(command: list[str], *, environment: dict[str, str], timeout: float) -> str:
    result = subprocess.run(
        command,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} exited {result.returncode}: {result.stdout.strip()}")
    return result.stdout


def probe_egl_renderer(
    environment: dict[str, str],
    *,
    run: Callable[..., Any] = subprocess.run,
) -> str:
    result = run(
        ["eglinfo", "-B"],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=15,
        check=False,
    )
    renderer = parse_egl_renderer(result.stdout)
    if renderer is None:
        raise RuntimeError(f"eglinfo exited {result.returncode} without a renderer: {result.stdout.strip()}")
    return renderer


def finalize_renderer_attestation(
    result: dict[str, object],
    *,
    probe_errors: list[str],
    wall_frequency_errors: dict[str, str],
) -> None:
    if probe_errors:
        result["accepted"] = False
        result["reasons"] = [*result.get("reasons", []), "probe_error"]
        result["probe_errors"] = probe_errors
    if wall_frequency_errors:
        result["wall_frequency_errors"] = wall_frequency_errors


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--render-engine", choices=("ogre", "ogre2"), default="ogre2")
    parser.add_argument("--expected-sensors-plugin", type=Path)
    parser.add_argument("--expected-sensors-plugin-sha256")
    parser.add_argument("--expected-server-config", type=Path)
    parser.add_argument("--expected-server-config-sha256")
    parser.add_argument("--forbidden-server-plugin-name", action="append", default=[])
    parser.add_argument("--forbidden-mapped-library", action="append", default=[])
    parser.add_argument("--expected-gz-ip")
    parser.add_argument("--gazebo-pid", type=int, required=True)
    parser.add_argument("--expected-depth-topics", type=int, required=True)
    parser.add_argument("--expected-width", type=int, default=160)
    parser.add_argument("--expected-height", type=int, default=120)
    parser.add_argument("--expected-frequency-hz", type=float, default=10.0)
    parser.add_argument("--phase-ready-marker", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.expected_sensors_plugin is None) != (
        args.expected_sensors_plugin_sha256 is None
    ):
        parser.error("expected sensors plugin path and SHA-256 must be provided together")
    if (args.expected_server_config is None) != (
        args.expected_server_config_sha256 is None
    ):
        parser.error("expected server config path and SHA-256 must be provided together")
    if args.expected_sensors_plugin is not None and args.expected_server_config is None:
        parser.error("custom sensors plugin attestation requires a server config pair")
    if args.forbidden_server_plugin_name and args.expected_server_config is None:
        parser.error("forbidden server plugins require a server config pair")

    profile = resolve_renderer_profile(args.profile)
    environment = os.environ.copy()
    environment.pop("GALLIUM_DRIVER", None)
    environment.pop("MESA_D3D12_DEFAULT_ADAPTER_NAME", None)
    environment.update(profile.environment)
    errors: list[str] = []

    try:
        egl_renderer = probe_egl_renderer(environment)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        egl_renderer = None
        errors.append(f"eglinfo: {exc}")

    try:
        maps = Path(f"/proc/{args.gazebo_pid}/maps").read_text(encoding="utf-8", errors="replace")
        libraries = parse_mapped_libraries(maps)
    except OSError as exc:
        libraries = set()
        errors.append(f"process-maps: {exc}")

    process_environment: dict[str, str] = {}
    if args.expected_server_config is not None or args.expected_gz_ip is not None:
        try:
            process_environment = read_process_environment(args.gazebo_pid)
        except OSError as exc:
            errors.append(f"process-environ: {exc}")

    try:
        listed = _run(["gz", "topic", "-l"], environment=environment, timeout=15)
        topics = sorted(
            line.strip() for line in listed.splitlines()
            if line.strip().endswith("/sensor/StereoOV7251/depth_image")
        )
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        topics = []
        errors.append(f"topic-list: {exc}")

    observations: dict[str, DepthObservation] = {}
    wall_frequencies: dict[str, float | str] = {}
    wall_frequency_errors: dict[str, str] = {}
    if args.phase_ready_marker is not None:
        try:
            observations = load_phase_depth_observations(
                args.phase_ready_marker,
                expected_topics=topics,
                minimum_message_count=11,
            )
            wall_frequencies = {
                topic: observation.frequency_hz for topic, observation in observations.items()
            }
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            errors.append(f"phase-depth-evidence: {exc}")
    else:
        for topic in topics:
            try:
                messages = _run(
                    ["gz", "topic", "-e", "--json-output", "-t", topic, "-n", "11"],
                    environment=environment,
                    timeout=15,
                )
                width, height, count = parse_depth_messages(messages)
                frequency = parse_depth_sim_frequency(messages)
                observations[topic] = DepthObservation(width, height, frequency, count)
            except (ValueError, OSError, subprocess.SubprocessError, RuntimeError) as exc:
                observations[topic] = DepthObservation(0, 0, 0.0, 0)
                errors.append(f"depth-topic {topic}: {exc}")
                continue
            try:
                wall_frequencies[topic] = parse_topic_frequency(_run(
                    ["gz", "topic", "-f", "-t", topic, "-d", "2"],
                    environment=environment,
                    timeout=10,
                ))
            except (ValueError, OSError, subprocess.SubprocessError, RuntimeError) as exc:
                wall_frequencies[topic] = "unavailable"
                wall_frequency_errors[topic] = str(exc)

    result = evaluate_renderer_attestation(
        profile=profile,
        egl_renderer=egl_renderer,
        mapped_libraries=libraries,
        depth_observations=observations,
        expected_depth_topics=args.expected_depth_topics,
        expected_width=args.expected_width,
        expected_height=args.expected_height,
        expected_frequency_hz=args.expected_frequency_hz,
        expected_render_engine=args.render_engine,
    )
    if args.expected_sensors_plugin is not None:
        plugin = evaluate_expected_plugin(
            args.expected_sensors_plugin,
            expected_sha256=args.expected_sensors_plugin_sha256,
            mapped_libraries=libraries,
        )
        result["sensors_plugin"] = plugin
        if not plugin["accepted"]:
            result["accepted"] = False
            result["reasons"] = [*result.get("reasons", []), "sensors_plugin_rejected"]
    if args.expected_server_config is not None:
        server_config = evaluate_expected_server_config(
            args.expected_server_config,
            expected_sha256=args.expected_server_config_sha256,
            expected_plugin_path=args.expected_sensors_plugin,
            forbidden_plugin_names=args.forbidden_server_plugin_name,
            process_environment=process_environment,
        )
        result["server_config"] = server_config
        if not server_config["accepted"]:
            result["accepted"] = False
            result["reasons"] = [
                *result.get("reasons", []),
                "server_config_rejected",
            ]
    if args.expected_gz_ip is not None:
        transport_environment = evaluate_expected_process_environment(
            process_environment,
            expected_gz_ip=args.expected_gz_ip,
        )
        result["transport_environment"] = transport_environment
        if not transport_environment["accepted"]:
            result["accepted"] = False
            result["reasons"] = [
                *result.get("reasons", []),
                "transport_environment_rejected",
            ]
    if args.forbidden_mapped_library:
        forbidden_libraries = evaluate_forbidden_mapped_libraries(
            args.forbidden_mapped_library,
            mapped_libraries=libraries,
        )
        result["forbidden_mapped_libraries"] = forbidden_libraries
        if not forbidden_libraries["accepted"]:
            result["accepted"] = False
            result["reasons"] = [
                *result.get("reasons", []),
                "forbidden_mapped_library_rejected",
            ]
    finalize_renderer_attestation(
        result,
        probe_errors=errors,
        wall_frequency_errors=wall_frequency_errors,
    )
    result["wall_frequency_hz"] = wall_frequencies
    _atomic_json(args.output, result)
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
