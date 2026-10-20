"""场景脚本共享助手（pcap 经典格式版）。

时间窗口分段（pcap 无 Custom Block，用时间间隔表达阶段）：
  before : [base,        base+30s)
  gap 10s
  fault  : [base+40s,    base+70s)
  gap 10s
  after  : [base+80s,    base+95s)

segment_boundary() 不再写自定义块，而是推进时间指针到下一段起点。
verify.py 按 ts 距 BASE_TS_US 的偏移判定 stage。
"""
from __future__ import annotations

from typing import Callable

from isis_simulator.pcap_writer import PcapWriter
from isis_simulator import isis_pdu as pdu
from isis_simulator.isis_topology import L2_MULTICAST_MAC

BASE_TS_US = 1_700_000_000_000_000
IIH_INTERVAL_US = 3_000_000         # 3s
DEFAULT_HOLDING = 27                # hello 3s * mult 9

BG_NODES = (3, 4)
BG_INTERVAL_US = 9_000_000

# 阶段时间窗口（相对 BASE_TS_US 的偏移，单位 us）
STAGE_WINDOWS = {
    "before": (0,                30 * 1_000_000),
    "fault":  (40 * 1_000_000,  70 * 1_000_000),
    "after":  (80 * 1_000_000,  95 * 1_000_000),
}
# 段间 gap = 10s，verify 据此判定阶段


def open_writer(path: str) -> PcapWriter:
    return PcapWriter(path)


def _emit_iih(w: PcapWriter, ts_us: int, node: int, holding: int,
              pdu_func: Callable = pdu.build_l2_lan_iih,
              pdu_kwargs: dict | None = None,
              dst_mac: bytes | None = None,
              comment: str | None = None) -> int:
    """发一个 IIH；返回 ts（不变，调用方自行推进）。comment 在 pcap 下被忽略。"""
    kw = dict(pdu_kwargs or {})
    mac = dst_mac or L2_MULTICAST_MAC
    frame = pdu.eth_iso_frame(node, mac, pdu_func(node, holding, **kw))
    w.write_packet(frame, ts_us)
    return ts_us


def emit_normal_all(w: PcapWriter, start: int, duration_s: int = 30,
                    holding: int = DEFAULT_HOLDING) -> int:
    """正常基线段：R01/R02 同周期 IIH + 背景邻居。返回下段可用起始 ts。"""
    import isis_topology as topo

    layout = [
        (topo.STAR_CENTER, 0, IIH_INTERVAL_US),
        (topo.FAULT_PEER,  IIH_INTERVAL_US // 2, IIH_INTERVAL_US),
    ]
    for n in BG_NODES:
        layout.append((n, IIH_INTERVAL_US * 2 // 3, BG_INTERVAL_US))

    end = start
    full_duration_us = duration_s * 1_000_000
    horizon = start + full_duration_us
    for node, off, interval in layout:
        t = start + off
        while t < horizon:
            _emit_iih(w, t, node, holding, dst_mac=L2_MULTICAST_MAC)
            if t + interval > end:
                end = t + interval
            t += interval
    return max(end, horizon)


def segment_boundary(w: PcapWriter, stage: str, current_end: int | None = None,
                     base_ts: int = BASE_TS_US) -> int:
    """pcap 无阶段块；返回下段起始 ts（带 gap）。

    current_end 传入当前段已写到的最大 ts，函数按 STAGE_WINDOWS 返回对应阶段起点。
    简化：直接按 stage 名称返回其绝对起点。
    """
    off_start, _ = STAGE_WINDOWS[stage]
    return base_ts + off_start