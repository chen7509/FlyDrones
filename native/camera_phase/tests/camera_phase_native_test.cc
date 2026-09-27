#include "flydrones/camera_phase_native.hpp"

#include <atomic>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace camera = flydrones::camera_phase;

namespace {

void Require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

std::string ReadFile(const std::string& path) {
  std::ifstream input(path);
  Require(static_cast<bool>(input), "shared vector fixture cannot be opened");
  std::ostringstream contents;
  contents << input.rdbuf();
  return contents.str();
}

std::int64_t JsonInteger(const std::string& object, const std::string& key) {
  const std::regex expression("\\\"" + key + "\\\"\\s*:\\s*(-?[0-9]+)");
  std::smatch match;
  Require(std::regex_search(object, match, expression), "missing integer: " + key);
  return std::stoll(match[1].str());
}

std::vector<std::int64_t> JsonArray(const std::string& object,
                                    const std::string& key) {
  const auto keyPosition = object.find("\"" + key + "\"");
  const auto arrayStart = object.find('[', keyPosition);
  const auto arrayEnd = object.find(']', arrayStart);
  Require(keyPosition != std::string::npos && arrayStart != std::string::npos &&
              arrayEnd != std::string::npos,
          "missing array: " + key);
  std::vector<std::int64_t> values;
  const std::regex number("-?[0-9]+");
  const auto body = object.substr(arrayStart + 1, arrayEnd - arrayStart - 1);
  for (std::sregex_iterator iterator(body.begin(), body.end(), number), end;
       iterator != end; ++iterator) {
    values.push_back(std::stoll((*iterator)[0].str()));
  }
  return values;
}

void TestSharedScheduleVectors() {
  const auto fixture = ReadFile(CAMERA_PHASE_VECTOR_PATH);
  Require(fixture.find("flydrones-camera-phase-vectors-v1") != std::string::npos,
          "fixture schema mismatch");
  const auto epoch = JsonInteger(fixture, "epoch_ns");
  const auto count = static_cast<int>(JsonInteger(fixture, "vehicle_count"));
  const auto delay = JsonInteger(fixture, "dispatch_delay_ns");
  camera::TriggerScheduler scheduler(count, epoch, delay);
  std::size_t vectorCount = 0;
  std::size_t cursor = fixture.find("\"vectors\"");
  while ((cursor = fixture.find("\"name\"", cursor)) != std::string::npos) {
    const auto objectStart = fixture.rfind('{', cursor);
    const auto objectEnd = fixture.find('}', cursor);
    Require(objectStart != std::string::npos && objectEnd != std::string::npos,
            "malformed shared vector object");
    const auto object = fixture.substr(objectStart, objectEnd - objectStart + 1);
    const auto simNs = JsonInteger(object, "sim_ns");
    const auto expectedVehicles = JsonArray(object, "expected_vehicle_ids");
    const auto expectedPlanned = JsonArray(object, "expected_planned_ns");
    const auto expectedMissed = JsonArray(object, "expected_missed_vehicle_ids");
    const auto actual = scheduler.Advance(simNs);
    Require(actual.size() == expectedVehicles.size(), "scheduled vector size mismatch");
    Require(actual.size() == expectedPlanned.size(), "planned vector size mismatch");
    for (std::size_t index = 0; index < actual.size(); ++index) {
      Require(actual[index].vehicleId == expectedVehicles[index],
              "scheduled vehicle mismatch");
      Require(actual[index].plannedSimNs == expectedPlanned[index],
              "planned timestamp mismatch");
    }
    Require(scheduler.MissedSlots().size() == expectedMissed.size(),
            "missed vector size mismatch");
    for (std::size_t index = 0; index < expectedMissed.size(); ++index) {
      Require(scheduler.MissedSlots()[index].vehicleId == expectedMissed[index],
              "missed vehicle ordering mismatch");
    }
    ++vectorCount;
    cursor = objectEnd + 1;
  }
  Require(vectorCount == 5, "all shared vectors must be consumed");
}

void TestQueueBoundsAndHighWatermark() {
  camera::BoundedEventQueue queue(2);
  camera::EventRecord first;
  first.sequence = 1;
  camera::EventRecord second;
  second.sequence = 2;
  camera::EventRecord overflow;
  overflow.sequence = 3;
  Require(queue.TryPush(std::move(first)), "first queue push failed");
  Require(queue.TryPush(std::move(second)), "second queue push failed");
  Require(queue.HighWatermark() == 2, "queue high watermark mismatch");
  Require(!queue.TryPush(std::move(overflow)), "overflow must be rejected");
  Require(queue.DroppedCount() == 1, "overflow count mismatch");
  camera::EventRecord popped;
  Require(queue.WaitPop(popped, std::chrono::milliseconds(0)), "queue pop failed");
  Require(popped.sequence == 1, "queue ordering changed");
  queue.Close();
}

void TestSourceTimestampValidation() {
  Require(!camera::ValidSourceTimestamp(false, true, 1),
          "missing image header must be rejected");
  Require(!camera::ValidSourceTimestamp(true, false, 1),
          "missing image stamp must be rejected");
  Require(!camera::ValidSourceTimestamp(true, true, -1),
          "negative image simulation time must be rejected");
  Require(camera::ValidSourceTimestamp(true, true, 0),
          "zero image simulation time must be accepted");
  Require(camera::ValidSourceTimestamp(true, true, 1),
          "positive image simulation time must be accepted");
}

void TestLifecycleAndUniqueStopRecord() {
  camera::Lifecycle normal;
  Require(normal.MarkReady(), "ready transition failed");
  Require(normal.MarkRunning(), "running transition failed");
  Require(normal.BeginDrain(), "draining transition failed");
  Require(normal.MarkStopped(), "stopped transition failed");
  Require(normal.State() == camera::LifecycleState::kStopped,
          "normal lifecycle did not stop");
  Require(normal.ClaimStopRecord(), "first stop claim failed");
  Require(!normal.ClaimStopRecord(), "stop record must be unique");

  camera::Lifecycle completionBeforeReadiness;
  Require(completionBeforeReadiness.Fail("completion_before_readiness"),
          "early completion failure not accepted");
  Require(!completionBeforeReadiness.MarkReady(),
          "failed lifecycle must never become ready");
  Require(completionBeforeReadiness.State() == camera::LifecycleState::kFailed,
          "early completion must remain failed");

  camera::Lifecycle signalEquivalent;
  Require(signalEquivalent.MarkReady(), "signal ready transition failed");
  Require(signalEquivalent.MarkRunning(), "signal running transition failed");
  Require(signalEquivalent.BeginDrain(), "SIGTERM-equivalent drain failed");
  Require(signalEquivalent.MarkStopped(), "SIGTERM-equivalent stop failed");
  Require(signalEquivalent.State() == camera::LifecycleState::kStopped,
          "SIGTERM-equivalent shutdown did not stop");
}

void TestCompletionBeforeReadinessRunProbe() {
  const auto directory = std::filesystem::temp_directory_path() /
                         "flydrones-camera-phase-completion-before-ready";
  std::filesystem::remove_all(directory);
  std::filesystem::create_directories(directory);
  const auto completion = directory / "complete.json";
  {
    std::ofstream marker(completion);
    marker << "{}\n";
  }
  camera::ProbeOptions options;
  options.mode = "observe";
  options.vehicleCount = 1;
  options.subscriberCount = 0;
  options.output = directory / "events.jsonl";
  options.readyMarker = directory / "ready.json";
  options.completionMarker = completion;
  options.durationS = 1.0;
  options.pollIntervalMs = 1;
  options.flushIntervalMs = 10;
  options.completionDrainMs = 1;
  std::atomic_bool stopRequested{false};
  Require(camera::RunProbe(options, stopRequested) == 3,
          "completion before readiness must exit 3");
  const auto events = ReadFile(options.output.string());
  Require(events.find("\"reason\":\"completion_before_readiness\"") !=
              std::string::npos,
          "completion failure reason missing");
  const std::string stopToken = "\"event\":\"stop\"";
  const auto firstStop = events.find(stopToken);
  Require(firstStop != std::string::npos, "stop record missing");
  Require(events.find(stopToken, firstStop + stopToken.size()) == std::string::npos,
          "stop record must be unique in RunProbe");
  Require(events.find("\"source_sha256\":\"") != std::string::npos,
          "source hash missing from stop record");
  Require(events.find("\"executable_sha256\":\"") != std::string::npos,
          "executable hash missing from stop record");
  std::filesystem::remove_all(directory);
}

}  // namespace

int main() {
  try {
    TestSharedScheduleVectors();
    TestQueueBoundsAndHighWatermark();
    TestSourceTimestampValidation();
    TestLifecycleAndUniqueStopRecord();
    TestCompletionBeforeReadinessRunProbe();
  } catch (const std::exception& error) {
    std::cerr << "camera_phase_native_test: " << error.what() << '\n';
    return EXIT_FAILURE;
  }
  std::cout << "camera_phase_native_test: all checks passed\n";
  return EXIT_SUCCESS;
}
