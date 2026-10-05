// Research-only adapter to the pinned GPL-3.0 OpenVINS library.
// Not linked into the FlyDrones flight stack. No Gazebo truth input.
#include <cmath>
#include <chrono>
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
#include "exclusive_probe_output.h"


class DiagnosticManager : public ov_msckf::VioManager {
public:
  using ov_msckf::VioManager::VioManager;
  void write_diagnostics(std::ostream &out, long long image_ns, double wall_s) {
    out << std::setprecision(17) << std::boolalpha
        << "{\"image_ns\":" << image_ns
        << ",\"internal_initialized\":" << is_initialized_vio
        << ",\"public_initialized\":" << initialized()
        << ",\"initializer_time_s\":" << startup_time
        << ",\"state_time_s\":" << state->_timestamp
        << ",\"last_regular_update_s\":" << timelastupdate
        << ",\"zupt_flag_latched\":" << did_zupt_update
        << ",\"has_moved_since_zupt\":" << has_moved_since_zupt
        << ",\"feed_camera_wall_s\":" << wall_s;
    if (!is_initialized_vio) {
      out << ",\"quaternion_xyzw\":null,\"position\":null,\"velocity\":null,\"imu_covariance\":null}\n";
      return;
    }
    auto vector = [&out](const char *name, const auto &value) {
      out << ",\"" << name << "\":[";
      for (int i=0; i<value.size(); ++i) { if(i) out << ','; out << value(i); }
      out << ']';
    };
    vector("quaternion_xyzw", state->_imu->quat());
    vector("position", state->_imu->pos());
    vector("velocity", state->_imu->vel());
    auto cov = ov_msckf::StateHelper::get_marginal_covariance(state, {state->_imu});
    if (cov.rows()!=15 || cov.cols()!=15) throw std::runtime_error("unexpected IMU covariance shape");
    out << ",\"imu_covariance\":[";
    for(int i=0;i<15;++i) {
      if(i) out << ',';
      out << '[';
      for(int j=0;j<15;++j) { if(j) out << ','; out << cov(i,j); }
      out << ']';
    }
    out << "]}\n";
  }
};

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
    std::cerr << "usage: offline_probe config.yaml input_dir episode_dir state.csv diagnostics.jsonl\n";
    return 2;
  }
  try {
    const std::string config = argv[1], input_dir = argv[2], episode = argv[3], output = argv[4];
    flydrones_probe::validate_output_pair(output, argv[5]);
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
    DiagnosticManager manager(options);
    flydrones_probe::ExclusiveOutput diagnostics_file(argv[5]), states_file(output);
    auto &diagnostics = diagnostics_file.stream();
    auto &states = states_file.stream();
    states << "image_ns,initialized,state_timestamp_s,qx,qy,qz,qw,px,py,pz\n";
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
      const auto feed_start = std::chrono::steady_clock::now();
      manager.feed_measurement_camera(camera);
      const double feed_wall = std::chrono::duration<double>(std::chrono::steady_clock::now()-feed_start).count();
      manager.write_diagnostics(diagnostics, frame.ns, feed_wall);
      auto state = manager.get_state();
      states << frame.ns << ',' << (manager.initialized() ? 1 : 0) << ',' << std::setprecision(17)
             << state->_timestamp;
      if (manager.initialized()) {
        ++initialized_frames;
        auto value = state->_imu->value();
        states << ',' << value(0) << ',' << value(1) << ',' << value(2) << ',' << value(3)
               << ',' << value(4) << ',' << value(5) << ',' << value(6);
      } else {
        states << ",,,,,,,";
      }
      states << '\n';
    }
    diagnostics_file.finish();
    states_file.finish();
    std::cout << "frames=" << frames.size() << " imu_fed=" << next_imu
              << " initialized_frames=" << initialized_frames << "\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "offline_probe_error=" << error.what() << '\n';
    return 1;
  }
}
