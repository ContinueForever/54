"""area-mismatch 场景：fault 段 R02 对端把自己的 area 改成 49.0002（与全网 49.0001 不一致）。

拓扑受限：当前 66 节点为 level-2-only，Area 不匹配在 L2 域下未必形成强邻接断开，
因此本场景预期为"记录性"样本。注入点在 R02 的 IIH TLV 1（Area Address）。
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

WRONG_AREA = bytes((0x49, 0x00, 0x02))


def emit_fault(w, start, dur_s=30) -> int:
    horizon = start + dur_s * 1_000_000
    layout = [
        (STAR_CENTER, 0, IIH_INTERVAL_US, {}),
        (FAULT_PEER, IIH_INTERVAL_US // 2, IIH_INTERVAL_US, {"area_bytes": WRONG_AREA}),
    ]
    for n in BG_NODES:
        layout.append((n, IIH_INTERVAL_US * 2 // 3, BG_INTERVAL_US, {}))
    end = start
    for node, off, interval, kw in layout:
        t = start + off
        while t < horizon:
            if node == FAULT_PEER:
                _emit_iih(w, t, node, 27, pdu.build_l2_lan_iih, kw, comment="area-mismatch")
            else:
                _emit_iih(w, t, node, 27, pdu.build_l2_lan_iih, kw)
            if t + interval > end:
                end = t + interval
            t += interval
    return max(end, horizon)


def run(outpath="pcapng/area-mismatch.pcap") -> tuple[str, int]:
    w = open_writer(outpath)
    t = segment_boundary(w, "before"); t = emit_normal_all(w, t, 30)
    t = segment_boundary(w, "fault");  t = emit_fault(w, t, 30)
    t = segment_boundary(w, "after");  t = emit_normal_all(w, t, 15)
    w.close()
    return outpath, w.packet_count


if __name__ == "__main__":
    print(run())