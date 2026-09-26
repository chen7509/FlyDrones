"""Attest the renderer and depth streams of an already-running Gazebo server."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from flydrones.gazebo_renderer import (
    DepthObservation,
    evaluate_renderer_attestation,
    parse_egl_renderer,
    resolve_renderer_profile,
)


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
    parser.add_argument("--gazebo-pid", type=int, required=True)
    parser.add_argument("--expected-depth-topics", type=int, required=True)
    parser.add_argument("--expected-width", type=int, default=160)
    parser.add_argument("--expected-height", type=int, default=120)
    parser.add_argument("--expected-frequency-hz", type=float, default=10.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

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
        libraries = {line.split()[-1] for line in maps.splitlines() if ".so" in line and line.split()}
    except OSError as exc:
        libraries = set()
        errors.append(f"process-maps: {exc}")

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
    )
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
