from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

from tools.configure_gazebo_vio_model import with_raw_odometry_topic
from tools.relay_gazebo_vio import apply_position_offset, frame_id_and_stamp


def fake_message():
    position = SimpleNamespace(x=1.0, y=-2.0, z=3.0)
    pose = SimpleNamespace(position=position)
    return SimpleNamespace(
        header=SimpleNamespace(
            data=[SimpleNamespace(key="frame_id", value=["x500_depth_fly_0/odom"])],
            stamp=SimpleNamespace(sec=4, nsec=5),
        ),
        pose_with_covariance=SimpleNamespace(pose=pose),
    )


def test_fault_trial_model_moves_covariance_odometry_to_raw_topic():
    source = Path("assets/gazebo/models/x500_depth_fly/model.sdf").read_text(encoding="utf-8")
    result = with_raw_odometry_topic(source, "/flydrones/odometry_raw")
    plugin = ElementTree.fromstring(result).find(".//plugin[@name='gz::sim::systems::OdometryPublisher']")
    assert plugin is not None
    assert plugin.findtext("odom_covariance_topic") == "/flydrones/odometry_raw"
    assert ElementTree.fromstring(source).find(".//odom_covariance_topic") is None


def test_relay_preserves_source_stamp_and_original_when_offsetting_position():
    original = fake_message()
    assert frame_id_and_stamp(original) == ("x500_depth_fly_0/odom", 4_000_000_005)
    modified = apply_position_offset(original, (0.5, -0.25, 1.0))
    assert (modified.pose_with_covariance.pose.position.x,
            modified.pose_with_covariance.pose.position.y,
            modified.pose_with_covariance.pose.position.z) == (1.5, -2.25, 4.0)
    assert frame_id_and_stamp(modified) == frame_id_and_stamp(original)
    assert original.pose_with_covariance.pose.position.x == 1.0
