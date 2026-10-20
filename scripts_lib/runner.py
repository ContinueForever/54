#!/usr/bin/env python3
"""共享工作流工具模块。

被 workspace-orchestrator 和 knowledge-builder 共同使用，
集中管理 PYTHONPATH、目录路径、环境变量、以及通用子进程执行。
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

SOURCE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ.get("WORKSPACE", SOURCE_ROOT)).resolve()
GRAPHRAG_VENV = WORKSPACE / "graphrag" / ".venv" / "bin" / "python"


def graphrag_python() -> str:
    """微软 GraphRAG 依赖安装于 graphrag/.venv，优先使用该解释器。"""
    if os.environ.get("GRAPHRAG_PYTHON"):
        return os.environ["GRAPHRAG_PYTHON"]
    if GRAPHRAG_VENV.exists():
        return str(GRAPHRAG_VENV)
    return sys.executable


def pythonpath_env(extra: Optional[List[Path]] = None) -> Dict[str, str]:
    """返回统一的环境变量，包含所有 src 目录。"""
    paths = [
        WORKSPACE / "agent-analysis/src",
        WORKSPACE / "isis-simulator/src",
        WORKSPACE / "graphrag/src",
        WORKSPACE / "knowledge",
    ]
    if extra:
        paths.extend(extra)
    env = os.environ.copy()
    env["WORKSPACE"] = str(WORKSPACE)
    env["PYTHONPATH"] = ":".join(str(p) for p in paths)
    env.setdefault("GRAPHRAG_HOST", "localhost")
    env.setdefault("GRAPHRAG_PORT", "9200")
    return env


def run(cmd: List[str], cwd: Optional[Path] = None, check: bool = True, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """执行子进程命令，打印命令并返回结果。"""
    print(f"[RUN] {' '.join(cmd)} (cwd={cwd or WORKSPACE})", flush=True)
    return subprocess.run(cmd, cwd=str(cwd or WORKSPACE), env=env or pythonpath_env(), check=check, text=True)


def run_popen(cmd: List[str], cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None) -> subprocess.Popen:
    """启动后台子进程。"""
    print(f"[BG]  {' '.join(cmd)} (cwd={cwd or WORKSPACE})")
    return subprocess.Popen(
        cmd,
        cwd=str(cwd or WORKSPACE),
        env=env or pythonpath_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_for_service(host: str, port: int, timeout: int = 10) -> bool:
    """等待 HTTP 服务就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            import http.client
            c = http.client.HTTPConnection(host, port, timeout=1)
            c.request("GET", "/health")
            if c.getresponse().status == 200:
                c.close()
                return True
            c.close()
        except Exception:
            pass
        time.sleep(0.2)
    return False


def generate_isis_scenario(scenario: Optional[str], output_dir: Path) -> None:
    """生成 IS-IS 仿真数据。"""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "isis_simulator"]
    if scenario:
        cmd.append(scenario)
    cmd.extend(["--output", str(output_dir)])
    run(cmd, cwd=WORKSPACE / "isis-simulator")


def prepare_analysis_input(source_dir: Path, run_id: str) -> Path:
    """把 pcap/log 从仿真输出目录复制到 agent-analysis 输入目录。"""
    pcap_dir = source_dir / "pcapng"
    logs_dir = source_dir / "logs"
    input_dir = WORKSPACE / "agent-analysis" / "data" / "incoming" / run_id
    input_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for f in pcap_dir.glob("*.pcap"):
        shutil.copy2(f, input_dir / f.name)
        copied += 1
    for f in logs_dir.glob("*.log"):
        shutil.copy2(f, input_dir / f.name)
        copied += 1
    # Optional collected observations; exclude generator metadata and answers.
    state_file = source_dir / "network-state.json"
    if state_file.exists():
        shutil.copy2(state_file, input_dir / state_file.name)
        copied += 1
    print(f"[COPY] {copied} files to {input_dir}")
    return input_dir


def run_analysis(input_dir: Path) -> Path:
    """运行分析引擎。"""
    cmd = [sys.executable, "-m", "agent_analysis", "--input", str(input_dir)]
    run(cmd, cwd=WORKSPACE / "agent-analysis")
    reports = sorted((WORKSPACE / "agent-analysis" / "output" / "reports").glob("*.md"), reverse=True)
    return reports[0] if reports else None


def read_latest_report() -> Optional[Path]:
    """读取最新生成的报告。"""
    reports_dir = WORKSPACE / "agent-analysis" / "output" / "reports"
    if not reports_dir.exists():
        return None
    reports = sorted(reports_dir.glob("*.md"), reverse=True)
    return reports[0] if reports else None


def read_latest_trace() -> Optional[Dict]:
    """读取最新生成的 trace json。"""
    traces_dir = WORKSPACE / "agent-analysis" / "data" / "traces"
    if not traces_dir.exists():
        return None
    files = sorted(traces_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def load_knowledge_tables() -> Dict:
    """加载 knowledge/tables/*.csv。"""
    tables_dir = WORKSPACE / "knowledge" / "tables"
    result = {"nodes": [], "edges": []}
    nodes_path = tables_dir / "nodes.csv"
    edges_path = tables_dir / "edges.csv"
    if nodes_path.exists():
        with open(nodes_path, "r", encoding="utf-8") as f:
            result["nodes"] = list(csv.DictReader(f))
    if edges_path.exists():
        with open(edges_path, "r", encoding="utf-8") as f:
            result["edges"] = list(csv.DictReader(f))
    return result


def build_graphrag_input() -> None:
    """生成 GraphRAG 输入文本。"""
    cmd = [sys.executable, str(SOURCE_ROOT / "knowledge/scripts/build_graphrag_input.py")]
    run(cmd)


def validate_knowledge(checks: str = "A,B,C,D,E,F", graphrag_url: str = "",
                       sample: int = 10, json_output: bool = False) -> None:
    """校验正式知识库；CRITICAL 通过非零退出码阻止后续流程。"""
    cmd = [sys.executable, str(SOURCE_ROOT / "skills/kg-validator/run.py"),
           "--checks", checks, "--graphrag-url", graphrag_url, "--sample", str(sample)]
    if json_output:
        cmd.append("--json")
        subprocess.run(cmd, cwd=WORKSPACE, env=pythonpath_env(), check=True)
    else:
        run(cmd)


def run_material_to_csv(arguments: List[str]) -> None:
    """在统一项目环境中调用素材提取、差异审阅或合并。"""
    run([sys.executable, str(SOURCE_ROOT / "skills/material-to-csv/run.py"), *arguments])


def build_knowledge_graph() -> None:
    """构建本地图谱；构建入口负责自动验证。"""
    run([sys.executable, str(SOURCE_ROOT / "knowledge/scripts/build.py")])


def build_graphrag_index() -> None:
    """构建 GraphRAG 索引。"""
    validate_knowledge()
    build_graphrag_input()
    cmd = [graphrag_python(), "-m", "graphrag_server.indexer"]
    run(cmd, cwd=WORKSPACE / "graphrag", env=pythonpath_env())
    restart_graphrag_service_if_running()


def restart_graphrag_service_if_running():
    """indexer 重建索引后，若 systemd 常驻服务正在运行则重启之，
    以保证运行中的向量化器（tfidf_vectorizer.pkl）与索引一致。"""
    try:
        import subprocess
        check = subprocess.run(
            ["systemctl", "--user", "is-active", "isis-graphrag.service"],
            capture_output=True, text=True, timeout=5)
        if check.returncode != 0 or check.stdout.strip() != "active":
            print("[INFO] isis-graphrag.service 未运行，跳过重启")
            return
        print("[INFO] 检测到 isis-graphrag.service 运行中，索引已重建，执行重启...")
        result = subprocess.run(
            ["systemctl", "--user", "restart", "isis-graphrag.service"],
            capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print("[OK] isis-graphrag.service 已重启，新索引已加载")
        else:
            print(f"[WARN] isis-graphrag.service 重启失败: {result.stderr.strip()}")
    except FileNotFoundError:
        print("[INFO] systemctl 不可用（非 systemd 环境），跳过自动重启")
    except Exception as e:
        print(f"[WARN] 重启 isis-graphrag.service 失败: {e}")



def start_graphrag_server(port: int = 9200) -> subprocess.Popen:
    """启动 GraphRAG 服务。

    若 9200 端口已有健康实例（systemd 常驻服务等），直接复用并返回哨兵对象
    （复用对象无 terminate 副作用，避免端口冲突与假健康）。
    """
    env = pythonpath_env()
    env["GRAPHRAG_ENABLED"] = "true"
    if wait_for_service("localhost", port, timeout=2):
        print(f"[INFO] GraphRAG 服务已在 {port} 端口运行，直接复用")
        return _ExistingProcess(port)
    proc = run_popen([graphrag_python(), "-m", "graphrag_server.server", "--port", str(port)],
                     cwd=WORKSPACE / "graphrag", env=env)
    if not wait_for_service("localhost", port, timeout=10):
        print(f"[WARN] GraphRAG 服务在 {port} 端口未就绪，可能索引缺失或端口占用")
    return proc


class _ExistingProcess:
    """已存在服务进程的哨兵包装，兼容 subprocess.Popen 接口的常用调用。"""

    def __init__(self, port: int):
        self.port = port

    def poll(self):
        return 0 if wait_for_service("localhost", self.port, timeout=1) else 1

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def start_frontend(port: int = 8080) -> subprocess.Popen:
    """启动前端演示服务。"""
    env = pythonpath_env()
    env["PYTHONPATH"] += ":" + str(WORKSPACE / "frontend")
    return run_popen([sys.executable, str(WORKSPACE / "frontend" / "server.py"), "--port", str(port)],
                     cwd=WORKSPACE, env=env)


def make_run_id() -> str:
    return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
