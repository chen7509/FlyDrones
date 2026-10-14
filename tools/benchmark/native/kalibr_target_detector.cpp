// Actual pinned upstream tag extraction; no calibration or sensor authority.
// This product includes software developed by the Autonomous Systems Lab and Skybotix AG.
#include <apriltags/Tag36h11.h>
#include <apriltags/TagDetector.h>
#include <opencv2/imgcodecs.hpp>
#include <cmath>
#include <iomanip>
#include <iostream>

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  const cv::Mat image = cv::imread(argv[1], cv::IMREAD_GRAYSCALE);
  if (image.empty() || image.cols != 960 || image.rows != 960) return 3;
  AprilTags::TagDetector detector(AprilTags::tagCodes36h11, 2);
  const auto rows = detector.extractTags(image);
  std::cout << std::setprecision(17) << "{\"width\":960,\"height\":960,\"black_border\":2,\"detections\":[";
  for (size_t i = 0; i < rows.size(); ++i) {
    const auto &d = rows[i];
    if (i) std::cout << ',';
    std::cout << "{\"id\":" << d.id << ",\"hamming\":" << d.hammingDistance
              << ",\"rotation\":" << d.rotation << ",\"good\":" << (d.good ? "true" : "false")
              << ",\"corners\":[";
    for (int k = 0; k < 4; ++k) {
      if (k) std::cout << ',';
      std::cout << '[';
      if (std::isfinite(d.p[k].first)) std::cout << d.p[k].first; else std::cout << "null";
      std::cout << ',';
      if (std::isfinite(d.p[k].second)) std::cout << d.p[k].second; else std::cout << "null";
      std::cout << ']';
    }
    std::cout << "]}";
  }
  std::cout << "],\"measured_calibration\":false,\"source_qualified\":false}\n";
  return 0;
}
