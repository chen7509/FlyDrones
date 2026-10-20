#pragma once

#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
#include <ostream>
#include <sstream>

namespace flydrones {

template <typename Array>
void append_float32_array(std::ostream & output, const Array & values) {
  output << '[';
  bool first = true;
  for (const auto raw : values) {
    if (!first) {output << ',';}
    first = false;
    const float value = static_cast<float>(raw);
    if (!std::isfinite(value)) {
      output << "null";
    } else {
      std::ostringstream number;
      number.imbue(std::locale::classic());
      number << std::setprecision(std::numeric_limits<float>::max_digits10) << value;
      output << number.str();
    }
  }
  output << ']';
}

template <typename Message>
void append_full_odometry_fields(std::ostream & output, const Message & decoded) {
  output << ",\"position_ned_m\":";
  append_float32_array(output, decoded.position);
  output << ",\"q_body_to_ned_wxyz\":";
  append_float32_array(output, decoded.q);
  output << ",\"velocity_ned_m_s\":";
  append_float32_array(output, decoded.velocity);
  output << ",\"omega_body_frd_rad_s\":";
  append_float32_array(output, decoded.angular_velocity);
  output << ",\"position_variance_m2\":";
  append_float32_array(output, decoded.position_variance);
  output << ",\"orientation_variance_rad2\":";
  append_float32_array(output, decoded.orientation_variance);
  output << ",\"velocity_variance_m2_s2\":";
  append_float32_array(output, decoded.velocity_variance);
}

}  // namespace flydrones
