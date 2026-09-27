#include "flydrones/camera_phase_native.hpp"

#include <gz/msgs/boolean.pb.h>
#include <gz/msgs/clock.pb.h>
#include <gz/msgs/config.hh>
#include <gz/msgs/image.pb.h>
#include <gz/transport/Node.hh>
#include <gz/transport/config.hh>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <functional>
#include <iomanip>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <utility>
#include <unistd.h>

namespace flydrones::camera_phase {
namespace {

#ifndef FLYDRONES_CAMERA_PHASE_SOURCE_SHA256
#define FLYDRONES_CAMERA_PHASE_SOURCE_SHA256 "unknown"
#endif

using SteadyClock = std::chrono::steady_clock;

std::int64_t MonotonicNs() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             SteadyClock::now().time_since_epoch())
      .count();
}

std::string ExecutableSha256() {
  std::array<char, 128> buffer{};
  std::string output;
  const auto command =
      "sha256sum /proc/" + std::to_string(static_cast<long long>(getpid())) +
      "/exe";
  FILE* pipe = popen(command.c_str(), "r");
  if (pipe == nullptr) return "unavailable";
  while (fgets(buffer.data(), static_cast<int>(buffer.size()), pipe) != nullptr) {
    output.append(buffer.data());
  }
  const int status = pclose(pipe);
  const auto separator = output.find_first_of(" \t\r\n");
  const auto hash = output.substr(0, separator);
  return status == 0 && hash.size() == 64 ? hash : "unavailable";
}

std::string JsonEscape(std::string_view value) {
  std::ostringstream output;
  for (const unsigned char character : value) {
    switch (character) {
      case '\"': output << "\\\""; break;
      case '\\': output << "\\\\"; break;
      case '\b': output << "\\b"; break;
      case '\f': output << "\\f"; break;
      case '\n': output << "\\n"; break;
      case '\r': output << "\\r"; break;
      case '\t': output << "\\t"; break;
      default:
        if (character < 0x20) {
          output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                 << static_cast<int>(character) << std::dec;
        } else {
          output << character;
        }
    }
  }
  return output.str();
}

template <std::size_t Size>
void CopyText(std::array<char, Size>& destination, std::string_view source) {
  const auto count = std::min(source.size(), Size - 1);
  std::copy_n(source.data(), count, destination.data());
  destination[count] = '\0';
}

const char* EventName(EventKind kind) {
  switch (kind) {
    case EventKind::kStart: return "start";
    case EventKind::kTopology: return "topology";
    case EventKind::kReady: return "ready";
    case EventKind::kImage: return "image";
    case EventKind::kTriggerReceived: return "trigger-received";
    case EventKind::kTrigger: return "trigger";
    case EventKind::kMissed: return "missed";
    case EventKind::kQueueOverflow: return "queue-overflow";
    case EventKind::kFailure: return "failure";
    case EventKind::kStop: return "stop";
  }
  return "failure";
}

std::int64_t MessageTimeNs(const gz::msgs::Time& time) {
  return static_cast<std::int64_t>(time.sec()) * 1'000'000'000LL + time.nsec();
}

std::string EventJson(const EventRecord& event, const ProbeOptions& options,
                      std::size_t queueHighWatermark,
                      std::uint64_t droppedCount,
                      std::int64_t callbackCpuNs,
                      std::int64_t writerCpuNs) {
  std::ostringstream json;
  json << "{\"event\":\"" << EventName(event.kind) << "\""
       << ",\"implementation\":\"native-cpp\""
       << ",\"wall_monotonic_ns\":" << MonotonicNs();
  if (event.vehicleId >= 0) json << ",\"vehicle_id\":" << event.vehicleId;
  if (event.cycle >= 0) json << ",\"cycle\":" << event.cycle;
  if (event.topic[0] != '\0') {
    json << ",\"topic\":\"" << JsonEscape(event.topic.data()) << "\"";
  }
  if (event.kind == EventKind::kImage && event.sourceSimNs >= 0) {
    json << ",\"sim_ns\":" << event.sourceSimNs;
  } else if (event.sourceSimNs >= 0) {
    json << ",\"planned_sim_ns\":" << event.sourceSimNs;
  }
  if (event.receiptSimNs >= 0) {
    const char* field = event.kind == EventKind::kTrigger
                            ? "published_sim_ns"
                            : "receipt_sim_ns";
    json << ",\"" << field << "\":" << event.receiptSimNs;
  }
  if (event.receiptMonotonicNs >= 0) {
    json << ",\"receipt_monotonic_ns\":" << event.receiptMonotonicNs;
  }
  if (event.kind == EventKind::kImage ||
      event.kind == EventKind::kTriggerReceived) {
    json << ",\"sequence\":" << event.sequence;
  }
  if (event.kind == EventKind::kImage) {
    json << ",\"width\":" << event.width
         << ",\"height\":" << event.height
         << ",\"format\":\"" << JsonEscape(event.format.data()) << "\""
         << ",\"image_payload_bytes_seen\":" << event.messageBytes;
  }
  if (event.reason[0] != '\0') {
    json << ",\"reason\":\"" << JsonEscape(event.reason.data()) << "\"";
  }
  if (event.kind == EventKind::kStart) {
    json << ",\"schema\":\"flydrones-camera-phase-probe-v1\""
         << ",\"mode\":\"" << JsonEscape(options.mode) << "\""
         << ",\"vehicle_count\":" << options.vehicleCount
         << ",\"subscriber_count\":" << options.subscriberCount
         << ",\"queue_capacity\":" << options.queueCapacity;
  }
  if (event.kind == EventKind::kTopology) {
    json << ",\"accepted\":true,\"depth_topics\":[";
    for (int vehicle = 0; vehicle < options.vehicleCount; ++vehicle) {
      if (vehicle) json << ',';
      json << '\"' << JsonEscape(DepthTopic(options.world, vehicle)) << '\"';
    }
    json << "]";
  }
  if (event.kind == EventKind::kReady) {
    json << ",\"epoch_ns\":" << event.sourceSimNs
         << ",\"subscriber_count\":" << options.subscriberCount;
  }
  if (event.kind == EventKind::kQueueOverflow) {
    json << ",\"dropped_count\":" << droppedCount;
  }
  if (event.kind == EventKind::kStop) {
    json << ",\"subscriber_count\":" << options.subscriberCount
         << ",\"callback_cpu_ns\":" << callbackCpuNs
         << ",\"writer_cpu_ns\":" << writerCpuNs
         << ",\"queue_high_watermark\":" << queueHighWatermark
         << ",\"dropped_count\":" << droppedCount
         << ",\"compiler\":\"" << JsonEscape(__VERSION__) << "\""
         << ",\"gz_transport_version\":\"" << GZ_TRANSPORT_VERSION_FULL << "\""
         << ",\"gz_msgs_version\":\"" << GZ_MSGS_VERSION_FULL << "\""
         << ",\"source_sha256\":\""
         << FLYDRONES_CAMERA_PHASE_SOURCE_SHA256 << "\""
         << ",\"executable_sha256\":\"" << ExecutableSha256() << "\"";
  }
  json << "}";
  return json.str();
}

void WriteMarker(const std::filesystem::path& path, const std::string& body) {
  if (path.empty()) return;
  std::filesystem::create_directories(path.parent_path());
  const auto temporary = path.string() + ".tmp";
  {
    std::ofstream output(temporary, std::ios::trunc);
    if (!output) throw std::runtime_error("marker_open_failed");
    output << body << '\n';
    output.flush();
    if (!output) throw std::runtime_error("marker_write_failed");
  }
  std::filesystem::rename(temporary, path);
}

bool TopicExists(gz::transport::Node& node, const std::string& topic) {
  std::vector<std::string> topics;
  node.TopicList(topics);
  return std::find(topics.begin(), topics.end(), topic) != topics.end();
}

bool DepthTopologyExact(gz::transport::Node& node,
                        const ProbeOptions& options) {
  constexpr std::string_view suffix =
      "/link/camera_link/sensor/StereoOV7251/depth_image";
  std::vector<std::string> topics;
  node.TopicList(topics);
  std::vector<std::string> actual;
  for (const auto& topic : topics) {
    if (topic.size() >= suffix.size() &&
        topic.compare(topic.size() - suffix.size(), suffix.size(), suffix) == 0) {
      actual.push_back(topic);
    }
  }
  std::vector<std::string> expected;
  for (int vehicle = 0; vehicle < options.vehicleCount; ++vehicle) {
    expected.push_back(DepthTopic(options.world, vehicle));
  }
  std::sort(actual.begin(), actual.end());
  std::sort(expected.begin(), expected.end());
  return actual == expected;
}

}  // namespace

TriggerScheduler::TriggerScheduler(int vehicleCount, std::int64_t epochNs,
                                   std::int64_t dispatchDelayNs)
    : vehicleCount_(vehicleCount),
      epochNs_(epochNs),
      dispatchDelayNs_(dispatchDelayNs) {
  if (vehicleCount != 1 && vehicleCount != 5) {
    throw std::invalid_argument("vehicleCount must be 1 or 5");
  }
  if (epochNs < 0) throw std::invalid_argument("epochNs must be non-negative");
  if (dispatchDelayNs < 0 || dispatchDelayNs >= kPhaseStepNs) {
    throw std::invalid_argument("dispatchDelayNs out of range");
  }
}

TriggerSlot TriggerScheduler::SlotAt(std::int64_t index,
                                     std::int64_t observedSimNs) const {
  const auto cycle = index / vehicleCount_;
  const auto vehicle = static_cast<int>(index % vehicleCount_);
  const auto planned = epochNs_ + cycle * kPeriodNs + vehicle * kPhaseStepNs;
  return TriggerSlot{vehicle, cycle, planned, observedSimNs,
                     observedSimNs - planned};
}

std::vector<TriggerSlot> TriggerScheduler::Advance(std::int64_t simNs) {
  if (simNs < 0) throw std::invalid_argument("simNs must be non-negative");
  if (lastSimNs_ && simNs < *lastSimNs_) {
    throw std::invalid_argument("simulation time reversed");
  }
  missedSlots_.clear();
  if (lastSimNs_ && simNs == *lastSimNs_) return {};
  lastSimNs_ = simNs;
  std::vector<TriggerSlot> due;
  while (true) {
    auto slot = SlotAt(nextSlotIndex_, simNs);
    if (slot.plannedSimNs + dispatchDelayNs_ > simNs) break;
    due.push_back(slot);
    ++nextSlotIndex_;
  }
  if (due.empty()) return {};
  missedSlots_.assign(due.begin(), due.end() - 1);
  return {due.back()};
}

const std::vector<TriggerSlot>& TriggerScheduler::MissedSlots() const noexcept {
  return missedSlots_;
}

BoundedEventQueue::BoundedEventQueue(std::size_t capacity) : capacity_(capacity) {
  if (capacity == 0) throw std::invalid_argument("queue capacity must be positive");
}

bool BoundedEventQueue::TryPush(EventRecord event) {
  std::lock_guard lock(mutex_);
  if (closed_ || records_.size() >= capacity_) {
    ++droppedCount_;
    return false;
  }
  records_.push_back(std::move(event));
  highWatermark_ = std::max(highWatermark_, records_.size());
  condition_.notify_one();
  return true;
}

bool BoundedEventQueue::WaitPop(EventRecord& event,
                                std::chrono::milliseconds timeout) {
  std::unique_lock lock(mutex_);
  condition_.wait_for(lock, timeout, [&] { return closed_ || !records_.empty(); });
  if (records_.empty()) return false;
  event = std::move(records_.front());
  records_.pop_front();
  return true;
}

void BoundedEventQueue::Close() {
  std::lock_guard lock(mutex_);
  closed_ = true;
  condition_.notify_all();
}

bool BoundedEventQueue::Empty() const {
  std::lock_guard lock(mutex_);
  return records_.empty();
}

std::size_t BoundedEventQueue::HighWatermark() const {
  std::lock_guard lock(mutex_);
  return highWatermark_;
}

std::uint64_t BoundedEventQueue::DroppedCount() const {
  std::lock_guard lock(mutex_);
  return droppedCount_;
}

bool Lifecycle::MarkReady() {
  std::lock_guard lock(mutex_);
  if (state_ != LifecycleState::kStarting) return false;
  state_ = LifecycleState::kReady;
  return true;
}

bool Lifecycle::MarkRunning() {
  std::lock_guard lock(mutex_);
  if (state_ != LifecycleState::kReady) return false;
  state_ = LifecycleState::kRunning;
  return true;
}

bool Lifecycle::BeginDrain() {
  std::lock_guard lock(mutex_);
  if (state_ != LifecycleState::kRunning && state_ != LifecycleState::kReady) return false;
  state_ = LifecycleState::kDraining;
  return true;
}

bool Lifecycle::MarkStopped() {
  std::lock_guard lock(mutex_);
  if (state_ != LifecycleState::kDraining) return false;
  state_ = LifecycleState::kStopped;
  return true;
}

bool Lifecycle::Fail(std::string reason) {
  std::lock_guard lock(mutex_);
  if (state_ == LifecycleState::kStopped || state_ == LifecycleState::kFailed) return false;
  state_ = LifecycleState::kFailed;
  failureReason_ = std::move(reason);
  return true;
}

LifecycleState Lifecycle::State() const {
  std::lock_guard lock(mutex_);
  return state_;
}

std::string Lifecycle::FailureReason() const {
  std::lock_guard lock(mutex_);
  return failureReason_;
}

bool Lifecycle::ClaimStopRecord() {
  std::lock_guard lock(mutex_);
  if (stopRecordClaimed_) return false;
  stopRecordClaimed_ = true;
  return true;
}

std::int64_t AlignEpochNs(std::int64_t simNs) {
  if (simNs < 0) throw std::invalid_argument("simNs must be non-negative");
  return ((simNs + kPeriodNs - 1) / kPeriodNs) * kPeriodNs;
}

bool ValidSourceTimestamp(bool hasHeader, bool hasStamp,
                          std::int64_t simNs) noexcept {
  return hasHeader && hasStamp && simNs >= 0;
}

std::string DepthTopic(const std::string& world, int vehicleId) {
  return "/world/" + world + "/model/x500_depth_fly_" +
         std::to_string(vehicleId) +
         "/link/camera_link/sensor/StereoOV7251/depth_image";
}

std::string TriggerTopic(const std::string& world, int vehicleId) {
  return DepthTopic(world, vehicleId) + "/trigger";
}

std::string PhaseReadyMarkerJson(
    const ProbeOptions& options, std::int64_t epochNs,
    const std::vector<DepthObservation>& observations) {
  if (observations.size() != static_cast<std::size_t>(options.subscriberCount)) {
    throw std::invalid_argument("depth observation count mismatch");
  }
  std::ostringstream json;
  json << std::setprecision(17)
       << "{\"schema\":\"flydrones-camera-phase-ready-v1\""
       << ",\"mode\":\"phased\""
       << ",\"vehicle_count\":" << options.vehicleCount
       << ",\"epoch_ns\":" << epochNs
       << ",\"warmup_image_counts\":{";
  for (int vehicle = 0; vehicle < options.subscriberCount; ++vehicle) {
    if (vehicle) json << ',';
    json << '\"' << vehicle << "\":" << observations[vehicle].messageCount;
  }
  json << "},\"depth_topics\":[";
  for (int vehicle = 0; vehicle < options.vehicleCount; ++vehicle) {
    if (vehicle) json << ',';
    json << '\"' << JsonEscape(DepthTopic(options.world, vehicle)) << '\"';
  }
  json << "],\"depth_observations\":{";
  for (int vehicle = 0; vehicle < options.subscriberCount; ++vehicle) {
    if (vehicle) json << ',';
    const auto& observation = observations[vehicle];
    const auto frequency =
        observation.messageCount >= 2 && observation.lastSimNs > observation.firstSimNs
            ? static_cast<double>(observation.messageCount - 1) * 1'000'000'000.0 /
                  static_cast<double>(observation.lastSimNs - observation.firstSimNs)
            : 0.0;
    json << '\"' << JsonEscape(DepthTopic(options.world, vehicle)) << "\":{"
         << "\"width\":" << observation.width
         << ",\"height\":" << observation.height
         << ",\"frequency_hz\":" << frequency
         << ",\"message_count\":" << observation.messageCount << '}';
  }
  json << "}}";
  return json.str();
}

int RunProbe(const ProbeOptions& options, std::atomic_bool& stopRequested) {
  if ((options.vehicleCount != 1 && options.vehicleCount != 5) ||
      options.subscriberCount < 0 ||
      options.subscriberCount > options.vehicleCount ||
      (options.subscriberCount != 0 && options.subscriberCount != 1 &&
       options.subscriberCount != 5)) {
    return 64;
  }
  std::filesystem::create_directories(options.output.parent_path());
  std::error_code ignored;
  std::filesystem::remove(options.readyMarker, ignored);
  BoundedEventQueue queue(options.queueCapacity);
  Lifecycle lifecycle;
  std::atomic<std::int64_t> latestClockNs{-1};
  std::atomic<std::int64_t> latestClockReceiptNs{-1};
  std::atomic<std::int64_t> callbackCpuNs{0};
  std::atomic_bool integrityRejected{false};
  std::atomic<std::uint64_t> triggerCount{0};
  std::vector<std::atomic<std::uint64_t>> imageSequences(options.vehicleCount);
  std::vector<std::atomic<std::uint64_t>> triggerSequences(options.vehicleCount);
  std::vector<std::atomic<std::int64_t>> firstImageSimNs(options.vehicleCount);
  std::vector<std::atomic<std::int64_t>> lastImageSimNs(options.vehicleCount);
  std::vector<std::atomic<std::uint32_t>> imageWidths(options.vehicleCount);
  std::vector<std::atomic<std::uint32_t>> imageHeights(options.vehicleCount);
  for (int vehicle = 0; vehicle < options.vehicleCount; ++vehicle) {
    firstImageSimNs[vehicle].store(-1);
    lastImageSimNs[vehicle].store(-1);
    imageWidths[vehicle].store(0);
    imageHeights[vehicle].store(0);
  }
  std::atomic<std::int64_t> writerCpuNs{0};

  std::ofstream output(options.output, std::ios::trunc);
  if (!output) return 3;
  std::atomic_bool writerDone{false};
  std::thread writer([&] {
    const auto flushInterval = std::chrono::milliseconds(options.flushIntervalMs);
    auto lastFlush = SteadyClock::now();
    EventRecord event;
    while (!writerDone.load() || !queue.Empty()) {
      const auto begin = SteadyClock::now();
      if (queue.WaitPop(event, std::chrono::milliseconds(20))) {
        output << EventJson(event, options, queue.HighWatermark(),
                            queue.DroppedCount(), callbackCpuNs.load(),
                            writerCpuNs.load())
               << '\n';
      }
      const auto now = SteadyClock::now();
      if (now - lastFlush >= flushInterval) {
        output.flush();
        lastFlush = now;
      }
      writerCpuNs.fetch_add(
          std::chrono::duration_cast<std::chrono::nanoseconds>(SteadyClock::now() - begin)
              .count());
    }
    if (queue.DroppedCount() > 0) {
      EventRecord overflow;
      overflow.kind = EventKind::kQueueOverflow;
      output << EventJson(overflow, options, queue.HighWatermark(),
                          queue.DroppedCount(), callbackCpuNs.load(),
                          writerCpuNs.load())
             << '\n';
    }
    if (lifecycle.ClaimStopRecord()) {
      EventRecord stop;
      stop.kind = EventKind::kStop;
      CopyText(stop.reason, lifecycle.FailureReason());
      output << EventJson(stop, options, queue.HighWatermark(),
                          queue.DroppedCount(), callbackCpuNs.load(),
                          writerCpuNs.load())
             << '\n';
    }
    output.flush();
  });

  int exitCode = 3;
  try {
    EventRecord start;
    start.kind = EventKind::kStart;
    if (!queue.TryPush(std::move(start))) throw std::runtime_error("queue_overflow");

    auto clockNode = std::make_unique<gz::transport::Node>();
    auto triggerNode = std::make_unique<gz::transport::Node>();
    std::vector<std::unique_ptr<gz::transport::Node>> imageNodes;
    imageNodes.reserve(options.subscriberCount);

    const auto clockCallback = [&](const gz::msgs::Clock& message) {
      const auto begin = SteadyClock::now();
      latestClockNs.store(MessageTimeNs(message.sim()));
      latestClockReceiptNs.store(MonotonicNs());
      callbackCpuNs.fetch_add(
          std::chrono::duration_cast<std::chrono::nanoseconds>(SteadyClock::now() - begin)
              .count());
    };
    if (!clockNode->Subscribe<gz::msgs::Clock>("/clock", clockCallback)) {
      throw std::runtime_error("clock_subscription_failed");
    }

    for (int vehicle = 0; vehicle < options.subscriberCount; ++vehicle) {
      auto node = std::make_unique<gz::transport::Node>();
      const auto topic = DepthTopic(options.world, vehicle);
      const auto imageCallback = [&, vehicle, topic](const gz::msgs::Image& message) {
        const auto begin = SteadyClock::now();
        const auto sourceSimNs =
            message.has_header() && message.header().has_stamp()
                ? MessageTimeNs(message.header().stamp())
                : -1;
        if (!ValidSourceTimestamp(message.has_header(),
                                  message.has_header() &&
                                      message.header().has_stamp(),
                                  sourceSimNs)) {
          integrityRejected.store(true);
          lifecycle.Fail("malformed_image_timestamp");
          EventRecord failure;
          failure.kind = EventKind::kFailure;
          CopyText(failure.reason, "malformed_image_timestamp");
          queue.TryPush(std::move(failure));
          return;
        }
        EventRecord event;
        event.kind = EventKind::kImage;
        event.vehicleId = vehicle;
        CopyText(event.topic, topic);
        event.sourceSimNs = sourceSimNs;
        event.receiptSimNs = latestClockNs.load();
        event.receiptMonotonicNs = MonotonicNs();
        event.sequence = imageSequences[vehicle].fetch_add(1);
        event.width = message.width();
        event.height = message.height();
        CopyText(event.format,
                 gz::msgs::PixelFormatType_Name(message.pixel_format_type()));
        event.messageBytes = message.ByteSizeLong();
        if (event.sequence == 0) firstImageSimNs[vehicle].store(sourceSimNs);
        lastImageSimNs[vehicle].store(sourceSimNs);
        imageWidths[vehicle].store(message.width());
        imageHeights[vehicle].store(message.height());
        if (!queue.TryPush(std::move(event))) {
          integrityRejected.store(true);
          lifecycle.Fail("queue_overflow");
        }
        callbackCpuNs.fetch_add(
            std::chrono::duration_cast<std::chrono::nanoseconds>(SteadyClock::now() - begin)
                .count());
      };
      if (!node->Subscribe<gz::msgs::Image>(topic, imageCallback)) {
        throw std::runtime_error("image_subscription_failed");
      }
      imageNodes.push_back(std::move(node));
    }

    if (options.observeTriggers) {
      for (int vehicle = 0; vehicle < options.vehicleCount; ++vehicle) {
        const auto topic = TriggerTopic(options.world, vehicle);
        const auto triggerCallback = [&, vehicle, topic](const gz::msgs::Boolean&) {
          const auto begin = SteadyClock::now();
          EventRecord event;
          event.kind = EventKind::kTriggerReceived;
          event.vehicleId = vehicle;
          CopyText(event.topic, topic);
          event.receiptSimNs = latestClockNs.load();
          event.receiptMonotonicNs = MonotonicNs();
          event.sequence = triggerSequences[vehicle].fetch_add(1);
          if (!queue.TryPush(std::move(event))) {
            integrityRejected.store(true);
            lifecycle.Fail("queue_overflow");
          }
          callbackCpuNs.fetch_add(
              std::chrono::duration_cast<std::chrono::nanoseconds>(
                  SteadyClock::now() - begin)
                  .count());
        };
        if (!triggerNode->Subscribe<gz::msgs::Boolean>(topic, triggerCallback)) {
          throw std::runtime_error("trigger_subscription_failed");
        }
      }
    }

    std::vector<gz::transport::Node::Publisher> publishers;
    if (options.mode == "schedule-observe") {
      publishers.reserve(options.vehicleCount);
      for (int vehicle = 0; vehicle < options.vehicleCount; ++vehicle) {
        auto publisher = triggerNode->Advertise<gz::msgs::Boolean>(
            TriggerTopic(options.world, vehicle));
        if (!publisher) throw std::runtime_error("trigger_publisher_invalid");
        publishers.push_back(std::move(publisher));
      }
    }

    const auto readinessDeadline =
        SteadyClock::now() + std::chrono::duration<double>(options.readinessTimeoutS);
    while (!stopRequested.load()) {
      if (std::filesystem::exists(options.completionMarker)) {
        throw std::runtime_error("completion_before_readiness");
      }
      const bool topologyReady = TopicExists(*clockNode, "/clock") &&
                                 DepthTopologyExact(*clockNode, options);
      bool publishersReady = true;
      for (const auto& publisher : publishers) {
        publishersReady = publishersReady && publisher.HasConnections();
      }
      bool imagesReady = true;
      for (int vehicle = 0; vehicle < options.subscriberCount; ++vehicle) {
        imagesReady = imagesReady &&
                      imageSequences[vehicle].load() >= options.warmupImageCountMin;
      }
      if (topologyReady && publishersReady && imagesReady &&
          latestClockNs.load() >= 0) {
        break;
      }
      if (SteadyClock::now() >= readinessDeadline) {
        throw std::runtime_error("readiness_timeout");
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(options.pollIntervalMs));
    }
    if (stopRequested.load()) throw std::runtime_error("stopped_before_readiness");

    EventRecord topology;
    topology.kind = EventKind::kTopology;
    if (!queue.TryPush(std::move(topology))) throw std::runtime_error("queue_overflow");
    const auto epochNs = AlignEpochNs(latestClockNs.load());
    if (!lifecycle.MarkReady()) throw std::runtime_error("lifecycle_ready_failed");
    EventRecord ready;
    ready.kind = EventKind::kReady;
    ready.sourceSimNs = epochNs;
    if (!queue.TryPush(std::move(ready))) throw std::runtime_error("queue_overflow");
    std::vector<DepthObservation> observations;
    observations.reserve(options.subscriberCount);
    for (int vehicle = 0; vehicle < options.subscriberCount; ++vehicle) {
      observations.push_back(DepthObservation{
          imageWidths[vehicle].load(), imageHeights[vehicle].load(),
          imageSequences[vehicle].load(), firstImageSimNs[vehicle].load(),
          lastImageSimNs[vehicle].load()});
    }
    WriteMarker(options.readyMarker,
                PhaseReadyMarkerJson(options, epochNs, observations));
    if (!lifecycle.MarkRunning()) throw std::runtime_error("lifecycle_running_failed");

    std::optional<TriggerScheduler> scheduler;
    if (options.mode == "schedule-observe") {
      scheduler.emplace(options.vehicleCount, epochNs, kDispatchDelayNs);
    }
    const auto runDeadline = SteadyClock::now() +
                             std::chrono::duration_cast<SteadyClock::duration>(
                                 std::chrono::duration<double>(options.durationS));
    std::int64_t processedClockNs = -1;
    while (!stopRequested.load() && SteadyClock::now() < runDeadline) {
      if (std::filesystem::exists(options.completionMarker)) break;
      if (lifecycle.State() == LifecycleState::kFailed) break;
      if (!DepthTopologyExact(*clockNode, options)) {
        lifecycle.Fail("topology_changed");
      }
      for (const auto& publisher : publishers) {
        if (!publisher.HasConnections()) {
          lifecycle.Fail("trigger_connection_lost");
          exitCode = 4;
          break;
        }
      }
      if (latestClockReceiptNs.load() >= 0 &&
          MonotonicNs() - latestClockReceiptNs.load() > 5'000'000'000LL) {
        lifecycle.Fail("stale_clock");
      }
      if (lifecycle.State() == LifecycleState::kFailed) break;
      const auto simNs = latestClockNs.load();
      if (scheduler && simNs >= 0 && simNs != processedClockNs) {
        processedClockNs = simNs;
        const auto due = scheduler->Advance(simNs);
        for (const auto& slot : scheduler->MissedSlots()) {
          EventRecord missed;
          missed.kind = EventKind::kMissed;
          missed.vehicleId = slot.vehicleId;
          missed.cycle = slot.cycle;
          missed.sourceSimNs = slot.plannedSimNs;
          missed.receiptSimNs = simNs;
          if (!queue.TryPush(std::move(missed))) {
            integrityRejected.store(true);
            lifecycle.Fail("queue_overflow");
          }
        }
        for (const auto& slot : due) {
          gz::msgs::Boolean message;
          message.set_data(true);
          if (!publishers[slot.vehicleId].Publish(message)) {
            lifecycle.Fail("trigger_publish_failed");
            break;
          }
          EventRecord trigger;
          trigger.kind = EventKind::kTrigger;
          trigger.vehicleId = slot.vehicleId;
          trigger.cycle = slot.cycle;
          CopyText(trigger.topic, TriggerTopic(options.world, slot.vehicleId));
          trigger.sourceSimNs = slot.plannedSimNs;
          trigger.receiptSimNs = slot.publishedSimNs;
          trigger.receiptMonotonicNs = MonotonicNs();
          if (!queue.TryPush(std::move(trigger))) {
            integrityRejected.store(true);
            lifecycle.Fail("queue_overflow");
          }
          const auto count = triggerCount.fetch_add(1) + 1;
          if (options.stopAfterTriggerCount && count >= *options.stopAfterTriggerCount) {
            lifecycle.Fail("directed_scheduler_failure");
            exitCode = 4;
            break;
          }
        }
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(options.pollIntervalMs));
    }

    if (queue.DroppedCount() > 0 || integrityRejected.load()) {
      lifecycle.Fail("queue_overflow");
      exitCode = 2;
    } else if (lifecycle.State() == LifecycleState::kFailed) {
      if (exitCode != 4) exitCode = 3;
    } else {
      lifecycle.BeginDrain();
      std::this_thread::sleep_for(
          std::chrono::milliseconds(options.completionDrainMs));
      lifecycle.MarkStopped();
      exitCode = 0;
    }
  } catch (const std::exception& error) {
    lifecycle.Fail(error.what());
    EventRecord failure;
    failure.kind = EventKind::kFailure;
    CopyText(failure.reason, error.what());
    queue.TryPush(std::move(failure));
    exitCode = queue.DroppedCount() > 0 ? 2 : 3;
  }

  queue.Close();
  writerDone.store(true);
  writer.join();
  output.close();
  return exitCode;
}

}  // namespace flydrones::camera_phase
