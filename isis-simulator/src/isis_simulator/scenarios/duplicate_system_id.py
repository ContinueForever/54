"""duplicate-system-id 场景：fault 段 R03 节点把自己的 NET 改成与 R02 相同的 system-id，
但保留 R03 自己的 MAC——即出现"同 system-id 不同源 MAC"的 IIH/LSP。

预期命中：DUPLICATE_NEIGHBOR_SYSTEM_ID，SOURCE_ID_MAC_CONFLICT。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from isis_simulator.scenario_lib import (
    open_writer, emit_normal_all, segment_boundary, _emit_iih,
    IIH_INTERVAL_US, BASE_TS_US, DEFAULT_HOLDING, BG_NODES, BG_INTERVAL_US,
)
from isis_simulator import isis_pdu as pdu
from isis_simulator import isis_topology as topo
from isis_simulator.isis_topology import STAR_CENTER, FAULT_PEER, L2_MULTICAST_MAC

DUP_NODE = topo.DUPLICATE_NODE   # R03 作为克隆源
DUP_SYSID = topo.sys_id_bytes(FAULT_PEER)  # 克隆目标接口的 system-id


def _lsp_body(me: int, neighbor: int) -> bytes:
    return pdu.lsp_ext_is_reach(neighbor) + pdu.lsp_ext_ip_reach("10.0.12.0", 24)


def emit_fault(w, start, dur_s=30) -> int:
    horizon = start + dur_s * 1_000_000
    end = start
    layout = [
        (STAR_CENTER, 0, IIH_INTERVAL_US, None, None),
        (FAULT_PEER,  IIH_INTERVAL_US // 2, IIH_INTERVAL_US, None, None),
        (DUP_NODE, IIH_INTERVAL_US // 3, IIH_INTERVAL_US, DUP_SYSID, "dup-R03-clone-of-R02"),
    ]
    for n in BG_NODES:
        layout.append((n, IIH_INTERVAL_US * 2 // 3, BG_INTERVAL_US, None, None))
    for node, off, interval, sysid, dup_tag in layout:
        t = start + off
        first = True
        while t < horizon:
            kw = {"src_sysid": sysid} if sysid else {}
            comment = dup_tag or ""
            _emit_iih(w, t, node, DEFAULT_HOLDING, pdu.build_l2_lan_iih, kw,
                      dst_mac=L2_MULTICAST_MAC, comment=comment)
            end = max(end, t + interval)
            if first:
                body = _lsp_body(node, STAR_CENTER)
                lsp_pdu = pdu.build_l2_lsp(node, sequence=1, body_tlvs=body,
                                            src_sysid=sysid if sysid else None)
                frame = pdu.eth_iso_frame(node, L2_MULTICAST_MAC, lsp_pdu)
                w.write_packet(frame, t + 100_000,
                               comment=f"lsp clone-R03 sysid=002".strip() if sysid else f"lsp R{node:02d}")
                end = max(end, t + interval)
                first = False
            t += interval
    return max(end, horizon)


def run(outpath="pcapng/duplicate-system-id.pcap") -> tuple[str, int]:
    w = open_writer(outpath)
    t = segment_boundary(w, "before"); t = emit_normal_all(w, t, 30)
    t = segment_boundary(w, "fault");  t = emit_fault(w, t, 30)
    t = segment_boundary(w, "after");  t = emit_normal_all(w, t, 15)
    w.close()
    return outpath, w.packet_count


if __name__ == "__main__":
    print(run())