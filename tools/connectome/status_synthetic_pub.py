"""Synthetic ROS EstimatorStatus publisher for an isolated offline build.

It is deliberately unrelated to PX4/EKF2 and never grants capture.
"""

import argparse
import time

import rclpy
from px4_msgs.msg import EstimatorStatus
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=120)
    args = parser.parse_args()
    if not 3 <= args.count <= 120:
        raise ValueError("synthetic count outside 3..120")
    rclpy.init()
    node = Node("flydrones_synthetic_estimator_status")
    publisher = node.create_publisher(
        EstimatorStatus, "/fmu/out/estimator_status", qos_profile_sensor_data)
    try:
        deadline = time.monotonic() + 5
        while publisher.get_subscription_count() == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        if publisher.get_subscription_count() == 0:
            raise RuntimeError("synthetic status subscriber missing")
        for index in range(1, args.count + 1):
            message = EstimatorStatus()
            message.timestamp_sample = 1_000_000 + 50_000 * index
            message.timestamp = message.timestamp_sample + 1_000
            message.control_mode_flags = 3
            message.filter_fault_flags = 0
            message.gps_check_fail_flags = 0
            message.solution_status_flags = 7
            message.pos_horiz_accuracy = 0.123456789
            message.pos_vert_accuracy = 0.987654321
            message.hdg_test_ratio = 0.234567891
            message.vel_test_ratio = float("nan")
            message.pos_test_ratio = 0.345678912
            message.hgt_test_ratio = 0.456789123
            message.tas_test_ratio = 0.567891234
            message.hagl_test_ratio = 0.678912345
            message.beta_test_ratio = 0.789123456
            publisher.publish(message)
            time.sleep(0.05)
        print(f"synthetic_status_messages_published={args.count}", flush=True)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
