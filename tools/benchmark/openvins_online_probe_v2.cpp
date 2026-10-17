// GPL-linked research adapter. Single native owner; pixels/IMU only, no truth or network.
#include <chrono>
#include <cmath>
#include <cstdio>
#include <iostream>
#include <memory>
#include <limits>
#include <sstream>
#include <string>
#include <vector>
#include <utility>
#include <unistd.h>
#include <opencv2/imgproc.hpp>
#include "core/VioManager.h"
#include "core/VioManagerOptions.h"
#include "state/State.h"
#include "state/StateHelper.h"
#include "utils/opencv_yaml_parse.h"
#include "utils/print.h"
#include "utils/sensor_data.h"
#include "exclusive_probe_output.h"
#include "openvins_fast_probe_v2.h"

long long clock_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

long long align_fast_target_ns(long long sample) {
  constexpr long long fast_period_ns = 20000000;
  return ((sample + fast_period_ns - 1) / fast_period_ns) * fast_period_ns;
}

class OnlineManagerV2 : public ov_msckf::VioManager {
public:
  using ov_msckf::VioManager::VioManager;
  bool ready() const { return is_initialized_vio; }
  void bind_lifecycle(const std::string &session, long long offset_ns) {
    if (lifecycle_bound) throw std::runtime_error("native lifecycle already bound");
    native_session = session; fixed_offset_ns = offset_ns;
    owned_state = state; owned_imu = state->_imu; owned_propagator = propagator;
    lifecycle_bound = true;
    observe_lifecycle();
  }
  void observe_lifecycle() {
    if (!lifecycle_bound) throw std::runtime_error("native lifecycle unbound");
    const double offset = state->_calib_dt_CAMtoIMU->value()(0);
    const bool changed = state != owned_state || state->_imu != owned_imu || propagator != owned_propagator ||
        !std::isfinite(offset) || !std::isfinite(startup_time) || !std::isfinite(state->_timestamp) ||
        std::abs(offset * 1e9 - fixed_offset_ns) > 1e-3 ||
        (ever_initialized && (!ready() || startup_time != initialized_at || state->_timestamp < last_state_time));
    if (changed) {
      ++reset_total;
      std::cerr << "{\"event\":\"native_lifecycle_failure\"";
      lifecycle_fields(std::cerr);
      std::cerr << "}\n" << std::flush;
      throw std::runtime_error("native lifecycle reset/discontinuity; new admitted session required");
    }
    if (ready()) {
      if (!ever_initialized) { ever_initialized = true; initialized_at = startup_time; }
      last_state_time = state->_timestamp;
    }
  }
  void lifecycle_fields(std::ostream &out) const {
    out << std::boolalpha << ",\"native_profile\":\"offset-reset-v2\",\"native_pid\":" << ::getpid()
        << ",\"native_session\":\"" << native_session << "\",\"camera_imu_offset_ns\":" << fixed_offset_ns
        << ",\"reset_total\":" << reset_total << ",\"reset_counter\":" << reset_total % 256
        << ",\"native_lifecycle_known\":true";
  }

  void fields(std::ostream &out) {
    out << std::setprecision(17) << std::boolalpha
        << ",\"internal_initialized\":" << ready() << ",\"public_initialized\":" << initialized()
        << ",\"initializer_time_s\":" << startup_time << ",\"state_time_s\":" << state->_timestamp
        << ",\"last_regular_update_s\":" << timelastupdate << ",\"zupt_flag_latched\":" << did_zupt_update
        << ",\"has_moved_since_zupt\":" << has_moved_since_zupt;
    if (ready()) {
      auto v = state->_imu->value();
      auto cov = ov_msckf::StateHelper::get_marginal_covariance(state, {state->_imu});
      if (cov.rows()!=15 || cov.cols()!=15 || !cov.allFinite())
        throw std::runtime_error("invalid native IMU covariance");
      out << ",\"imu_state\":[";
      for (int i=0; i<v.size(); ++i) { if(i) out << ','; out << v(i); }
      out << "],\"imu_covariance15\":[";
      for (int row=0; row<15; ++row) {
        if(row) out << ',';
        out << '[';
        for (int col=0; col<15; ++col) { if(col) out << ','; out << cov(row,col); }
        out << ']';
      }
      out << ']';
    } else out << ",\"imu_state\":null,\"imu_covariance15\":null";
  }

private:
  bool lifecycle_bound = false, ever_initialized = false;
  long long fixed_offset_ns = 0;
  unsigned long long reset_total = 0;
  double initialized_at = -1, last_state_time = -1;
  std::string native_session;
  std::shared_ptr<ov_msckf::State> owned_state;
  decltype(std::declval<ov_msckf::State>()._imu) owned_imu;
  std::shared_ptr<ov_msckf::Propagator> owned_propagator;

};

bool is_sha256(const std::string &value) {
  if (value.size() != 64) return false;
  for (char character : value)
    if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'))) return false;
  return true;
}

bool read_header(std::string &header) {
  header.clear();
  char ch;
  while (std::cin.get(ch)) {
    if (ch=='\n') return true;
    if (header.size()>=511 || ch<' ' || ch>'~') throw std::runtime_error("invalid/oversized header");
    header.push_back(ch);
  }
  if (!header.empty()) throw std::runtime_error("truncated header");
  return false;
}

int main(int argc, char **argv) {
  if (argc!=7) return 2;
  try {
    const std::string native_session(argv[4]);
    if (!is_sha256(native_session)) throw std::runtime_error("invalid native session nonce");
    size_t offset_used = 0;
    const long long offset_ns = std::stoll(argv[5], &offset_used);
    if (offset_used != std::string(argv[5]).size() || offset_ns < -1000000000 || offset_ns > 1000000000)
      throw std::runtime_error("invalid fixed native time offset");
    const bool parse_only = false; // v2 has no metadata/parse-only native bypass.
    flydrones_probe::validate_output_pair(argv[2], argv[3]);
    flydrones_probe::ExclusiveOutput state_file(argv[2]), fast_file(argv[3]);
    auto &states=state_file.stream(), &fast=fast_file.stream();
    int ack_fd=std::stoi(argv[6]);
    if (ack_fd<3) throw std::runtime_error("invalid ack descriptor");
    std::unique_ptr<OnlineManagerV2> manager;
    if (!parse_only) {
      ov_core::Printer::setPrintLevel("DEBUG");
      auto parser=std::make_shared<ov_core::YamlParser>(argv[1]);
      ov_msckf::VioManagerOptions options;
      options.print_and_load(parser);
      options.num_opencv_threads=1;
      options.use_multi_threading_pubs=false;
      options.use_multi_threading_subs=false;
      if (!parser->successful()) throw std::runtime_error("invalid native config");
      if (options.state_options.do_calib_camera_timeoffset || options.state_options.do_calib_camera_pose ||
          options.state_options.do_calib_camera_intrinsics || options.init_options.init_dyn_mle_opt_calib ||
          options.state_options.do_calib_imu_intrinsics || options.state_options.do_calib_imu_g_sensitivity)
        throw std::runtime_error("v2 requires fixed camera/IMU calibration");
      manager=std::make_unique<OnlineManagerV2>(options);
      manager->bind_lifecycle(native_session, offset_ns);
    }
    long long sequence=0, first_imu=-1, last_imu=-1, last_camera=-1, next_target=-1, last_dispatch=0;
    std::string header;
    while (read_header(header)) {
      std::istringstream row(header);
      char kind; long long seq, sample, arrival, dispatch;
      if (!(row>>kind>>seq>>sample>>arrival>>dispatch) || (kind!='I' && kind!='C') || seq!=sequence ||
          sample<=0 || sample>std::numeric_limits<long long>::max()-2000000000LL ||
          arrival<=0 || dispatch<arrival || dispatch<last_dispatch)
        throw std::runtime_error("invalid packet identity/clock");
      const long long receive=clock_ns();
      if (dispatch>receive) throw std::runtime_error("native receive precedes dispatch");
      std::string extra;
      double values[6]{};
      cv::Mat gray;
      if(kind=='I') {
        for (double &v:values) if (!(row>>v) || !std::isfinite(v)) throw std::runtime_error("invalid IMU vector");
        if(row>>extra) throw std::runtime_error("extra IMU fields");
        if (sample<=last_imu || (last_imu>=0 && sample-last_imu>4000000)) throw std::runtime_error("IMU regression/gap");
      } else if(kind=='C') {
        long long count;
        if (!(row>>count) || count!=57600 || row>>extra) throw std::runtime_error("invalid RGB size/fields");
        if (sample<=last_camera || first_imu<0 || sample + offset_ns < first_imu || sample + offset_ns >= last_imu || last_imu - (sample + offset_ns) > 200000000)
          throw std::runtime_error("camera missing causal IMU boundary");
        std::vector<unsigned char> pixels(57600);
        std::cin.read(reinterpret_cast<char*>(pixels.data()), pixels.size());
        if (std::cin.gcount()!=57600) throw std::runtime_error("truncated RGB payload");
        cv::Mat rgb(120,160,CV_8UC3,pixels.data());
        cv::cvtColor(rgb, gray, cv::COLOR_RGB2GRAY); // owns output; pixels may go out of scope.
      }

      const long long start=clock_ns();
      if (kind=='I') {
        if (first_imu<0) {first_imu=sample; next_target=align_fast_target_ns(sample);}
        last_imu=sample;
        if(manager) {
          ov_core::ImuData data;
          data.timestamp=sample*1e-9;
          data.wm<<values[0],values[1],values[2];
          data.am<<values[3],values[4],values[5];
          manager->feed_measurement_imu(data);
          manager->observe_lifecycle();
          while (next_target<last_imu) {
            std::ostringstream prediction;
            const auto begin=clock_ns();
            write_fast_prediction_v2(*manager, manager->ready(), prediction, next_target, last_camera, last_imu, first_imu);
            manager->observe_lifecycle();
            auto encoded=prediction.str();
            encoded.resize(encoded.size()-2); // replace final } and newline, append real call clocks.
            fast << encoded << ",\"trigger_sequence\":" << sequence << ",\"native_begin_ns\":" << begin
                 << ",\"native_end_ns\":" << clock_ns() << ",\"fusion_eligible\":false,\"quality\":null";
            manager->lifecycle_fields(fast);
            fast << "}\n";
            next_target+=20000000;
          }
          fast.flush();
        }
      } else if(kind=='C') {
        last_camera=sample;
        if(manager) {
          ov_core::CameraData data;
          data.timestamp=sample*1e-9;
          data.sensor_ids.push_back(0);
          data.images.push_back(gray);
          data.masks.push_back(cv::Mat::zeros(gray.rows,gray.cols,CV_8UC1));
          manager->feed_measurement_camera(data);
          manager->observe_lifecycle();
        }
      }

      const auto end=clock_ns();
      std::ostringstream ack;
      ack << "{\"sequence\":" << sequence << ",\"kind\":\"" << kind << "\",\"sample_ns\":" << sample
          << ",\"receive_ns\":" << receive << ",\"start_ns\":" << start << ",\"end_ns\":" << end
          ;
      ack << ",\"gray_first\":" << (kind=='C' ? int(gray.at<unsigned char>(0,0)) : -1);
      if (manager && kind=='C') manager->fields(ack);
      manager->observe_lifecycle();
      ack << ",\"fusion_eligible\":false,\"quality\":null";
      manager->lifecycle_fields(ack);
      ack << '}';
      if (kind=='C') {states<<ack.str()<<'\n'; states.flush();}
      const auto response=ack.str()+"\n";
      size_t sent=0;
      while(sent<response.size()) {
        auto amount=::write(ack_fd,response.data()+sent,response.size()-sent);
        if(amount<=0) throw std::runtime_error("ack write failed");
        sent+=amount;
      }
      last_dispatch=dispatch;
      ++sequence;
    }
    return 0;
  } catch(const std::exception &e) {
    std::cerr<<"native_refusal: "<<e.what()<<'\n';
    return 2;
  }
}
