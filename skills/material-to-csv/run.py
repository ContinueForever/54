#!/usr/bin/env python3
"""material-to-csv — 素材转 CSV 知识表格。

三个子命令：
  extract  从素材提取候选 nodes/edges 到 knowledge/incoming/<batch>/
  diff     候选批次与现有 knowledge/tables/ 对比（新增/重复/冲突）
  merge    人工确认后合并进 knowledge/tables/（自动快照，幂等去重）

Schema 契约（与项目现有表格一致）：
  nodes.csv: node_id,node_type,name,description,source
  edges.csv: source_id,relation,target_id,description
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import subprocess
import sys
import os
import tempfile
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE", Path(__file__).resolve().parents[2])).resolve()
TABLES = WORKSPACE / "knowledge" / "tables"
INCOMING = WORKSPACE / "knowledge" / "incoming"
RULES_DIR = WORKSPACE / "agent-analysis" / "config" / "diagnosis_rules"

NODES_COLS = ["node_id", "node_type", "name", "description", "source"]
EDGES_COLS = ["source_id", "relation", "target_id", "description"]
ATTRS_COLS = ["node_id", "attribute", "value"]

# 日志事件关键词 → (node_id, node_type, name) 映射（与现有知识库对齐）
LOG_EVENT_MAP = {
    "adjacency.*down|邻接.*中断": ("adjacency_down", "state", "Adjacency Down"),
    "adjacency.*up|邻接.*建立": ("adjacency_up", "state", "Adjacency Up"),
    "authentication fail|auth.*fail|认证失败": ("auth_mismatch", "fault", "Authentication Mismatch"),
    "area mismatch|区域.*不匹配": ("area_mismatch", "fault", "Area Mismatch"),
    "mtu": ("mtu_mismatch", "fault", "MTU Mismatch"),
    "holding timer|hold timer|hello timer": ("hello_timer_mismatch", "fault", "Hello Timer Mismatch"),
    "duplicate system id": ("duplicate_system_id", "fault", "Duplicate System ID"),
    "circuit type": ("circuit_type_mismatch", "fault", "Circuit Type Mismatch"),
    "lsp.*suppress": ("lsp_suppression", "fault", "LSP Suppression"),
    "interface.*down|link.*down": ("link_down", "fault", "Link Down"),
}

# RFC 文本句式 → 边关系（英文 + 中文）
RELATION_PATTERNS = [
    (r"(\w[\w\s\-]{2,40}?)\s+(?:can\s+)?cause[s]?\s+(\w[\w\s\-]{2,40}?)[.,]", "causes"),
    (r"(\w[\w\s\-]{2,40}?)\s+prevent[s]?\s+(\w[\w\s\-]{2,40}?)[.,]", "prevents"),
    (r"(\w[\w\s\-]{2,40}?)\s+(?:may\s+)?indicate[s]?\s+(\w[\w\s\-]{2,40}?)[.,]", "indicates"),
    (r"(\w[\w\s\-]{2,40}?)\s+lead[s]?\s+to\s+(\w[\w\s\-]{2,40}?)[.,]", "causes"),
    (r"([\u4e00-\u9fff\w][\u4e00-\u9fff\w\s\-]{1,30}?)(?:会)?(?:导致|引起|造成)([\u4e00-\u9fff\w][\u4e00-\u9fff\w\s\-]{1,30}?)[，。,.]", "causes"),
    (r"([\u4e00-\u9fff\w][\u4e00-\u9fff\w\s\-]{1,30}?)(?:表明|指示|说明存在)([\u4e00-\u9fff\w][\u4e00-\u9fff\w\s\-]{1,30}?)[，。,.]", "indicates"),
    (r"([\u4e00-\u9fff\w][\u4e00-\u9fff\w\s\-]{1,30}?)(?:防止|避免)([\u4e00-\u9fff\w][\u4e00-\u9fff\w\s\-]{1,30}?)[，。,.]", "prevents"),
]

TLV_PATTERN = re.compile(
    r"TLV[:\s]+(\w[\w\s/\-]{1,30}?)[,\s]+(?:Type|Code|code)[:\s=]+(\d{1,3})\b", re.I)


def snake(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s.strip().lower()).strip("_")
    return re.sub(r"_+", "_", s)


def entity_id(name: str) -> str:
    name = name.strip()
    return (snake(name) or "zh_" + hashlib.md5(name.encode("utf-8")).hexdigest()[:10]) if name else ""


def node_type(name: str) -> str:
    if re.search(r"mismatch|fail|down|loss|error|suppress|duplicate|失败|中断|异常|不匹配", name, re.I):
        return "fault"
    if re.search(r"\bup\b|established|normal|正常|建立", name, re.I):
        return "state"
    return "symptom"


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------ 提取器
def extract_rfc(text: str, source: str) -> tuple[list[dict], list[dict], list[dict]]:
    """从 RFC 文本提取节点/边/TLV 属性。"""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    attrs: list[dict] = []

    # 故障/症状条目：**Term** 或 "Term: description" 或 "- Term — description"
    # 兼容中文条目（如 "- 邻接中断：邻居关系丢失"）；纯中文名称用内容哈希生成 ID
    for m in re.finditer(
            r"(?:^|\n)[ \t]*(?:\*\*|-|\d+\.)[ \t]*(?:\*\*)?([A-Z一-鿿][A-Za-z一-鿿 \t\-]{1,40}?)"
            r"(?:\*\*)?[ \t]*[:：—–-][ \t]*([^\n]{1,160})", text):
        name, desc = m.group(1).strip(), m.group(2).strip()
        nid = entity_id(name)
        if len(nid) < 4 or nid in nodes:
            continue
        ntype = "fault" if re.search(r"mismatch|fail|down|loss|error|suppress|duplicate|失败|中断|异常|不匹配", nid + name) \
            else "state" if re.search(r"\bup\b|established|normal|正常|建立", nid + name) else "symptom"
        nodes[nid] = {"node_id": nid, "node_type": ntype, "name": name,
                      "description": desc[:200], "source": source}

    # 因果关系边
    existing = {r.get("name", "").strip().casefold(): r for r in load_csv(TABLES / "nodes.csv")}
    for pat, rel in RELATION_PATTERNS:
        # Match each sentence independently: \s in the legacy patterns must not
        # capture a previous heading or another line as part of an entity.
        for m in (match for sentence in re.split(r"[\r\n]+", text)
                  for match in re.finditer(pat, sentence, re.I)):
            names = [m.group(1).strip(), m.group(2).strip()]
            ids = []
            for name in names:
                local = next((n for n in nodes.values() if n["name"].casefold() == name.casefold()), None)
                known = local or existing.get(name.casefold())
                nid = known["node_id"] if known else entity_id(name)
                ids.append(nid)
                if nid and not known:
                    nodes.setdefault(nid, {"node_id": nid, "node_type": node_type(name),
                                           "name": name, "description": m.group(0).strip()[:200],
                                           "source": source})
            sid, tid = ids
            if sid and tid and sid != tid:
                edges.append({"source_id": sid, "relation": rel, "target_id": tid,
                              "description": m.group(0).strip()[:200]})

    # TLV 定义（两种书写格式）
    # 格式一：TLV: Area Address, Type: 1
    for m in TLV_PATTERN.finditer(text):
        tname, code = m.group(1).strip(), m.group(2)
        nid = "tlv_" + entity_id(tname)
        nodes.setdefault(nid, {"node_id": nid, "node_type": "tlv",
                               "name": f"TLV {tname}", "description": f"TLV {tname}, code {code}",
                               "source": source})
        attrs.append({"node_id": nid, "attribute": "code", "value": code})
    # 格式二（项目 RFC 摘要常用）：- **TLV 128 (IP Internal Reachability)**：宣告直连前缀。
    for m in re.finditer(
            r"TLV\s+(\d{1,3})\s*\(([\w\s/\-]{2,40})\)\*{0,2}\s*[:：]?\s*([^\n]{0,120})",
            text):
        code, tname, desc = m.group(1), m.group(2).strip(), m.group(3).strip()
        nid = "tlv_" + (snake(tname) or code)
        nodes.setdefault(nid, {"node_id": nid, "node_type": "tlv",
                               "name": f"TLV {code} ({tname})",
                               "description": (desc or f"TLV {tname}, code {code}")[:200],
                               "source": source})
        attrs.append({"node_id": nid, "attribute": "code", "value": code})

    return list(nodes.values()), edges, attrs


def extract_log(text: str, source: str) -> tuple[list[dict], list[dict], list[dict]]:
    """从日志提取事件节点；未知事件标 candidate 供人工判读。"""
    nodes: dict[str, dict] = {}
    unknown_lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "ISIS" not in line.upper():
            continue
        matched = False
        for pat, (nid, ntype, name) in LOG_EVENT_MAP.items():
            if re.search(pat, line, re.I):
                matched = True
                nodes.setdefault(nid, {"node_id": nid, "node_type": ntype, "name": name,
                                       "description": f"日志事件：{line[:120]}", "source": source})
                break
        if not matched:
            unknown_lines.append(line)
    # 未知事件 → candidate 节点，留待人工/LLM 判读
    for i, line in enumerate(unknown_lines[:20]):
        frag = entity_id(re.split(r"ISIS\s*:", line, maxsplit=1, flags=re.I)[-1])[:40]
        if not frag:
            continue
        nid = f"candidate_{frag}"
        nodes.setdefault(nid, {"node_id": nid, "node_type": "unknown",
                               "name": line[:60], "description": f"未识别日志事件，需人工判读：{line[:120]}",
                               "source": source})
    return list(nodes.values()), [], []


def extract_table(path: Path, source: str) -> tuple[list[dict], list[dict], list[dict]]:
    """规整既有 CSV 到标准 schema（列名容错映射）。"""
    rows = load_csv(path)
    nodes, edges = [], []
    if not rows:
        return nodes, edges, []
    header = set(rows[0].keys())
    if {"source_id", "relation", "target_id"} <= header:
        edges = [{k: r.get(k, "") for k in EDGES_COLS} | {"source": source} for r in rows]
    else:
        # 列名容错映射：英文/中文常见表头
        ID_ALIASES = ("node_id", "id", "ID", "编号", "节点ID")
        NAME_ALIASES = ("name", "Name", "名称", "故障名称", "节点名称", "现象")
        TYPE_ALIASES = ("node_type", "type", "类型")
        DESC_ALIASES = ("description", "desc", "描述", "说明", "备注")
        id_col = next((c for c in ID_ALIASES if c in header), None)
        name_col = next((c for c in NAME_ALIASES if c in header), None)
        type_col = next((c for c in TYPE_ALIASES if c in header), None)
        desc_col = next((c for c in DESC_ALIASES if c in header), None)
        if id_col or name_col:
            for r in rows:
                raw_id = r.get(id_col, "") if id_col else ""
                name = r.get(name_col, "") if name_col else raw_id
                nid = entity_id(raw_id) or entity_id(name)
                if not nid:
                    continue
                nodes.append({
                    "node_id": nid,
                    "node_type": r.get(type_col, "fault") if type_col else "fault",
                    "name": name,
                    "description": r.get(desc_col, "") if desc_col else "",
                    "source": source})
        else:
            print(f"[WARN] 未识别的表头 {sorted(header)}：需要 id/名称 类列或"
                  f" source_id,relation,target_id 边表结构；请按 references/extraction-guide.md"
                  f" 改写为 manual CSV", file=sys.stderr)
    return nodes, edges, []


def extract_rule_json(path: Path, source: str) -> tuple[list[dict], list[dict], list[dict]]:
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data if isinstance(data, list) else data.get("rules", [data])
    nodes = []
    for r in rules:
        rid = r.get("rule_id") or r.get("id") or r.get("name")
        if not rid:
            continue
        nodes.append({"node_id": entity_id(rid), "node_type": "rule",
                      "name": r.get("name", rid),
                      "description": (r.get("description") or r.get("action") or "")[:200],
                      "source": source})
    return nodes, [], []


# ------------------------------------------------------------------ 子命令
def cmd_extract(args: argparse.Namespace) -> int:
    src = Path(args.material)
    if not src.exists():
        print(f"[ERROR] 素材不存在: {src}", file=sys.stderr)
        return 1
    source_tag = args.source
    if args.batch and (Path(args.batch).name != args.batch or args.batch in (".", "..")):
        raise ValueError("--batch 必须是批次目录名，不能包含路径")
    text_suffix = src.suffix.lower()

    if source_tag.startswith("log:") or text_suffix == ".log":
        nodes, edges, attrs = extract_log(src.read_text(encoding="utf-8", errors="replace"), source_tag)
    elif source_tag.startswith("table:") or text_suffix == ".csv":
        nodes, edges, attrs = extract_table(src, source_tag)
    elif source_tag.startswith("rule:") or text_suffix == ".json":
        nodes, edges, attrs = extract_rule_json(src, source_tag)
    else:
        nodes, edges, attrs = extract_rfc(src.read_text(encoding="utf-8", errors="replace"), source_tag)

    batch = INCOMING / (args.batch or datetime.now().strftime("%Y%m%d_%H%M%S"))
    if not nodes and not edges and not attrs:
        print("[WARN] 本次提取结果为空！常见原因：", file=sys.stderr)
        print("  - 素材为自由中文文本：正则只覆盖结构化句式，请由 Hermes 按", file=sys.stderr)
        print("    references/extraction-guide.md 判读后写 manual_nodes.csv/manual_edges.csv", file=sys.stderr)
        print("  - 日志行不含 'ISIS' 关键词或不匹配已知事件模板", file=sys.stderr)
        print("  - CSV 表头非标准（需要 node_id/名称 或 source_id,relation,target_id）", file=sys.stderr)
    write_csv(batch / "candidate_nodes.csv", NODES_COLS, nodes)
    write_csv(batch / "candidate_edges.csv", EDGES_COLS, edges)
    write_csv(batch / "candidate_attributes.csv", ATTRS_COLS, attrs)

    # 自动附带 diff，便于人工审阅
    diff_text = build_diff(nodes, edges)
    (batch / "diff_report.md").write_text(diff_text, encoding="utf-8")
    print(diff_text)
    print(f"\n[候选批次] {batch}")
    print("下一步：人工审阅 diff_report.md → run.py diff <批次> → run.py merge <批次>")
    return 0


def unique_rows(rows: list[dict], keys: list[str], cols: list[str]) -> list[dict]:
    result = {}
    for row in rows:
        if any(not isinstance(row.get(c), str) for c in cols):
            raise ValueError(f"候选记录缺列或行长度错误: {row}")
        key = tuple(row[c].strip() for c in keys)
        if any(not value for value in key):
            raise ValueError(f"候选记录主键为空: {row}")
        normalized = {c: row[c] for c in cols}
        if key in result and result[key] != normalized:
            raise ValueError(f"候选批次内部同键不同内容，需人工裁决: {key}")
        result[key] = normalized
    return list(result.values())


def _diff_sets(nodes: list[dict], edges: list[dict]):
    nodes = unique_rows(nodes, ["node_id"], NODES_COLS)
    edges = unique_rows(edges, EDGES_COLS[:3], EDGES_COLS)
    old_nodes = {r["node_id"]: r for r in load_csv(TABLES / "nodes.csv")}
    old_edges = {(r["source_id"], r["relation"], r["target_id"])
                 for r in load_csv(TABLES / "edges.csv")}
    new_n, dup_n, conflict_n = [], [], []
    for n in nodes:
        nid = n["node_id"]
        if nid not in old_nodes:
            new_n.append(n)
        elif all((old_nodes[nid].get(c, "") or "") == (n.get(c, "") or "") for c in NODES_COLS):
            dup_n.append(n)
        else:
            conflict_n.append((old_nodes[nid], n))
    new_e = [e for e in edges
             if (e["source_id"], e["relation"], e["target_id"]) not in old_edges]
    dup_e = [e for e in edges
             if (e["source_id"], e["relation"], e["target_id"]) in old_edges]
    return new_n, dup_n, conflict_n, new_e, dup_e


def build_diff(nodes: list[dict], edges: list[dict]) -> str:
    new_n, dup_n, conflict_n, new_e, dup_e = _diff_sets(nodes, edges)
    lines = [
        f"# 素材导入差异报告 — {datetime.now():%Y-%m-%d %H:%M:%S}", "",
        f"- 新增节点：{len(new_n)}　重复跳过：{len(dup_n)}　冲突待裁决：{len(conflict_n)}",
        f"- 新增边：{len(new_e)}　重复跳过：{len(dup_e)}", "",
        "## 新增节点",
    ]
    lines += [f"- `{n['node_id']}` ({n['node_type']}) {n['name']}" for n in new_n] or ["- 无"]
    lines.append("\n## 冲突（同 ID 不同描述，merge 默认保留旧值，--prefer-new 覆盖）")
    for old, new in conflict_n:
        lines.append(f"- `{old['node_id']}`\n  - 旧：{old.get('description','')[:100]}"
                     f"\n  - 新：{new.get('description','')[:100]}")
    if not conflict_n:
        lines.append("- 无")
    warns = [n["node_id"] for n in new_n if n["node_type"] == "composite_fault"
             and not any(e["source_id"] == n["node_id"] and e["relation"] == "combines"
                         for e in new_e)]
    if warns:
        lines.append(f"\n## ⚠️ WARN：复合节点缺少 combines 边（合并后 kg-validator B 类将报 MAJOR）")
        lines += [f"- `{w}`" for w in warns]
    return "\n".join(lines)


def cmd_diff(args: argparse.Namespace) -> int:
    batch = Path(args.batch)
    if not batch.is_dir():
        raise ValueError(f"候选批次不存在: {batch}")
    nodes = load_csv(batch / "candidate_nodes.csv") + load_csv(batch / "manual_nodes.csv")
    edges = load_csv(batch / "candidate_edges.csv") + load_csv(batch / "manual_edges.csv")
    print(build_diff(nodes, edges))
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    batch = Path(args.batch)
    if not batch.is_dir() or not any((batch / f).exists() for f in
                                    ("candidate_nodes.csv", "manual_nodes.csv", "candidate_edges.csv", "manual_edges.csv", "candidate_attributes.csv", "manual_attributes.csv")):
        raise ValueError(f"候选批次不存在或没有候选表: {batch}")
    nodes = load_csv(batch / "candidate_nodes.csv") + load_csv(batch / "manual_nodes.csv")
    edges = load_csv(batch / "candidate_edges.csv") + load_csv(batch / "manual_edges.csv")
    new_n, dup_n, conflict_n, new_e, dup_e = _diff_sets(nodes, edges)
    merged_nodes = load_csv(TABLES / "nodes.csv")
    for old, new in conflict_n:
        if args.prefer_new:
            merged_nodes = [new if r["node_id"] == old["node_id"] else r for r in merged_nodes]
    merged_nodes += new_n
    merged_edges = load_csv(TABLES / "edges.csv") + new_e
    old_attrs = unique_rows(load_csv(TABLES / "node_attributes.csv"), ATTRS_COLS[:2], ATTRS_COLS)
    incoming_attrs = unique_rows(load_csv(batch / "candidate_attributes.csv") + load_csv(batch / "manual_attributes.csv"), ATTRS_COLS[:2], ATTRS_COLS)
    attr_map = {(a["node_id"], a["attribute"]): a for a in old_attrs}
    for a in incoming_attrs:
        key = (a["node_id"], a["attribute"])
        if key in attr_map and attr_map[key]["value"] != a["value"] and not args.prefer_new:
            raise ValueError(f"属性冲突: {key}，请人工裁决或使用 --prefer-new")
        attr_map[key] = a
    merged_attrs = list(attr_map.values())
    ids = {n["node_id"] for n in merged_nodes}
    if len(ids) != len(merged_nodes):
        raise ValueError("合并结果包含重复 node_id")
    if any(not n.get("name", "").strip() or not n.get("source", "").strip() for n in merged_nodes):
        raise ValueError("节点 name/source 不能为空")
    valid_types = {"fault", "state", "device", "symptom", "protocol", "rule", "composite_fault", "tlv", "interface", "unknown"}
    if any(n.get("node_type") not in valid_types for n in merged_nodes):
        raise ValueError("合并结果包含非法 node_type")
    merged_edges = unique_rows(merged_edges, EDGES_COLS[:3], EDGES_COLS)
    merged_attrs = unique_rows(merged_attrs, ATTRS_COLS[:2], ATTRS_COLS)
    if any(e["source_id"] not in ids or e["target_id"] not in ids for e in merged_edges):
        raise ValueError("合并结果包含悬空边，未修改正式表")
    if any(a["node_id"] not in ids for a in merged_attrs):
        raise ValueError("合并结果包含悬空属性，未修改正式表")
    types = {n["node_id"]: n["node_type"] for n in merged_nodes}
    for e in merged_edges:
        if e["relation"] == "combines" and (types[e["source_id"]] != "composite_fault" or types[e["target_id"]] != "fault"):
            raise ValueError("combines 端点类型错误，未修改正式表")
    for nid, ntype in types.items():
        if ntype == "composite_fault" and len({e["target_id"] for e in merged_edges if e["source_id"] == nid and e["relation"] == "combines"}) < 2:
            raise ValueError(f"复合节点 {nid} 不足两个不同的 fault 子节点")
    snap = batch / "merge_snapshot"
    if snap.exists() and (any(snap.glob("*.csv")) or (snap / ".initialized").exists()):
        # 已有快照 = 本批次此前 merge 过；保留最早快照（首次 merge 前的状态），
        # 否则重复 merge 会把"已合并状态"存成快照，导致回滚失效
        print(f"[快照] 已存在，保留首次 merge 前的原始快照（{snap}）")
    else:
        snap.mkdir(parents=True, exist_ok=True)
        for f in TABLES.glob("*.csv"):
            shutil.copy2(f, snap / f.name)
        (snap / ".initialized").touch()

    TABLES.mkdir(parents=True, exist_ok=True)
    staged = []
    backups = {}
    try:
        for fname, cols, rows in (("nodes.csv", NODES_COLS, merged_nodes),
                                   ("edges.csv", EDGES_COLS, merged_edges),
                                   ("node_attributes.csv", ATTRS_COLS, merged_attrs)):
            target = TABLES / fname
            backups[target] = target.read_bytes() if target.exists() else None
            fd, temporary = tempfile.mkstemp(dir=TABLES, suffix=".tmp")
            os.close(fd)
            staged.append((Path(temporary), target))
            write_csv(Path(temporary), cols, rows)
        replaced = []
        try:
            for temporary, target in staged:
                os.replace(temporary, target)
                replaced.append(target)
        except Exception:
            for target in replaced:
                if backups[target] is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(backups[target])
            raise
    finally:
        for temporary, target in staged:
            temporary.unlink(missing_ok=True)

    print(f"[MERGED] 新增节点 {len(new_n)}，覆盖冲突 {len(conflict_n) if args.prefer_new else 0}，"
          f"新增边 {len(new_e)}；跳过重复节点 {len(dup_n)} / 边 {len(dup_e)}")
    print(f"[快照] {snap}（回滚 = 快照内 CSV 拷回 knowledge/tables/）")
    # 正式表已提交；构建失败时保留首次合并前快照，并明确返回失败。
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts_lib"))
    from runner import build_knowledge_graph, build_graphrag_input, build_graphrag_index
    try:
        build_knowledge_graph()
        build_graphrag_input()
        if args.index:
            build_graphrag_index()
        else:
            print("[INFO] 本地图谱已构建并校验；GraphRAG 索引尚未更新，需运行 knowledge-builder graphrag-index。")
    except subprocess.CalledProcessError:
        print(f"[ERROR] 表格已合并，但后续构建或校验失败；请检查报告。合并前快照：{snap}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="素材转 CSV 知识表格")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("extract", help="从素材提取候选表格")
    p.add_argument("material", help="素材文件路径（.txt/.md/.log/.csv/.json）")
    p.add_argument("--source", required=True,
                   help="来源标注：RFC5301 / log:<文件名> / table:<文件名> / rule:<文件名>")
    p.add_argument("--batch", help="批次目录名（默认时间戳）")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("diff", help="候选批次与现有库对比")
    p.add_argument("batch", help="批次目录")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("merge", help="合并候选批次进 knowledge/tables/")
    p.add_argument("batch", help="批次目录")
    p.add_argument("--prefer-new", action="store_true", help="冲突时采用新值（默认保留旧值）")
    p.add_argument("--index", action="store_true", help="合并、构建和校验后继续更新 GraphRAG 索引")
    p.set_defaults(fn=cmd_merge)

    args = ap.parse_args()
    try:
        return args.fn(args)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
