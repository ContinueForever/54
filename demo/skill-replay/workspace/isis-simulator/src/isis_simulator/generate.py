#!/usr/bin/env python3
"""统一生成入口：pcap + 设备日志。"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

from isis_simulator.log_generator import generate_for_scenario

SCENARIOS = [
    ("baseline", "baseline.pcap"),
    ("area_mismatch", "area-mismatch.pcap"),
    ("auth_mismatch", "auth-mismatch.pcap"),
    ("circuit_type_mismatch", "circuit-type-mismatch.pcap"),
    ("link_down", "link-down.pcap"),
    ("hello_timer_mismatch", "hello-timer-mismatch.pcap"),
    ("netem_loss_delay", "netem-loss-delay.pcap"),
    ("mtu_mismatch", "mtu-mismatch.pcap"),
    ("lsp_suppression", "lsp-suppression.pcap"),
    ("duplicate_system_id", "duplicate-system-id.pcap"),
]

# 复合故障：两个单故障叠加在同一个 fault 窗口
COMBO_SCENARIOS = [
    ("combo-auth-area", "combo-auth-area.pcap"),
    ("combo-auth-mtu", "combo-auth-mtu.pcap"),
    ("combo-auth-circuit", "combo-auth-circuit.pcap"),
    ("combo-auth-hello", "combo-auth-hello.pcap"),
    ("combo-mtu-area", "combo-mtu-area.pcap"),
    ("combo-mtu-hello", "combo-mtu-hello.pcap"),
    ("combo-mtu-circuit", "combo-mtu-circuit.pcap"),
    ("combo-circuit-area", "combo-circuit-area.pcap"),
    ("combo-hello-area", "combo-hello-area.pcap"),
    ("combo-duplicate-auth", "combo-duplicate-auth.pcap"),
    ("combo-link-netem", "combo-link-netem.pcap"),
]


def run_all(selected: list[str] | None = None, output_dir: str | Path = "output"):
    output_dir = Path(output_dir)
    pcap_dir = output_dir / "pcapng"
    logs_dir = output_dir / "logs"
    pcap_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    names = selected if selected else [s[0] for s in SCENARIOS] + [s[0] for s in COMBO_SCENARIOS]
    results = []
    for mod_name, outname in SCENARIOS + COMBO_SCENARIOS:
        if mod_name not in names:
            continue
        pcap_path = pcap_dir / outname
        if mod_name.startswith("combo-"):
            from isis_simulator.scenarios.combo_lib import run_combo
            path, n = run_combo(mod_name, str(pcap_path))
        else:
            mod = importlib.import_module(f"isis_simulator.scenarios.{mod_name}")
            path, n = mod.run(str(pcap_path))
        log_path = generate_for_scenario(mod_name, logs_dir)
        print(f"[OK] {mod_name:24s} -> {pcap_path.name} pkt={n}, log={log_path.name}")
        results.append((mod_name, n, str(pcap_path), str(log_path)))
    return results


def main():
    parser = argparse.ArgumentParser(description="生成 IS-IS 场景数据")
    parser.add_argument("scenarios", nargs="*", help="指定场景，缺省生成全部")
    parser.add_argument("-o", "--output", default="pcapng", help="输出目录")
    args = parser.parse_args()
    selected = []
    for s in (args.scenarios or []):
        if s.startswith("combo-"):
            selected.append(s)  # 复合场景名保留连字符
        else:
            selected.append(s.replace("-", "_"))
    run_all(selected or None, args.output)


if __name__ == "__main__":
    main()
