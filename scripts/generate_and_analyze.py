#!/usr/bin/env python3
"""轻量无头工作流：生成 IS-IS 数据并运行分析（不启动 GraphRAG 服务）。

用途：
- 开发调试：快速生成一个场景并跑一遍分析
- 定时任务：配合 cron 做无头演示（不启动长期服务）

注意：本脚本不会构建或启动 GraphRAG 服务。
若需要知识图谱构建或 GraphRAG 查询，请使用 knowledge-builder skill 或
手动启动 graphrag_server.server。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path("/home/hermes/workspace")


def set_pythonpath():
    paths = [
        WORKSPACE / "agent-analysis/src",
        WORKSPACE / "isis-simulator/src",
        WORKSPACE / "graphrag/src",
        WORKSPACE / "knowledge",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = ":".join(str(p) for p in paths)
    env["GRAPHRAG_ENABLED"] = "false"  # 轻量脚本不依赖 GraphRAG 服务
    return env


def main():
    parser = argparse.ArgumentParser(description="生成 IS-IS 数据并运行分析（无 GraphRAG）")
    parser.add_argument("scenario", nargs="?", default=None, help="指定场景")
    parser.add_argument("--output", default=None, help="输出目录")
    args = parser.parse_args()

    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir = Path(args.output) if args.output else WORKSPACE / "isis-simulator" / "output" / run_id

    cmd = [sys.executable, "-m", "isis_simulator"]
    if args.scenario:
        cmd.append(args.scenario)
    cmd.extend(["--output", str(output_dir)])
    print(f"[RUN] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=WORKSPACE / "isis-simulator", env=set_pythonpath(), check=True)

    input_dir = WORKSPACE / "agent-analysis" / "data" / "incoming" / run_id
    input_dir.mkdir(parents=True, exist_ok=True)
    for f in (output_dir / "pcapng").glob("*.pcap"):
        shutil.copy2(f, input_dir / f.name)
    for f in (output_dir / "logs").glob("*.log"):
        shutil.copy2(f, input_dir / f.name)
    print(f"[COPY] 数据已复制到 {input_dir}")

    cmd = [sys.executable, "-m", "agent_analysis", "--input", str(input_dir)]
    print(f"[RUN] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=WORKSPACE / "agent-analysis", env=set_pythonpath(), check=True)
    print(f"[DONE] 分析完成，输入目录: {input_dir}")
    print("[INFO] 如需构建知识图谱或启动 GraphRAG，请使用 knowledge-builder skill")


if __name__ == "__main__":
    main()
