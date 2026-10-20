#include <array>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>

#include "tools/connectome/px4_ros2_source/full_odometry_fields.hpp"

struct SyntheticOdometry {
  std::array<float, 3> position{{1.25f, -2.5f, std::numeric_limits<float>::quiet_NaN()}};
  std::array<float, 4> q{{1.f, 0.f, 0.f, 0.f}};
  std::array<float, 3> velocity{{0.1f, 0.2f, -0.3f}};
  std::array<float, 3> angular_velocity{{0.f, 0.f, 0.5f}};
  std::array<float, 3> position_variance{{0.01f, 0.02f, 0.03f}};
  std::array<float, 3> orientation_variance{{0.001f, 0.002f, 0.003f}};
  std::array<float, 3> velocity_variance{{0.1f, 0.2f, std::numeric_limits<float>::infinity()}};
};

int main() {
  std::ostringstream output;
  output << '{' << "\"kind\":\"sample\"";
  flydrones::append_full_odometry_fields(output, SyntheticOdometry{});
  output << '}';
  const std::string json = output.str();
  if (json.find("\"position_ned_m\":[1.25,-2.5,null]") == std::string::npos
      || json.find("\"velocity_variance_m2_s2\":[0.100000001,0.200000003,null]")
          == std::string::npos) {
    std::cerr << json << '\n';
    return 1;
  }
  std::cout << json << '\n';
}
