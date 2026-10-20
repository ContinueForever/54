"""pcap 解析 + IS-IS 字段提取 + 13 类异常检测。

读回我们生成的 .pcap，按时间窗口（before/fault/after）聚合信号，
应用确定性规则，输出每个场景命中的异常类型，与文档 4.1 的预期对照表对齐。
不依赖任何第三方库。
"""
from __future__ import annotations

import os
import struct
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from isis_simulator.scenario_lib import BASE_TS_US, STAGE_WINDOWS


# ---- PDU type codes ----
PDU_L1_LAN_IIH = 0x11
PDU_L2_LAN_IIH = 0x12
PDU_P2P_IIH    = 0x13
PDU_L1_LSP     = 0x14
PDU_L2_LSP     = 0x15
PDU_L1_CSNP    = 0x18
PDU_L2_CSNP    = 0x19

PDU_NAME = {
    0x11: "L1_IIH", 0x12: "L2_IIH", 0x13: "P2P_IIH",
    0x14: "L1_LSP", 0x15: "L2_LSP",
    0x18: "L1_CSNP", 0x19: "L2_CSNP",
}

# ---- TLV codes ----
TLV_AREA_ADDR        = 1
TLV_PADDING          = 8
TLV_AUTH             = 10
TLV_PROTOS_SUPPORTED = 129
TLV_IP_ADDR          = 132
TLV_HOSTNAME         = 137
TLV_EXT_IS_REACH     = 22
TLV_EXT_IP_REACH     = 135


def _stage_of(ts_us: int) -> str:
    """按时间窗口判定阶段。落在 gap 也归到前一段。"""
    off = ts_us - BASE_TS_US
    for stage, (s, e) in STAGE_WINDOWS.items():
        if s <= off < e:
            return stage
    # gap 区间：归到最近的前一段
    if off < STAGE_WINDOWS["fault"][0]:
        return "before"
    if off < STAGE_WINDOWS["after"][0]:
        return "fault"
    return "after"


def read_pcap(path: str):
    """读经典 pcap，返回 [(ts_us, frame, stage), ...]"""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 24:
        return []
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic not in (0xA1B2C3D4, 0xA1B2CD34):   # 也接受纳秒精度变体
        # 尝试大端
        magic = struct.unpack_from(">I", data, 0)[0]
        if magic != 0xA1B2C3D4:
            return []
        endian = ">"
    else:
        endian = "<"
    pos = 24
    packets = []
    while pos + 16 <= len(data):
        ts_sec, ts_usec, incl, orig = struct.unpack_from(endian + "IIII", data, pos)
        pos += 16
        frame = data[pos:pos + incl]
        pos += incl
        ts = ts_sec * 1_000_000 + ts_usec
        packets.append((ts, frame, _stage_of(ts)))
    packets.sort(key=lambda p: p[0])
    return packets


# ========== IS-IS decoder ==========
def parse_tlvs(buf: bytes) -> list[tuple[int, bytes]]:
    out = []
    pos = 0
    while pos + 2 <= len(buf):
        code = buf[pos]
        ln = buf[pos + 1]
        if code == 0 and ln == 0:
            break
        val = buf[pos + 2: pos + 2 + ln]
        out.append((code, val))
        pos += 2 + ln
    return out


def decode_packet(frame: bytes) -> dict:
    res = {"kind": None}
    if len(frame) < 14:
        return res
    ethertype = struct.unpack_from(">H", frame, 12)[0]
    res["src_mac"] = frame[6:12].hex()
    res["dst_mac"] = frame[0:6].hex()
    res["ethertype"] = ethertype
    if ethertype == 0x0800:
        res["kind"] = "ipv4"
        res["ipv4_proto"] = frame[23] if len(frame) >= 24 else 0
        if res["ipv4_proto"] == 1 and len(frame) >= 42:
            res["icmp_type"] = frame[34]
        return res
    if ethertype != 0xFEFE:
        res["kind"] = f"ether-0x{ethertype:04x}"
        return res
    p = frame[14:]
    if len(p) < 8 or p[0] != 0x83:
        return res
    res["kind"] = "isis"
    res["pdu_type"] = p[4] & 0x1F
    res["pdu_type_name"] = PDU_NAME.get(res["pdu_type"], "?")
    res["hdr_len"] = p[1]
    if res["pdu_type"] in (PDU_L1_LAN_IIH, PDU_L2_LAN_IIH, PDU_P2P_IIH):
        off = 8
        res["circuit_type"] = p[off] & 0x03
        res["source_id"] = p[off + 1: off + 7].hex()
        res["holding_timer"] = int.from_bytes(p[off + 7: off + 9], "big")
        res["pdu_length"] = int.from_bytes(p[off + 9: off + 11], "big")
        tlvs = parse_tlvs(p[off + 19: res["pdu_length"]])
    elif res["pdu_type"] == PDU_L2_LSP:
        off = 8
        res["pdu_length"] = int.from_bytes(p[off: off + 2], "big")
        res["lifetime"] = int.from_bytes(p[off + 2: off + 4], "big")
        res["lsp_id"] = p[off + 4: off + 12].hex()
        res["seq"] = int.from_bytes(p[off + 12: off + 16], "big")
        tlvs = parse_tlvs(p[off + 19: res["pdu_length"]])
    else:
        tlvs = []
    res["tlvs"] = tlvs
    res["area_addresses"] = []
    res["protocols_supported"] = []
    res["hostname"] = None
    res["has_auth"] = False
    res["padding_total"] = 0
    for code, val in tlvs:
        if code == TLV_AREA_ADDR:
            i = 0
            while i < len(val):
                ln = val[i]
                res["area_addresses"].append(val[i + 1: i + 1 + ln].hex())
                i += 1 + ln
        elif code == TLV_PROTOS_SUPPORTED:
            res["protocols_supported"] = list(val)
        elif code == TLV_HOSTNAME:
            res["hostname"] = val.decode("ascii", "replace")
        elif code == TLV_AUTH:
            res["has_auth"] = True
        elif code == TLV_PADDING:
            res["padding_total"] += len(val)
    res["pdu_total_len"] = res.get("pdu_length", len(p))
    return res


# ========== 信号聚合 + 规则检测 ==========
FOCUS_PEER_ID = "000000000002"     # R02 system-id


def _empty_slot():
    return {"iih_count": 0, "iih_ts": [], "holding_values": set(),
            "pdu_types": set(), "areas": set(), "has_auth": False,
            "max_pdu_total": 0, "macs": set(), "lsp_ids": set()}


def aggregate(packets) -> tuple[dict, dict]:
    agg = defaultdict(_empty_slot)
    icmp = defaultdict(lambda: {"req": 0, "reply": 0})
    for ts, frame, stage in packets:
        d = decode_packet(frame)
        if d["kind"] == "isis" and d["pdu_type"] in (
                PDU_L1_LAN_IIH, PDU_L2_LAN_IIH, PDU_P2P_IIH):
            key = (stage, d["source_id"])
            a = agg[key]
            a["iih_count"] += 1
            a["iih_ts"].append(ts)
            a["holding_values"].add(d.get("holding_timer", 0))
            a["pdu_types"].add(d["pdu_type"])
            for ar in d.get("area_addresses", []):
                a["areas"].add(ar)
            if d.get("has_auth"):
                a["has_auth"] = True
            a["max_pdu_total"] = max(a["max_pdu_total"], d.get("pdu_total_len", 0))
            a["macs"].add(d["src_mac"])
        elif d["kind"] == "isis" and d["pdu_type"] in (PDU_L1_LSP, PDU_L2_LSP):
            src = d.get("lsp_id", "")[:12]
            key = (stage, src)
            agg[key]["lsp_ids"].add(d.get("lsp_id"))
            agg[key]["macs"].add(d["src_mac"])
        elif d["kind"] == "ipv4" and d.get("ipv4_proto") == 1:
            if d.get("icmp_type") == 0x08:
                icmp[(stage, "req")]["req"] += 1
            elif d.get("icmp_type") == 0x00:
                icmp[(stage, "reply")]["reply"] += 1
    return agg, icmp


def detect_anomalies(packets) -> set[str]:
    agg, icmp = aggregate(packets)
    found = set()

    def focus(stage):
        return agg.get((stage, FOCUS_PEER_ID)) or _empty_slot()

    peer_before = focus("before")
    peer_fault = focus("fault")

    # 1. NEIGHBOR_LOSS_AT_FAULT
    if peer_before["iih_count"] > 0:
        if peer_fault["iih_count"] < peer_before["iih_count"] * 0.5 or peer_fault["iih_count"] == 0:
            found.add("NEIGHBOR_LOSS_AT_FAULT")

    # 2. auth -> NEIGHBOR_LOSS_AT_FAULT + INITIALIZING_NEIGHBOR_PRESENT
    if peer_fault["has_auth"] and not peer_before["has_auth"] and peer_fault["iih_count"] > 0:
        found.add("NEIGHBOR_LOSS_AT_FAULT")
        found.add("INITIALIZING_NEIGHBOR_PRESENT")

    # 3. CIRCUIT_TYPE_CHANGE / MIXED_HELLO_PDU_TYPES
    b_type = peer_before["pdu_types"]
    f_type = peer_fault["pdu_types"]
    if b_type and f_type and b_type != f_type:
        found.add("CIRCUIT_TYPE_CHANGE")
    if len(b_type | f_type) > 1:
        found.add("MIXED_HELLO_PDU_TYPES")

    # 4. HELLO_INTERVAL_CHANGE / HOLDING_TIMER_CHANGE / PARAMETER_VALIDATION_ALERTS
    def interval(ts_list):
        if len(ts_list) < 2:
            return None
        ts_list = sorted(ts_list)
        return min(ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1))
    b_int = interval(peer_before["iih_ts"])
    f_int = interval(peer_fault["iih_ts"])
    if b_int is not None and f_int is not None and abs(b_int - f_int) > 200_000:
        found.add("HELLO_INTERVAL_CHANGE")
        found.add("PARAMETER_VALIDATION_ALERTS")
    if peer_before["holding_values"] and peer_fault["holding_values"] and \
            peer_before["holding_values"] != peer_fault["holding_values"]:
        found.add("HOLDING_TIMER_CHANGE")
        found.add("PARAMETER_VALIDATION_ALERTS")

    # 5. INTERFACE_MTU_CHANGE
    if abs(peer_fault["max_pdu_total"] - peer_before["max_pdu_total"]) >= 50:
        found.add("INTERFACE_MTU_CHANGE")

    # 6. DUPLICATE_NEIGHBOR_SYSTEM_ID / SOURCE_ID_MAC_CONFLICT
    by_src = defaultdict(set)
    for (stage, sid), a in agg.items():
        if sid:
            by_src[sid].update(a["macs"])
    for sid, macs in by_src.items():
        if len(macs) > 1:
            found.add("DUPLICATE_NEIGHBOR_SYSTEM_ID")
            found.add("SOURCE_ID_MAC_CONFLICT")

    # 7. LINK_PROBE_DEGRADATION
    req = icmp.get(("fault", "req"), {"req": 0})["req"]
    rep = icmp.get(("fault", "reply"), {"reply": 0})["reply"]
    if req > 5 and (1 - rep / req) > 0.25:
        found.add("LINK_PROBE_DEGRADATION")

    # 8. area mismatch -> PARAMETER_VALIDATION_ALERTS
    before_areas = set()
    for (stage, sid), a in agg.items():
        if stage == "before":
            before_areas |= a["areas"]
    for (stage, sid), a in agg.items():
        if stage == "fault" and a["areas"] - before_areas:
            found.add("PARAMETER_VALIDATION_ALERTS")
            break

    return found


# ========== 期望对照表 + main ==========
EXPECTED = {
    "baseline": set(),
    "area-mismatch": set(),
    "auth-mismatch": {"NEIGHBOR_LOSS_AT_FAULT", "INITIALIZING_NEIGHBOR_PRESENT"},
    "circuit-type-mismatch": {"CIRCUIT_TYPE_CHANGE", "MIXED_HELLO_PDU_TYPES"},
    "link-down": {"NEIGHBOR_LOSS_AT_FAULT"},
    "hello-timer-mismatch": {"HELLO_INTERVAL_CHANGE", "HOLDING_TIMER_CHANGE", "PARAMETER_VALIDATION_ALERTS"},
    "netem-loss-delay": {"LINK_PROBE_DEGRADATION"},
    "mtu-mismatch": {"INTERFACE_MTU_CHANGE"},
    "lsp-suppression": {"NEIGHBOR_LOSS_AT_FAULT"},
    "duplicate-system-id": {"DUPLICATE_NEIGHBOR_SYSTEM_ID", "SOURCE_ID_MAC_CONFLICT"},
}


def run_check(pcap_dir: str | None = None):
    pcap_dir = pcap_dir or os.path.join(HERE, "pcapng")
    print(f"\n{'场景':24s} {'命中异常':60s} 命中预期")
    print("-" * 110)
    all_ok = True
    for fname in sorted(os.listdir(pcap_dir)):
        if not fname.endswith(".pcap"):
            continue
        scenario = fname[:-len(".pcap")]
        path = os.path.join(pcap_dir, fname)
        packets = read_pcap(path)
        if not packets:
            print(f"{scenario:24s} (no packets)")
            continue
        detected = detect_anomalies(packets)
        expected = EXPECTED.get(scenario, set())
        ok = expected.issubset(detected)
        if not ok:
            all_ok = False
        mark = "OK" if ok else "DIFF"
        print(f"{scenario:24s} {','.join(sorted(detected)) or '(none)':60s} {mark}")
    print("-" * 110)
    print("回归结果:", "全部命中" if all_ok else "存在差异")
    return all_ok


if __name__ == "__main__":
    pcap_dir = os.path.join(HERE, "pcapng")
    files = os.listdir(pcap_dir) if os.path.isdir(pcap_dir) else []
    if not any(f.endswith(".pcap") for f in files):
        print("未发现 .pcap，先调 generate.py 生成。")
        sys.exit(2)
    sys.exit(0 if run_check(pcap_dir) else 1)