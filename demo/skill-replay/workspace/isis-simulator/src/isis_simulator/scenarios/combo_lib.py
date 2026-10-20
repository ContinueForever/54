"""复合故障场景共享助手。

将两个独立故障的 pcap 特征叠加到同一 fault 窗口，由 emit_combo_pair() 统一发射：
fault 段 R01 保持正常参数，R02 同时携带多个故障特征（认证/区域/MTU/定时器/电路类型）。

配合 log_generator 的组合日志与 knowledge 的组合节点，用于验证复合故障诊断能力。
"""
from __future__ import annotations

from isis_simulator.scenario_lib import (
    open_writer, emit_normal_all, segment_boundary, _emit_iih,
    IIH_INTERVAL_US, DEFAULT_HOLDING, BG_NODES, BG_INTERVAL_US,
)
from isis_simulator import isis_pdu as pdu
from isis_simulator.isis_topology import (
    STAR_CENTER, FAULT_PEER, L2_MULTICAST_MAC, L1_MULTICAST_MAC,
)

# 子故障特征常量（与单场景模块保持一致）
WRONG_AREA = bytes((0x49, 0x00, 0x02))
AUTH_PASSWORD = "lab123"
MTU_PDU_FAULT = 1399        # R02 故障段 padding 到 1399
MTU_PDU_NORMAL = 1497       # R01 正常 padding 到 1497
HELLO_FAULT_HOLDING = 10    # R02 故障段 holding=10（正常 9）
HELLO_FAULT_INTERVAL_US = 1_000_000  # R02 故障段 hello 1s（正常 3s）


def _build_pair_emit(r02_builder, r02_kwargs, r01_builder=pdu.build_l2_lan_iih,
                     r01_kwargs=None, r02_holding=DEFAULT_HOLDING,
                     r01_holding=DEFAULT_HOLDING, r02_interval_us=IIH_INTERVAL_US,
                     r01_interval_us=IIH_INTERVAL_US):
    """构造 fault 窗口发射函数：R01 正常 + R02 携带多故障特征。"""
    def emit(w, start, dur_s=30) -> int:
        horizon = start + dur_s * 1_000_000
        end = start
        t = start
        while t < horizon:
            _emit_iih(w, t, STAR_CENTER, r01_holding, r01_builder,
                      r01_kwargs or {}, dst_mac=L2_MULTICAST_MAC,
                      comment="combo R01 normal")
            end = max(end, t + r01_interval_us)
            t += r01_interval_us
        t = start + IIH_INTERVAL_US // 2
        while t < horizon:
            dst = L1_MULTICAST_MAC if r02_builder is pdu.build_l1_lan_iih else L2_MULTICAST_MAC
            _emit_iih(w, t, FAULT_PEER, r02_holding, r02_builder, r02_kwargs,
                      dst_mac=dst, comment="combo R02 multi-fault")
            end = max(end, t + r02_interval_us)
            t += r02_interval_us
        for n in BG_NODES:
            t = start + IIH_INTERVAL_US * 2 // 3
            while t < horizon:
                _emit_iih(w, t, n, DEFAULT_HOLDING, pdu.build_l2_lan_iih, {},
                          dst_mac=L2_MULTICAST_MAC)
                end = max(end, t + BG_INTERVAL_US)
                t += BG_INTERVAL_US
        return max(end, horizon)
    return emit


# ---------- 各复合故障组合的 fault 发射器 ----------

def combo_auth_area(w, start, dur_s=30) -> int:
    """认证 + 区域不匹配：R02 IIH 携带 auth TLV 且 area 改 49.0002。"""
    return _build_pair_emit(pdu.build_l2_lan_iih, {
        "password": AUTH_PASSWORD, "area_bytes": WRONG_AREA})(w, start, dur_s)


def combo_auth_mtu(w, start, dur_s=30) -> int:
    """认证 + MTU：R02 IIH 携带 auth TLV 且 padding 到 1399。"""
    return _build_pair_emit(pdu.build_l2_lan_iih, {
        "password": AUTH_PASSWORD, "target_total_pdu": MTU_PDU_FAULT},
        r01_kwargs={"target_total_pdu": MTU_PDU_NORMAL})(w, start, dur_s)


def combo_auth_circuit(w, start, dur_s=30) -> int:
    """认证 + 电路类型：R02 切换为 L1 IIH 且携带 auth TLV。"""
    return _build_pair_emit(pdu.build_l1_lan_iih, {
        "password": AUTH_PASSWORD})(w, start, dur_s)


def combo_auth_hello(w, start, dur_s=30) -> int:
    """认证 + Hello 定时器：R02 IIH 携带 auth TLV 且 holding/间隔变更。"""
    return _build_pair_emit(pdu.build_l2_lan_iih, {"password": AUTH_PASSWORD},
                            r02_holding=HELLO_FAULT_HOLDING,
                            r02_interval_us=HELLO_FAULT_INTERVAL_US)(w, start, dur_s)


def combo_mtu_area(w, start, dur_s=30) -> int:
    """MTU + 区域：R02 IIH padding 到 1399 且 area 改 49.0002。"""
    return _build_pair_emit(pdu.build_l2_lan_iih, {
        "target_total_pdu": MTU_PDU_FAULT, "area_bytes": WRONG_AREA},
        r01_kwargs={"target_total_pdu": MTU_PDU_NORMAL})(w, start, dur_s)


def combo_mtu_hello(w, start, dur_s=30) -> int:
    """MTU + Hello 定时器：R02 IIH padding 到 1399 且 holding/间隔变更。"""
    return _build_pair_emit(pdu.build_l2_lan_iih, {
        "target_total_pdu": MTU_PDU_FAULT},
        r01_kwargs={"target_total_pdu": MTU_PDU_NORMAL},
        r02_holding=HELLO_FAULT_HOLDING,
        r02_interval_us=HELLO_FAULT_INTERVAL_US)(w, start, dur_s)


def combo_mtu_circuit(w, start, dur_s=30) -> int:
    """MTU + 电路类型：R02 切换为 L1 IIH 且 padding 到 1399。"""
    return _build_pair_emit(pdu.build_l1_lan_iih, {
        "target_total_pdu": MTU_PDU_FAULT},
        r01_kwargs={"target_total_pdu": MTU_PDU_NORMAL})(w, start, dur_s)


def combo_circuit_area(w, start, dur_s=30) -> int:
    """电路类型 + 区域：R02 切换为 L1 IIH 且 area 改 49.0002。"""
    return _build_pair_emit(pdu.build_l1_lan_iih, {
        "area_bytes": WRONG_AREA})(w, start, dur_s)


def combo_hello_area(w, start, dur_s=30) -> int:
    """Hello 定时器 + 区域：R02 IIH holding/间隔变更且 area 改 49.0002。"""
    return _build_pair_emit(pdu.build_l2_lan_iih, {"area_bytes": WRONG_AREA},
                            r02_holding=HELLO_FAULT_HOLDING,
                            r02_interval_us=HELLO_FAULT_INTERVAL_US)(w, start, dur_s)


def combo_duplicate_auth(w, start, dur_s=30) -> int:
    """重复 System ID + 认证：R03 克隆 R02 的 system-id（fault 段出现），
    同时 R02 的 IIH 携带 auth TLV。"""
    from isis_simulator import isis_topology as topo
    horizon = start + dur_s * 1_000_000
    end = start
    DUP_SYSID = topo.sys_id_bytes(FAULT_PEER)
    layout = [
        (STAR_CENTER, 0, IIH_INTERVAL_US, {}),
        (FAULT_PEER,  IIH_INTERVAL_US // 2, IIH_INTERVAL_US,
         {"password": AUTH_PASSWORD}),
        (topo.DUPLICATE_NODE, IIH_INTERVAL_US // 3, IIH_INTERVAL_US,
         {"src_sysid": DUP_SYSID}),
    ]
    for n in BG_NODES:
        layout.append((n, IIH_INTERVAL_US * 2 // 3, BG_INTERVAL_US, {}))
    for node, off, interval, kw in layout:
        t = start + off
        while t < horizon:
            _emit_iih(w, t, node, DEFAULT_HOLDING, pdu.build_l2_lan_iih, kw,
                      dst_mac=L2_MULTICAST_MAC,
                      comment=f"combo dup+auth node={node}")
            end = max(end, t + interval)
            t += interval
    return max(end, horizon)


def combo_link_netem(w, start, dur_s=30) -> int:
    """链路断开 + 网络劣化：R02 完全静默（link down），
    同时对链路施加丢包/延迟（ICMP 探针高丢包高延迟）。"""
    import random
    rng = random.Random(42)
    horizon = start + dur_s * 1_000_000
    end = start
    # R01 受到劣化影响：~40% 丢包 + 400ms 延迟
    t = start
    while t < horizon:
        if rng.random() < 0.40:
            t += IIH_INTERVAL_US
            continue
        ts = t + 400_000 + rng.randint(-150_000, 150_000)
        _emit_iih(w, ts, STAR_CENTER, DEFAULT_HOLDING, pdu.build_l2_lan_iih, {},
                  dst_mac=L2_MULTICAST_MAC, comment="combo link+netem degraded R01")
        end = max(end, ts + IIH_INTERVAL_US)
        t += IIH_INTERVAL_US
    # ICMP 探针：R01 -> R02，40% 丢包、延迟 400ms±jitter
    for seq in range(15):
        req_ts = start + seq * 1_000_000
        if req_ts >= horizon:
            break
        req = pdu.build_icmp_echo(STAR_CENTER, FAULT_PEER, seq=seq)
        w.write_packet(req, req_ts, comment=f"combo link+netem icmp req seq={seq}")
        end = max(end, req_ts + 1_000_000)
        if rng.random() < 0.40:
            continue
        reply_ts = req_ts + 400_000 + rng.randint(0, 150_000)
        reply = pdu.build_icmp_echo_reply(FAULT_PEER, STAR_CENTER, seq=seq)
        w.write_packet(reply, reply_ts, comment=f"combo link+netem icmp reply seq={seq}")
        end = max(end, reply_ts + 1_000_000)
    return max(end, horizon)


# 复合场景登记表：与 generate.py SCENARIOS 对齐
COMBO_FAULTS = {
    "combo-auth-area":          ("auth_mismatch + area_mismatch", combo_auth_area),
    "combo-auth-mtu":           ("auth_mismatch + mtu_mismatch", combo_auth_mtu),
    "combo-auth-circuit":       ("auth_mismatch + circuit_type_mismatch", combo_auth_circuit),
    "combo-auth-hello":         ("auth_mismatch + hello_timer_mismatch", combo_auth_hello),
    "combo-mtu-area":           ("mtu_mismatch + area_mismatch", combo_mtu_area),
    "combo-mtu-hello":          ("mtu_mismatch + hello_timer_mismatch", combo_mtu_hello),
    "combo-mtu-circuit":        ("mtu_mismatch + circuit_type_mismatch", combo_mtu_circuit),
    "combo-circuit-area":       ("circuit_type_mismatch + area_mismatch", combo_circuit_area),
    "combo-hello-area":         ("hello_timer_mismatch + area_mismatch", combo_hello_area),
    "combo-duplicate-auth":     ("duplicate_system_id + auth_mismatch", combo_duplicate_auth),
    "combo-link-netem":         ("link_down + netem_loss_delay", combo_link_netem),
}


def run_combo(name: str, outpath: str = "pcapng/combo.pcap") -> tuple[str, int]:
    """按组合名生成一个复合故障 pcap（before 正常 → fault 叠加 → after 正常）。"""
    if name not in COMBO_FAULTS:
        raise ValueError(f"未知复合故障: {name}，可选: {sorted(COMBO_FAULTS)}")
    desc, emit_fault = COMBO_FAULTS[name]
    w = open_writer(outpath)
    t = segment_boundary(w, "before"); t = emit_normal_all(w, t, 30)
    t = segment_boundary(w, "fault");  t = emit_fault(w, t, 30)
    t = segment_boundary(w, "after");  t = emit_normal_all(w, t, 15)
    w.close()
    return outpath, w.packet_count


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="?", default="combo-auth-area")
    parser.add_argument("-o", "--output", default="pcapng/combo.pcap")
    args = parser.parse_args()
    print(run_combo(args.name, args.output))