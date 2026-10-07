// GPL-linked research adapter. Single native owner; pixels/IMU only, no truth or network.
#include <chrono>
#include <cmath>
#include <cstdio>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>
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
#include "openvins_fast_probe.h"

long long clock_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

class OnlineManager : public ov_msckf::VioManager {
public:
  using ov_msckf::VioManager::VioManager;
  bool ready() const { return is_initialized_vio; }
  void apply_motion_intent(long long effective_sim_ns, long long command_sequence,
                           const std::string &intent_sha256, const std::string &session_sha256,
                           const std::string &clock_sha256) {
    if (!ready()) throw std::runtime_error("motion intent before internal initialization");
    if (!params.try_zupt || !params.zupt_only_at_beginning)
      throw std::runtime_error("motion intent requires frozen beginning-only ZUPT configuration");
    if (motion_intent_applied || has_moved_since_zupt)
      throw std::runtime_error("duplicate native motion intent");
    if (command_sequence != 0) throw std::runtime_error("invalid native motion intent sequence");
    const auto state_ns = static_cast<long long>(std::llround(state->_timestamp * 1e9));
    if (effective_sim_ns < state_ns) throw std::runtime_error("motion intent precedes initialized state");
    has_moved_since_zupt = true;
    did_zupt_update = false;
    motion_intent_applied = true;
    motion_intent_effective_ns = effective_sim_ns;
    motion_intent_sequence = command_sequence;
    motion_intent_sha256 = intent_sha256;
    motion_session_sha256 = session_sha256;
    motion_clock_sha256 = clock_sha256;
  }
  void motion_fields(std::ostream &out) const {
    out << std::boolalpha << ",\"intent_sha256\":\"" << motion_intent_sha256
        << "\",\"estimator_session_sha256\":\"" << motion_session_sha256
        << "\",\"clock_id_sha256\":\"" << motion_clock_sha256
        << "\",\"command_sequence\":" << motion_intent_sequence
        << ",\"internal_initialized\":" << ready()
        << ",\"has_moved_since_zupt\":" << has_moved_since_zupt
        << ",\"motion_intent_applied\":" << motion_intent_applied
        << ",\"try_zupt\":" << params.try_zupt
        << ",\"zupt_only_at_beginning\":" << params.zupt_only_at_beginning;
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
  bool motion_intent_applied = false;
  long long motion_intent_effective_ns = -1;
  long long motion_intent_sequence = -1;
  std::string motion_intent_sha256, motion_session_sha256, motion_clock_sha256;
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
  if (argc!=5) return 2;
  try {
    const bool parse_only = std::string(argv[1])=="--parse-only";
    flydrones_probe::validate_output_pair(argv[2], argv[3]);
    flydrones_probe::ExclusiveOutput state_file(argv[2]), fast_file(argv[3]);
    auto &states=state_file.stream(), &fast=fast_file.stream();
    int ack_fd=std::stoi(argv[4]);
    if (ack_fd<3) throw std::runtime_error("invalid ack descriptor");
    std::unique_ptr<OnlineManager> manager;
    if (!parse_only) {
      ov_core::Printer::setPrintLevel("DEBUG");
      auto parser=std::make_shared<ov_core::YamlParser>(argv[1]);
      ov_msckf::VioManagerOptions options;
      options.print_and_load(parser);
      options.num_opencv_threads=1;
      options.use_multi_threading_pubs=false;
      options.use_multi_threading_subs=false;
      if (!parser->successful()) throw std::runtime_error("invalid native config");
      manager=std::make_unique<OnlineManager>(options);
    }
    long long sequence=0, first_imu=-1, last_imu=-1, last_camera=-1, next_target=-1, last_dispatch=0;
    std::string header;
    while (read_header(header)) {
      std::istringstream row(header);
      char kind; long long seq, sample, arrival, dispatch;
      if (!(row>>kind>>seq>>sample>>arrival>>dispatch) || (kind!='I' && kind!='C' && kind!='M') || seq!=sequence ||
          sample<=0 || arrival<=0 || dispatch<arrival || dispatch<last_dispatch)
        throw std::runtime_error("invalid packet identity/clock");
      const long long receive=clock_ns();
      if (dispatch>receive) throw std::runtime_error("native receive precedes dispatch");
      std::string extra;
      std::string intent_sha256, session_sha256, clock_sha256;
      long long command_sequence=-1;
      double values[6]{};
      cv::Mat gray;
      if(kind=='I') {
        for (double &v:values) if (!(row>>v) || !std::isfinite(v)) throw std::runtime_error("invalid IMU vector");
        if(row>>extra) throw std::runtime_error("extra IMU fields");
        if (sample<=last_imu || (last_imu>=0 && sample-last_imu>4000000)) throw std::runtime_error("IMU regression/gap");
      } else if(kind=='C') {
        long long count;
        if (!(row>>count) || count!=57600 || row>>extra) throw std::runtime_error("invalid RGB size/fields");
        if (sample<=last_camera || first_imu<0 || sample<first_imu || sample>=last_imu || last_imu-sample>200000000)
          throw std::runtime_error("camera missing causal IMU boundary");
        std::vector<unsigned char> pixels(57600);
        std::cin.read(reinterpret_cast<char*>(pixels.data()), pixels.size());
        if (std::cin.gcount()!=57600) throw std::runtime_error("truncated RGB payload");
        cv::Mat rgb(120,160,CV_8UC3,pixels.data());
        cv::cvtColor(rgb, gray, cv::COLOR_RGB2GRAY); // owns output; pixels may go out of scope.
      } else {
        if (!(row>>command_sequence>>intent_sha256>>session_sha256>>clock_sha256) || row>>extra ||
            command_sequence!=0 || !is_sha256(intent_sha256) || !is_sha256(session_sha256) || !is_sha256(clock_sha256))
          throw std::runtime_error("invalid motion intent fields");
      }
      const long long start=clock_ns();
      if (kind=='I') {
        if (first_imu<0) {first_imu=sample; next_target=sample;}
        last_imu=sample;
        if(manager) {
          ov_core::ImuData data;
          data.timestamp=sample*1e-9;
          data.wm<<values[0],values[1],values[2];
          data.am<<values[3],values[4],values[5];
          manager->feed_measurement_imu(data);
          while (next_target<last_imu) {
            std::ostringstream prediction;
            const auto begin=clock_ns();
            write_fast_prediction(*manager, manager->ready(), prediction, next_target, last_camera, last_imu);
            auto encoded=prediction.str();
            encoded.resize(encoded.size()-2); // replace final } and newline, append real call clocks.
            fast << encoded << ",\"trigger_sequence\":" << sequence << ",\"native_begin_ns\":" << begin
                 << ",\"native_end_ns\":" << clock_ns() << ",\"fusion_eligible\":false,\"quality\":null,\"reset_counter\":null}\n";
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
        }
      } else {
        if (!manager) throw std::runtime_error("motion intent requires estimator");
        manager->apply_motion_intent(sample, command_sequence, intent_sha256, session_sha256, clock_sha256);
      }
      const auto end=clock_ns();
      std::ostringstream ack;
      ack << "{\"sequence\":" << sequence << ",\"kind\":\"" << kind << "\",\"sample_ns\":" << sample
          << ",\"receive_ns\":" << receive << ",\"start_ns\":" << start << ",\"end_ns\":" << end
          ;
      if (kind!='M') ack << ",\"gray_first\":" << (kind=='C' ? int(gray.at<unsigned char>(0,0)) : -1);
      if (manager && kind=='C') manager->fields(ack);
      if (manager && kind=='M') manager->motion_fields(ack);
      ack << ",\"fusion_eligible\":false,\"quality\":null,\"reset_counter\":null}";
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
