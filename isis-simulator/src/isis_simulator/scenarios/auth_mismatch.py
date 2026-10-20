"""auth-mismatch 场景：fault 段 R02 在焦点接口开启 isis password clear lab123 ——
IIH 携带 Authentication TLV(10)，与对端 R01（无认证）不一致，触发邻接握手失败。

预期命中：NEIGHBOR_LOSS_AT_FAULT，INITIALIZING_NEIGHBOR_PRESENT。
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
from isis_simulator.isis_topology import STAR_CENTER, FAULT_PEER

PASSWORD = "lab123"


def emit_fault(w, start, dur_s=30) -> int:
    horizon = start + dur_s * 1_000_000
    layout = [
        (STAR_CENTER, 0, IIH_INTERVAL_US, {}),
        (FAULT_PEER, IIH_INTERVAL_US // 2, IIH_INTERVAL_US, {"password": PASSWORD}),
    ]
    for n in BG_NODES:
        layout.append((n, IIH_INTERVAL_US * 2 // 3, BG_INTERVAL_US, {}))
    end = start
    for node, off, interval, kw in layout:
        t = start + off
        while t < horizon:
            comment = "auth-mismatch" if node == FAULT_PEER else ""
            _emit_iih(w, t, node, 27, pdu.build_l2_lan_iih, kw, comment=comment)
            if t + interval > end:
                end = t + interval
            t += interval
    return max(end, horizon)


def run(outpath="pcapng/auth-mismatch.pcap") -> tuple[str, int]:
    w = open_writer(outpath)
    t = segment_boundary(w, "before"); t = emit_normal_all(w, t, 30)
    t = segment_boundary(w, "fault");  t = emit_fault(w, t, 30)
    t = segment_boundary(w, "after");  t = emit_normal_all(w, t, 15)
    w.close()
    return outpath, w.packet_count


if __name__ == "__main__":
    print(run())