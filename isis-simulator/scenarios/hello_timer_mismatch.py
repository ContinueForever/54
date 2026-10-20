"""hello-timer-mismatch 场景：fault 段 R02 把 hello-interval 改为 1s、hello-multiplier 改为 10，
holding_timer 从 9 改为 10，表现为 IIH 周期 3s->1s、Holding timer 9->10。

预期命中：HELLO_INTERVAL_CHANGE，HOLDING_TIMER_CHANGE，PARAMETER_VALIDATION_ALERTS。
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

BEFORE_HOLDING = 9           # hello 3s * mult 3
AFTER_HOLDING = 10           # hello 1s * mult 10
AFTER_INTERVAL_US = 1_000_000


def emit_fault(w, start, dur_s=30) -> int:
    horizon = start + dur_s * 1_000_000
    end = start
    # R01 维持 before 参数（基线对照，保持 holding=9、3s 周期）
    t = start
    while t < horizon:
        _emit_iih(w, t, STAR_CENTER, BEFORE_HOLDING, pdu.build_l2_lan_iih, {}, dst_mac=L2_MULTICAST_MAC)
        end = max(end, t + IIH_INTERVAL_US)
        t += IIH_INTERVAL_US
    # R02 改为 holding=10、周期 1s
    t = start + 500_000
    while t < horizon:
        _emit_iih(w, t, FAULT_PEER, AFTER_HOLDING, pdu.build_l2_lan_iih, {},
                  dst_mac=L2_MULTICAST_MAC, comment="hello-timer R02 1s/hold10")
        end = max(end, t + AFTER_INTERVAL_US)
        t += AFTER_INTERVAL_US
    # 背景
    for n in BG_NODES:
        t = start + IIH_INTERVAL_US * 2 // 3
        while t < horizon:
            _emit_iih(w, t, n, DEFAULT_HOLDING, pdu.build_l2_lan_iih, {}, dst_mac=L2_MULTICAST_MAC)
            end = max(end, t + BG_INTERVAL_US)
            t += BG_INTERVAL_US
    return max(end, horizon)


def run(outpath="pcapng/hello-timer-mismatch.pcap") -> tuple[str, int]:
    w = open_writer(outpath)
    t = segment_boundary(w, "before"); t = emit_normal_all(w, t, 30, holding=BEFORE_HOLDING)
    t = segment_boundary(w, "fault");  t = emit_fault(w, t, 30)
    t = segment_boundary(w, "after");  t = emit_normal_all(w, t, 15, holding=BEFORE_HOLDING)
    w.close()
    return outpath, w.packet_count


if __name__ == "__main__":
    print(run())