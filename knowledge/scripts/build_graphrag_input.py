#!/usr/bin/env python3
"""Generate GraphRAG input text from knowledge tables and RFC summaries."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE", "/home/hermes/workspace"))
KNOWLEDGE_DIR = WORKSPACE / "knowledge"
GR_INPUT_DIR = WORKSPACE / "graphrag" / "input"


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_input_text() -> str:
    nodes = load_csv(KNOWLEDGE_DIR / "tables" / "nodes.csv")
    edges = load_csv(KNOWLEDGE_DIR / "tables" / "edges.csv")
    rfc_files = sorted((KNOWLEDGE_DIR / "rfc").glob("*.md"))

    chunks: list[str] = []

    # RFC summaries as documents
    for rfc_file in rfc_files:
        title = rfc_file.stem.replace("_summary", "").upper()
        content = rfc_file.read_text(encoding="utf-8")
        chunks.append(f"# {title}\n{content}\n")

    # Nodes as entities
    for node in nodes:
        nid = node.get("node_id", "").strip()
        ntype = node.get("node_type", "").strip()
        name = node.get("name", "").strip()
        desc = node.get("description", "").strip()
        source = node.get("source", "").strip()
        if not nid:
            continue
        lines = [f"## Entity: {name} ({nid})"]
        lines.append(f"Type: {ntype}")
        lines.append(f"Description: {desc}")
        if source:
            lines.append(f"Source: {source}")
        # Append related edges
        for edge in edges:
            if edge.get("source_id") == nid:
                rel = edge.get("relation", "").strip()
                tgt = edge.get("target_id", "").strip()
                edesc = edge.get("description", "").strip()
                lines.append(f"Relationship: {nid} --{rel}--> {tgt}. {edesc}")
        chunks.append("\n".join(lines) + "\n")

    return "\n---\n".join(chunks)


def main():
    GR_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    text = build_input_text()
    out_file = GR_INPUT_DIR / "knowledge_graph.txt"
    out_file.write_text(text, encoding="utf-8")
    print(f"[OK] GraphRAG input written: {out_file}")
    print(f"     chars: {len(text)}, lines: {len(text.splitlines())}")


if __name__ == "__main__":
    main()
