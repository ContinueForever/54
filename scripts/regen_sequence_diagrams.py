#!/usr/bin/env python3
"""用新模板重新生成所有历史时序图（从 data/traces/*.json）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent-analysis" / "src"))

from agent_analysis.tracer import Tracer

ws = Path(__file__).resolve().parents[1]
traces_dir = ws / "agent-analysis" / "data" / "traces"
seq_dir = ws / "agent-analysis" / "output" / "sequence_diagrams"

count = 0
for tf in sorted(traces_dir.glob("*.json")):
    try:
        data = json.loads(tf.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[SKIP] {tf.name}: {e}")
        continue
    tracer = Tracer(traces_dir)
    tracer.generate_mermaid_html(trace_data=data)
    html = tracer.generate_mermaid_html(trace_data=data)
    out = seq_dir / f"{data.get('trace_id', tf.stem)}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    count += 1
    print(f"[OK] {out.name}")

print(f"共重新生成 {count} 个时序图")
