#pragma once

#include <atomic>
#include <array>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace flydrones::camera_phase {

inline constexpr std::int64_t kPeriodNs = 100'000'000;
inline constexpr std::int64_t kPhaseStepNs = 20'000'000;
inline constexpr std::int64_t kDispatchDelayNs = 4'000'000;

struct TriggerSlot {
  int vehicleId{};
  std::int64_t cycle{};
  std::int64_t plannedSimNs{};
  std::int64_t publishedSimNs{};
  std::int64_t lateNs{};
};

class TriggerScheduler {
 public:
  TriggerScheduler(int vehicleCount, std::int64_t epochNs,
                   std::int64_t dispatchDelayNs = kDispatchDelayNs);
  std::vector<TriggerSlot> Advance(std::int64_t simNs);
  const std::vector<TriggerSlot>& MissedSlots() const noexcept;

 private:
  TriggerSlot SlotAt(std::int64_t index, std::int64_t observedSimNs) const;
  int vehicleCount_;
  std::int64_t epochNs_;
  std::int64_t dispatchDelayNs_;
  std::int64_t nextSlotIndex_{0};
  std::optional<std::int64_t> lastSimNs_;
  std::vector<TriggerSlot> missedSlots_;
};

enum class EventKind {
  kStart,
  kTopology,
  kReady,
  kImage,
  kTriggerReceived,
  kTrigger,
  kMissed,
  kQueueOverflow,
  kFailure,
  kStop,
};

struct EventRecord {
  EventKind kind{EventKind::kFailure};
  int vehicleId{-1};
  std::int64_t cycle{-1};
  std::array<char, 256> topic{};
  std::int64_t sourceSimNs{-1};
  std::int64_t receiptSimNs{-1};
  std::int64_t receiptMonotonicNs{-1};
  std::uint64_t sequence{};
  std::uint32_t width{};
  std::uint32_t height{};
  std::array<char, 32> format{};
  std::uint64_t messageBytes{};
  std::array<char, 128> reason{};
};

class BoundedEventQueue {
 public:
  explicit BoundedEventQueue(std::size_t capacity);
  bool TryPush(EventRecord event);
  bool WaitPop(EventRecord& event, std::chrono::milliseconds timeout);
  void Close();
  bool Empty() const;
  std::size_t HighWatermark() const;
  std::uint64_t DroppedCount() const;

 private:
  const std::size_t capacity_;
  mutable std::mutex mutex_;
  std::condition_variable condition_;
  std::deque<EventRecord> records_;
  std::size_t highWatermark_{0};
  std::uint64_t droppedCount_{0};
  bool closed_{false};
};

enum class LifecycleState {
  kStarting,
  kReady,
  kRunning,
  kDraining,
  kStopped,
  kFailed,
};

class Lifecycle {
 public:
  bool MarkReady();
  bool MarkRunning();
  bool BeginDrain();
  bool MarkStopped();
  bool Fail(std::string reason);
  LifecycleState State() const;
  std::string FailureReason() const;
  bool ClaimStopRecord();

 private:
  mutable std::mutex mutex_;
  LifecycleState state_{LifecycleState::kStarting};
  std::string failureReason_;
  bool stopRecordClaimed_{false};
};

struct ProbeOptions {
  std::string mode;
  int vehicleCount{5};
  int subscriberCount{5};
  std::filesystem::path output;
  std::filesystem::path readyMarker;
  std::filesystem::path completionMarker;
  double durationS{120.0};
  int pollIntervalMs{10};
  int flushIntervalMs{250};
  int completionDrainMs{1000};
  std::optional<std::uint64_t> stopAfterTriggerCount;
  std::string world{"flydrones_forest"};
  std::size_t queueCapacity{4096};
};

std::int64_t AlignEpochNs(std::int64_t simNs);
bool ValidSourceTimestamp(bool hasHeader, bool hasStamp,
                          std::int64_t simNs) noexcept;
std::string DepthTopic(const std::string& world, int vehicleId);
std::string TriggerTopic(const std::string& world, int vehicleId);
int RunProbe(const ProbeOptions& options, std::atomic_bool& stopRequested);

}  // namespace flydrones::camera_phase
