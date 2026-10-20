// SPDX-License-Identifier: GPL-3.0-or-later
// Isolated research consumer helpers; never linked into the MIT flight backend.
#pragma once
#include <charconv>
#include <cmath>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace recorded_dataset {
struct Frame { long long ns; std::string name; };
struct Imu { long long ns; double value[6]; };
inline std::vector<std::string> cells(std::string line) {
  if (!line.empty() && line.back()=='\r') line.pop_back();
  std::vector<std::string> out;
  size_t start=0;
  for (;;) {
    auto end=line.find(',', start);
    out.push_back(line.substr(start, end==std::string::npos ? end : end-start));
    if (end==std::string::npos) return out;
    start=end+1;
  }
}
inline long long stamp(const std::string &text) {
  long long value=0;
  auto result=std::from_chars(text.data(), text.data()+text.size(), value);
  if (text.empty() || text[0]<'1' || text[0]>'9' || result.ec!=std::errc{} ||
      result.ptr!=text.data()+text.size() || value<=0)
    throw std::runtime_error("invalid integer nanosecond stamp");
  return value;
}
inline std::vector<std::vector<std::string>> csv(const std::string &path, const std::string &header,
                                               size_t limit, size_t max_bytes) {
  std::ifstream input(path, std::ios::binary|std::ios::ate);
  if (!input || input.tellg()<0 || size_t(input.tellg())>max_bytes)
    throw std::runtime_error("missing or oversized CSV");
  input.seekg(0);
  std::string line;
  std::getline(input, line);
  if (!line.empty() && line.back()=='\r') line.pop_back();
  if (line!=header) throw std::runtime_error("unexpected CSV header");
  std::vector<std::vector<std::string>> rows;
  while (std::getline(input, line)) {
    if (line.size()>1048576 || rows.size()>=limit) throw std::runtime_error("CSV row bound exceeded");
    rows.push_back(cells(line));
  }
  if (!input.eof() || rows.empty()) throw std::runtime_error("incomplete or empty CSV");
  return rows;
}
inline std::vector<Frame> frames(const std::string &path) {
  auto rows=csv(path, "#timestamp [ns],filename", 512, 1048576);
  std::vector<Frame> result;
  long long last=0;
  for (const auto &row:rows) {
    if (row.size()!=2) throw std::runtime_error("camera CSV field count");
    auto ns=stamp(row[0]);
    if (ns<=last || row[1]!=std::to_string(ns)+".png") throw std::runtime_error("camera identity/order invalid");
    result.push_back({ns,row[1]}); last=ns;
  }
  return result;
}
inline std::vector<Imu> imus(const std::string &path) {
  auto rows=csv(path, "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]",
                100000, 33554432);
  std::vector<Imu> result;
  long long last=0;
  for (const auto &row:rows) {
    if (row.size()!=7) throw std::runtime_error("IMU CSV field count");
    Imu sample{}; sample.ns=stamp(row[0]);
    if (sample.ns<=last) throw std::runtime_error("IMU time nonincreasing");
    for (int i=0; i<6; ++i) {
      size_t used=0; sample.value[i]=std::stod(row[i+1], &used);
      if (used!=row[i+1].size() || !std::isfinite(sample.value[i])) throw std::runtime_error("IMU scalar invalid");
    }
    result.push_back(sample); last=sample.ns;
  }
  return result;
}
}
