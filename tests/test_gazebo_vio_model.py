from pathlib import Path
import xml.etree.ElementTree as ET


def test_depth_vehicle_model_publishes_external_vision_odometry():
    model_path = (
        Path(__file__).parents[1]
        / "assets"
        / "gazebo"
        / "models"
        / "x500_depth_fly"
        / "model.sdf"
    )
    root = ET.parse(model_path).getroot()
    model = root.find("model")
    assert model is not None
    included_models = {include.findtext("uri") for include in model.findall("include")}
    assert "x500" in included_models
    assert "model://OakD-Lite-Fly" in included_models
    plugins = {plugin.get("filename"): plugin for plugin in model.findall("plugin")}
    odometry = plugins["gz-sim-odometry-publisher-system"]
    assert odometry.get("name") == "gz::sim::systems::OdometryPublisher"
    assert odometry.findtext("dimensions") == "3"
