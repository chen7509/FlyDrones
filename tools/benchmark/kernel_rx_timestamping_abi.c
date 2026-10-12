/* Read installed UAPI definitions; never creates a socket. */
#define _GNU_SOURCE
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <sys/socket.h>
#include <linux/time_types.h>
#include <linux/errqueue.h>
#include <linux/net_tstamp.h>

#if !defined(__linux__) || !defined(__x86_64__) || !defined(SO_TIMESTAMPING_NEW)
#error unsupported generated RX timestamp ABI
#endif

int main(void) {
    const uint32_t endian = 1;
    if (*(const unsigned char *)&endian != 1 || sizeof(void *) != 8 ||
        sizeof(struct scm_timestamping64) != 48 || sizeof(struct __kernel_timespec) != 16 ||
        offsetof(struct scm_timestamping64, ts[0]) != 0 ||
        offsetof(struct scm_timestamping64, ts[1]) != 16 ||
        offsetof(struct scm_timestamping64, ts[2]) != 32 ||
        offsetof(struct __kernel_timespec, tv_sec) != 0 || offsetof(struct __kernel_timespec, tv_nsec) != 8 ||
        sizeof(((struct __kernel_timespec *)0)->tv_sec) != 8 ||
        sizeof(((struct __kernel_timespec *)0)->tv_nsec) != 8) return 2;
    printf("{\"schema\":\"flydrones.kernel_rx_timestamping_new_abi.v1\","
           "\"machine\":\"x86_64\",\"byteorder\":\"little\",\"pointer_bytes\":%zu,"
           "\"sol_socket\":%d,\"so_timestamping_new\":%d,\"cmsg_type\":%d,"
           "\"rx_software\":%d,\"report_software\":%d,"
           "\"forbidden_timestamp_old\":%d,\"forbidden_timestamp_new\":%d,"
           "\"forbidden_timestampns_old\":%d,\"forbidden_timestampns_new\":%d,"
           "\"timespec_bytes\":%zu,\"element_bytes\":%zu,\"ts0_offset\":%zu,\"ts1_offset\":%zu,\"ts2_offset\":%zu,"
           "\"sec_offset\":%zu,\"sec_bytes\":%zu,\"nsec_offset\":%zu,\"nsec_bytes\":%zu,"
           "\"cmsg_space\":%zu,\"msg_dontwait\":%d,\"msg_trunc\":%d,\"msg_ctrunc\":%d}\n",
           sizeof(void *), SOL_SOCKET, SO_TIMESTAMPING_NEW, SO_TIMESTAMPING_NEW,
           SOF_TIMESTAMPING_RX_SOFTWARE, SOF_TIMESTAMPING_SOFTWARE,
           SO_TIMESTAMP_OLD, SO_TIMESTAMP_NEW, SO_TIMESTAMPNS_OLD, SO_TIMESTAMPNS_NEW,
           sizeof(struct scm_timestamping64), sizeof(struct __kernel_timespec),
           offsetof(struct scm_timestamping64, ts[0]), offsetof(struct scm_timestamping64, ts[1]),
           offsetof(struct scm_timestamping64, ts[2]), offsetof(struct __kernel_timespec, tv_sec),
           sizeof(((struct __kernel_timespec *)0)->tv_sec), offsetof(struct __kernel_timespec, tv_nsec),
           sizeof(((struct __kernel_timespec *)0)->tv_nsec), (size_t)CMSG_SPACE(sizeof(struct scm_timestamping64)),
           MSG_DONTWAIT, MSG_TRUNC, MSG_CTRUNC);
    return 0;
}
