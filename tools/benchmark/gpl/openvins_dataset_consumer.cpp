// SPDX-License-Identifier: GPL-3.0-or-later
// Links the pinned GPL OpenVINS library only in an isolated research process.
#include "openvins_dataset_io.h"
#include <fcntl.h>
#include <unistd.h>
#include <iomanip>
#include <iostream>
#include <memory>
#include <opencv2/imgcodecs.hpp>
#include "core/VioManager.h"
#include "core/VioManagerOptions.h"
#include "state/State.h"
#include "utils/opencv_yaml_parse.h"
#include "utils/print.h"
#include "utils/sensor_data.h"

int main(int argc,char **argv) {
  if (argc!=4) return 2;
  try {
    const std::string config=argv[1], root=argv[2], output=argv[3];
    auto frames=recorded_dataset::frames(root+"/cam0/data.csv");
    auto imu=recorded_dataset::imus(root+"/imu0/data.csv");
    if (frames.size()<20 || imu.size()<100) throw std::runtime_error("dataset too short");
    int fd=::open(output.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600);
    if (fd<0) throw std::runtime_error("exclusive output unavailable");
    ::close(fd);
    std::ofstream states(output,std::ios::out);
    states << "frame_ns,status,imu_fed_total,boundary_imu_ns,public_initialized,state_reference_s,qualification\n";
    states.flush();
    std::string imu_path=output+".imu-fed.csv";
    int imu_fd=::open(imu_path.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600);
    if (imu_fd<0) throw std::runtime_error("exclusive IMU journal unavailable");
    ::close(imu_fd);
    std::ofstream imu_journal(imu_path);
    imu_journal << "source_index,sample_ns,call_status,qualification\n";
    ov_core::Printer::setPrintLevel("DEBUG");
    auto parser=std::make_shared<ov_core::YamlParser>(config);
    ov_msckf::VioManagerOptions options;
    options.print_and_load(parser);
    options.num_opencv_threads=1;
    options.use_multi_threading_pubs=false;
    options.use_multi_threading_subs=false;
    if (!parser->successful()) throw std::runtime_error("upstream configuration rejected");
    ov_msckf::VioManager manager(options);
    size_t next=0, calls=0, initialized=0, refused=0;
    auto feed=[&](size_t index) {
      ov_core::ImuData sample;
      sample.timestamp=imu[index].ns*1e-9;
      sample.wm=Eigen::Vector3d(imu[index].value[0],imu[index].value[1],imu[index].value[2]);
      sample.am=Eigen::Vector3d(imu[index].value[3],imu[index].value[4],imu[index].value[5]);
      manager.feed_measurement_imu(sample);
      imu_journal << index << ',' << imu[index].ns << ",native_returned,unqualified\n";
    };
    for (const auto &frame:frames) {
      cv::Mat image=cv::imread(root+"/cam0/data/"+frame.name,cv::IMREAD_GRAYSCALE);
      if (image.empty() || image.cols!=160 || image.rows!=120 || image.type()!=CV_8UC1)
        throw std::runtime_error("OpenCV image decode rejected");
      // Preserve exactly the derived pixels passed to the native camera API.
      std::string gray=output+"."+std::to_string(frame.ns)+".pgm";
      int grayfd=::open(gray.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600);
      if (grayfd<0) throw std::runtime_error("exclusive gray output unavailable");
      ::close(grayfd);
      std::ofstream pgm(gray,std::ios::binary);
      pgm << "P5\n160 120\n255\n";
      for (int y=0;y<image.rows;++y) pgm.write(reinterpret_cast<const char*>(image.ptr(y)),image.cols);
      pgm.close();
      if (!pgm) throw std::runtime_error("gray derivative write failure");
      if (frame.ns<imu.front().ns || frame.ns>imu.back().ns) {
        ++refused;
        states << frame.ns << ",imu_range_refused," << next << ",,,,unqualified\n";
        states.flush();
        continue;
      }
      // Offline look-ahead, explicitly not a source arrival/causality assertion.
      while (next<imu.size() && imu[next].ns<=frame.ns) { feed(next); ++next; }
      if (next<imu.size() && (next==0 || imu[next-1].ns<=frame.ns)) { feed(next); ++next; }
      ov_core::CameraData camera;
      camera.timestamp=frame.ns*1e-9;
      camera.sensor_ids={0}; camera.images={image};
      camera.masks={cv::Mat::zeros(image.rows,image.cols,CV_8UC1)};
      manager.feed_measurement_camera(camera); ++calls;
      bool ready=manager.initialized(); initialized+=ready;
      states << frame.ns << ",native_returned," << next << ',' << imu[next-1].ns << ','
             << (ready?1:0) << ',' << std::setprecision(17) << manager.get_state()->_timestamp << ",unqualified\n";
      states.flush();
    }
    while (next<imu.size()) { feed(next); ++next; }
    states.close();
    imu_journal.close();
    if (!states) throw std::runtime_error("state journal write failure");
    if (!imu_journal) throw std::runtime_error("IMU journal write failure");
    std::cout << "DATASET_COUNTS frames=" << frames.size() << " imu_fed=" << next
              << " camera_calls=" << calls << " refused=" << refused
              << " public_initialized_frames=" << initialized << " qualifications=false\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "dataset_consumer_error=" << error.what() << '\n'; return 1;
  }
}
