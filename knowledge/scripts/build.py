#!/usr/bin/env python3
"""从 RFC 摘要和 pcap/log 总结知识图谱节点与边。"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = Path(os.environ.get("WORKSPACE", SOURCE_ROOT)).resolve()
sys.path.insert(0, str(SOURCE_ROOT / "scripts_lib"))
from runner import validate_knowledge

# combo_lib.py 依赖 isis_simulator.scenario_lib，需注入其包路径
_ISIS_SRC = WORKSPACE / "isis-simulator" / "src"
if str(_ISIS_SRC) not in sys.path:
    sys.path.insert(0, str(_ISIS_SRC))

NODES_CSV = WORKSPACE / "knowledge/tables/nodes.csv"
EDGES_CSV = WORKSPACE / "knowledge/tables/edges.csv"
RFC_DIR = WORKSPACE / "knowledge/rfc"


def load_nodes() -> dict[str, dict[str, str]]:
    nodes = {}
    if not NODES_CSV.exists():
        return nodes
    with open(NODES_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nodes[row["node_id"]] = row
    return nodes


def load_edges() -> list[dict[str, str]]:
    edges = []
    if not EDGES_CSV.exists():
        return edges
    with open(EDGES_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            edges.append(row)
    return edges


def extract_fault_nodes_from_scenarios() -> list[dict[str, str]]:
    """从 isis-simulator 场景模块中提取故障定义。"""
    nodes = []
    scenarios_dir = WORKSPACE / "isis-simulator/src/isis_simulator/scenarios"
    for f in sorted(scenarios_dir.glob("*.py")):
        if f.name.startswith("__") or f.name == "combo_lib.py":
            continue
        text = f.read_text(encoding="utf-8")
        # 取第一行 docstring
        match = re.search(r'"""(.+?)"""', text, re.DOTALL)
        desc = ""
        if match:
            lines = [l.strip() for l in match.group(1).splitlines() if l.strip()]
            desc = lines[0] if lines else ""
        node_id = f.stem
        nodes.append({
            "node_id": node_id,
            "node_type": "fault",
            "name": node_id.replace("_", " ").title(),
            "description": desc,
            "source": "scenario",
        })
    # 复合故障节点：来自 combo_lib.COMBO_FAULTS
    combo_lib = scenarios_dir / "combo_lib.py"
    if combo_lib.exists():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("combo_lib_det", combo_lib)
            mod = importlib.util.module_from_spec(spec)
            import sys
            sys.modules["combo_lib_det"] = mod
            spec.loader.exec_module(mod)
        except Exception:
            mod = None
        if mod is not None:
            for combo_name, (desc, _fn) in getattr(mod, "COMBO_FAULTS", {}).items():
                nodes.append({
                    "node_id": combo_name.replace("-", "_"),
                    "node_type": "composite_fault",
                    "name": combo_name,
                    "description": f"复合故障：{desc}。表现为两个独立故障在同一故障窗口同时出现，"
                                   "需分别识别各子故障证据，按规则逐项排查。",
                    "source": "combo_lib",
                })
    return nodes


def _discover_combo_edges() -> list[dict[str, str]]:
    """复合故障节点 -> 各子故障节点的组合关系（combines 边）。"""
    edges = []
    combo_lib = WORKSPACE / "isis-simulator/src/isis_simulator/scenarios/combo_lib.py"
    if not combo_lib.exists():
        return edges
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("combo_lib_det2", combo_lib)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["combo_lib_det2"] = mod
    spec.loader.exec_module(mod)
    for combo_name, (desc, _fn) in getattr(mod, "COMBO_FAULTS", {}).items():
        combo_id = combo_name.replace("-", "_")
        for sub in desc.split(" + "):
            sub_id = sub.strip()
            edges.append({
                "source_id": combo_id,
                "relation": "combines",
                "target_id": sub_id,
                "description": f"复合故障 {combo_name} 由 {sub_id} 与另一故障叠加而成",
            })
    return edges


def discover_new_edges(nodes: dict[str, dict[str, str]], edges: list[dict[str, str]]) -> list[dict[str, str]]:
    """为尚未建立关联的 fault 节点生成推荐边。"""
    existing_pairs = {(e["source_id"], e["target_id"]) for e in edges}
    new_edges = []
    for nid, node in nodes.items():
        if node["node_type"] != "fault":
            continue
        # 通用：每个 fault 都指向 adjacency_down
        if (nid, "adjacency_down") not in existing_pairs:
            new_edges.append({
                "source_id": nid,
                "relation": "causes",
                "target_id": "adjacency_down",
                "description": f"{node['name']} may cause adjacency Down",
            })
        # 物理类 fault 指向 neighbor_loss
        if nid in {"link_down", "netem_loss_delay"} and (nid, "neighbor_loss") not in existing_pairs:
            new_edges.append({
                "source_id": nid,
                "relation": "causes",
                "target_id": "neighbor_loss",
                "description": f"{node['name']} may lead to neighbor loss",
            })
    return new_edges


def build():
    # 写入前先检查输入结构，避免把损坏表格读成正常数据并覆盖。
    validate_knowledge(checks="A")
    snapshot = WORKSPACE / "knowledge/learnings/snapshots" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    snapshot.mkdir(parents=True, exist_ok=True)
    for table in NODES_CSV.parent.glob("*.csv"):
        shutil.copy2(table, snapshot / table.name)
    kg_path = WORKSPACE / "knowledge/knowledge_graph.json"
    if kg_path.exists():
        shutil.copy2(kg_path, snapshot / kg_path.name)
    print(f"[BACKUP] 构建前知识库快照：{snapshot}")
    nodes = load_nodes()
    edges = load_edges()

    # 从已有初始表补齐属性引用的实体，保留正式表中已有节点的内容。
    attributes_path = NODES_CSV.parent / "node_attributes.csv"
    with attributes_path.open(encoding="utf-8-sig", newline="") as f:
        referenced = {a["node_id"] for a in csv.DictReader(f)}
    seed_path = WORKSPACE / "agent-analysis/config/knowledge_tables/nodes.csv"
    if seed_path.exists():
        with seed_path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row["node_id"] in referenced and row["node_id"] not in nodes:
                    row["node_type"] = {"protocol_pdu": "protocol", "protocol_tlv": "tlv"}.get(row["node_type"], row["node_type"])
                    nodes[row["node_id"]] = {k: row.get(k, "") for k in ("node_id", "node_type", "name", "description", "source")}

    # 规则中的指标必须先成为症状节点，再生成 indicates 边。
    # 使用现有建表规则的 ID 格式，保留历史边的引用。
    def rule_id(value):
        return value.lower().replace(" ", "_").replace("-", "_")

    for rule_file in sorted((WORKSPACE / "agent-analysis/config/diagnosis_rules").glob("*.json")):
        raw = json.loads(rule_file.read_text(encoding="utf-8"))
        rules = raw if isinstance(raw, list) else raw.get("rules", [raw])
        for rule in rules:
            name = rule.get("name") or rule.get("rule_id") or rule.get("id")
            if not name:
                continue
            nid = rule_id(name)
            source = f"rule:{rule_file.name}"
            nodes.setdefault(nid, {"node_id": nid, "node_type": "rule", "name": name,
                                   "description": rule.get("description", ""), "source": source})
            for indicator in rule.get("indicators", []):
                target = rule_id(indicator)
                if target == nid:
                    continue
                nodes.setdefault(target, {"node_id": target, "node_type": "symptom", "name": indicator,
                                          "description": f"规则 {name} 的指标：{indicator}", "source": source})
                edges.append({"source_id": nid, "relation": "indicates", "target_id": target,
                              "description": f"{name} indicates {indicator}"})

    # 合并场景节点
    scenario_nodes = extract_fault_nodes_from_scenarios()
    for node in scenario_nodes:
        if node["node_id"] not in nodes:
            nodes[node["node_id"]] = node

    # 生成推荐边
    new_edges = discover_new_edges(nodes, edges)
    edges.extend(new_edges)

    # 复合故障组合关系边
    combo_edges = _discover_combo_edges()
    existing_combos = {(e["source_id"], e["relation"], e["target_id"]) for e in edges}
    for ce in combo_edges:
        if (ce["source_id"], ce["relation"], ce["target_id"]) not in existing_combos:
            edges.append(ce)

    unique_edges = {}
    for edge in edges:
        unique_edges.setdefault((edge["source_id"], edge["relation"], edge["target_id"]), edge)
    edges = list(unique_edges.values())

    # 写入 nodes.csv
    with open(NODES_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["node_id", "node_type", "name", "description", "source"])
        writer.writeheader()
        for nid in sorted(nodes.keys()):
            writer.writerow(nodes[nid])

    # 写入 edges.csv
    with open(EDGES_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source_id", "relation", "target_id", "description"])
        writer.writeheader()
        for e in edges:
            writer.writerow(e)

    # 写入 json 便于 GraphRAG 索引
    kg = {"nodes": list(nodes.values()), "edges": edges}
    kg_path = WORKSPACE / "knowledge/knowledge_graph.json"
    with open(kg_path, "w", encoding="utf-8") as f:
        json.dump(kg, f, indent=2, ensure_ascii=False)

    print(f"[OK] 知识图谱已更新: nodes={len(nodes)}, edges={len(edges)}")
    print(f"     {NODES_CSV}")
    print(f"     {EDGES_CSV}")
    print(f"     {kg_path}")
    validate_knowledge()


if __name__ == "__main__":
    try:
        build()
    except subprocess.CalledProcessError:
        print("[ERROR] 知识构建未通过校验；请检查验证报告和构建前快照。", file=sys.stderr)
        sys.exit(1)
