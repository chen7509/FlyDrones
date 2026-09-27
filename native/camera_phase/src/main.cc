#include "flydrones/camera_phase_native.hpp"

#include <atomic>
#include <csignal>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>

namespace {

enum ExitCode {
  kComplete = 0,
  kIntegrityRejected = 2,
  kRuntimeFailure = 3,
  kSchedulerFailure = 4,
  kInvalidCli = 64,
};

std::atomic_bool stopRequested{false};

void OnSignal(int) { stopRequested.store(true); }

void PrintHelp() {
  std::cout
      << "usage: flydrones_camera_phase_native MODE [OPTIONS]\n\n"
      << "modes:\n"
      << "  observe           observe clock, triggers, and selected images\n"
      << "  schedule-observe  publish phased triggers and observe metadata\n\n"
      << "options:\n"
      << "  --vehicle-count N\n"
      << "  --subscriber-count N\n"
      << "  --output PATH\n"
      << "  --ready-marker PATH\n"
      << "  --completion-marker PATH\n"
      << "  --duration-s SECONDS\n"
      << "  --poll-interval-ms N\n"
      << "  --flush-interval-ms N\n"
      << "  --completion-drain-ms N\n"
      << "  --warmup-image-count-min N\n"
      << "  --stop-after-trigger-count N\n";
}

long long ParseInteger(const std::string& value, const char* name,
                       bool allowZero = false) {
  std::size_t consumed = 0;
  long long parsed = 0;
  try {
    parsed = std::stoll(value, &consumed);
  } catch (const std::exception&) {
    throw std::invalid_argument(std::string(name) + " must be an integer");
  }
  if (consumed != value.size() || parsed < (allowZero ? 0 : 1)) {
    throw std::invalid_argument(std::string(name) + " is out of range");
  }
  return parsed;
}

double ParsePositiveDouble(const std::string& value, const char* name) {
  std::size_t consumed = 0;
  double parsed = 0.0;
  try {
    parsed = std::stod(value, &consumed);
  } catch (const std::exception&) {
    throw std::invalid_argument(std::string(name) + " must be numeric");
  }
  if (consumed != value.size() || !(parsed > 0.0) ||
      parsed == std::numeric_limits<double>::infinity()) {
    throw std::invalid_argument(std::string(name) + " is out of range");
  }
  return parsed;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc == 2 && std::string(argv[1]) == "--help") {
    PrintHelp();
    return kComplete;
  }
  if (argc < 2) {
    PrintHelp();
    return kInvalidCli;
  }
  flydrones::camera_phase::ProbeOptions options;
  options.mode = argv[1];
  if (options.mode != "observe" && options.mode != "schedule-observe") {
    std::cerr << "unknown mode: " << options.mode << '\n';
    return kInvalidCli;
  }
  try {
    for (int index = 2; index < argc; ++index) {
      const std::string option = argv[index];
      if (option == "--help") {
        PrintHelp();
        return kComplete;
      }
      if (index + 1 >= argc) {
        throw std::invalid_argument("missing value for " + option);
      }
      const std::string value = argv[++index];
      if (option == "--vehicle-count") {
        options.vehicleCount = static_cast<int>(ParseInteger(value, option.c_str()));
      } else if (option == "--subscriber-count") {
        options.subscriberCount =
            static_cast<int>(ParseInteger(value, option.c_str(), true));
      } else if (option == "--output") {
        options.output = value;
      } else if (option == "--ready-marker") {
        options.readyMarker = value;
      } else if (option == "--completion-marker") {
        options.completionMarker = value;
      } else if (option == "--duration-s") {
        options.durationS = ParsePositiveDouble(value, option.c_str());
      } else if (option == "--poll-interval-ms") {
        options.pollIntervalMs = static_cast<int>(ParseInteger(value, option.c_str()));
      } else if (option == "--flush-interval-ms") {
        options.flushIntervalMs = static_cast<int>(ParseInteger(value, option.c_str()));
      } else if (option == "--completion-drain-ms") {
        options.completionDrainMs = static_cast<int>(ParseInteger(value, option.c_str()));
      } else if (option == "--warmup-image-count-min") {
        options.warmupImageCountMin =
            static_cast<std::uint64_t>(ParseInteger(value, option.c_str()));
      } else if (option == "--stop-after-trigger-count") {
        options.stopAfterTriggerCount =
            static_cast<std::uint64_t>(ParseInteger(value, option.c_str()));
      } else {
        throw std::invalid_argument("unknown option: " + option);
      }
    }
    if (options.output.empty() || options.readyMarker.empty() ||
        options.completionMarker.empty()) {
      throw std::invalid_argument(
          "--output, --ready-marker, and --completion-marker are required");
    }
    if ((options.vehicleCount != 1 && options.vehicleCount != 5) ||
        (options.subscriberCount != 0 && options.subscriberCount != 1 &&
         options.subscriberCount != 5) ||
        options.subscriberCount > options.vehicleCount) {
      throw std::invalid_argument("invalid vehicle/subscriber count combination");
    }
  } catch (const std::invalid_argument& error) {
    std::cerr << error.what() << '\n';
    return kInvalidCli;
  }

  std::signal(SIGINT, OnSignal);
  std::signal(SIGTERM, OnSignal);
  const int result = flydrones::camera_phase::RunProbe(options, stopRequested);
  if (result == kComplete || result == kIntegrityRejected ||
      result == kRuntimeFailure || result == kSchedulerFailure) {
    return result;
  }
  return kRuntimeFailure;
}
