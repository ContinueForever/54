#!/usr/bin/env python3
"""knowledge-builder 可执行入口 — 知识图谱构建与持续学习。

主要子命令：
    build              从规则和场景构建 CSV 知识图谱，并构建 GraphRAG 索引
    build-csv          仅构建 CSV 知识图谱
    graphrag-input     生成 GraphRAG 输入文本
    graphrag-index     构建 GraphRAG 索引
    discover           从历史 trace/report 中发现未知故障模式
    candidates         列出待确认候选节点
    apply-candidates   合并候选到主图谱
    serve              启动 GraphRAG 服务

典型用法：
    python -m knowledge_builder build --scenario link-down
    python -m knowledge_builder discover --days 30
    python -m knowledge_builder candidates
    python -m knowledge_builder apply-candidates --candidate 20260706_143052
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

SOURCE_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = Path(os.environ.get("WORKSPACE", SOURCE_ROOT)).resolve()
SCRIPTS_LIB = SOURCE_ROOT / "scripts_lib"
sys.path.insert(0, str(SCRIPTS_LIB))

from runner import (
    build_knowledge_graph,
    validate_knowledge,
    run_material_to_csv,
    build_graphrag_index,
    build_graphrag_input,
    generate_isis_scenario,
    load_knowledge_tables,
    make_run_id,
    run,
    start_graphrag_server,
)

KNOWLEDGE_DIR = WORKSPACE / "knowledge"
TABLES_DIR = KNOWLEDGE_DIR / "tables"
LEARNINGS_DIR = KNOWLEDGE_DIR / "learnings"
CANDIDATES_DIR = LEARNINGS_DIR / "candidates"
TRACES_DIR = WORKSPACE / "agent-analysis" / "data" / "traces"
REPORTS_DIR = WORKSPACE / "agent-analysis" / "output" / "reports"
RULES_DIR = WORKSPACE / "agent-analysis" / "config" / "diagnosis_rules"
SIM_SCENARIOS_DIR = WORKSPACE / "isis-simulator" / "src" / "isis_simulator" / "scenarios"


def backup_tables():
    """备份当前知识表到 learnings/snapshots/。"""
    snapshot_dir = LEARNINGS_DIR / "snapshots" / datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for f in TABLES_DIR.glob("*.csv"):
        shutil.copy2(f, snapshot_dir / f.name)
    print(f"[BACKUP] 知识表已备份到 {snapshot_dir}")
    return snapshot_dir


def cmd_build_csv(args):
    """复用项目构建入口，构建 CSV/JSON 并自动校验。"""
    build_knowledge_graph()
    return 0


def cmd_build(args):
    """完整构建：CSV + GraphRAG 输入 + GraphRAG 索引。"""
    # 1. 若指定场景，生成仿真数据
    if args.scenario:
        run_id = make_run_id()
        output_dir = WORKSPACE / "isis-simulator" / "output" / run_id
        generate_isis_scenario(args.scenario, output_dir)
        print(f"[OK] 仿真数据已生成：{output_dir}")

    # 2. 构建 CSV 知识图谱
    cmd_build_csv(args)

    # 3. 生成 GraphRAG 输入
    build_graphrag_input()

    # 4. 构建 GraphRAG 索引
    if not args.no_index:
        build_graphrag_index()

    # 5. 启动服务（可选）
    if args.serve:
        proc = start_graphrag_server(args.port)
        print(f"[OK] GraphRAG 服务已启动：http://localhost:{args.port}")
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    return 0


def cmd_graphrag_input(args):
    build_graphrag_input()
    return 0



def cmd_graphrag_index(args):
    build_graphrag_index()
    return 0


def cmd_serve(args):
    proc = start_graphrag_server(args.port)
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def load_all_traces(days: Optional[int] = None) -> List[Dict]:
    """加载历史 trace 文件。"""
    if not TRACES_DIR.exists():
        return []
    traces = []
    cutoff = None
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)
    for f in sorted(TRACES_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if cutoff and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            continue
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                data["_file"] = str(f)
                data["_mtime"] = f.stat().st_mtime
                traces.append(data)
        except Exception:
            continue
    return traces


def load_all_rules() -> List[Dict]:
    """加载所有诊断规则。"""
    rules = []
    if not RULES_DIR.exists():
        return rules
    for f in RULES_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            rules.append(data)
        except Exception:
            continue
    return rules


def extract_event_types_from_trace(trace: Dict) -> List[str]:
    """从 trace 中提取 event_types。"""
    types = []
    features = trace.get("features", {})
    for log_features in features.get("log", {}).values():
        types.extend(log_features.get("event_types", []))
    return types


def collect_indicators(rules: List[Dict]) -> set:
    """收集所有规则 indicators。"""
    indicators = set()
    for rule_group in rules:
        for rule in rule_group.get("rules", []):
            for ind in rule.get("indicators", []):
                indicators.add(ind.lower().replace(" ", "_").replace("-", "_"))
    return indicators


def cmd_discover(args):
    """从历史数据中发现未知故障模式。"""
    traces = load_all_traces(args.days)
    if not traces:
        print("[WARN] 未找到历史 trace 数据")
        return 0

    rules = load_all_rules()
    indicators = collect_indicators(rules)

    unknown_events = Counter()
    event_samples = defaultdict(list)

    for trace in traces:
        event_types = extract_event_types_from_trace(trace)
        for et in event_types:
            et_norm = et.lower().replace(" ", "_").replace("-", "_")
            if et_norm not in indicators:
                unknown_events[et] += 1
                if len(event_samples[et]) < 3:
                    event_samples[et].append(trace.get("trace_id", "unknown"))

    if not unknown_events:
        print("[OK] 未发现未覆盖的故障事件，所有事件都已命中规则")
        return 0

    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    candidate_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate_path = CANDIDATES_DIR / f"{candidate_id}.json"

    candidates = []
    for event, count in unknown_events.most_common():
        candidates.append({
            "node_id": event.lower().replace(" ", "_").replace("-", "_"),
            "node_type": "fault_candidate",
            "name": event,
            "description": f"Unknown event discovered from traces (count={count})",
            "source": "learning",
            "occurrence": count,
            "sample_trace_ids": event_samples[event][:3],
        })

    candidate_doc = {
        "candidate_id": candidate_id,
        "created_at": datetime.now().isoformat(),
        "traces_analyzed": len(traces),
        "days": args.days,
        "unknown_events_count": len(unknown_events),
        "candidates": candidates,
    }
    with open(candidate_path, "w", encoding="utf-8") as f:
        json.dump(candidate_doc, f, indent=2, ensure_ascii=False)

    print(f"[OK] 发现 {len(unknown_events)} 类未知事件，候选文件已保存：{candidate_path}")
    for c in candidates:
        print(f"  - {c['name']}: {c['occurrence']} 次")
    return 0


def cmd_candidates(args):
    """列出候选文件。"""
    if not CANDIDATES_DIR.exists():
        print("[INFO] 暂无候选文件")
        return 0
    files = sorted(CANDIDATES_DIR.glob("*.json"), reverse=True)
    print(f"[INFO] 共 {len(files)} 个候选文件：")
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            print(f"  {f.name}: {data.get('unknown_events_count', 0)} 个候选事件，创建于 {data.get('created_at', '未知')}")
        except Exception:
            print(f"  {f.name}: 无法解析")
    return 0


def cmd_apply_candidates(args):
    """合并候选节点到主图谱。"""
    candidate_name = args.candidate
    if not candidate_name.endswith(".json"):
        candidate_name += ".json"
    candidate_path = CANDIDATES_DIR / candidate_name
    if not candidate_path.exists():
        print(f"[ERROR] 候选文件不存在：{candidate_path}")
        return 1

    try:
        data = json.loads(candidate_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] 解析候选文件失败：{e}")
        return 1

    backup_tables()
    kg = load_knowledge_tables()
    nodes = {n["node_id"]: n for n in kg.get("nodes", [])}
    edges = kg.get("edges", [])

    applied = 0
    for c in data.get("candidates", []):
        nid = c.get("node_id")
        if not nid or nid in nodes:
            continue
        nodes[nid] = {
            "node_id": nid,
            "node_type": c.get("node_type", "fault"),
            "name": c.get("name", nid),
            "description": c.get("description", ""),
            "source": "learning",
        }
        # 默认关联到 adjacency_down
        edges.append({
            "source_id": nid,
            "relation": "causes",
            "target_id": "adjacency_down",
            "description": f"{c.get('name')} may cause adjacency Down",
        })
        applied += 1

    # 写入
    nodes_path = TABLES_DIR / "nodes.csv"
    with open(nodes_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["node_id", "node_type", "name", "description", "source"])
        writer.writeheader()
        for nid in sorted(nodes.keys()):
            writer.writerow(nodes[nid])

    edges_path = TABLES_DIR / "edges.csv"
    with open(edges_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source_id", "relation", "target_id", "description"])
        writer.writeheader()
        for e in edges:
            writer.writerow(e)


    print(f"[OK] 已合并 {applied} 个候选节点到主图谱")
    print(f"     当前节点数：{len(nodes)}，边数：{len(edges)}")

    # 同步 CSV、JSON，校验通过后再更新检索输入和索引
    build_knowledge_graph()
    build_graphrag_input()
    if not args.no_index:
        build_graphrag_index()
    candidate_path.with_suffix(".applied").write_text(datetime.now().isoformat(), encoding="utf-8")
    return 0


def cmd_material(args):
    arguments = [args.command]
    if args.command == "extract":
        arguments += [args.material, "--source", args.source]
        if args.batch:
            arguments += ["--batch", args.batch]
    else:
        arguments.append(args.batch)
        if args.command == "merge":
            if args.prefer_new:
                arguments.append("--prefer-new")
            if args.index:
                arguments.append("--index")
    run_material_to_csv(arguments)
    return 0


def cmd_validate(args):
    validate_knowledge(args.checks, args.graphrag_url, args.sample, args.json)
    return 0


def main():
    parser = argparse.ArgumentParser(description="54所 IS-IS 知识图谱构建与持续学习")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_build = subparsers.add_parser("build", help="构建完整知识图谱（含 GraphRAG 索引）")
    p_build.add_argument("--scenario", help="先生成指定场景的仿真数据")
    p_build.add_argument("--no-index", action="store_true", help="不构建 GraphRAG 索引")
    p_build.add_argument("--serve", action="store_true", help="构建完成后启动 GraphRAG 服务")
    p_build.add_argument("--port", type=int, default=9200, help="GraphRAG 服务端口")
    p_build.set_defaults(func=cmd_build)

    p_build_csv = subparsers.add_parser("build-csv", help="仅构建 CSV 知识图谱")
    p_build_csv.set_defaults(func=cmd_build_csv)

    p_gr_input = subparsers.add_parser("graphrag-input", help="生成 GraphRAG 输入文本")
    p_gr_input.set_defaults(func=cmd_graphrag_input)

    p_gr_index = subparsers.add_parser("graphrag-index", help="构建 GraphRAG 索引")
    p_gr_index.set_defaults(func=cmd_graphrag_index)

    p_discover = subparsers.add_parser("discover", help="从历史 trace 中发现未知故障")
    p_discover.add_argument("--days", type=int, help="只分析最近 N 天的 trace")
    p_discover.set_defaults(func=cmd_discover)

    p_candidates = subparsers.add_parser("candidates", help="列出候选新故障")
    p_candidates.set_defaults(func=cmd_candidates)

    p_apply = subparsers.add_parser("apply-candidates", help="合并候选到主图谱")
    p_apply.add_argument("--candidate", required=True, help="候选文件名或 ID（如 20260706_143052）")
    p_apply.add_argument("--no-index", action="store_true", help="不重新构建 GraphRAG 索引")
    p_apply.set_defaults(func=cmd_apply_candidates)

    p_serve = subparsers.add_parser("serve", help="启动 GraphRAG 服务")
    p_serve.add_argument("--port", type=int, default=9200)
    p_serve.set_defaults(func=cmd_serve)

    p_extract = subparsers.add_parser("extract", help="从素材提取候选 CSV，不修改正式知识库")
    p_extract.add_argument("material")
    p_extract.add_argument("--source", required=True)
    p_extract.add_argument("--batch", help="候选批次目录名")
    p_extract.set_defaults(func=cmd_material)

    p_diff = subparsers.add_parser("diff", help="审阅候选 CSV 与正式知识库的差异")
    p_diff.add_argument("batch", help="候选批次目录路径")
    p_diff.set_defaults(func=cmd_material)

    p_merge = subparsers.add_parser("merge", help="合并候选 CSV，自动构建并校验本地图谱")
    p_merge.add_argument("batch", help="已审阅的候选批次目录路径")
    p_merge.add_argument("--prefer-new", action="store_true")
    p_merge.add_argument("--index", action="store_true", help="继续更新 GraphRAG 索引")
    p_merge.set_defaults(func=cmd_material)

    p_validate = subparsers.add_parser("validate", help="校验知识表格、图谱及 GraphRAG 服务")
    p_validate.add_argument("--checks", default="A,B,C,D,E,F")
    p_validate.add_argument("--graphrag-url", default=os.environ.get("GRAPHRAG_URL", "http://localhost:9200"))
    p_validate.add_argument("--sample", type=int, default=10)
    p_validate.add_argument("--json", action="store_true")
    p_validate.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    try:
        return args.func(args)
    except subprocess.CalledProcessError as exc:
        print("[ERROR] 知识工作流失败；请检查上方错误及验证报告。", file=sys.stderr)
        return exc.returncode



if __name__ == "__main__":
    sys.exit(main())
