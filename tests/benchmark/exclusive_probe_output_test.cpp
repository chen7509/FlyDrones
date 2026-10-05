// Run with g++ on Linux; no estimator or simulation is linked or started.
#include "exclusive_probe_output.h"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <csignal>
#include <sys/resource.h>

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  const std::filesystem::path root(argv[1]);
  if (!std::filesystem::create_directory(root)) throw std::runtime_error("fresh test directory required");
  auto rejects = [](auto operation) {
    try { operation(); } catch (const std::exception &) { return true; }
    return false;
  };
  auto check = [](bool condition) { if (!condition) throw std::runtime_error("output guard regression"); };
  using namespace flydrones_probe;
  const auto a = root / "a.csv", b = root / "b.jsonl";
  check(rejects([&] { validate_output_pair(a, root / "sub/../a.csv"); }));
  std::filesystem::create_symlink(root / "outside.csv", a);
  check(rejects([&] { validate_output_pair(a, b); }));
  check(rejects([&] { ExclusiveOutput output(a); }));
  check(!std::filesystem::exists(root / "outside.csv"));
  std::filesystem::remove(a);
  std::filesystem::create_directory(a);
  check(rejects([&] { validate_output_pair(a, b); }));
  check(!std::filesystem::exists(b));
  std::filesystem::remove(a);
  validate_output_pair(a, b);
  { ExclusiveOutput output(a); output.stream() << "preserved\n"; output.finish(); }
  check(rejects([&] { ExclusiveOutput output(a); }));
  std::ifstream in(a); std::string line; std::getline(in, line);
  check(line == "preserved");
  std::filesystem::create_hard_link(a, b);
  check(rejects([&] { validate_output_pair(a, b); }));
  std::signal(SIGXFSZ, SIG_IGN);
  rlimit original;
  check(getrlimit(RLIMIT_FSIZE, &original) == 0);
  rlimit limited = original;
  limited.rlim_cur = 16;
  check(setrlimit(RLIMIT_FSIZE, &limited) == 0);
  check(rejects([&] { ExclusiveOutput output(root / "limited.txt"); output.stream() << std::string(100, 'x'); output.finish(); }));
  check(setrlimit(RLIMIT_FSIZE, &original) == 0);
  std::cout << "normal, alias, dangling symlink, directory, existing file, hardlink, write failure: passed\n";
}
