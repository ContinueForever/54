"""circuit-type-mismatch 场景：fault 段 R02 把 is-type 从 level-2-only 切到 level-1，
即 IIH 由 L2 LAN IIH 改为 L1 LAN IIH（PDU 类型 0x11，circuit_type=0x01，
目的 MAC 使用 AllL1IS 01-80-C2-00-00-14）。

预期命中：CIRCUIT_TYPE_CHANGE，MIXED_HELLO_PDU_TYPES（同一 source_id 出现不同 Hello PDU 类型）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from isis_simulator.scenario_lib import (
    open_writer, emit_normal_all, segment_boundary, _emit_iih,
    IIH_INTERVAL_US, BASE_TS_US,
)
from isis_simulator import isis_pdu as pdu
from isis_simulator.scenario_lib import BG_NODES, BG_INTERVAL_US
from isis_simulator.isis_topology import (
    STAR_CENTER, FAULT_PEER, L1_MULTICAST_MAC, L2_MULTICAST_MAC,
)


def emit_fault(w, start, dur_s=30) -> int:
    horizon = start + dur_s * 1_000_000
    end = start
    # R01 仍 L2 对 L2 多播
    t = start
    while t < horizon:
        _emit_iih(w, t, STAR_CENTER, 27, pdu.build_l2_lan_iih, {}, dst_mac=L2_MULTICAST_MAC)
        end = max(end, t + IIH_INTERVAL_US)
        t += IIH_INTERVAL_US
    # R02 改 L1，用 L1 多播 + L1 LAN IIH
    t = start + IIH_INTERVAL_US // 2
    while t < horizon:
        _emit_iih(w, t, FAULT_PEER, 27, pdu.build_l1_lan_iih, {},
                  dst_mac=L1_MULTICAST_MAC, comment="circuit-type-mismatch R02->L1")
        end = max(end, t + IIH_INTERVAL_US)
        t += IIH_INTERVAL_US
    # 背景
    for n in BG_NODES:
        t = start + IIH_INTERVAL_US * 2 // 3
        while t < horizon:
            _emit_iih(w, t, n, 27, pdu.build_l2_lan_iih, {}, dst_mac=L2_MULTICAST_MAC)
            end = max(end, t + BG_INTERVAL_US)
            t += BG_INTERVAL_US
    return max(end, horizon)


def run(outpath="pcapng/circuit-type-mismatch.pcap") -> tuple[str, int]:
    w = open_writer(outpath)
    t = segment_boundary(w, "before"); t = emit_normal_all(w, t, 30)
    t = segment_boundary(w, "fault");  t = emit_fault(w, t, 30)
    t = segment_boundary(w, "after");  t = emit_normal_all(w, t, 15)
    w.close()
    return outpath, w.packet_count


if __name__ == "__main__":
    print(run())