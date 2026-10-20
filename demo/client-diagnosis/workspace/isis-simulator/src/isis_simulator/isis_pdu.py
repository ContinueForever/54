"""纯 bytes 的 IS-IS PDU 构造器。

按 ISO 10589 / RFC 1195 手工排版常见 TLV，覆盖文档 5.2 列出的解析字段：
source_id, pdu_type, holding_timer, circuit_type, area_address,
protocols_supported, authentication, hostname, lsp_id。

封装方式：Ethernet II + ethertype 0xFEFE + IS-IS PDU（PDU 首字节 0x83 即 NLPID，
既是协议鉴别符也是 demux 选择子，与 Ethertype 0xFEFE 复用）。
不依赖任何第三方库。
"""
from __future__ import annotations

import struct

from isis_simulator.isis_topology import (
    AREA_BYTES, sys_id_bytes, mac_bytes, hostname, lan_id,
    ip_to_bytes, LINK_IP,
    L2_MULTICAST_MAC, L1_MULTICAST_MAC, ETHERTYPE_ISO,
    STAR_CENTER, FAULT_PEER,
)


# ---------- PDU 类型码 ----------
PDU_L1_LAN_IIH = 0x11
PDU_L2_LAN_IIH = 0x12
PDU_P2P_IIH    = 0x13
PDU_L1_LSP     = 0x14
PDU_L2_LSP     = 0x15
PDU_L1_CSNP    = 0x18
PDU_L2_CSNP    = 0x19
PDU_L1_PSNP    = 0x1A
PDU_L2_PSNP    = 0x1B

# ---------- TLV 码 ----------
TLV_AREA_ADDR        = 1
TLV_PADDING          = 8
TLV_LSP_ENTRIES      = 9
TLV_AUTH             = 10
TLV_LSP              = 6   # IS reachability (老式, 兼用)
TLV_PROTOS_SUPPORTED = 129
TLV_IP_ADDR          = 132
TLV_HOSTNAME         = 137
TLV_EXT_IS_REACH     = 22
TLV_EXT_IP_REACH     = 135


# ---------- TLV 编码 ----------
def tlv(code: int, value: bytes) -> bytes:
    return struct.pack(">BB", code & 0xFF, len(value) & 0xFF) + value


def tlv_area(area_bytes: bytes = AREA_BYTES) -> bytes:
    """TLV 1：1 字节地址长度 + 地址字节。"""
    return tlv(TLV_AREA_ADDR, bytes((len(area_bytes),)) + area_bytes)


def tlv_protos_supported(nlpid_list=(0xCC,)) -> bytes:
    """129：支持的 NLPID。默认 IPv4(0xCC)；可加 CLNP(0x83)。"""
    return tlv(TLV_PROTOS_SUPPORTED, bytes(nlpid_list))


def tlv_ip_address(ip: str) -> bytes:
    return tlv(TLV_IP_ADDR, ip_to_bytes(ip))


def tlv_hostname(name: str) -> bytes:
    return tlv(TLV_HOSTNAME, name.encode("ascii"))


def tlv_auth_clear(password: str) -> bytes:
    """TLV 10：auth_type=1(clear text) + password。"""
    return tlv(TLV_AUTH, bytes((1,)) + password.encode("ascii"))


def tlv_padding(total_inner_len: int) -> bytes:
    """TLV 8：填充。total_inner_len 为 value 字节数（≥0）。"""
    assert total_inner_len >= 0
    out = b""
    remain = total_inner_len
    while remain > 0:
        chunk = min(remain, 255)
        out += tlv(TLV_PADDING, b"\x00" * chunk)
        remain -= chunk
    return out


# ---------- IS-IS 公共与 PDU 头 ----------
def _common_header(hdr_len: int, pdu_type: int, sys_id_len: int = 6) -> bytes:
    """8 字节公共头：discr 0x83 / hdr_len / ver 1 / sysid_len / pdu_type / ver2 1 / res 0 / max_area 3。"""
    return bytes((0x83, hdr_len, 0x01, sys_id_len, pdu_type & 0x1F, 0x01, 0x00, 0x03))


def _pdu_len_w(incl_common_hdr_len: int, tlv_bytes: bytes) -> int:
    """ISO IS-IS 的 PDU Length 字段表示“从 octet 1 起的整个 PDU 长度”。"""
    return incl_common_hdr_len + len(tlv_bytes)


# ---------- LAN IIH ----------
def build_l2_lan_iih(
    src_node: int,
    holding_timer: int,
    dr_node: int = STAR_CENTER,
    priority: int = 64,
    area_bytes: bytes | None = None,
    protocols_nlpids=(0xCC,),
    password: str | None = None,
    target_total_pdu: int | None = None,
    use_l1_multicast: bool = False,
    src_sysid: bytes | None = None,
) -> bytes:
    """构造 L2 LAN IIH（也可发 L1 类型电路用于 circuit-type-mismatch）。

    target_total_pdu：若指定，则用 TLV 8 把整个 PDU 填充到该总长度（含公共头 27 + TLV）。
    use_l1_multicast：选 L1 多播目的 MAC（用于 circuit-type-mismatch，但 PDU 仍是 L2? 
        真实“circuit_type”变化体现在 IIH 的 circuit_type 字段本身，本构造器已用 pdu_type=L2，
        此处用于兼容需要 L1 IIH 类型时再换）。
    """
    circuit_type = 0x02  # L2-only
    src_sysid = src_sysid if src_sysid is not None else sys_id_bytes(src_node)
    lan = lan_id(dr_node, 0)
    p_id = (priority & 0x3F) << 2

    body_tlv = b""
    body_tlv += tlv_area(area_bytes or AREA_BYTES)
    body_tlv += tlv_protos_supported(protocols_nlpids)
    body_tlv += tlv_ip_address(LINK_IP.get(src_node, f"10.0.{src_node}.1"))
    body_tlv += tlv_hostname(hostname(src_node))
    if password:
        body_tlv += tlv_auth_clear(password)

    # 公共头(8)+IIH 专属(19)=27
    hdr_len = 27
    pdu_len = _pdu_len_w(hdr_len, body_tlv)

    if target_total_pdu is not None and target_total_pdu > pdu_len:
        # 想让最终 PDU 长度 = target_total_pdu。需补 padding TLV；每个 TLV = 2 字节头 + 最多 255 字节值。
        # 27 + B0 + val_bytes + 2*n = target，n = ceil(val_bytes/255)。迭代求解。
        B0 = len(body_tlv)
        avail = target_total_pdu - 27 - B0
        n = max(1, avail // 257)
        # 收敛 n
        while True:
            val_bytes = avail - 2 * n
            if val_bytes < 0:
                n -= 1
                continue
            n_actual = (val_bytes + 254) // 255
            if n_actual == n:
                break
            n = n_actual
        body_tlv += tlv_padding(val_bytes)
        pdu_len = _pdu_len_w(hdr_len, body_tlv)

    # 组装：公共头 + IIH 专属字段
    out = _common_header(hdr_len, PDU_L2_LAN_IIH)
    out += bytes((circuit_type,))
    out += src_sysid
    out += struct.pack(">H", holding_timer)
    out += struct.pack(">H", pdu_len)
    out += bytes((p_id,))
    out += lan
    out += body_tlv
    return out


def build_l1_lan_iih(
    src_node: int,
    holding_timer: int,
    dr_node: int = STAR_CENTER,
    priority: int = 64,
    area_bytes: bytes | None = AREA_BYTES,
    protocols_nlpids=(0xCC,),
    password: str | None = None,
    target_total_pdu: int | None = None,
    src_sysid: bytes | None = None,
) -> bytes:
    """构造 L1 LAN IIH——仅用于 circuit-type-mismatch：对端把 is-type 切到 level-1。

    扩展支持 password / target_total_pdu / src_sysid，以便复合故障场景
    （如 circuit-type + auth / circuit-type + mtu）在 L1 IIH 上叠加多个故障特征。
    """
    circuit_type = 0x01
    src_sysid = src_sysid if src_sysid is not None else sys_id_bytes(src_node)
    lan = lan_id(dr_node, 0)
    p_id = (priority & 0x3F) << 2

    body_tlv = b""
    body_tlv += tlv_area(area_bytes)
    body_tlv += tlv_protos_supported(protocols_nlpids)
    body_tlv += tlv_ip_address(LINK_IP.get(src_node, f"10.0.{src_node}.1"))
    body_tlv += tlv_hostname(hostname(src_node))
    if password:
        body_tlv += tlv_auth_clear(password)

    hdr_len = 27
    pdu_len = _pdu_len_w(hdr_len, body_tlv)

    if target_total_pdu is not None and target_total_pdu > pdu_len:
        B0 = len(body_tlv)
        avail = target_total_pdu - 27 - B0
        n = max(1, avail // 257)
        while True:
            val_bytes = avail - 2 * n
            if val_bytes < 0:
                n -= 1
                continue
            n_actual = (val_bytes + 254) // 255
            if n_actual == n:
                break
            n = n_actual
        body_tlv += tlv_padding(val_bytes)
        pdu_len = _pdu_len_w(hdr_len, body_tlv)

    out = _common_header(hdr_len, PDU_L1_LAN_IIH)
    out += bytes((circuit_type,))
    out += src_sysid
    out += struct.pack(">H", holding_timer)
    out += struct.pack(">H", pdu_len)
    out += bytes((p_id,))
    out += lan
    out += body_tlv
    return out


# ---------- LSP ----------
def build_l2_lsp(
    src_node: int,
    sequence: int = 1,
    fragment: int = 0,
    pseudo_node: int = 0,
    lifetime: int = 1195,
    body_tlvs: bytes = b"",
    src_sysid: bytes | None = None,
) -> bytes:
    """构造 L2 LSP（最小可用：含 LSP ID / sequence / checksum 占位）。"""
    sysid = src_sysid if src_sysid is not None else sys_id_bytes(src_node)
    lsp_id = sysid + bytes((pseudo_node, fragment))

    hdr_len = 27  # common 8 + LSP-specific 19
    pdu_len = _pdu_len_w(hdr_len, body_tlvs)

    out = _common_header(hdr_len, PDU_L2_LSP)
    out += struct.pack(">H", pdu_len)
    out += struct.pack(">H", lifetime)
    out += lsp_id
    out += struct.pack(">I", sequence)
    out += struct.pack(">H", 0)        # checksum 占位（解析侧不强校验）
    out += bytes((0x00,))              # type block：P=0, ATT=0, OL=0
    out += body_tlvs
    return out


def lsp_ext_is_reach(neighbor_node: int, metric: int = 10) -> bytes:
    """TLV 22 Extended IS Reachability：单邻居最小项。
      value = sysid(6)+pseudo(1) + metric(3) + subtlv_len(1)=0
    """
    neigh = sys_id_bytes(neighbor_node) + bytes((0,))
    v = neigh + bytes((metric & 0xFF, (metric >> 8) & 0xFF, (metric >> 16) & 0xFF)) + bytes((0,))
    return tlv(TLV_EXT_IS_REACH, v + b"")  # 包外封装 code+len


def lsp_ext_ip_reach(prefix: str, prefix_len: int, metric: int = 10) -> bytes:
    """TLV 135 Extended IP Reachability：metric(3) + 1 byte(control+prefix_len) + prefix bytes。"""
    metric_b = bytes((metric & 0xFF, (metric >> 8) & 0xFF, (metric >> 16) & 0xFF))
    ctrl = bytes((prefix_len & 0x3F,))
    pix = ip_to_bytes(prefix)
    nbytes = (prefix_len + 7) // 8
    v = metric_b + ctrl + pix[:nbytes]
    return tlv(TLV_EXT_IP_REACH, v)


# ---------- 封装成完整以太网帧 ----------
def eth_iso_frame(src_node: int, dst_multicast_mac: bytes, isis_pdu: bytes) -> bytes:
    """dst 常为 L2 多播。src 为节点 MAC。"""
    eth = dst_multicast_mac + mac_bytes(src_node) + struct.pack(">H", ETHERTYPE_ISO) + isis_pdu
    # 以太最小帧长 60（不含 FCS），不足补 0
    if len(eth) < 60:
        eth += b"\x00" * (60 - len(eth))
    return eth


# ---------- ICMP（netem-loss-delay 用） ----------
def _ip_checksum(header: bytes) -> int:
    if len(header) % 2:
        header += b"\x00"
    s = 0
    for i in range(0, len(header), 2):
        s += (header[i] << 8) | header[i + 1]
    s = (s >> 16) + (s & 0xFFFF)
    s = (s >> 16) + (s & 0xFFFF)
    return (~s) & 0xFFFF


def build_icmp_echo(src_node: int, dst_node: int, seq: int, identifier: int = 0xBEEF,
                    payload: bytes = b"\x00" * 16, src_ip: str | None = None,
                    dst_ip: str | None = None) -> bytes:
    s_ip = src_ip or f"10.0.{src_node}.1"
    d_ip = dst_ip or f"10.0.{dst_node}.1"
    src_mac = mac_bytes(src_node)
    dst_mac = mac_bytes(dst_node)

    # ICMP
    icmp_type = 0x08  # echo request
    icmphdr = bytes((icmp_type, 0x00)) + struct.pack(">HH", identifier, seq) + payload
    cksum = _ip_checksum(icmphdr)
    icmphdr = icmphdr[:2] + struct.pack(">H", cksum) + icmphdr[4:]

    total_len = 20 + len(icmphdr)
    iphdr = struct.pack(">BBHHHBBH", 0x45, 0, total_len, 0, 0x40, 64, 1, 0) + ip_to_bytes(s_ip) + ip_to_bytes(d_ip)
    iphdr = iphdr[:10] + struct.pack(">H", _ip_checksum(iphdr)) + iphdr[12:]
    eth = dst_mac + src_mac + struct.pack(">H", 0x0800) + iphdr + icmphdr
    if len(eth) < 60:
        eth += b"\x00" * (60 - len(eth))
    return eth


def build_icmp_echo_reply(src_node: int, dst_node: int, seq: int, identifier: int = 0xBEEF,
                         payload: bytes = b"\x00" * 16, src_ip: str | None = None,
                         dst_ip: str | None = None) -> bytes:
    # 与 request 同路径，仅 type=0
    s_ip = src_ip or f"10.0.{src_node}.1"
    d_ip = dst_ip or f"10.0.{dst_node}.1"
    src_mac = mac_bytes(src_node)
    dst_mac = mac_bytes(dst_node)
    icmphdr = bytes((0x00, 0x00)) + struct.pack(">HH", identifier, seq) + payload
    cksum = _ip_checksum(icmphdr)
    icmphdr = icmphdr[:2] + struct.pack(">H", cksum) + icmphdr[4:]
    total_len = 20 + len(icmphdr)
    iphdr = struct.pack(">BBHHHBBH", 0x45, 0, total_len, 0, 0x40, 64, 1, 0) + ip_to_bytes(s_ip) + ip_to_bytes(d_ip)
    iphdr = iphdr[:10] + struct.pack(">H", _ip_checksum(iphdr)) + iphdr[12:]
    eth = dst_mac + src_mac + struct.pack(">H", 0x0800) + iphdr + icmphdr
    if len(eth) < 60:
        eth += b"\x00" * (60 - len(eth))
    return eth