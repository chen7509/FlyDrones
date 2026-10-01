#!/usr/bin/env python3
"""TCP-to-ROS observation bridge for the pinned EGO-Swarm container."""

from __future__ import annotations

import argparse
import base64
import json
import socket
import struct
import threading
import time

import numpy as np
import rclpy
from builtin_interfaces.msg import Time
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from quadrotor_msgs.msg import PositionCommand
from rclpy.node import Node
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Image


OBSERVATION_FIELDS = {
    'sim_ns', 'frame_ns', 'rgb', 'depth_m', 'camera_pose',
    'position', 'velocity', 'yaw', 'yaw_rate', 'goal',
}


def stamp(nanoseconds: int) -> Time:
    return Time(sec=nanoseconds // 1_000_000_000, nanosec=nanoseconds % 1_000_000_000)


def recv_exact(stream: socket.socket, size: int) -> bytes:
    chunks = []
    while size:
        chunk = stream.recv(size)
        if not chunk:
            raise ConnectionError('benchmark client disconnected')
        chunks.append(chunk)
        size -= len(chunk)
    return b''.join(chunks)


def recv_packet(stream: socket.socket) -> bytes:
    size = struct.unpack('!I', recv_exact(stream, 4))[0]
    if not 0 < size <= 8_000_000:
        raise ValueError('invalid observation packet size')
    return recv_exact(stream, size)


def send_packet(stream: socket.socket, payload: bytes) -> None:
    stream.sendall(struct.pack('!I', len(payload)) + payload)


def decode_observation(payload: bytes) -> dict:
    data = json.loads(payload)
    if set(data) != OBSERVATION_FIELDS:
        raise ValueError('unexpected observation fields')
    packed = data['depth_m']
    shape = packed['shape']
    raw = base64.b64decode(packed['data'], validate=True)
    depth = np.frombuffer(raw, dtype='<f4').reshape(shape)
    if depth.shape != (120, 160):
        raise ValueError('unexpected depth geometry')
    data['depth_m'] = depth
    return data


class Bridge(Node):
    def __init__(self, host: str, port: int, response_timeout_s: float):
        super().__init__('fly_ego_benchmark_bridge', parameter_overrides=[
            rclpy.parameter.Parameter('use_sim_time', value=True)
        ])
        self.clock_pub = self.create_publisher(Clock, '/clock', 10)
        self.odom_pub = self.create_publisher(Odometry, '/benchmark/ego/odom', 10)
        self.trigger_pub = self.create_publisher(PoseStamped, '/traj_start_trigger', 1)
        self.pose_pub = self.create_publisher(PoseStamped, '/benchmark/ego/camera_pose', 10)
        self.depth_pub = self.create_publisher(Image, '/benchmark/ego/depth', 10)
        self.create_subscription(PositionCommand, '/benchmark/ego/position_cmd', self.on_reference, 50)
        self.host = host
        self.port = port
        self.response_timeout_s = response_timeout_s
        self.last_frame_ns = -1
        self.reference_revision = 0
        self.reference = None
        self.trigger_sent = False
        self.latest_observation_sim_ns = None
        self.condition = threading.Condition()
        self.server_thread = threading.Thread(target=self.serve, daemon=True)
        self.server_thread.start()

    def on_reference(self, message: PositionCommand) -> None:
        if message.trajectory_flag != PositionCommand.TRAJECTORY_STATUS_READY:
            return
        with self.condition:
            if self.latest_observation_sim_ns is None:
                return
            reference = {
                # The ROS 2 upstream port constructs an unattached RCL_ROS_TIME
                # clock in traj_server, so its header stamp is wall time even
                # with use_sim_time. Anchor freshness to the newest observation
                # available when this command was received and retain the raw
                # upstream stamp as provenance.
                'sim_ns': int(self.latest_observation_sim_ns),
                'upstream_stamp_ns': (
                    int(message.header.stamp.sec) * 1_000_000_000
                    + int(message.header.stamp.nanosec)
                ),
                'position_ref': [message.position.x, message.position.y, message.position.z],
                'velocity_ref': [message.velocity.x, message.velocity.y, message.velocity.z],
                'yaw_rate': message.yaw_dot,
            }
            self.reference = reference
            self.reference_revision += 1
            self.condition.notify_all()

    def publish_observation(self, data: dict) -> None:
        with self.condition:
            self.latest_observation_sim_ns = int(data['sim_ns'])
        message_time = stamp(int(data['sim_ns']))
        self.clock_pub.publish(Clock(clock=message_time))

        odom = Odometry()
        odom.header.stamp = message_time
        odom.header.frame_id = 'world'
        odom.child_frame_id = 'base_link'
        odom.pose.pose.position.x, odom.pose.pose.position.y, odom.pose.pose.position.z = data['position']
        half = float(data['yaw']) / 2
        odom.pose.pose.orientation.z = float(np.sin(half))
        odom.pose.pose.orientation.w = float(np.cos(half))
        odom.twist.twist.linear.x, odom.twist.twist.linear.y, odom.twist.twist.linear.z = data['velocity']
        odom.twist.twist.angular.z = float(data['yaw_rate'])
        self.odom_pub.publish(odom)
        if not self.trigger_sent:
            trigger = PoseStamped()
            trigger.header.stamp = message_time
            trigger.header.frame_id = 'world'
            trigger.pose = odom.pose.pose
            self.trigger_pub.publish(trigger)
            self.trigger_sent = True

        if int(data['frame_ns']) <= self.last_frame_ns:
            return
        self.last_frame_ns = int(data['frame_ns'])
        frame_time = stamp(self.last_frame_ns)
        camera_pose = PoseStamped()
        camera_pose.header.stamp = frame_time
        camera_pose.header.frame_id = 'world'
        pose = data['camera_pose']
        camera_pose.pose.position.x, camera_pose.pose.position.y, camera_pose.pose.position.z = pose[:3]
        camera_pose.pose.orientation.x, camera_pose.pose.orientation.y = pose[3:5]
        camera_pose.pose.orientation.z, camera_pose.pose.orientation.w = pose[5:7]
        self.pose_pub.publish(camera_pose)

        depth = np.ascontiguousarray(data['depth_m'], dtype='<f4')
        image = Image()
        image.header.stamp = frame_time
        image.header.frame_id = 'camera_optical'
        image.height, image.width = depth.shape
        image.encoding = '32FC1'
        image.is_bigendian = False
        image.step = image.width * 4
        image.data = depth.tobytes()
        self.depth_pub.publish(image)

    def serve(self) -> None:
        with socket.create_server((self.host, self.port), reuse_port=False) as server:
            self.get_logger().info(f'TCP adapter listening on {self.host}:{self.port}')
            server.settimeout(.5)
            while rclpy.ok():
                try:
                    stream, _ = server.accept()
                except TimeoutError:
                    continue
                with stream:
                    stream.settimeout(self.response_timeout_s + 2)
                    try:
                        self.serve_client(stream)
                    except Exception as exc:
                        self.get_logger().error(f'adapter client failed: {exc!r}')

    def serve_client(self, stream: socket.socket) -> None:
        reset = json.loads(recv_packet(stream))
        if set(reset) != {'type', 'seed'} or reset['type'] != 'reset':
            raise ValueError('reset handshake required')
        self.last_frame_ns = -1
        self.trigger_sent = False
        with self.condition:
            self.reference = None
            self.latest_observation_sim_ns = None
        send_packet(stream, json.dumps({'status': 'ready'}).encode())
        while rclpy.ok():
            observation = decode_observation(recv_packet(stream))
            with self.condition:
                baseline_revision = self.reference_revision
            self.publish_observation(observation)
            deadline = time.monotonic() + self.response_timeout_s
            with self.condition:
                while self.reference_revision == baseline_revision and time.monotonic() < deadline:
                    self.condition.wait(deadline - time.monotonic())
                if self.reference_revision == baseline_revision:
                    response = {'error': 'EGO produced no new trajectory reference'}
                else:
                    response = self.reference
            send_packet(stream, json.dumps(response, allow_nan=False).encode())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=46200)
    parser.add_argument('--response-timeout-s', type=float, default=15.)
    args = parser.parse_args()
    rclpy.init()
    node = Bridge(args.host, args.port, args.response_timeout_s)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
