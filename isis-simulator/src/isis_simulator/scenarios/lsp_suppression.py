"""lsp-suppression 场景：fault 段在 R02 焦点接口执行 no ip router isis CORE，
R02 不再在该接口发 IIH 也不发 LSP；R01 仍持续发 IIH/LSP。

预期命中：NEIGHBOR_LOSS_AT_FAULT + 状态机类告警。
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


def _lsp_body(me: int, neighbor: int) -> bytes:
    return pdu.lsp_ext_is_reach(neighbor) + pdu.lsp_ext_ip_reach("10.0.12.0", 24)


def emit_node_with_lsp(w, start, horizon, node, interval, holding, comment=""):
    """发 IIH + 在第一拍附带发 LSP。"""
    end = start
    t = start
    first = True
    while t < horizon:
        _emit_iih(w, t, node, holding, pdu.build_l2_lan_iih, {},
                  dst_mac=L2_MULTICAST_MAC, comment=comment)
        end = max(end, t + interval)
        if first:
            body = _lsp_body(node, STAR_CENTER if node != STAR_CENTER else FAULT_PEER)
            lsp = pdu.build_l2_lsp(node, sequence=1, body_tlvs=body)
            frame = pdu.eth_iso_frame(node, L2_MULTICAST_MAC, lsp)
            w.write_packet(frame, t + 100_000,
                           comment=f"lsp src=R{node:02d} {comment}".strip())
            end = max(end, t + interval)
            first = False
        t += interval
    return end


def emit_fault(w, start, dur_s=30) -> int:
    """R02 完全静默；R01 + 背景照常发包含 LSP。"""
    horizon = start + dur_s * 1_000_000
    end = start
    end = max(end, emit_node_with_lsp(w, start, horizon, STAR_CENTER, IIH_INTERVAL_US, DEFAULT_HOLDING))
    for n in BG_NODES:
        end = max(end, emit_node_with_lsp(w, start + IIH_INTERVAL_US * 2 // 3, horizon,
                                          n, BG_INTERVAL_US, DEFAULT_HOLDING,
                                          comment="bg"))
    return max(end, horizon)


def emit_normal_with_lsp(w, start, dur_s, holding=DEFAULT_HOLDING) -> int:
    horizon = start + dur_s * 1_000_000
    layout = [
        (STAR_CENTER, 0, IIH_INTERVAL_US),
        (FAULT_PEER, IIH_INTERVAL_US // 2, IIH_INTERVAL_US),
    ]
    for n in BG_NODES:
        layout.append((n, IIH_INTERVAL_US * 2 // 3, BG_INTERVAL_US))
    end = start
    for node, off, interval in layout:
        sub_end = emit_node_with_lsp(w, start + off, horizon, node, interval, holding)
        end = max(end, sub_end)
    return max(end, horizon)


def run(outpath="pcapng/lsp-suppression.pcap") -> tuple[str, int]:
    w = open_writer(outpath)
    t = segment_boundary(w, "before"); t = emit_normal_with_lsp(w, t, 30)
    t = segment_boundary(w, "fault");  t = emit_fault(w, t, 30)
    t = segment_boundary(w, "after");  t = emit_normal_with_lsp(w, t, 15)
    w.close()
    return outpath, w.packet_count


if __name__ == "__main__":
    print(run())