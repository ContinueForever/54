#!/usr/bin/env python3
"""GraphRAG 索引构建脚本（方案 B）。

用法:
    cd /home/hermes/workspace/graphrag && python -m graphrag_server.indexer
    cd /home/hermes/workspace/graphrag && python -m graphrag_server.indexer --dry-run

本脚本复用 Microsoft GraphRAG 2.7.2 的 CLI 内部入口。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 必须先 import 本地扩展以注册 local_tfidf provider
import graphrag_server

from graphrag.cli.index import index_cli
from graphrag.config.enums import IndexingMethod


def main():
    parser = argparse.ArgumentParser(description="Build GraphRAG index for agent-analysis.")
    parser.add_argument("--root", default=".", help="GraphRAG project root directory")
    parser.add_argument("--config", default="config/settings.yaml", help="settings.yaml path")
    parser.add_argument("--method", default="standard", help="Indexing method (standard, drift)")
    parser.add_argument("--dry-run", action="store_true", help="Validate config without indexing")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--no-cache", action="store_true", help="Disable LLM cache")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    config_path = root / args.config

    if not config_path.exists():
        print(f"[ERROR] Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    method = IndexingMethod(args.method)

    index_cli(
        root_dir=root,
        config_filepath=config_path,
        method=method,
        verbose=args.verbose,
        memprofile=False,
        cache=not args.no_cache,
        dry_run=args.dry_run,
        skip_validation=False,
        output_dir=None,
    )


if __name__ == "__main__":
    main()
