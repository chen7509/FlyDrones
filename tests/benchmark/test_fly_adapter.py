import numpy as np
import pytest

from flydrones.benchmark.contract import Command, Observation
from flydrones.benchmark.fly import FullFlyController, blend_goal, body_command_to_enu
from flydrones.motor.command import FlightCommand


def test_neural_turn_survives_goal_guidance():
    a = blend_goal(Command((.2,0.,0.), .2), (0.,0.,1.5), 0., (8.,0.,1.5), gain=.5, limit=.6)
    b = blend_goal(Command((.2,0.,0.), -.2), (0.,0.,1.5), 0., (8.,0.,1.5), gain=.5, limit=.6)
    assert a.yaw_rate > b.yaw_rate
    assert a.velocity_enu == (.2,0.,0.)


def test_guidance_does_not_add_forward_motion():
    cmd = blend_goal(Command((0.,0.,0.), 0.), (0.,0.,1.), 0., (0.,8.,1.), gain=.5, limit=.6)
    assert cmd.velocity_enu == (0.,0.,0.)
    assert cmd.yaw_rate == pytest.approx(.6)


def test_original_axes_map_clockwise_yaw_and_body_right():
    cmd = body_command_to_enu(FlightCommand(forward=1., lateral=.5, throttle=.4, yaw=1.), 0.)
    assert np.allclose(cmd.velocity_enu, (1., -.5, .2))
    assert cmd.yaw_rate == pytest.approx(-np.pi/4)
    turned = body_command_to_enu(FlightCommand(forward=1.), np.pi/2)
    assert np.allclose(turned.velocity_enu, (0.,1.,0.))


def test_step_ticks_full_brain_once_and_records_model_hash():
    class BrainStub:
        last_counts = np.array([1, 2, 3])

        def __init__(self):
            self.calls = 0

        def tick(self, inputs, ms):
            self.calls += 1
            assert ms == 50.0
            return {'DNg02_L': 4.0}

    class RetinaStub:
        def encode(self, rgb):
            return 'vision'

    class EncoderStub:
        def encode(self, vision, yaw_rate):
            return {'R16_L': np.array([1.0])}

    class DecoderStub:
        def update(self, rates, dt):
            assert dt == 0.05
            return FlightCommand(forward=0.2, yaw=0.1)

    controller = FullFlyController.__new__(FullFlyController)
    controller.guided = False
    controller.brain = BrainStub()
    controller.retina = RetinaStub()
    controller.encoder = EncoderStub()
    controller.decoder = DecoderStub()
    controller.connectome = type('ConnectomeStub', (), {'n': 166700, 'n_connections': 123})()
    controller.model_sha256 = 'abc123'
    controller.calls = 0
    controller.last_sim_ns = None
    obs = Observation(
        sim_ns=50_000_000, frame_ns=50_000_000,
        rgb=np.zeros((2, 2, 3), np.uint8), depth_m=np.ones((2, 2), np.float32),
        camera_pose=(0., 0., 1.5, 0., 0., 0., 1.), position=(0., 0., 1.5),
        velocity=(0., 0., 0.), yaw=0., yaw_rate=0., goal=(8., 0., 1.5),
    )

    decision = controller.step(obs)

    assert controller.brain.calls == 1
    assert decision.evidence['neurons'] == 166700
    assert decision.evidence['model_sha256'] == 'abc123'
