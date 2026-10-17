"""Exact generated RX profile; no source or clock grant."""
import struct

from tools.benchmark.kernel_datagram_arrival import KernelTimestampNS

RX_ABI = {
    "schema": "flydrones.kernel_rx_timestamping_new_abi.v1", "machine": "x86_64", "byteorder": "little",
    "pointer_bytes": 8, "sol_socket": 1, "so_timestamping_new": 65, "cmsg_type": 65,
    "rx_software": 8, "report_software": 16,
    "forbidden_timestamp_old": 29, "forbidden_timestamp_new": 63,
    "forbidden_timestampns_old": 35, "forbidden_timestampns_new": 64,
    "timespec_bytes": 48, "element_bytes": 16, "ts0_offset": 0, "ts1_offset": 16, "ts2_offset": 32,
    "sec_offset": 0, "sec_bytes": 8, "nsec_offset": 8, "nsec_bytes": 8,
    "cmsg_space": 64, "msg_dontwait": 64, "msg_trunc": 32, "msg_ctrunc": 8,
}


class KernelRXTimestamping(KernelTimestampNS):
    _expected_abi = RX_ABI
    ancillary_bytes = 64

    def _option(self):
        return self._abi["so_timestamping_new"], self._abi["rx_software"] | self._abi["report_software"]

    def _additional_option_check(self, sock):
        for name in ("forbidden_timestamp_old", "forbidden_timestamp_new",
                     "forbidden_timestampns_old", "forbidden_timestampns_new"):
            self._open()
            value = sock.getsockopt(self._abi["sol_socket"], self._abi[name])
            self._open()
            if type(value) is not int or value != 0:
                self._refuse("legacy receive timestamp option conflicts with generated RX")

    def parse(self, ancillary, flags, after_realtime_ns):
        self._open()
        if (type(flags) is not int or flags != 0 or type(ancillary) is not list or len(ancillary) != 1
                or type(ancillary[0]) is not tuple or len(ancillary[0]) != 3):
            self._refuse("generated RX ancillary missing/duplicate/truncated or flags invalid")
        level, kind, raw = ancillary[0]
        if (type(level) is not int or level != self._abi["sol_socket"]
                or type(kind) is not int or kind != self._abi["cmsg_type"]
                or type(raw) is not bytes or len(raw) != self._abi["timespec_bytes"]):
            self._refuse("generated RX ancillary type/ABI/length invalid")
        values = struct.unpack("<6q", raw)
        if any(values[2:]):
            self._refuse("unexpected nonsoftware generated RX timestamp")
        return self._validate_value(values[0], values[1], after_realtime_ns)
