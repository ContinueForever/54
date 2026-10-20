"""从 isis-simulator 生成的 pcap 中提取 IS-IS 特征。"""
from __future__ import annotations

import os
import struct
import sys
from collections import defaultdict
from pathlib import Path

from typing import Any, Dict, List, Tuple

# 复用 isis_simulator 的解析代码
from isis_simulator.verify import (
    read_pcap,
    decode_packet,
    aggregate,
    detect_anomalies,
    PDU_NAME,
)
from isis_simulator.scenario_lib import BASE_TS_US, STAGE_WINDOWS

PDU_L1_LAN_IIH = 0x11
PDU_L2_LAN_IIH = 0x12
PDU_P2P_IIH = 0x13
PDU_L1_LSP = 0x14
PDU_L2_LSP = 0x15


def _stage_of(ts_us: int) -> str:
    off = ts_us - BASE_TS_US
    for stage, (s, e) in STAGE_WINDOWS.items():
        if s <= off < e:
            return stage
    if off < STAGE_WINDOWS["fault"][0]:
        return "before"
    if off < STAGE_WINDOWS["after"][0]:
        return "fault"
    return "after"


def _signal_evidence(packets) -> Dict[str, str]:
    """为每条 pcap 异常信号生成简短的数值证据描述。"""
    agg, icmp = aggregate(packets)
    ev = {}
    focus = {s: agg.get((s, "000000000002")) for s in ("before", "fault", "after")}
    focus = {k: (v or {"iih_count": 0, "holding_values": set(), "pdu_types": set(),
                       "iih_ts": [], "has_auth": False, "max_pdu_total": 0})
             for k, v in focus.items()}

    def interval(ts_list):
        ts_list = sorted(ts_list)
        if len(ts_list) < 2:
            return None
        return min(ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1))

    b, f = focus["before"], focus["fault"]
    if f["iih_count"] < b["iih_count"] * 0.5 or f["iih_count"] == 0:
        ev["NEIGHBOR_LOSS_AT_FAULT"] = (
            f"R02 IIH: before={b['iih_count']}, fault={f['iih_count']}")
    bi, fi = interval(b["iih_ts"]), interval(f["iih_ts"])
    if bi is not None and fi is not None and abs(bi - fi) > 200_000:
        ev["HELLO_INTERVAL_CHANGE"] = f"R02 Hello 间隔: {bi/1e6:.1f}s -> {fi/1e6:.1f}s"
    if b["holding_values"] and f["holding_values"] and \
            b["holding_values"] != f["holding_values"]:
        ev["HOLDING_TIMER_CHANGE"] = (
            f"R02 Holding: {sorted(b['holding_values'])} -> {sorted(f['holding_values'])}")
    if b["pdu_types"] and f["pdu_types"] and b["pdu_types"] != f["pdu_types"]:
        ev["CIRCUIT_TYPE_CHANGE"] = (
            f"R02 PDU类型: {sorted(b['pdu_types'])} -> {sorted(f['pdu_types'])}")
    if abs(f["max_pdu_total"] - b["max_pdu_total"]) >= 50:
        ev["INTERFACE_MTU_CHANGE"] = (
            f"R02 最大PDU: {b['max_pdu_total']} -> {f['max_pdu_total']}")
    if f["has_auth"] and not b["has_auth"]:
        ev["INITIALIZING_NEIGHBOR_PRESENT"] = "R02 故障窗口出现携带认证TLV的Hello"

    by_src = {}
    for (stage, sid), a in agg.items():
        if sid:
            by_src.setdefault(sid, set()).update(a["macs"])
    dup = [sid for sid, macs in by_src.items() if len(macs) > 1]
    if dup:
        ev["DUPLICATE_NEIGHBOR_SYSTEM_ID"] = f"SystemID {dup[0]} 关联多个源MAC"

    req = icmp.get(("fault", "req"), {"req": 0})["req"]
    rep = icmp.get(("fault", "reply"), {"reply": 0})["reply"]
    if req > 5 and (1 - rep / req) > 0.25:
        ev["LINK_PROBE_DEGRADATION"] = f"fault 窗口 ICMP: req={req}, reply={rep}"
    return ev


def _per_source_detail(packets) -> Dict[str, Any]:
    """按源 System ID 输出每阶段的计数/定时器/认证明细（支持 pcap 判定与报告）。"""
    agg, _ = aggregate(packets)
    detail = {}
    for (stage, sid), a in sorted(agg.items()):
        if not sid:
            continue
        entry = detail.setdefault(sid, {})
        entry.setdefault("stages", {})[stage] = {
            "iih_count": a["iih_count"],
            "holding_values": sorted(a["holding_values"]),
            "areas": sorted(a["areas"]),
            "has_auth": bool(a["has_auth"]),
            "max_pdu_total": a["max_pdu_total"],
            "pdu_types": sorted(PDU_NAME.get(t, hex(t)) for t in a["pdu_types"]),
            "hello_intervals_s": _intervals_human(a["iih_ts"]),
        }
        entry["lsp_ids"] = sorted(a["lsp_ids"])
    return detail


def _intervals_human(ts_list) -> List[float]:
    ts_list = sorted(ts_list)
    if len(ts_list) < 2:
        return []
    return [round((ts_list[i + 1] - ts_list[i]) / 1e6, 1)
            for i in range(len(ts_list) - 1)]


def extract_features(pcap_path: str | Path) -> Dict[str, Any]:
    """提取 pcap 中的关键特征，按 before/fault/after 聚合。"""
    packets = read_pcap(str(pcap_path))

    stats = {
        "before": {"iih": 0, "lsp": 0, "src_ids": set(), "areas": set(), "holding_timers": set(), "pdu_types": set(), "max_pdu_len": 0},
        "fault": {"iih": 0, "lsp": 0, "src_ids": set(), "areas": set(), "holding_timers": set(), "pdu_types": set(), "max_pdu_len": 0},
        "after": {"iih": 0, "lsp": 0, "src_ids": set(), "areas": set(), "holding_timers": set(), "pdu_types": set(), "max_pdu_len": 0},
    }
    src_mac_by_id = defaultdict(set)
    icmp_stats = defaultdict(lambda: {"req": 0, "reply": 0})

    for ts, frame, stage in packets:
        d = decode_packet(frame)
        if d["kind"] != "isis":
            if d["kind"] == "ipv4" and d.get("ipv4_proto") == 1:
                if d.get("icmp_type") == 0x08:
                    icmp_stats[stage]["req"] += 1
                elif d.get("icmp_type") == 0x00:
                    icmp_stats[stage]["reply"] += 1
            continue

        s = stats[stage]
        pdu_type = d.get("pdu_type")
        s["pdu_types"].add(PDU_NAME.get(pdu_type, "?"))
        if pdu_type in (PDU_L1_LAN_IIH, PDU_L2_LAN_IIH, PDU_P2P_IIH):
            s["iih"] += 1
            sid = d.get("source_id")
            if sid:
                s["src_ids"].add(sid)
                src_mac_by_id[sid].add(d.get("src_mac"))
            if d.get("holding_timer") is not None:
                s["holding_timers"].add(d["holding_timer"])
            for a in d.get("area_addresses", []):
                s["areas"].add(a)
        elif pdu_type in (PDU_L1_LSP, PDU_L2_LSP):
            s["lsp"] += 1
        s["max_pdu_len"] = max(s["max_pdu_len"], d.get("pdu_total_len", 0))

    # 转换为 JSON 可序列化结构
    def serialize(stage_stats):
        return {
            "iih_count": stage_stats["iih"],
            "lsp_count": stage_stats["lsp"],
            "src_ids": sorted(list(stage_stats["src_ids"])),
            "areas": sorted(list(stage_stats["areas"])),
            "holding_timers": sorted(list(stage_stats["holding_timers"])),
            "pdu_types": sorted(list(stage_stats["pdu_types"])),
            "max_pdu_len": stage_stats["max_pdu_len"],
        }

    duplicate_system_id = any(len(macs) > 1 for macs in src_mac_by_id.values())

    return {
        "pcap_path": str(pcap_path),
        "total_packets": len(packets),
        "stages": {k: serialize(v) for k, v in stats.items()},
        "icmp": {k: dict(v) for k, v in icmp_stats.items()},
        "duplicate_system_id": duplicate_system_id,
        "pcap_signals": sorted(detect_anomalies(packets)),
        "signal_evidence": _signal_evidence(packets),
        "per_source": _per_source_detail(packets),
    }


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "../isis-simulator/pcapng/baseline.pcap"
    import json
    print(json.dumps(extract_features(path), ensure_ascii=False, indent=2))
