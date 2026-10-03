// SPDX-License-Identifier: GPL-3.0-only
// Research-only adapter to the pinned GPL-3.0 OpenVINS library.
// Not linked into the FlyDrones flight stack. No Gazebo truth input.
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <opencv2/imgcodecs.hpp>
#include "core/VioManager.h"
#include "core/VioManagerOptions.h"
#include "state/State.h"
#include "state/StateHelper.h"
#include "utils/opencv_yaml_parse.h"
#include "utils/print.h"
#include "utils/sensor_data.h"

struct Frame { long long ns; std::string relative_path; };
struct Imu { long long us; double gx, gy, gz, ax, ay, az; };

void strip_cr(std::string &line) {
  if (!line.empty() && line.back() == '\r') line.pop_back();
}

std::vector<std::string> cells(const std::string &line) {
  std::stringstream stream(line);
  std::vector<std::string> result;
  std::string value;
  while (std::getline(stream, value, ',')) result.push_back(value);
  return result;
}

std::vector<Frame> read_frames(const std::string &path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot read frames CSV");
  std::string line;
  std::getline(input, line);
  strip_cr(line);
  if (line != "timestamp_ns,relative_ppm_path") throw std::runtime_error("bad frame header");
  std::vector<Frame> frames;
  while (std::getline(input, line)) {
    strip_cr(line);
    auto c = cells(line);
    if (c.size() != 2) throw std::runtime_error("bad frame row");
    Frame row{std::stoll(c[0]), c[1]};
    if (!frames.empty() && row.ns <= frames.back().ns) throw std::runtime_error("frames not increasing");
    if (row.relative_path.find("..") != std::string::npos || row.relative_path[0] == '/')
      throw std::runtime_error("invalid relative frame path");
    frames.push_back(row);
  }
  return frames;
}

std::vector<Imu> read_imu(const std::string &path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot read IMU CSV");
  std::string line;
  std::getline(input, line);
  strip_cr(line);
  if (line != "timestamp_us,gx,gy,gz,ax,ay,az") throw std::runtime_error("bad IMU header");
  std::vector<Imu> samples;
  while (std::getline(input, line)) {
    strip_cr(line);
    auto c = cells(line);
    if (c.size() != 7) throw std::runtime_error("bad IMU row");
    Imu row{std::stoll(c[0]), std::stod(c[1]), std::stod(c[2]), std::stod(c[3]),
            std::stod(c[4]), std::stod(c[5]), std::stod(c[6])};
    if (!samples.empty() && row.us <= samples.back().us) throw std::runtime_error("IMU not increasing");
    if (!std::isfinite(row.gx) || !std::isfinite(row.gy) || !std::isfinite(row.gz) ||
        !std::isfinite(row.ax) || !std::isfinite(row.ay) || !std::isfinite(row.az))
      throw std::runtime_error("nonfinite IMU");
    samples.push_back(row);
  }
  return samples;
}

int main(int argc, char **argv) {
  if (argc != 6) {
    std::cerr << "usage: openvins_native_moments_probe config.yaml input_dir episode_dir state.csv moments.csv\n";
    return 2;
  }
  try {
    const std::string config = argv[1], input_dir = argv[2], episode = argv[3];
    const std::string output = argv[4], moments_output = argv[5];
    auto frames = read_frames(input_dir + "/frames.csv");
    auto imu = read_imu(input_dir + "/imu.csv");
    if (frames.size() < 20 || imu.size() < 100) throw std::runtime_error("input streams too short");
    ov_core::Printer::setPrintLevel("DEBUG");
    auto parser = std::make_shared<ov_core::YamlParser>(config);
    ov_msckf::VioManagerOptions options;
    options.print_and_load(parser);
    options.num_opencv_threads = 1;
    options.use_multi_threading_pubs = false;
    options.use_multi_threading_subs = false;
    if (!parser->successful()) throw std::runtime_error("OpenVINS config parser rejected config");
    ov_msckf::VioManager manager(options);
    std::ofstream states(output);
    if (!states) throw std::runtime_error("cannot open state output");
    states << "image_ns,initialized,state_timestamp_s,qx,qy,qz,qw,px,py,pz\n";
    std::ofstream moments(moments_output);
    if (!moments) throw std::runtime_error("cannot open moments output");
    moments << "image_ns,state_timestamp_s,vx,vy,vz";
    for (int row = 0; row < 15; ++row)
      for (int col = 0; col < 15; ++col)
        moments << ",cov_" << row << '_' << col;
    moments << '\n';
    size_t next_imu = 0, initialized_frames = 0;
    for (const auto &frame : frames) {
      const double frame_s = frame.ns * 1e-9;
      // Feed the first IMU sample *after* each camera timestamp as a buffer
      // boundary, matching the upstream camera/IMU subscriber's intent.
      while (next_imu < imu.size() && (imu[next_imu].us * 1e-6 <= frame_s ||
             (next_imu > 0 && imu[next_imu - 1].us * 1e-6 <= frame_s))) {
        const auto &sample = imu[next_imu++];
        ov_core::ImuData message;
        message.timestamp = sample.us * 1e-6;
        message.wm = Eigen::Vector3d(sample.gx, sample.gy, sample.gz);
        message.am = Eigen::Vector3d(sample.ax, sample.ay, sample.az);
        manager.feed_measurement_imu(message);
      }
      cv::Mat image = cv::imread(episode + "/" + frame.relative_path, cv::IMREAD_GRAYSCALE);
      if (image.empty() || image.cols != 160 || image.rows != 120 || image.type() != CV_8UC1)
        throw std::runtime_error("missing or malformed image at " + std::to_string(frame.ns));
      ov_core::CameraData camera;
      camera.timestamp = frame_s;
      camera.sensor_ids = {0};
      camera.images = {image};
      camera.masks = {cv::Mat::zeros(image.rows, image.cols, CV_8UC1)};
      manager.feed_measurement_camera(camera);
      auto state = manager.get_state();
      states << frame.ns << ',' << (manager.initialized() ? 1 : 0) << ',' << std::setprecision(17)
             << state->_timestamp;
      if (manager.initialized()) {
        ++initialized_frames;
        auto value = state->_imu->value();
        states << ',' << value(0) << ',' << value(1) << ',' << value(2) << ',' << value(3)
               << ',' << value(4) << ',' << value(5) << ',' << value(6);
        const auto velocity = state->_imu->vel();
        const auto covariance = ov_msckf::StateHelper::get_marginal_covariance(state, {state->_imu});
        if (covariance.rows() != 15 || covariance.cols() != 15 || !covariance.allFinite() || !velocity.allFinite())
          throw std::runtime_error("invalid native IMU state or covariance at " + std::to_string(frame.ns));
        moments << frame.ns << ',' << std::setprecision(17) << state->_timestamp
                << ',' << velocity(0) << ',' << velocity(1) << ',' << velocity(2);
        for (int row = 0; row < 15; ++row)
          for (int col = 0; col < 15; ++col)
            moments << ',' << covariance(row, col);
        moments << '\n';
      } else {
        states << ",,,,,,,";
      }
      states << '\n';
    }
    std::cout << "frames=" << frames.size() << " imu_fed=" << next_imu
              << " initialized_frames=" << initialized_frames << "\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "offline_probe_error=" << error.what() << '\n';
    return 1;
  }
}
