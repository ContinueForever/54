"""link-down 场景：fault 段在 R02 焦点接口执行 ip link set down，
表现为 R02 完全停止在该链路上的 IIH 发送（链路物理中断），
R01 仍持续发 IIH 但邻接消失。

预期命中：NEIGHBOR_LOSS_AT_FAULT。
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
from isis_simulator.isis_topology import STAR_CENTER, L2_MULTICAST_MAC


def emit_fault(w, start, dur_s=30) -> int:
    """R02 完全不发包；R01 与背景邻居照常。"""
    horizon = start + dur_s * 1_000_000
    end = start
    layout = [
        (STAR_CENTER, 0, IIH_INTERVAL_US),
    ]
    for n in BG_NODES:
        layout.append((n, IIH_INTERVAL_US * 2 // 3, BG_INTERVAL_US))
    for node, off, interval in layout:
        t = start + off
        while t < horizon:
            _emit_iih(w, t, node, 27, pdu.build_l2_lan_iih, {}, dst_mac=L2_MULTICAST_MAC,
                      comment="link-down R02 silent" if node == STAR_CENTER else "")
            end = max(end, t + interval)
            t += interval
    return max(end, horizon)


def run(outpath="pcapng/link-down.pcap") -> tuple[str, int]:
    w = open_writer(outpath)
    t = segment_boundary(w, "before"); t = emit_normal_all(w, t, 30)
    t = segment_boundary(w, "fault");  t = emit_fault(w, t, 30)
    t = segment_boundary(w, "after");  t = emit_normal_all(w, t, 15)
    w.close()
    return outpath, w.packet_count


if __name__ == "__main__":
    print(run())