"""libpcap 经典格式 (.pcap) 写入器。

24 字节全局头 + 每包 16 字节记录头 + 报文数据，小端字节序，LINKTYPE_ETHERNET=1。
pcap 没有 Custom Block / option，阶段标记改用时间窗口：
  before  : [base,           base+30s)
  gap
  fault   : [base+40s,       base+70s)
  gap
  after   : [base+80s,       base+95s)
verify.py 按时间戳距 base 的偏移判定阶段。不依赖任何第三方库。
"""
from __future__ import annotations

import struct

LINKTYPE_ETHERNET = 1
PCAP_MAGIC = 0xA1B2C3D4


class PcapWriter:
    """单 interface 的经典 pcap 写入器。

    用法:
        w = PcapWriter("out.pcap")
        w.write_packet(frame_bytes, ts_us)
        w.close()
    """

    def __init__(self, path: str, snaplen: int = 65535):
        self._f = open(path, "wb")
        # 全局头：magic / ver_major / ver_minor / thiszone / sigfigs / snaplen / network
        hdr = struct.pack("<IHHIIII",
                          PCAP_MAGIC, 2, 4, 0, 0, snaplen, LINKTYPE_ETHERNET)
        self._f.write(hdr)
        self._pkt_count = 0

    def write_packet(self, frame: bytes, ts_us: int, comment: str | None = None) -> None:
        """写一个包。ts_us 为微秒级 Unix 时间戳。comment 在 pcap 下被忽略（无注释选项）。"""
        ts_sec = ts_us // 1_000_000
        ts_usec = ts_us % 1_000_000
        rec_hdr = struct.pack("<IIII", ts_sec, ts_usec, len(frame), len(frame))
        self._f.write(rec_hdr)
        self._f.write(frame)
        self._pkt_count += 1

    @property
    def packet_count(self) -> int:
        return self._pkt_count

    def close(self) -> None:
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()