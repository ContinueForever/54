#!/usr/bin/env python3
"""kg-validator — 知识图谱提取准确性验证。

六大类检查：
  A. Schema 校验（CSV 列名 / 必填列 / JSON 合法性）
  B. 引用完整性（边两端节点存在、combines 指向 fault 节点）
  C. 去重（node_id 重复、边重复、名称近似重复）
  D. 来源真实性（source 字段可溯源到 RFC / 规则 JSON / 场景注册表）
  E. 三级一致性（CSV ↔ knowledge_graph.json ↔ GraphRAG /health）
  F. 提取准确性抽检（描述核心术语与来源素材比对 + TLV code 交叉核对）

退出码：0 = 无 CRITICAL；1 = 存在 CRITICAL。
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE", Path(__file__).resolve().parents[2])).resolve()
TABLES = WORKSPACE / "knowledge" / "tables"
KG_JSON = WORKSPACE / "knowledge" / "knowledge_graph.json"
RFC_DIR = WORKSPACE / "knowledge" / "rfc"
RULES_DIR = WORKSPACE / "agent-analysis" / "config" / "diagnosis_rules"
LEARNINGS = WORKSPACE / "knowledge" / "learnings"
VALIDATION_OUT = LEARNINGS / "validation"
SCENARIO_GENERATE = WORKSPACE / "isis-simulator" / "src" / "isis_simulator" / "generate.py"
ISIS_PDU = WORKSPACE / "isis-simulator" / "src" / "isis_simulator" / "isis_pdu.py"

NODES_COLS = ["node_id", "node_type", "name", "description", "source"]
EDGES_COLS = ["source_id", "relation", "target_id", "description"]
ATTRS_COLS = ["node_id", "attribute", "value"]
VALID_NODE_TYPES = {"fault", "state", "device", "symptom", "protocol", "rule",
                    "composite_fault", "tlv", "interface", "unknown"}

LEVELS = ("CRITICAL", "MAJOR", "MINOR", "INFO")


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str, str]] = []  # (check, level, title, evidence)

    def add(self, check: str, level: str, title: str, evidence: str = "") -> None:
        assert level in LEVELS or level in ("PASS", "SKIP"), level
        self.items.append((check, level, title, evidence))

    def counts(self) -> Counter:
        return Counter(lv for _, lv, _, _ in self.items)

    def has_critical(self) -> bool:
        return any(lv == "CRITICAL" for _, lv, _, _ in self.items)


def load_csv(path: Path) -> tuple[list[dict], list[str]]:
    """返回 (rows, header)。文件不存在返回 ([], [])。"""
    if not path.exists():
        return [], []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), (reader.fieldnames or [])


# ---------------------------------------------------------------- A. Schema
def check_schema(rep: Report) -> dict:
    data: dict = {}
    for fname, cols in (("nodes.csv", NODES_COLS), ("edges.csv", EDGES_COLS),
                        ("node_attributes.csv", ATTRS_COLS)):
        path = TABLES / fname
        if not path.exists():
            rep.add("A", "CRITICAL", f"{fname} 不存在", str(path))
            data[fname] = ([], [])
            continue
        try:
            rows, header = load_csv(path)
        except (OSError, UnicodeError, csv.Error) as exc:
            rep.add("A", "CRITICAL", f"{fname} 无法读取", str(exc))
            data[fname] = ([], [])
            continue
        data[fname] = (rows, header)
        if header != cols:
            rep.add("A", "CRITICAL", f"{fname} 列名不符",
                    f"期望 {cols}，实际 {header}")
        else:
            rep.add("A", "PASS", f"{fname} schema 正确", f"{len(rows)} 行")
        for i, row in enumerate(rows, 2):  # 行号从 2 起（含表头）
            if None in row or any(row.get(c) is None for c in cols):
                rep.add("A", "CRITICAL", f"{fname} 第{i}行列数不符", str(row))
            for col in cols[:3]:
                if not (row.get(col) or "").strip():
                    rep.add("A", "MAJOR", f"{fname} 第{i}行 {col} 为空", str(row))
    # knowledge_graph.json 合法性
    if not KG_JSON.exists():
        rep.add("A", "MAJOR", "knowledge_graph.json 不存在", str(KG_JSON))
        data["kg"] = None
    else:
        try:
            kg = json.loads(KG_JSON.read_text(encoding="utf-8"))
            if not isinstance(kg, dict) or not isinstance(kg.get("nodes"), list) or not isinstance(kg.get("edges"), list):
                raise ValueError("nodes/edges 必须为列表")
            if any(not isinstance(row, dict) for row in kg["nodes"] + kg["edges"]):
                raise ValueError("nodes/edges 元素必须为对象")
            if any(not isinstance(n.get("node_id") or n.get("id"), str) or
                   not (n.get("node_id") or n.get("id")).strip() for n in kg["nodes"]):
                raise ValueError("JSON 节点缺少有效 node_id/id")
            data["kg"] = kg
            rep.add("A", "PASS", "knowledge_graph.json 合法",
                    f"nodes={len(kg['nodes'])} edges={len(kg['edges'])}")
        except Exception as e:  # noqa: BLE001
            rep.add("A", "CRITICAL", "knowledge_graph.json 非法", f"{type(e).__name__}: {e}")
            data["kg"] = None
    # node_type 合法性
    rows, _ = data.get("nodes.csv", ([], []))
    bad = [r.get("node_id", "") for r in rows if r.get("node_type") not in VALID_NODE_TYPES]
    if bad:
        rep.add("A", "MINOR", f"{len(bad)} 个节点 node_type 不在标准集合",
                f"{bad[:10]}（标准：{sorted(VALID_NODE_TYPES)}）")
    unknown = [r.get("node_id", "") for r in rows if r.get("node_type") == "unknown"]
    if unknown:
        rep.add("A", "MINOR", "unknown 节点待人工确认", str(unknown[:10]))
    if not rows:
        rep.add("A", "MAJOR", "知识节点表为空", str(TABLES / "nodes.csv"))
    return data


# ------------------------------------------------------- B. 引用完整性
def check_integrity(rep: Report, data: dict) -> None:
    nodes, _ = data.get("nodes.csv", ([], []))
    edges, _ = data.get("edges.csv", ([], []))
    ids = {r["node_id"] for r in nodes}
    faults = {r["node_id"] for r in nodes if r.get("node_type") == "fault"}
    combos = {r["node_id"] for r in nodes if r.get("node_type") == "composite_fault"}

    dangling = []
    for e in edges:
        for end in ("source_id", "target_id"):
            if e.get(end) and e[end] not in ids:
                dangling.append(f"{e.get('source_id')} -[{e.get('relation')}]-> {e.get('target_id')}（{end} 悬空）")
    if dangling:
        rep.add("B", "CRITICAL", f"{len(dangling)} 条悬空边", "\n".join(dangling[:10]))
    elif edges:
        rep.add("B", "PASS", "边引用完整", f"{len(edges)} 条边两端节点均存在")

    # combines 边：源必须是 composite_fault，目标必须是 fault
    bad_combines = []
    combo_targets = set()
    for e in edges:
        if e.get("relation") != "combines":
            continue
        combo_targets.add(e["target_id"])
        if e["source_id"] not in combos:
            bad_combines.append(f"{e['source_id']} 不是 composite_fault")
        if e["target_id"] not in faults:
            bad_combines.append(f"{e['target_id']} 不是 fault 节点")
    if bad_combines:
        rep.add("B", "MAJOR", "combines 边端点类型错误", "\n".join(bad_combines[:10]))

    # 每个 composite_fault 至少 2 条 combines 出边
    out = Counter(s for s, t in {(e["source_id"], e["target_id"]) for e in edges if e.get("relation") == "combines"})
    insufficient = False
    for c in sorted(combos):
        if out.get(c, 0) < 2:
            insufficient = True
            rep.add("B", "MAJOR", f"复合节点 {c} combines 出边 {out.get(c,0)} 条（<2）",
                    "复合故障必须能分解到至少 2 个子故障")
    if combos and not bad_combines and not insufficient:
        rep.add("B", "PASS", "combines 结构正确",
                f"{len(combos)} 个复合节点均分解到 fault 子节点")
    attrs, _ = data.get("node_attributes.csv", ([], []))
    dangling_attrs = [a for a in attrs if a.get("node_id") not in ids]
    if dangling_attrs:
        rep.add("B", "CRITICAL", "属性引用不存在的节点", str(dangling_attrs[:10]))


# ---------------------------------------------------------------- C. 去重
def check_dedup(rep: Report, data: dict) -> None:
    nodes, _ = data.get("nodes.csv", ([], []))
    edges, _ = data.get("edges.csv", ([], []))

    id_dup = [k for k, v in Counter(r["node_id"] for r in nodes).items() if v > 1]
    if id_dup:
        rep.add("C", "CRITICAL", f"node_id 重复 {len(id_dup)} 个", str(id_dup[:10]))
    elif nodes:
        rep.add("C", "PASS", "node_id 无重复", f"{len(nodes)} 个节点")

    edge_keys = Counter((e["source_id"], e["relation"], e["target_id"]) for e in edges)
    edge_dup = [k for k, v in edge_keys.items() if v > 1]
    if edge_dup:
        rep.add("C", "MAJOR", f"重复边 {len(edge_dup)} 条", str(edge_dup[:10]))
    elif edges:
        rep.add("C", "PASS", "边无重复", f"{len(edges)} 条边")

    # 名称近似重复（同类型节点，相似度 > 0.85）
    near = []
    by_type: dict[str, list[dict]] = {}
    for r in nodes:
        by_type.setdefault(r.get("node_type", ""), []).append(r)
    for t, group in by_type.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                sim = SequenceMatcher(None, a["name"].lower(), b["name"].lower()).ratio()
                if sim > 0.85 and a["node_id"] != b["node_id"]:
                    near.append(f"{a['node_id']} ~ {b['node_id']}（name 相似度 {sim:.2f}）")
    if near:
        rep.add("C", "MINOR", f"{len(near)} 对疑似同义节点", "\n".join(near[:10]))
    attrs, _ = data.get("node_attributes.csv", ([], []))
    attr_dup = [key for key, count in Counter((a.get("node_id"), a.get("attribute")) for a in attrs).items() if count > 1]
    if attr_dup:
        rep.add("C", "MAJOR", "重复属性键（可能含值冲突）", str(attr_dup[:10]))


# ------------------------------------------------------- D. 来源真实性
def _scenario_names() -> set[str]:
    """从 generate.py 注册表解析场景名（短横线命名）。"""
    names: set[str] = set()
    if SCENARIO_GENERATE.exists():
        text = SCENARIO_GENERATE.read_text(encoding="utf-8")
        names.update(re.findall(r'\("([a-z0-9_\-]+)",\s*"', text))
    return names


def check_sources(rep: Report, data: dict) -> None:
    nodes, _ = data.get("nodes.csv", ([], []))
    rfc_files = {p.stem.lower() for p in RFC_DIR.glob("*") if p.is_file()} if RFC_DIR.exists() else set()
    rule_files = {p.name for p in RULES_DIR.glob("*.json")} if RULES_DIR.exists() else set()
    scenarios = _scenario_names()

    bad, unchecked = [], Counter()
    for r in nodes:
        src = (r.get("source") or "").strip()
        nid = r["node_id"]
        if not src:
            bad.append(f"{nid}: source 为空")
            continue
        if src.lower().startswith("rfc"):
            if not _rfc_paths(src):
                bad.append(f"{nid}: source={src} 但 knowledge/rfc/ 无对应文件（现有 {sorted(rfc_files)}）")
        elif src.startswith("rule:"):
            fname = src.split(":", 1)[1]
            if fname not in rule_files:
                bad.append(f"{nid}: source={src} 但 diagnosis_rules/ 无 {fname}")
        elif src == "scenario":
            dash = nid.replace("_", "-")
            if dash not in scenarios and nid not in scenarios:
                bad.append(f"{nid}: source=scenario 但 generate.py 未注册场景 {dash}/{nid}")
        elif src == "combo_lib":
            dash = r.get("name", nid).replace("_", "-")
            if dash not in scenarios and nid.replace("_", "-") not in scenarios:
                bad.append(f"{nid}: source=combo_lib 但 generate.py 未注册 {dash}")
        else:
            unchecked[src] += 1  # observational 等约定来源不强制核对
    if bad:
        rep.add("D", "MAJOR", f"{len(bad)} 个节点来源不可溯源", "\n".join(bad[:12]))
    elif unchecked:
        rep.add("D", "SKIP", "部分约定来源未核验", str(dict(unchecked)))
    elif nodes:
        rep.add("D", "PASS", "来源均可溯源",
                f"核对 {len(nodes)} 节点；约定来源跳过 {dict(unchecked)}")


# ------------------------------------------------------- E. 三级一致性
def check_consistency(rep: Report, data: dict, graphrag_url: str | None) -> None:
    nodes, _ = data.get("nodes.csv", ([], []))
    edges, _ = data.get("edges.csv", ([], []))
    kg = data.get("kg")

    if kg is not None:
        kg_ids = {n.get("node_id") or n.get("id") for n in kg["nodes"]}
        csv_ids = {r["node_id"] for r in nodes}
        only_csv = csv_ids - kg_ids
        only_kg = kg_ids - csv_ids
        if only_csv or only_kg:
            rep.add("E", "CRITICAL", "CSV 与 knowledge_graph.json 节点集不一致",
                    f"仅CSV: {sorted(only_csv)[:8]} 仅JSON: {sorted(only_kg)[:8]}"
                    "（需重跑 knowledge-builder build）")
        else:
            rep.add("E", "PASS", "CSV ↔ JSON 节点集一致", f"{len(csv_ids)} 节点")
        if len(kg["edges"]) != len(edges):
            rep.add("E", "MAJOR", "CSV 与 JSON 边数不一致",
                    f"csv={len(edges)} json={len(kg['edges'])}")
        csv_keys = Counter((e.get("source_id"), e.get("relation"), e.get("target_id")) for e in edges)
        json_keys = Counter((e.get("source_id", e.get("source")),
                             e.get("relation", e.get("type")),
                             e.get("target_id", e.get("target"))) for e in kg["edges"])
        if any(None in key for key in json_keys):
            rep.add("E", "MAJOR", "JSON 边缺少端点或关系字段", "需包含 source_id/relation/target_id 或 source/type/target")
        elif csv_keys != json_keys:
            rep.add("E", "MAJOR", "CSV 与 JSON 边内容不一致", f"仅CSV: {list((csv_keys-json_keys).elements())[:8]}；仅JSON: {list((json_keys-csv_keys).elements())[:8]}")
        else:
            rep.add("E", "PASS", "CSV ↔ JSON 边三元组一致", f"{len(edges)} 条边")

    if not graphrag_url:
        rep.add("E", "SKIP", "GraphRAG 一致性未检查", "未提供 --graphrag-url")
        return
    try:
        with urllib.request.urlopen(graphrag_url.rstrip("/") + "/health", timeout=10) as r:
            health = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        rep.add("E", "SKIP", "GraphRAG 服务不可达", f"{type(e).__name__}: {e}")
        return
    if not isinstance(health, dict):
        rep.add("E", "MAJOR", "GraphRAG health 响应结构错误", str(health))
        return
    if not health.get("graphrag_index_loaded"):
        rep.add("E", "CRITICAL", "GraphRAG 索引未加载", str(health))
        return
    gn, ge = health.get("nodes"), health.get("edges")
    if (gn is not None and gn != len(nodes)) or (ge is not None and ge != len(edges)):
        rep.add("E", "MAJOR", "GraphRAG 索引与 CSV 不同步（索引陈旧）",
                f"graphrag nodes={gn} edges={ge} vs csv nodes={len(nodes)} edges={len(edges)}，需重建索引")
    elif gn is not None and ge is not None:
        rep.add("E", "PASS", "GraphRAG 索引与 CSV 计数一致", f"nodes={gn} edges={ge}（计数不能证明内容一致）")
    else:
        rep.add("E", "SKIP", "GraphRAG health 缺少节点或边计数", str(health))


# ------------------------------------------------------- F. 提取准确性抽检
def _norm_terms(text: str) -> set[str]:
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}|\d+", text.lower()))
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        terms.update(segment[i:i+2] for i in range(len(segment)-1))
    return terms


def _rfc_paths(source: str) -> list[Path]:
    match = re.match(r"rfc\s*(\d+)(?:\b|_)", source, re.I)
    if not match:
        return []
    number = match.group(1)
    return [p for p in RFC_DIR.glob("*") if p.is_file() and
            re.match(r"rfc\s*" + re.escape(number) + r"(?:\b|_)", p.stem, re.I)]


def check_accuracy(rep: Report, data: dict, sample: int) -> None:
    nodes, _ = data.get("nodes.csv", ([], []))
    if not nodes:
        return
    pool = [r for r in nodes if (r.get("source") or "").lower().startswith("rfc")]
    if sample > 0:
        pool = pool[:sample]
    checked, mismatched = 0, []
    for r in pool:
        paths = _rfc_paths(r["source"])
        if not paths:
            rep.add("F", "SKIP", f"{r['node_id']} 对应 RFC 语料缺失", r["source"])
            continue
        rfc_corpus = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in paths).lower()
        desc_terms = _norm_terms(r.get("description", "")) - {"the", "and", "for", "with", "isis"}
        if not desc_terms or not rfc_corpus:
            rep.add("F", "SKIP", f"{r['node_id']} 缺少可比对术语或来源内容", r["source"])
            continue
        desc_zh = bool(re.search(r"[\u4e00-\u9fff]", r.get("description", "")))
        corpus_zh = bool(re.search(r"[\u4e00-\u9fff]", rfc_corpus))
        if desc_zh != corpus_zh:
            rep.add("F", "INFO", f"{r['node_id']} 来源与描述可能跨语言，需人工复核", r["source"])
            continue
        checked += 1
        hit = sum(1 for t in desc_terms if t in rfc_corpus)
        if hit / len(desc_terms) < 0.5:
            mismatched.append(f"{r['node_id']}: 描述术语命中率 {hit}/{len(desc_terms)}"
                              f"（source={r['source']}）")
    if mismatched:
        rep.add("F", "MAJOR", f"{len(mismatched)}/{checked} 个节点描述术语与对应来源匹配不足",
                "\n".join(mismatched[:10]))
    elif checked:
        rep.add("F", "PASS", f"抽检 {checked} 个 RFC 节点通过词面比对", "不代表语义准确性已验证")

    # TLV code 与 isis_pdu.py 交叉核对
    attrs, _ = data.get("node_attributes.csv", ([], []))
    if attrs and ISIS_PDU.exists():
        pdu_text = ISIS_PDU.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(pdu_text)
            tlv_codes = set()
            for item in ast.walk(tree):
                if isinstance(item, (ast.Assign, ast.AnnAssign)):
                    targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                    if any(isinstance(t, ast.Name) and "TLV" in t.id.upper() for t in targets):
                        if isinstance(item.value, ast.Constant) and type(item.value.value) is int:
                            tlv_codes.add(item.value.value)
        except SyntaxError:
            tlv_codes = set()
        bad_tlv = []
        for a in attrs:
            if a.get("attribute") == "code" and (a.get("value") or "").isdigit():
                # pdu 源码中 TLV 以十进制或 0x 十六进制出现
                v = int(a["value"])
                if v not in tlv_codes:
                    bad_tlv.append(f"{a['node_id']}.code={v}")
        if bad_tlv:
            rep.add("F", "INFO", f"{len(bad_tlv)} 个 TLV code 未在 isis_pdu.py 中直接出现",
                    "可能正常（pdu 未用到），人工确认：" + ", ".join(bad_tlv[:10]))
        elif tlv_codes and any(a.get("attribute") == "code" for a in attrs):
            rep.add("F", "PASS", "TLV code 与 isis_pdu.py 交叉核对通过", "")
        else:
            rep.add("F", "SKIP", "未解析到可核对的 TLV 整数常量", str(ISIS_PDU))
    # 规则节点与规则 JSON 内容比对
    rule_nodes = [r for r in nodes if r.get("node_type") == "rule" and (r.get("source") or "").startswith("rule:")]
    missing = []
    for r in rule_nodes:
        fname = r["source"].split(":", 1)[1]
        path = RULES_DIR / fname
        if Path(fname).name != fname or not path.is_file():
            missing.append(r["node_id"])
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            rules = raw if isinstance(raw, list) else raw.get("rules", [raw])
            identifiers = set()
            for rule in rules:
                for rid in (rule.get("rule_id"), rule.get("id"), rule.get("name")):
                    if isinstance(rid, str) and rid.strip():
                        normalized = re.sub(r"[^a-zA-Z0-9]+", "_", rid.strip().lower()).strip("_")
                        if not normalized:
                            import hashlib
                            normalized = "zh_" + hashlib.md5(rid.strip().encode("utf-8")).hexdigest()[:10]
                        identifiers.add(normalized)
            if r["node_id"] not in identifiers:
                missing.append(r["node_id"])
        except (ValueError, TypeError, AttributeError, OSError):
            missing.append(r["node_id"])
    if missing:
        rep.add("F", "MAJOR", f"{len(missing)} 个规则节点在规则 JSON 中找不到同名定义",
                str(missing[:10]))


# ----------------------------------------------------------------- 输出
def render(rep: Report) -> str:
    counts = rep.counts()
    lines = [
        f"# 知识图谱验证报告 — {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        f"**结论**：{'❌ 存在 CRITICAL，需修复后重新验证' if rep.has_critical() else '✅ 无 CRITICAL 问题'}",
        f"**统计**：CRITICAL {counts.get('CRITICAL',0)} / MAJOR {counts.get('MAJOR',0)} "
        f"/ MINOR {counts.get('MINOR',0)} / INFO {counts.get('INFO',0)} "
        f"/ PASS {counts.get('PASS',0)} / SKIP {counts.get('SKIP',0)}",
        "",
    ]
    cur = None
    for check, level, title, evidence in rep.items:
        if check != cur:
            lines.append(f"\n## {check} 类检查")
            cur = check
        icon = {"CRITICAL": "🔴", "MAJOR": "🟠", "MINOR": "🟡",
                "INFO": "🔵", "PASS": "✅", "SKIP": "⏭️"}[level]
        lines.append(f"- {icon} [{level}] {title}")
        if evidence:
            for ln in evidence.splitlines()[:6]:
                lines.append(f"  > {ln}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="知识图谱提取准确性验证")
    ap.add_argument("--checks", default="A,B,C,D,E,F",
                    help="逗号分隔的检查类别，默认全部")
    ap.add_argument("--graphrag-url", default=os.environ.get("GRAPHRAG_URL", "http://localhost:9200"),
                    help="GraphRAG 服务地址；设为空串跳过")
    ap.add_argument("--sample", type=int, default=10, help="F 类抽检节点数，0=全量")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非 Markdown")
    args = ap.parse_args()

    checks = {c.strip().upper() for c in args.checks.split(",") if c.strip()}
    if not checks or checks - set("ABCDEF"):
        ap.error("--checks 只能包含 A,B,C,D,E,F，且不能为空")
    if args.sample < 0:
        ap.error("--sample 不能为负数")
    rep = Report()
    data: dict = {}
    if "A" in checks:
        data = check_schema(rep)
    else:  # 后续检查依赖数据；即使未选 A，也不能对损坏输入继续操作。
        prerequisites = Report()
        data = check_schema(prerequisites)
        rep.items.extend(item for item in prerequisites.items if item[1] == "CRITICAL")
    if rep.has_critical():
        rep.add("A", "SKIP", "结构错误，跳过依赖该数据的检查", "修复 CRITICAL 后重跑")
        checks = {"A"}
    if "B" in checks:
        check_integrity(rep, data)
    if "C" in checks:
        check_dedup(rep, data)
    if "D" in checks:
        check_sources(rep, data)
    if "E" in checks:
        check_consistency(rep, data, args.graphrag_url or None)
    if "F" in checks:
        check_accuracy(rep, data, args.sample)

    if args.json:
        print(json.dumps([{"check": c, "level": l, "title": t, "evidence": e}
                          for c, l, t, e in rep.items], ensure_ascii=False, indent=2))
    else:
        md = render(rep)
        print(md)
        VALIDATION_OUT.mkdir(parents=True, exist_ok=True)
        out = VALIDATION_OUT / f"kg_validation_{datetime.now():%Y%m%d_%H%M%S_%f}.md"
        out.write_text(md, encoding="utf-8")
        print(f"\n[报告已保存] {out}", file=sys.stderr)

    counts = rep.counts()
    print(f"[SUMMARY] CRITICAL={counts.get('CRITICAL',0)} MAJOR={counts.get('MAJOR',0)} "
          f"MINOR={counts.get('MINOR',0)} INFO={counts.get('INFO',0)}", file=sys.stderr)
    return 1 if rep.has_critical() else 0


if __name__ == "__main__":
    sys.exit(main())
