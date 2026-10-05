// GPL-linked research adapter. Native coordinates only; no PX4 publication.
#pragma once
#include <chrono>
#include <iomanip>
#include <ostream>
#include "core/VioManager.h"
#include "state/Propagator.h"
#include "state/StateHelper.h"

inline void write_fast_prediction(ov_msckf::VioManager &manager, bool internal_ready,
                                  std::ostream &out, long long target_ns,
                                  long long last_camera_ns, long long available_imu_ns) {
  auto state = manager.get_state();
  const double offset = state->_calib_dt_CAMtoIMU->value()(0);
  if (offset != 0.0) throw std::runtime_error("nonzero camera/IMU offset requires separate validation");
  const double before_time = state->_timestamp;
  const Eigen::MatrixXd before_value = state->_imu->value();
  const Eigen::MatrixXd before_cov = ov_msckf::StateHelper::get_marginal_covariance(state, {state->_imu});
  Eigen::Matrix<double, 13, 1> prediction;
  Eigen::Matrix<double, 12, 12> covariance;
  const auto start = std::chrono::steady_clock::now();
  const bool success = internal_ready && target_ns * 1e-9 > before_time &&
      manager.get_propagator()->fast_state_propagate(state, target_ns * 1e-9, prediction, covariance);
  const double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
  const bool unchanged = before_time == state->_timestamp &&
      (before_value.array() == state->_imu->value().array()).all() &&
      (before_cov.array() == ov_msckf::StateHelper::get_marginal_covariance(state, {state->_imu}).array()).all();
  out << std::setprecision(17) << std::boolalpha << "{\"target_ns\":" << target_ns
      << ",\"last_camera_ns\":";
  if (last_camera_ns < 0) out << "null"; else out << last_camera_ns;
  out << ",\"available_imu_ns\":" << available_imu_ns
      << ",\"filter_time_s\":" << before_time << ",\"camera_imu_offset_s\":" << offset
      << ",\"internal_initialized\":" << internal_ready << ",\"public_initialized\":" << manager.initialized()
      << ",\"success\":" << success << ",\"filter_unchanged\":" << unchanged
      << ",\"propagation_wall_s\":" << wall;
  if (success) {
    out << ",\"state13\":[";
    for (int i = 0; i < 13; ++i) { if (i) out << ','; out << prediction(i); }
    out << "],\"covariance12\":[";
    for (int i = 0; i < 12; ++i) {
      if (i) out << ',';
      out << '[';
      for (int j = 0; j < 12; ++j) { if (j) out << ','; out << covariance(i, j); }
      out << ']';
    }
    out << "]}\n";
  } else {
    out << ",\"state13\":null,\"covariance12\":null}\n";
  }
  if (!unchanged) throw std::runtime_error("fast propagation changed camera filter state");
}
