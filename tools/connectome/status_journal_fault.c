#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <limits.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static atomic_int short_write_stage = 0;

static int selected_fd(int fd) {
  const char *target = getenv("FAULT_TARGET");
  if (target == NULL || target[0] == '\0') return 0;
  char proc_path[64];
  char actual[PATH_MAX];
  snprintf(proc_path, sizeof(proc_path), "/proc/self/fd/%d", fd);
  ssize_t length = readlink(proc_path, actual, sizeof(actual) - 1);
  if (length < 0 || (size_t)length >= sizeof(actual)) return 0;
  actual[length] = '\0';
  return strcmp(actual, target) == 0;
}

ssize_t write(int fd, const void *buffer, size_t count) {
  ssize_t (*real_write)(int, const void *, size_t) = dlsym(RTLD_NEXT, "write");
  const char *mode = getenv("FAULT_MODE");
  if (mode != NULL && strcmp(mode, "partial_then_eio") == 0 && selected_fd(fd)) {
    int stage = atomic_load(&short_write_stage);
    if (stage == 0 && count > 1) {
      atomic_store(&short_write_stage, 1);
      return real_write(fd, buffer, count / 2);
    }
    if (stage == 1) {
      atomic_store(&short_write_stage, 2);
      static const char note[] = "flydrones injected write EIO\n";
      real_write(2, note, sizeof(note) - 1);
      errno = EIO;
      return -1;
    }
  }
  return real_write(fd, buffer, count);
}

int fsync(int fd) {
  int (*real_fsync)(int) = dlsym(RTLD_NEXT, "fsync");
  const char *mode = getenv("FAULT_MODE");
  if (mode != NULL && strcmp(mode, "fsync_eio") == 0 && selected_fd(fd)) {
    ssize_t (*real_write)(int, const void *, size_t) = dlsym(RTLD_NEXT, "write");
    static const char note[] = "flydrones injected fsync EIO\n";
    real_write(2, note, sizeof(note) - 1);
    errno = EIO;
    return -1;
  }
  return real_fsync(fd);
}

int close(int fd) {
  int (*real_close)(int) = dlsym(RTLD_NEXT, "close");
  const char *mode = getenv("FAULT_MODE");
  if (mode != NULL && strcmp(mode, "close_eio") == 0 && selected_fd(fd)) {
    int result = real_close(fd);
    if (result == 0) {
      ssize_t (*real_write)(int, const void *, size_t) = dlsym(RTLD_NEXT, "write");
      static const char note[] = "flydrones injected close EIO\n";
      real_write(2, note, sizeof(note) - 1);
      errno = EIO;
      return -1;
    }
    return result;
  }
  return real_close(fd);
}
