"""mtu-mismatch 场景：fault 段 R02 接口 MTU 改为 1400，
表现为该节点 IIH 被 padding TLV(8) 填充到 ~1399 字节（小于正常 1499），
解码侧比较焦点 PDU 最大长度变化得到 INTERFACE_MTU_CHANGE。

预期命中：INTERFACE_MTU_CHANGE（本地规则）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from isis_simulator.scenario_lib import (
    open_writer, emit_normal_all, segment_boundary, _emit_iih,
    IIH_INTERVAL_US, BASE_TS_US, DEFAULT_HOLDING, BG_NODES, BG_INTERVAL_US,
)
from isis_simulator import isis_pdu as pdu
from isis_simulator.isis_topology import STAR_CENTER, FAULT_PEER, L2_MULTICAST_MAC

BEFORE_MTU_PDU = 1497     # 默认 MTU 1500 -> IIH padded to 1497
FAULT_MTU_PDU = 1399      # MTU 1400 -> IIH padded to 1399


def emit_fault(w, start, dur_s=30) -> int:
    horizon = start + dur_s * 1_000_000
    end = start
    layout = [
        (STAR_CENTER, 0, IIH_INTERVAL_US, {"target_total_pdu": BEFORE_MTU_PDU}),
        (FAULT_PEER, IIH_INTERVAL_US // 2, IIH_INTERVAL_US, {"target_total_pdu": FAULT_MTU_PDU}),
    ]
    for n in BG_NODES:
        layout.append((n, IIH_INTERVAL_US * 2 // 3, BG_INTERVAL_US,
                       {"target_total_pdu": BEFORE_MTU_PDU}))
    for node, off, interval, kw in layout:
        t = start + off
        while t < horizon:
            comment = "mtu-fault R02 padded-to-1399" if node == FAULT_PEER else "mtu-normal padded-1497"
            _emit_iih(w, t, node, DEFAULT_HOLDING, pdu.build_l2_lan_iih, kw,
                      dst_mac=L2_MULTICAST_MAC, comment=comment)
            end = max(end, t + interval)
            t += interval
    return max(end, horizon)


def run(outpath="pcapng/mtu-mismatch.pcap") -> tuple[str, int]:
    w = open_writer(outpath)
    t = BASE_TS_US
    # before：所有节点 IIH padded 到 1497（贴近真实 IS-IS 默认 padding 行为）
    # 复用 emit_fault 思路但叁为 BEFORE：另写一个 before-emitter
    def emit_padded_normal(w, start, dur_s, target_pdu):
        horizon = start + dur_s * 1_000_000
        end = start
        layout = [
            (STAR_CENTER, 0, IIH_INTERVAL_US),
            (FAULT_PEER, IIH_INTERVAL_US // 2, IIH_INTERVAL_US),
        ]
        for n in BG_NODES:
            layout.append((n, IIH_INTERVAL_US * 2 // 3, BG_INTERVAL_US))
        for node, off, interval in layout:
            t = start + off
            while t < horizon:
                _emit_iih(w, t, node, DEFAULT_HOLDING, pdu.build_l2_lan_iih,
                          {"target_total_pdu": target_pdu}, dst_mac=L2_MULTICAST_MAC)
                end = max(end, t + interval)
                t += interval
        return max(end, horizon)

    t = segment_boundary(w, "before"); t = emit_padded_normal(w, t, 30, BEFORE_MTU_PDU)
    t = segment_boundary(w, "fault");  t = emit_fault(w, t, 30)
    t = segment_boundary(w, "after");  t = emit_padded_normal(w, t, 15, BEFORE_MTU_PDU)
    w.close()
    return outpath, w.packet_count


if __name__ == "__main__":
    print(run())