"""netem-loss-delay 场景：fault 段 tc netem loss 40% delay 400ms，
表现为 IIH 高丢包（约 40%）且到达时间抖动拉大、ICMP echo 高丢包高延迟。

预期命中：LINK_PROBE_DEGRADATION（焦点链路直连探针退化为本地规则）。
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from isis_simulator.scenario_lib import (
    open_writer, emit_normal_all, segment_boundary, _emit_iih,
    IIH_INTERVAL_US, BASE_TS_US, DEFAULT_HOLDING, BG_NODES, BG_INTERVAL_US,
)
from isis_simulator import isis_pdu as pdu
from isis_simulator.isis_topology import STAR_CENTER, FAULT_PEER, L2_MULTICAST_MAC

LOSS_RATE = 0.40          # 40% 丢包
DELAY_US = 400_000        # 400ms
JITTER_MAX_US = 150_000   # 抖动上限 150ms
ICMP_PAIRS = 15


def emit_fault(w, start, dur_s=30) -> int:
    rng = random.Random(42)              # 固定种子，回归可复现
    horizon = start + dur_s * 1_000_000
    end = start

    def jittered():
        return start + rng.randint(0, 0)  # placeholder unused

    # IIH：R01 与 R02 名义 3s 一发，~40% 丢，且每个未丢的报文 ts 加 400ms ± jitter
    for node, off in ((STAR_CENTER, 0), (FAULT_PEER, IIH_INTERVAL_US // 2)):
        t = start + off
        while t < horizon:
            if rng.random() < LOSS_RATE:
                t += IIH_INTERVAL_US
                continue
            ts = t + DELAY_US + rng.randint(-JITTER_MAX_US, JITTER_MAX_US)
            _emit_iih(w, ts, node, DEFAULT_HOLDING, pdu.build_l2_lan_iih, {},
                      dst_mac=L2_MULTICAST_MAC, comment="netem-degraded IIH")
            end = max(end, ts + IIH_INTERVAL_US)
            t += IIH_INTERVAL_US
    # 背景受同样链路劣化影响，简化保持同样延迟
    for n in BG_NODES:
        t = start + IIH_INTERVAL_US * 2 // 3
        while t < horizon:
            if rng.random() < LOSS_RATE:
                t += BG_INTERVAL_US
                continue
            ts = t + DELAY_US
            _emit_iih(w, ts, n, DEFAULT_HOLDING, pdu.build_l2_lan_iih, {},
                      dst_mac=L2_MULTICAST_MAC, comment="netem-degraded bg")
            end = max(end, ts + BG_INTERVAL_US)
            t += BG_INTERVAL_US
    # ICMP echo：R01 -> R02，每秒一次，~40% 丢包、回复延迟 400ms±jitter
    for seq in range(ICMP_PAIRS):
        req_ts = start + seq * 1_000_000
        if req_ts >= horizon:
            break
        req = pdu.build_icmp_echo(STAR_CENTER, FAULT_PEER, seq=seq)
        w.write_packet(req, req_ts, comment=f"netem ICMP echo req seq={seq} stage=fault")
        end = max(end, req_ts + 1_000_000)
        if rng.random() < LOSS_RATE:
            continue
        reply_ts = req_ts + DELAY_US + rng.randint(0, JITTER_MAX_US)
        reply = pdu.build_icmp_echo_reply(FAULT_PEER, STAR_CENTER, seq=seq)
        w.write_packet(reply, reply_ts, comment=f"netem ICMP reply seq={seq} stage=fault")
        end = max(end, reply_ts + 1_000_000)
    return max(end, horizon)


def run(outpath="pcapng/netem-loss-delay.pcap") -> tuple[str, int]:
    w = open_writer(outpath)
    t = segment_boundary(w, "before"); t = emit_normal_all(w, t, 30)
    t = segment_boundary(w, "fault");  t = emit_fault(w, t, 30)
    t = segment_boundary(w, "after");  t = emit_normal_all(w, t, 15)
    w.close()
    return outpath, w.packet_count


if __name__ == "__main__":
    print(run())