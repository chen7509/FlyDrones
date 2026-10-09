// Read-only ROS 2 source journal. No PX4 writes, actuator commands or capture grant.
#include <fcntl.h>
#include <openssl/sha.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

#include <ament_index_cpp/get_package_share_directory.hpp>
#include <px4_msgs/msg/vehicle_odometry.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp/serialization.hpp>
#include <rclcpp/serialized_message.hpp>
#include <rmw/types.h>

namespace {
constexpr auto kSchema = "flydrones.px4_ros2_odometry_cdr.v1";
constexpr auto kTopic = "/fmu/out/vehicle_odometry";
constexpr auto kType = "px4_msgs/msg/VehicleOdometry";
constexpr auto kBlob = "cf117ff82cdbf191bf576db91db900b7ce34f6a7";
constexpr auto kMsgSha256 = "a528b3d0b4c1a9083a71b32c367bad71a900e959efd82b9d03a9eb0e99fe6017";
constexpr std::size_t kMaxCdr = 4096;

std::string hex(const std::uint8_t * data, std::size_t size) {
  static constexpr char digits[] = "0123456789abcdef";
  std::string output(size * 2, '0');
  for (std::size_t i = 0; i < size; ++i) {
    output[2 * i] = digits[data[i] >> 4];
    output[2 * i + 1] = digits[data[i] & 15];
  }
  return output;
}

std::string sha256(const std::uint8_t * data, std::size_t size) {
  std::uint8_t digest[SHA256_DIGEST_LENGTH];
  if (SHA256(data, size, digest) == nullptr) {
    throw std::runtime_error("SHA256 failed");
  }
  return hex(digest, sizeof(digest));
}

void verify_installed_type() {
  const auto path = std::filesystem::path(
    ament_index_cpp::get_package_share_directory("px4_msgs")) / "msg/VehicleOdometry.msg";
  std::ifstream stream(path, std::ios::binary);
  if (!stream) {throw std::runtime_error("installed px4_msgs message missing");}
  const std::string bytes((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
  if (stream.bad() || sha256(reinterpret_cast<const std::uint8_t *>(bytes.data()), bytes.size())
      != kMsgSha256) {
    throw std::runtime_error("installed px4_msgs message changed");
  }
}

std::int64_t steady_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
}

std::string sequence_json(std::uint64_t value) {
  if (value == RMW_MESSAGE_INFO_SEQUENCE_NUMBER_UNSUPPORTED) {
    return "null";
  }
  return std::to_string(value);
}

class ExclusiveJournal {
public:
  ExclusiveJournal(const std::filesystem::path & path, std::string run_id)
  : run_id_(std::move(run_id)) {
    if (!std::regex_match(run_id_, std::regex("[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"))) {
      throw std::invalid_argument("run id invalid");
    }
    fd_ = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0644);
    if (fd_ < 0) {
      throw std::runtime_error(std::string("exclusive journal open failed: ") + std::strerror(errno));
    }
  }

  ExclusiveJournal(const ExclusiveJournal &) = delete;
  ExclusiveJournal & operator=(const ExclusiveJournal &) = delete;

  ~ExclusiveJournal() {
    if (fd_ >= 0) {
      ::close(fd_);
    }
  }

  void sample(const px4_msgs::msg::VehicleOdometry & decoded,
              const rclcpp::SerializedMessage & serialized,
              const rclcpp::MessageInfo & message_info,
              std::uint64_t journal_sequence, std::int64_t callback_ns) {
    const auto & raw = serialized.get_rcl_serialized_message();
    if (raw.buffer_length < 4 || raw.buffer_length > kMaxCdr || raw.buffer == nullptr) {
      throw std::runtime_error("CDR size invalid");
    }
    const auto & info = message_info.get_rmw_message_info();
    const auto * implementation = info.publisher_gid.implementation_identifier;
    if (implementation == nullptr || !std::regex_match(
          implementation, std::regex("[A-Za-z0-9_]{1,64}"))) {
      throw std::runtime_error("RMW implementation invalid");
    }
    const std::string gid = hex(info.publisher_gid.data, sizeof(info.publisher_gid.data));
    const std::string bytes = hex(raw.buffer, raw.buffer_length);
    std::ostringstream line;
    line << "{\"schema\":\"" << kSchema << "\",\"kind\":\"sample\""
         << ",\"topic\":\"" << kTopic << "\",\"ros_type\":\"" << kType << '"'
         << ",\"message_blob_sha\":\"" << kBlob << "\",\"run_id\":\"" << run_id_ << '"'
         << ",\"journal_sequence\":" << journal_sequence
         << ",\"rmw_implementation\":\"" << implementation << '"'
         << ",\"publisher_gid_hex\":\"" << gid << '"'
         << ",\"rmw_source_timestamp_ns\":" << std::max<std::int64_t>(0, info.source_timestamp)
         << ",\"rmw_received_timestamp_ns\":" << std::max<std::int64_t>(0, info.received_timestamp)
         << ",\"rmw_publication_sequence\":" << sequence_json(info.publication_sequence_number)
         << ",\"rmw_reception_sequence\":" << sequence_json(info.reception_sequence_number)
         << ",\"callback_steady_ns\":" << callback_ns
         << ",\"px4_publication_us\":" << decoded.timestamp
         << ",\"px4_sample_us\":" << decoded.timestamp_sample
         << ",\"pose_frame\":" << static_cast<int>(decoded.pose_frame)
         << ",\"velocity_frame\":" << static_cast<int>(decoded.velocity_frame)
         << ",\"reset_counter\":" << static_cast<int>(decoded.reset_counter)
         << ",\"quality\":" << static_cast<int>(decoded.quality)
         << ",\"cdr_hex\":\"" << bytes << "\",\"cdr_sha256\":\""
         << sha256(raw.buffer, raw.buffer_length) << "\"}\n";
    write_all(line.str());
  }

  void fault(const rclcpp::SerializedMessage & serialized, const std::string & reason) {
    const auto & raw = serialized.get_rcl_serialized_message();
    if (raw.buffer_length == 0 || raw.buffer == nullptr) {
      throw std::runtime_error("fault CDR cannot be retained");
    }
    const bool oversized = raw.buffer_length > kMaxCdr;
    std::ostringstream line;
    line << "{\"schema\":\"" << kSchema << "\",\"kind\":\"fault\""
         << ",\"run_id\":\"" << run_id_ << "\",\"reason\":\"" << reason << '"'
         << ",\"cdr_length\":" << raw.buffer_length
         << ",\"cdr_hex\":\"" << (oversized ? "" : hex(raw.buffer, raw.buffer_length))
         << "\",\"cdr_sha256\":\"" << sha256(raw.buffer, raw.buffer_length) << "\"}\n";
    write_all(line.str());
  }

  bool can_finish() const {return fd_ >= 0 && !terminal_attempted_;}

  void finish(std::uint64_t samples, bool complete, const std::string & reason) {
    if (!can_finish()) {throw std::runtime_error("journal terminal already attempted");}
    terminal_attempted_ = true;
    std::ostringstream line;
    line << "{\"schema\":\"" << kSchema << "\",\"kind\":\"finish\""
         << ",\"run_id\":\"" << run_id_ << "\",\"samples\":" << samples
         << ",\"status\":\"" << (complete ? "complete" : "failed") << '"'
         << ",\"reason\":\"" << reason << "\"}\n";
    write_all(line.str());
    if (::fsync(fd_) != 0) {
      throw std::runtime_error("journal fsync failed");
    }
    if (::close(fd_) != 0) {
      fd_ = -1;
      throw std::runtime_error("journal close failed");
    }
    fd_ = -1;
  }

private:
  void write_all(const std::string & text) {
    const char * cursor = text.data();
    std::size_t remaining = text.size();
    while (remaining != 0) {
      const auto written = ::write(fd_, cursor, remaining);
      if (written < 0 && errno == EINTR) {
        continue;
      }
      if (written <= 0) {
        throw std::runtime_error("journal write failed");
      }
      cursor += written;
      remaining -= static_cast<std::size_t>(written);
    }
  }

  int fd_{-1};
  std::string run_id_;
  bool terminal_attempted_{false};
};

class OdometrySource final : public rclcpp::Node {
public:
  explicit OdometrySource(ExclusiveJournal & journal, std::uint32_t max_samples)
  : Node("flydrones_px4_odometry_source"), journal_(journal), max_samples_(max_samples) {
    subscription_ = create_subscription<px4_msgs::msg::VehicleOdometry>(
      kTopic, rclcpp::SensorDataQoS().keep_last(10),
      [this](std::shared_ptr<rclcpp::SerializedMessage> serialized,
             const rclcpp::MessageInfo & info) { callback(*serialized, info); });
  }

  std::uint64_t samples() const {return samples_;}
  const std::string & failure() const {return failure_;}
  std::int64_t last_callback_ns() const {return last_callback_ns_;}

private:
  void callback(const rclcpp::SerializedMessage & serialized,
                const rclcpp::MessageInfo & info) {
    if (!failure_.empty() || samples_ >= max_samples_) {return;}
    const auto callback_ns = steady_ns();
    const auto & raw = serialized.get_rcl_serialized_message();
    if (raw.buffer_length > kMaxCdr) {
      try {journal_.fault(serialized, "cdr_oversize");} catch (const std::exception &) {}
      failure_ = "cdr_oversize";
      return;
    }
    px4_msgs::msg::VehicleOdometry decoded;
    try {
      rclcpp::Serialization<px4_msgs::msg::VehicleOdometry> codec;
      codec.deserialize_message(&serialized, &decoded);
    } catch (const std::exception &) {
      try {journal_.fault(serialized, "decode_error");} catch (const std::exception &) {}
      failure_ = "decode_error";
      return;
    }
    try {
      const auto & rmw = info.get_rmw_message_info();
      const auto gid = hex(rmw.publisher_gid.data, sizeof(rmw.publisher_gid.data));
      const auto * implementation = rmw.publisher_gid.implementation_identifier;
      const bool valid_implementation = implementation != nullptr &&
        std::regex_match(implementation, std::regex("[A-Za-z0-9_]{1,64}"));
      const bool invalid_current = !valid_implementation || gid == std::string(48, '0') ||
        decoded.pose_frame != 1 || decoded.velocity_frame != 1 || decoded.quality != 0 ||
        decoded.timestamp_sample == 0 || decoded.timestamp_sample > decoded.timestamp ||
        rmw.source_timestamp < 0 || rmw.received_timestamp < 0;
      const bool invalid_continuity = samples_ > 0 && (
        gid != first_gid_ || decoded.reset_counter != last_reset_ ||
        decoded.timestamp_sample <= last_sample_us_ ||
        decoded.timestamp <= last_publication_us_ ||
        decoded.timestamp_sample - last_sample_us_ > 100000 ||
        callback_ns <= last_callback_ns_ ||
        (rmw.source_timestamp > 0 && last_rmw_source_ns_ > 0 &&
         rmw.source_timestamp <= last_rmw_source_ns_) ||
        (rmw.received_timestamp > 0 && last_rmw_received_ns_ > 0 &&
         rmw.received_timestamp <= last_rmw_received_ns_) ||
        sequence_regressed(rmw.publication_sequence_number, last_rmw_publication_sequence_) ||
        sequence_regressed(rmw.reception_sequence_number, last_rmw_reception_sequence_));
      if (invalid_current || invalid_continuity) {
        journal_.fault(serialized, "source_invariant");
        failure_ = "source_invariant";
        return;
      }
      journal_.sample(decoded, serialized, info, samples_ + 1, callback_ns);
      ++samples_;
      if (samples_ == 1) {
        first_gid_ = gid;
        last_reset_ = decoded.reset_counter;
      }
      last_sample_us_ = decoded.timestamp_sample;
      last_publication_us_ = decoded.timestamp;
      last_callback_ns_ = callback_ns;
      last_rmw_source_ns_ = rmw.source_timestamp;
      last_rmw_received_ns_ = rmw.received_timestamp;
      last_rmw_publication_sequence_ = rmw.publication_sequence_number;
      last_rmw_reception_sequence_ = rmw.reception_sequence_number;
    } catch (const std::exception &) {
      failure_ = "journal_error";
    }
  }

  static bool sequence_regressed(std::uint64_t current, std::uint64_t previous) {
    const auto unsupported = RMW_MESSAGE_INFO_SEQUENCE_NUMBER_UNSUPPORTED;
    return (current == unsupported) != (previous == unsupported)
           || (current != unsupported && current <= previous);
  }

  ExclusiveJournal & journal_;
  std::uint32_t max_samples_;
  rclcpp::Subscription<px4_msgs::msg::VehicleOdometry>::SharedPtr subscription_;
  std::uint64_t samples_{0};
  std::uint64_t last_sample_us_{0};
  std::uint64_t last_publication_us_{0};
  std::int64_t last_callback_ns_{0};
  std::int64_t last_rmw_source_ns_{0};
  std::int64_t last_rmw_received_ns_{0};
  std::uint64_t last_rmw_publication_sequence_{RMW_MESSAGE_INFO_SEQUENCE_NUMBER_UNSUPPORTED};
  std::uint64_t last_rmw_reception_sequence_{RMW_MESSAGE_INFO_SEQUENCE_NUMBER_UNSUPPORTED};
  std::uint8_t last_reset_{0};
  std::string first_gid_;
  std::string failure_;
};

std::uint32_t bounded_argument(const char * text, std::uint32_t maximum) {
  const std::string raw(text);
  if (raw.empty() || raw.find_first_not_of("0123456789") != std::string::npos) {
    throw std::invalid_argument("numeric limit invalid");
  }
  const auto value = std::stoull(raw);
  if (value == 0 || value > maximum) {
    throw std::invalid_argument("numeric limit out of range");
  }
  return static_cast<std::uint32_t>(value);
}
}  // namespace

int main(int argc, char ** argv) {
  if (argc != 5) {
    std::cerr << "usage: px4_odometry_source OUTPUT.jsonl RUN_ID MAX_SECONDS MAX_SAMPLES\n";
    return 2;
  }
  try {
    const auto seconds = bounded_argument(argv[3], 120);
    const auto max_samples = bounded_argument(argv[4], 8192);
    ExclusiveJournal journal(argv[1], argv[2]);
    std::shared_ptr<OdometrySource> node;
    try {
      verify_installed_type();
      rclcpp::init(argc, argv);
      node = std::make_shared<OdometrySource>(journal, max_samples);
      rclcpp::executors::SingleThreadedExecutor executor;
      executor.add_node(node);
      const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
      while (rclcpp::ok() && std::chrono::steady_clock::now() < deadline
             && node->samples() < max_samples && node->failure().empty()) {
        executor.spin_some(std::chrono::milliseconds(10));
        if (node->last_callback_ns() > 0 &&
            steady_ns() - node->last_callback_ns() > 2'000'000'000LL) {
          journal.finish(node->samples(), false, "source_silence");
          rclcpp::shutdown();
          return 1;
        }
      }
      const std::string reason = node->failure().empty() ?
        (node->samples() == 0 ? "no_messages" : (rclcpp::ok() ? "" : "interrupted")) :
        node->failure();
      journal.finish(node->samples(), reason.empty(), reason);
      rclcpp::shutdown();
      return reason.empty() ? 0 : 1;
    } catch (const std::exception &) {
      if (journal.can_finish()) {
        try {journal.finish(node == nullptr ? 0 : node->samples(), false,
                            "startup_or_runtime_error");}
        catch (const std::exception &) {}
      }
      throw;
    }
  } catch (const std::exception & error) {
    std::cerr << "PX4 source journal failed: " << error.what() << '\n';
    if (rclcpp::ok()) {rclcpp::shutdown();}
    return 2;
  }
}
