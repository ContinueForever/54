"""前端演示服务，提供静态页面与数据 API。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

WORKSPACE = Path(os.environ.get("WORKSPACE", "/home/hermes/workspace"))

AGENT_SRC = WORKSPACE / "agent-analysis" / "src"
GRAPH_SRC = WORKSPACE / "graphrag" / "src"
KNOWLEDGE_SRC = WORKSPACE / "knowledge"
sys.path.insert(0, str(AGENT_SRC))
sys.path.insert(0, str(GRAPH_SRC))
sys.path.insert(0, str(KNOWLEDGE_SRC))

from agent_analysis.knowledge_adapter import KnowledgeAdapter

TABLES_DIR = WORKSPACE / "knowledge" / "tables"
adapter = KnowledgeAdapter(TABLES_DIR)
adapter.load()

REPORTS_DIR = WORKSPACE / "agent-analysis" / "output" / "reports"
TRACES_DIR = WORKSPACE / "agent-analysis" / "data" / "traces"
SEQ_DIR = WORKSPACE / "agent-analysis" / "output" / "sequence_diagrams"
WORKBENCH_DIR = WORKSPACE / "agent-analysis" / "output" / "workbenches"
ENV_PROJECT = WORKSPACE / "agent-analysis" / ".env.project"

SCENARIOS = [
    {"id": "link_down",            "label": "链路故障 (Link Down)"},
    {"id": "area_mismatch",        "label": "Area ID 不匹配"},
    {"id": "auth_mismatch",        "label": "认证不匹配"},
    {"id": "circuit_type_mismatch","label": "电路类型不匹配"},
    {"id": "hello_timer_mismatch", "label": "Hello 定时器不匹配"},
    {"id": "mtu_mismatch",         "label": "MTU 不匹配"},
    {"id": "netem_loss_delay",     "label": "网络损耗与延迟"},
    {"id": "lsp_suppression",      "label": "LSP 抑制"},
    {"id": "duplicate_system_id",  "label": "系统 ID 重复"},
    {"id": "baseline",             "label": "基准（正常）"},
]

_run_state: dict = {"running": False, "run_id": None, "scenario": None, "started": None, "error": None}
_run_lock = threading.Lock()


def _latest_file(directory: Path, pattern: str = "*"):
    if not directory.exists():
        return None
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def latest_trace():
    f = _latest_file(TRACES_DIR, "*.json")
    if not f:
        return None
    with open(f, "r", encoding="utf-8") as fh:
        return json.load(fh)


def latest_report():
    f = _latest_file(REPORTS_DIR, "*.md")
    return f.read_text(encoding="utf-8") if f else None


def latest_sequence_diagram():
    f = _latest_file(SEQ_DIR, "*.html")
    if f:
        return f"http://localhost:8080/api/seq/{f.stem}"
    return None


def trace_count():
    return len(list(TRACES_DIR.glob("*.json"))) if TRACES_DIR.exists() else 0


def report_count():
    return len(list(REPORTS_DIR.glob("*.md"))) if REPORTS_DIR.exists() else 0


def _load_env_project() -> dict:
    env = {}
    if ENV_PROJECT.exists():
        for line in ENV_PROJECT.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def llm_info():
    cfg = _load_env_project()
    provider = cfg.get("LLM_PROVIDER") or os.environ.get("LLM_PROVIDER", "kimi")
    if provider.lower() == "kimi":
        model = cfg.get("KIMI_MODEL_NAME") or os.environ.get("KIMI_MODEL_NAME", "kimi-k3")
        endpoint = cfg.get("KIMI_BASE_URL") or os.environ.get("KIMI_BASE_URL", "")
        env_vars = {
            "LLM_PROVIDER": "kimi",
            "KIMI_BASE_URL": "https://api.kimi.com/coding",
            "KIMI_API_KEY": "sk-***",
            "KIMI_MODEL_NAME": "kimi-k3",
        }
    else:
        model = cfg.get("DEFAULT_MODEL_NAME") or os.environ.get("DEFAULT_MODEL_NAME", "")
        endpoint = cfg.get("OPENAI_COMPATIBLE_CHAT_ENDPOINT") or os.environ.get("OPENAI_COMPATIBLE_CHAT_ENDPOINT", "")
        env_vars = {
            "LLM_PROVIDER": "openai",
            "DEFAULT_MODEL_NAME": model or "<model-name>",
            "OPENAI_COMPATIBLE_CHAT_ENDPOINT": "http://<host>:<port>/v1/chat/completions",
            "OPENAI_COMPATIBLE_CHAT_API_KEY": "<your-key>",
        }
    try:
        parsed = urlparse(endpoint)
        endpoint_display = f"{parsed.scheme}://{parsed.netloc}/..." if parsed.netloc else "-"
    except Exception:
        endpoint_display = "-"
    return {
        "provider": provider,
        "model": model,
        "endpoint": endpoint_display,
        "env_file": str(ENV_PROJECT.relative_to(WORKSPACE)),
        "env_vars": env_vars,
    }


def _do_run(scenario: str) -> None:
    env = os.environ.copy()
    env.update(_load_env_project())
    env["PYTHONPATH"] = ":".join([
        str(WORKSPACE / "agent-analysis/src"),
        str(WORKSPACE / "isis-simulator/src"),
        str(WORKSPACE / "graphrag/src"),
        str(WORKSPACE / "knowledge"),
    ])
    try:
        subprocess.run(
            [sys.executable, str(WORKSPACE / "scripts" / "generate_and_analyze.py"), scenario],
            cwd=str(WORKSPACE),
            env=env,
            check=True,
            capture_output=True,
        )
        with _run_lock:
            _run_state["running"] = False
            _run_state["error"] = None
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", errors="replace")[-800:] if e.stderr else str(e)
        with _run_lock:
            _run_state["running"] = False
            _run_state["error"] = err


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status, text, content_type="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path):
        if path == "/" or path == "/index.html":
            workbench = WORKSPACE / "frontend" / "workbench.html"
            p = workbench if workbench.exists() else WORKSPACE / "frontend" / "index.html"
        elif path in ("/workbench", "/workbench.html"):
            p = WORKSPACE / "frontend" / "workbench.html"
        elif path == "/legacy":
            p = WORKSPACE / "frontend" / "index.html"
        else:
            p = WORKSPACE / "frontend" / path.lstrip("/")
        if not p.exists() or p.is_dir():
            self.send_error(404)
            return
        content = p.read_bytes()
        self.send_response(200)
        if p.suffix == ".html":
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif p.suffix == ".css":
            self.send_header("Content-Type", "text/css")
        elif p.suffix == ".js":
            self.send_header("Content-Type", "application/javascript")
        else:
            self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            if path == "/api/workbench":
                record = _latest_file(WORKBENCH_DIR, "*.json")
                if record:
                    self._send_json(200, json.loads(record.read_text(encoding="utf-8")))
                else:
                    self._send_json(404, {"error": "尚无已保存的诊断任务工作台"})
            elif path == "/api/latest":
                self._send_json(200, {
                    "kg_nodes": len(adapter.nodes),
                    "kg_edges": len(adapter.edges),
                    "trace_count": trace_count(),
                    "report_count": report_count(),
                    "latest": latest_trace(),
                    "report": latest_report(),
                    "sequence_diagram": latest_sequence_diagram(),
                    "llm_info": llm_info(),
                })
            elif path == "/api/config":
                self._send_json(200, {
                    "llm_info": llm_info(),
                    "workspace": str(WORKSPACE),
                    "reports_dir": str(REPORTS_DIR),
                    "traces_dir": str(TRACES_DIR),
                })
            elif path == "/api/health":
                self._send_json(200, {"status": "ok", "time": datetime.now().isoformat(), "llm_info": llm_info()})
            elif path == "/api/scenarios":
                self._send_json(200, {"scenarios": SCENARIOS})
            elif path == "/api/run-status":
                with _run_lock:
                    self._send_json(200, dict(_run_state))
            elif path == "/api/traces":
                traces = []
                if TRACES_DIR.exists():
                    for f in sorted(TRACES_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
                        try:
                            data = json.loads(f.read_text(encoding="utf-8"))
                            traces.append({
                                "id": f.stem,
                                "time": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                                "anomalies": [a.get("type", "") for a in data.get("anomalies", [])],
                                "has_report": (REPORTS_DIR / f"{f.stem}.md").exists(),
                                "status": "异常" if data.get("anomalies") else "正常",
                            })
                        except Exception:
                            traces.append({"id": f.stem, "time": "-", "anomalies": [], "has_report": False, "status": "-"})
                self._send_json(200, {"traces": traces})
            elif path == "/api/reports":
                files = [f.name for f in sorted(REPORTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)] if REPORTS_DIR.exists() else []
                self._send_json(200, {"reports": files})
            elif path == "/api/graph":
                # 返回知识图谱网络数据
                nodes = [{"id": k, "label": v.get("name", k), "type": v.get("node_type", "unknown")}
                         for k, v in adapter.nodes.items()]
                edges = [{"source": e.get("source_id"), "target": e.get("target_id"),
                          "relation": e.get("relation", "")} for e in adapter.edges]
                self._send_json(200, {"nodes": nodes, "edges": edges})
            elif path == "/api/graphrag-status":
                # 检查 GraphRAG 索引状态
                graphrag_output = WORKSPACE / "graphrag" / "output"
                required_files = [
                    "entities.parquet",
                    "relationships.parquet",
                    "communities.parquet",
                    "text_units.parquet",
                ]
                existing = [f for f in required_files if (graphrag_output / f).exists()]
                lancedb_exists = (graphrag_output / "lancedb").exists()
                indexed = len(existing) == len(required_files)
                # 尝试连接 GraphRAG 服务
                service_up = False
                try:
                    import urllib.request
                    resp = urllib.request.urlopen("http://localhost:9200/health", timeout=2)
                    if resp.status == 200:
                        service_up = True
                        svc_data = json.loads(resp.read().decode())
                    else:
                        svc_data = {}
                except Exception:
                    svc_data = {}
                self._send_json(200, {
                    "indexed": indexed,
                    "index_files": existing,
                    "index_files_required": required_files,
                    "lancedb_ready": lancedb_exists,
                    "service_running": service_up,
                    "service_detail": svc_data,
                    "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
                    "provider": "openrouter",
                })
            elif path.startswith("/api/seq/"):
                seq_name = path.split("/")[-1]
                f = SEQ_DIR / f"{seq_name}.html"
                if f.exists():
                    self._send_text(200, f.read_text(encoding="utf-8"), "text/html; charset=utf-8")
                else:
                    self._send_json(404, {"error": "sequence diagram not found"})
            else:
                self._send_json(404, {"error": "not found"})
        else:
            self._send_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return
        if path == "/api/query":
            query = payload.get("query", "")
            results = adapter.query_by_name(query)
            self._send_json(200, {"query": query, "hits": len(results), "results": results})
        elif path == "/api/run":
            scenario = payload.get("scenario", "link_down")
            valid_ids = {s["id"] for s in SCENARIOS}
            if scenario not in valid_ids:
                self._send_json(400, {"error": f"unknown scenario: {scenario}"})
                return
            with _run_lock:
                if _run_state["running"]:
                    self._send_json(409, {"error": "already running", "run_id": _run_state["run_id"]})
                    return
                run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                _run_state.update({"running": True, "run_id": run_id, "scenario": scenario,
                                   "started": datetime.now().isoformat(), "error": None})
            t = threading.Thread(target=_do_run, args=(scenario,), daemon=True)
            t.start()
            self._send_json(200, {"started": True, "run_id": run_id, "scenario": scenario})
        else:
            self._send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def run(host="0.0.0.0", port=8080):
    server = HTTPServer((host, port), DemoHandler)
    print(f"[frontend] http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    run(args.host, args.port)


if __name__ == "__main__":
    main()
