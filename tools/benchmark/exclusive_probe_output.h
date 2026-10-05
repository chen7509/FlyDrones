// Linux/GCC offline research probes: preserve existing evidence, including links.
#pragma once
#include <ext/stdio_filebuf.h>
#include <fcntl.h>
#include <filesystem>
#include <ostream>
#include <stdexcept>
#include <system_error>

namespace flydrones_probe {
inline void validate_output_pair(const std::filesystem::path &a, const std::filesystem::path &b) {
  for (const auto &path : {a, b}) {
    std::error_code error;
    const auto status = std::filesystem::symlink_status(path, error);
    if ((error && error != std::errc::no_such_file_or_directory) ||
        status.type() != std::filesystem::file_type::not_found)
      throw std::runtime_error("output exists or cannot be inspected: " + path.string());
  }
  if (std::filesystem::weakly_canonical(a) == std::filesystem::weakly_canonical(b))
    throw std::runtime_error("output paths alias");
}

class ExclusiveOutput {
  static int create(const std::filesystem::path &path) {
    const int fd = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) throw std::system_error(errno, std::generic_category(), "exclusive output creation");
    return fd;
  }
  __gnu_cxx::stdio_filebuf<char> buffer_;
  std::ostream stream_;
public:
  explicit ExclusiveOutput(const std::filesystem::path &path) : buffer_(create(path), std::ios::out), stream_(&buffer_) {
    stream_.exceptions(std::ios::badbit | std::ios::failbit);
  }
  std::ostream &stream() { return stream_; }
  void finish() {
    stream_.flush();
    if (!buffer_.close()) throw std::runtime_error("output close failed");
  }
};
} // namespace flydrones_probe
