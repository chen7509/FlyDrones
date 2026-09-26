"""Attest the renderer and depth streams of an already-running Gazebo server."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from flydrones.gazebo_renderer import (
    DepthObservation,
    evaluate_renderer_attestation,
    parse_egl_renderer,
    resolve_renderer_profile,
)


def parse_depth_messages(text: str) -> tuple[int, int, int]:
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
    widths = {int(message.get("width", 0)) for message in messages}
    heights = {int(message.get("height", 0)) for message in messages}
    width = widths.pop() if len(widths) == 1 else 0
    height = heights.pop() if len(heights) == 1 else 0
    return width, height, len(messages)


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
        egl_renderer = parse_egl_renderer(_run(["eglinfo", "-B"], environment=environment, timeout=15))
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
    for topic in topics:
        try:
            messages = _run(
                ["gz", "topic", "-e", "--json-output", "-t", topic, "-n", "2"],
                environment=environment,
                timeout=15,
            )
            width, height, count = parse_depth_messages(messages)
            frequency = parse_topic_frequency(_run(
                ["gz", "topic", "-f", "-t", topic, "-d", "2"],
                environment=environment,
                timeout=10,
            ))
            observations[topic] = DepthObservation(width, height, frequency, count)
        except (ValueError, OSError, subprocess.SubprocessError, RuntimeError) as exc:
            observations[topic] = DepthObservation(0, 0, 0.0, 0)
            errors.append(f"depth-topic {topic}: {exc}")

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
    if errors:
        result["accepted"] = False
        result["reasons"] = [*result["reasons"], "probe_error"]
        result["probe_errors"] = errors
    _atomic_json(args.output, result)
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
