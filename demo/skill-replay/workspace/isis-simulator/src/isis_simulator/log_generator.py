
"""模拟网络设备侧 IS-IS 日志生成器。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def _ts(base_iso: str, offset_s: float) -> str:
    dt = datetime.fromisoformat(base_iso).replace(tzinfo=timezone.utc)
    dt = dt.fromtimestamp(dt.timestamp() + offset_s, tz=timezone.utc)
    return dt.strftime("%b %d %H:%M:%S")


class DeviceLog:
    """按场景生成 syslog / IS-IS 事件日志。"""

    def __init__(self, scenario: str, node: str = "R02", base_time_iso: str = "2024-01-01T00:00:00"):
        self.scenario = scenario
        self.node = node
        self.base = base_time_iso
        self.lines: list[str] = []

    def emit(self, offset_s: float, facility: str, msg: str):
        prefix = _ts(self.base, offset_s)
        self.lines.append(f"{prefix} {self.node} {facility}: {msg}")

    def baseline(self):
        self.emit(5, "ISIS", "Adjacency to R01 (Gig0/0/0) is UP")
        self.emit(10, "ISIS", "LSP flooding complete")

    def area_mismatch(self):
        self.emit(42, "ISIS", "IIH from R01 on Gig0/0/0 area mismatch")
        self.emit(43, "ISIS", "Possible duplicate system ID or area misconfiguration")

    def auth_mismatch(self):
        self.emit(42, "ISIS", "Authentication failed for IIH on Gig0/0/0 from R01")
        self.emit(45, "ISIS", "Adjacency to R01 (Gig0/0/0) going Down")

    def circuit_type_mismatch(self):
        self.emit(42, "ISIS", "Received L1 IIH on L2-only circuit from R01")
        self.emit(44, "ISIS", "Circuit type mismatch on Gig0/0/0")

    def link_down(self):
        self.emit(40, "IFNET", "Interface Gig0/0/0 is Down")
        self.emit(41, "ISIS", "Adjacency to R01 (Gig0/0/0) is Down")

    def hello_timer_mismatch(self):
        self.emit(42, "ISIS", "Holding timer mismatch with R01 on Gig0/0/0")
        self.emit(43, "ISIS", "Adjacency to R01 (Gig0/0/0) is Down")

    def netem_loss_delay(self):
        self.emit(45, "PING", "Ping to 10.0.12.1: 25% packet loss")
        self.emit(50, "PING", "Ping to 10.0.12.1: 40% packet loss")

    def mtu_mismatch(self):
        self.emit(42, "ISIS", "MTU mismatch detected on Gig0/0/0 (1492 vs 1500)")
        self.emit(44, "ISIS", "Adjacency to R01 (Gig0/0/0) is Down")

    def lsp_suppression(self):
        self.emit(40, "ISIS", "LSP suppression enabled on Gig0/0/0")
        self.emit(42, "ISIS", "Adjacency to R01 (Gig0/0/0) is Down")

    def duplicate_system_id(self):
        self.emit(42, "ISIS", "Duplicate System-ID 0000.0000.0002 detected on Gig0/0/0")
        self.emit(43, "ISIS", "Interface Gig0/0/0 flapping")

    def build(self) -> list[str]:
        # 复合故障：scenario 名为 combo-A-B，合并两个子场景的日志事件
        if self.scenario.startswith("combo-"):
            return self._build_combo()
        handler = getattr(self, self.scenario, self.baseline)
        handler()
        return self.lines

    def _build_combo(self) -> list[str]:
        """复合故障日志：依次调用两个子故障的事件序列。"""
        # combo 场景名 -> 子故障 log 方法名
        ALIAS = {
            "auth": "auth_mismatch",
            "area": "area_mismatch",
            "mtu": "mtu_mismatch",
            "hello": "hello_timer_mismatch",
            "circuit": "circuit_type_mismatch",
            "duplicate": "duplicate_system_id",
            "link": "link_down",
            "netem": "netem_loss_delay",
        }
        parts = [p for p in self.scenario.split("-") if p != "combo"]
        if len(parts) != 2:
            raise ValueError(f"复合场景命名无效: {self.scenario}，应为 combo-A-B")
        sub1, sub2 = ALIAS.get(parts[0]), ALIAS.get(parts[1])
        if not sub1 or not sub2:
            raise ValueError(f"复合场景未知子故障: {self.scenario}")
        for sub in (sub1, sub2):
            handler = getattr(self, sub, None)
            if handler:
                handler()
            else:
                raise ValueError(f"缺少子故障日志方法: {sub}")
        return self.lines

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(self.build()) + "\n", encoding="utf-8")
        return p


def generate_for_scenario(scenario: str, output_dir: str | Path, node: str = "R02") -> Path:
    log = DeviceLog(scenario, node=node)
    return log.write(Path(output_dir) / f"{scenario}.log")
