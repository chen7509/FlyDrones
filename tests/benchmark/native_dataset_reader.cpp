// SPDX-License-Identifier: GPL-3.0-or-later
// Native parser test harness only. Does not link or instantiate OpenVINS.
#include "openvins_dataset_io.h"
#include <iostream>
int main(int argc,char **argv) {
  if (argc!=3) return 2;
  try {
    auto frames=recorded_dataset::frames(argv[1]);
    auto imu=recorded_dataset::imus(argv[2]);
    std::cout << frames.size() << ',' << imu.size() << ',' << frames.front().ns << ',' << imu.front().ns << '\n';
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n'; return 1;
  }
}
