#!/usr/bin/env python3
"""验证 tracer.py 改动 — 复现 tests/test_engine.py 中 TestTracer 的断言。
（环境无 pytest/pip，tests 的 import analysis.tracer 已过时，此脚本直接对 agent_analysis.tracer 跑同等断言。）
注意：Tracer.finish() 会按 traces_dir.parent.parent/output/sequence_diagrams 推导时序图目录，
因此 tmpdir 需构造 data/traces 两层结构。
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent-analysis" / "src"))
from agent_analysis.tracer import Tracer

failures = []

def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

# --- test_trace_lifecycle ---
with tempfile.TemporaryDirectory() as tmpdir:
    tdir = Path(tmpdir) / "data" / "traces"
    tracer = Tracer(tdir)
    tracer.start("test_trace")
    tracer.record_step("L1", "测试步骤", "PASS", "正常")
    tracer.finish()
    tf = tdir / "test_trace.json"
    check("lifecycle: trace file exists", tf.exists())
    data = json.loads(tf.read_text(encoding="utf-8"))
    check("lifecycle: trace_id", data["trace_id"] == "test_trace")
    check("lifecycle: 1 step", len(data["steps"]) == 1)
    seq = Path(tmpdir) / "output" / "sequence_diagrams" / "test_trace.html"
    check("lifecycle: seq html auto-saved", seq.exists())

# --- test_generate_mermaid ---
with tempfile.TemporaryDirectory() as tmpdir:
    tdir = Path(tmpdir) / "data" / "traces"
    tracer = Tracer(tdir)
    tracer.start("test_trace")
    tracer.record_step("L1", "物理层检查", "PASS", "正常")
    tracer.record_step("L3", "路由检查", "FAIL", "异常", "L3-R001")
    tracer.finish()
    html = tracer.generate_mermaid_html()
    check("mermaid: sequenceDiagram", "sequenceDiagram" in html)
    check("mermaid: L1物理层", "L1物理层" in html)
    check("mermaid: L3-IS-IS路由层", "L3-IS-IS路由层" in html)

    # --- 本次改动的专项断言 ---
    check("local vendor mermaid script", "/static/vendor/mermaid.min.js" in html)
    check("CDN fallback present", "cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js" in html)
    check("no ESM module import", "mermaid.esm.min.mjs" not in html)
    check("no literal backslash-n in note", "\\n" not in html.split('<div class="mermaid">')[1])
    check("note uses <br/>", "<br/>" in html)
    check("load-failure message present", "mermaid 加载失败" in html)

# mermaid 语法层面：Note 单行、无非法字符
with tempfile.TemporaryDirectory() as tmpdir:
    tdir = Path(tmpdir) / "data" / "traces"
    tracer = Tracer(tdir)
    tracer.start("t2")
    tracer.record_step("L2", "链路层检查", "FAIL", "命中 2 条规则", "L2-R001")
    tracer.finish()
    code = tracer._generate_mermaid_code()
    for i, line in enumerate(code.splitlines(), 1):
        check(f"line {i} no CR/tab", "\r" not in line and "\t" not in line)

print()
if failures:
    print(f"FAILED: {len(failures)} 项")
    sys.exit(1)
print("ALL CHECKS PASSED")
