"""
执行追踪器 — 记录分析全过程，生成时序流程图

追踪记录格式：
{
  "trace_id": "run_20250602_143052",
  "start_time": "...",
  "end_time": "...",
  "steps": [
    {"seq": 1, "timestamp": "...", "layer": "L1", "action": "...", "status": "PASS/FAIL/DONE"}
  ]
}
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Dict, List, Optional, Any


class Tracer:
    """执行追踪器"""

    def __init__(self, traces_dir: Path):
        self.traces_dir = Path(traces_dir)
        self.traces_dir.mkdir(parents=True, exist_ok=True)

        self.trace_id: Optional[str] = None
        self.start_time: Optional[str] = None
        self.end_time: Optional[str] = None
        self.steps: List[Dict] = []
        self.errors: List[str] = []

    def start(self, trace_id: str):
        """开始新的追踪记录"""
        self.trace_id = trace_id
        self.start_time = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        self.steps = []
        self.errors = []

    def record_step(
        self,
        layer: str,
        action: str,
        status: str,
        detail: str = "",
        anomaly_id: str = "",
        duration_ms: int = 0,
    ):
        """记录一个步骤"""
        step = {
            "seq": len(self.steps) + 1,
            "timestamp": datetime.now(ZoneInfo('Asia/Shanghai')).strftime("%H:%M:%S.%f")[:-3],
            "layer": layer,
            "action": action,
            "status": status,
            "detail": detail,
        }
        if anomaly_id:
            step["anomaly_id"] = anomaly_id
        if duration_ms:
            step["duration_ms"] = duration_ms

        self.steps.append(step)

    def record_error(self, error: str):
        """记录错误"""
        self.errors.append({
            "timestamp": datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            "error": error,
        })

    def finish(self):
        """完成追踪记录并保存"""
        self.end_time = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()

        trace_data = {
            "trace_id": self.trace_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "steps": self.steps,
            "errors": self.errors,
            "conclusion": self._build_conclusion(),
        }

        # 保存 JSON
        trace_file = self.traces_dir / f"{self.trace_id}.json"
        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(trace_data, f, ensure_ascii=False, indent=2)

        # 自动生成时序图
        seq_dir = self.traces_dir.parent.parent / "output" / "sequence_diagrams"
        self.save_sequence_diagram(seq_dir, trace_data)

    def save_sequence_diagram(self, output_dir: Path, trace_data: Optional[Dict] = None) -> Path:
        """保存时序图 HTML 到指定目录。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        html = self.generate_mermaid_html(trace_data)
        path = output_dir / f"{self.trace_id}.html"
        path.write_text(html, encoding="utf-8")
        return path

    def _build_conclusion(self) -> Dict:
        """构建结论摘要"""
        fail_steps = [s for s in self.steps if s["status"] == "FAIL"]

        if not fail_steps:
            return {
                "status": "normal",
                "fault_layer": None,
                "fault_type": None,
                "affected_nodes": [],
                "severity": "none",
                "recommended_action": "无异常，无需操作",
            }

        # 取第一个失败的层级作为主要故障层
        first_fail = fail_steps[0]
        return {
            "status": "anomaly_detected",
            "fault_layer": first_fail["layer"],
            "fault_type": first_fail.get("anomaly_id", "unknown"),
            "affected_nodes": [],
            "severity": "critical" if any(
                s.get("anomaly_id", "").startswith("L3") for s in fail_steps
            ) else "warning",
            "recommended_action": "查看详细报告和时序流程图",
        }

    def generate_mermaid_html(self, trace_data: Optional[Dict] = None) -> str:
        """生成离线可用的 Mermaid 时序流程图 HTML。"""
        if trace_data:
            self.trace_id = trace_data.get("trace_id", self.trace_id)
            self.start_time = trace_data.get("start_time", self.start_time)
            self.end_time = trace_data.get("end_time", self.end_time)
            self.steps = trace_data.get("steps", self.steps)
            self.errors = trace_data.get("errors", self.errors)

        mermaid_code = self._generate_mermaid_code()

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>分析流程图 - {self.trace_id}</title>
    <!-- 优先本地 mermaid（离线可用），失败时回退 CDN -->
    <script src="/static/vendor/mermaid.min.js"></script>
    <script>
        if (typeof mermaid === 'undefined') {{
            document.write('<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"><\\/script>');
        }}
    </script>
    <script>
        document.addEventListener('DOMContentLoaded', function () {{
            if (typeof mermaid !== 'undefined') {{
                mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
                mermaid.run();
            }} else {{
                document.querySelector('.mermaid').innerHTML =
                    '<p style="color:#b91c1c">mermaid 加载失败，无法渲染时序图</p>';
            }}
        }});
    </script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; margin: 20px; background: #f7f9fc; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; border: 1px solid #e5e7eb; }}
        h1 {{ color: #1f2937; margin-bottom: 8px; }}
        .info {{ color: #6b7280; margin-bottom: 20px; font-size: 0.95rem; }}
        .mermaid {{ background: #fafafa; padding: 20px; border-radius: 8px; border: 1px solid #e5e7eb; overflow: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>IS-IS 故障诊断执行时序图</h1>
        <div class="info">
            <p>追踪ID: {self.trace_id}</p>
            <p>开始时间: {self.start_time}</p>
            <p>结束时间: {self.end_time}</p>
        </div>
        <div class="mermaid">
{mermaid_code}
        </div>
    </div>
</body>
</html>"""
        return html

    def _generate_mermaid_code(self) -> str:
        """生成 Mermaid 序列图代码。合并同一层的 RUNNING/DONE，过滤内部步骤。"""
        # 仅展示分析层（L1-L4 + LLM），排除 load/feature/knowledge/report 等内部步骤
        display_layers = {"L1", "L2", "L3", "L4", "llm"}
        # 合并连续同层的 RUNNING -> 下一个状态（DONE/PASS/FAIL）
        merged = []
        for step in self.steps:
            layer = step["layer"]
            if layer not in display_layers:
                continue
            if step["status"] == "RUNNING":
                # 等待下一个同层步骤替换为最终状态
                merged.append({"layer": layer, "action": step["action"], "status": "RUNNING", "detail": ""})
            else:
                if merged and merged[-1]["layer"] == layer and merged[-1]["status"] == "RUNNING":
                    merged[-1]["status"] = step["status"]
                    merged[-1]["detail"] = step.get("detail", "")
                else:
                    merged.append({"layer": layer, "action": step["action"], "status": step["status"], "detail": step.get("detail", "")})

        lines = ["sequenceDiagram"]
        lines.append("    participant H as Hermes分析引擎")

        layer_names = {
            "L1": "L1物理层",
            "L2": "L2链路层",
            "L3": "L3-IS-IS路由层",
            "L4": "L4应用层",
            "llm": "LLM辅助诊断",
        }

        present_layers = sorted({s["layer"] for s in merged}, key=lambda x: ["L1", "L2", "L3", "L4", "llm"].index(x) if x in ["L1", "L2", "L3", "L4", "llm"] else 99)
        for layer in present_layers:
            name = layer_names.get(layer, layer)
            lines.append(f"    participant {layer} as {name}")

        for step in merged:
            layer = step["layer"]
            action = step["action"]
            status = step["status"]
            detail = step.get("detail", "")

            icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "✅" if status == "DONE" else "⏳"
            lines.append(f"    H->>{layer}: {action}")
            lines.append(f"    activate {layer}")
            lines.append(f"    {layer}-->>H: {icon} {detail}")
            lines.append(f"    deactivate {layer}")

        # 添加结论
        conclusion = self._build_conclusion()
        if conclusion["status"] == "anomaly_detected":
            note_text = (
                f"【诊断结论】<br/>"
                f"故障层级: {conclusion['fault_layer']}<br/>"
                f"故障类型: {conclusion['fault_type']}<br/>"
                f"建议操作: {conclusion['recommended_action']}"
            )
            lines.append(f"    Note over H: {note_text}")
        else:
            lines.append("    Note over H: ✅ 全部分析通过，未发现异常")

        return "\n".join(lines)

    def load_trace(self, trace_id: str) -> Optional[Dict]:
        """加载历史追踪记录"""
        trace_file = self.traces_dir / f"{trace_id}.json"
        if not trace_file.exists():
            return None

        with open(trace_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_traces(self) -> List[str]:
        """列出所有追踪记录"""
        traces = []
        for f in self.traces_dir.glob("run_*.json"):
            traces.append(f.stem)
        return sorted(traces, reverse=True)


def main():
    """测试入口"""
    import sys

    if len(sys.argv) < 2:
        print("用法: python tracer.py <traces_dir>")
        sys.exit(1)

    tracer = Tracer(Path(sys.argv[1]))

    # 模拟一次分析
    tracer.start("run_test_001")
    tracer.record_step("L1", "物理层检查", "PASS", "所有接口正常")
    tracer.record_step("L2", "链路层检查", "PASS", "邻居发现正常")
    tracer.record_step("L3", "IS-IS路由检查", "FAIL", "s23 LSP序列号异常", "L3-R001")
    tracer.record_step("llm", "LLM辅助诊断", "DONE", "疑似LSP同步故障")
    tracer.finish()

    print(f"追踪记录已保存: {tracer.traces_dir / f'{tracer.trace_id}.json'}")

    # 生成时序图
    html = tracer.generate_mermaid_html()
    print("Mermaid 时序图 HTML 已生成")
    print(html[:500] + "...")


if __name__ == "__main__":
    main()
