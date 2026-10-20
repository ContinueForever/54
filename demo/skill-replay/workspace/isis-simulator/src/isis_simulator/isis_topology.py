"""66 节点 level-2-only 星拓扑身份表。

中心节点 R01 焦点链路对端固定为 R02（故障注入端）。所有节点统一 Area 49.0001，
system-id 形如 0000.0000.000X。本文件作为全项目唯一身份来源。
"""
from __future__ import annotations

STAR_CENTER = 1            # 中心节点编号（R01）
FAULT_PEER = 2             # 焦点链路对端 / 默认故障注入端（R02）
DUPLICATE_NODE = 3         # duplicate-system-id 场景中克隆 R02 身份的第三节点
NODE_COUNT = 66


def sys_id_bytes(node_no: int) -> bytes:
    """节点 system-id（6 字节），big-endian，形如 00:00:00:00:00:NN。"""
    return bytes((0, 0, 0, 0, 0, node_no))


def net_bytes(node_no: int) -> bytes:
    """完整 NET：Area(3) + SystemID(6) + NSEL(1)=00。"""
    return AREA_BYTES + sys_id_bytes(node_no) + b"\x00"


AREA_STR = "49.0001"
AREA_BYTES = bytes((0x49, 0x00, 0x01))   # 3 字节 area address


def hostname(node_no: int) -> str:
    return f"R{node_no:02d}"


def mac_bytes(node_no: int) -> bytes:
    """每节点一个固定单播 MAC，便于 duplicate-system-id 用不同 MAC + 相同 sysid 表达冲突。"""
    return bytes((0x00, 0x11, 0x22, 0x33, 0x44, node_no))


# L2 IS 多播目的 MAC（AllL2IS）
L2_MULTICAST_MAC = bytes((0x01, 0x80, 0xC2, 0x00, 0x00, 0x15))
# L1 IS 多播目的 MAC（AllL1IS）
L1_MULTICAST_MAC = bytes((0x01, 0x80, 0xC2, 0x00, 0x00, 0x14))

# ISO ethertype
ETHERTYPE_ISO = 0xFEFE
# IS-IS NLPID
NLPID_ISIS = 0x83


def lan_id(designated_no: int, pseudo: int = 0) -> bytes:
    """LAN ID = DR system-id(6) + pseudo(1)。"""
    return sys_id_bytes(designated_no) + bytes((pseudo,))


# 默认焦点链路两端节点的接口 IP（用于 ICMP 探测 / IP TLV）
LINK_IP = {
    STAR_CENTER: "10.0.12.1",
    FAULT_PEER:  "10.0.12.2",
}


def ip_to_bytes(ip: str) -> bytes:
    return bytes(int(o) for o in ip.split("."))


# 默认焦点链路节点对，便于场景脚本复用
FOCUS_LINK = (STAR_CENTER, FAULT_PEER)