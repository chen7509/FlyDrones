/* Read installed Linux UAPI layout/option values; no socket or network call. */
#define _GNU_SOURCE
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/socket.h>
#include <linux/time_types.h>

#if !defined(__linux__) || !defined(__x86_64__) || !defined(SO_TIMESTAMPNS_NEW)
#error unsupported first kernel timestamp ABI profile
#endif

int main(void) {
    const uint32_t endian = 1;
    if (*(const unsigned char *)&endian != 1 || sizeof(void *) != 8 ||
        sizeof(struct __kernel_timespec) != 16 ||
        offsetof(struct __kernel_timespec, tv_sec) != 0 ||
        offsetof(struct __kernel_timespec, tv_nsec) != 8 ||
        sizeof(((struct __kernel_timespec *)0)->tv_sec) != 8 ||
        sizeof(((struct __kernel_timespec *)0)->tv_nsec) != 8) {
        return 2;
    }
    printf("{\"schema\":\"flydrones.kernel_timestampns_new_abi.v1\","
           "\"machine\":\"x86_64\",\"byteorder\":\"little\",\"pointer_bytes\":%zu,"
           "\"sol_socket\":%d,\"so_timestampns_new\":%d,\"cmsg_type\":%d,"
           "\"timespec_bytes\":%zu,\"sec_offset\":%zu,\"sec_bytes\":%zu,"
           "\"nsec_offset\":%zu,\"nsec_bytes\":%zu,\"cmsg_space\":%zu,"
           "\"msg_dontwait\":%d,\"msg_trunc\":%d,\"msg_ctrunc\":%d}\n",
           sizeof(void *), SOL_SOCKET, SO_TIMESTAMPNS_NEW, SO_TIMESTAMPNS_NEW,
           sizeof(struct __kernel_timespec), offsetof(struct __kernel_timespec, tv_sec),
           sizeof(((struct __kernel_timespec *)0)->tv_sec),
           offsetof(struct __kernel_timespec, tv_nsec), sizeof(((struct __kernel_timespec *)0)->tv_nsec),
           (size_t)CMSG_SPACE(sizeof(struct __kernel_timespec)), MSG_DONTWAIT, MSG_TRUNC, MSG_CTRUNC);
    return 0;
}
