"""Route fault-trial Gazebo odometry through an isolated raw topic."""

from __future__ import annotations

import argparse
from pathlib import Path
from xml.etree import ElementTree


def with_raw_odometry_topic(sdf_text: str, raw_topic: str) -> str:
    if not raw_topic.startswith("/") or any(char.isspace() for char in raw_topic):
        raise ValueError("raw topic must be an absolute Gazebo topic without whitespace")
    root = ElementTree.fromstring(sdf_text)
    plugin = root.find(".//plugin[@name='gz::sim::systems::OdometryPublisher']")
    if plugin is None:
        raise ValueError("model has no Gazebo OdometryPublisher plugin")
    existing = plugin.find("odom_covariance_topic")
    if existing is None:
        existing = ElementTree.SubElement(plugin, "odom_covariance_topic")
    existing.text = raw_topic
    return ElementTree.tostring(root, encoding="unicode") + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("--raw-topic", default="/flydrones/odometry_raw")
    args = parser.parse_args()
    args.model.write_text(
        with_raw_odometry_topic(args.model.read_text(encoding="utf-8"), args.raw_topic),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
