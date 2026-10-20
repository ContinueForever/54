"""graphrag-server — GraphRAG 查询服务（支持真实 GraphRAG + CSV 降级）。

在完全离线环境下，本服务优先使用真实 Microsoft GraphRAG 索引；
若索引未构建或查询失败，则降级到 CSV 知识图谱后端。
使用 Python 标准库 http.server，无需额外 HTTP 框架。
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# 加载 agent-analysis 的 knowledge_adapter（CSV 降级用）
WORKSPACE = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(WORKSPACE / "agent-analysis" / "src"))
from agent_analysis.knowledge_adapter import KnowledgeAdapter

TABLES_DIR = os.environ.get("GRAPH_RAG_TABLES_DIR", str(WORKSPACE / "knowledge" / "tables"))
adapter = KnowledgeAdapter(Path(TABLES_DIR))
adapter.load()


# 延迟加载 GraphRAG 真实索引，避免服务启动时阻塞
_graphrag_search = None

_LAST_QUERY_STATUS = "none"   # none / ok / empty / error
_LAST_QUERY_ERROR = ""


def _health_model_name() -> str:
    """读取当前配置的 chat 模型名（失败返回空串）。"""
    try:
        from graphrag.config.load_config import load_config
        root = Path(os.environ.get("GRAPHRAG_ROOT", WORKSPACE / "graphrag")).resolve()
        config_path = root / "config" / "settings.yaml"
        if not config_path.exists():
            return ""
        config = load_config(root, config_path, {})
        chat_config = config.models.get(config.local_search.chat_model_id)
        return chat_config.model if chat_config else ""
    except Exception:
        return ""


def _index_built_at() -> str:
    """返回索引最近构建时间（entities.parquet 的 mtime，ISO 格式）。"""
    try:
        root = Path(os.environ.get("GRAPHRAG_ROOT", WORKSPACE / "graphrag")).resolve()
        f = root / "output" / "entities.parquet"
        if f.exists():
            from datetime import datetime
            return datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return ""


def _load_graphrag_search():
    """尝试加载真实 GraphRAG 索引，返回 LocalSearch 实例或 None。"""
    global _graphrag_search
    if _graphrag_search is not None:
        return _graphrag_search

    try:
        import graphrag_server  # noqa: F401  触发 local_tfidf provider 注册
        from graphrag.config.load_config import load_config
        from graphrag.language_model.manager import ModelManager
        from graphrag.query.indexer_adapters import (
            read_indexer_entities,
            read_indexer_relationships,
            read_indexer_reports,
            read_indexer_text_units,
        )
        from graphrag.query.structured_search.local_search.mixed_context import (
            LocalSearchMixedContext,
        )
        from graphrag.query.structured_search.local_search.search import LocalSearch

        root = Path(os.environ.get("GRAPHRAG_ROOT", WORKSPACE / "graphrag")).resolve()
        config_path = root / "config" / "settings.yaml"
        if not config_path.exists():
            return None

        config = load_config(root, config_path, {})

        # 初始化 chat model
        chat_config = config.models.get(config.local_search.chat_model_id)
        chat_model = ModelManager().register_chat(
            name=chat_config.model,
            model_type=chat_config.type,
            config=chat_config,
            callbacks=None,
            cache=None,
        )

        # 初始化 embedding model
        embed_config = config.models.get(config.local_search.embedding_model_id)
        embedding_model = ModelManager().register_embedding(
            name=embed_config.model,
            model_type=embed_config.type,
            config=embed_config,
            callbacks=None,
            cache=None,
        )

        # 读取索引输出
        output_dir = root / "output"
        lancedb_dir = output_dir / "lancedb"
        if not lancedb_dir.exists():
            return None

        from graphrag.config.embeddings import entity_description_embedding
        from graphrag.utils.api import get_embedding_store

        vector_store_args = {index: store.model_dump() for index, store in config.vector_store.items()}
        vector_store = get_embedding_store(
            config_args=vector_store_args,
            embedding_name=entity_description_embedding,
        )

        # 检查必要 Parquet 文件是否存在（新版 GraphRAG 输出无 create_final_ 前缀）
        f_entities = output_dir / "entities.parquet"
        f_communities = output_dir / "communities.parquet"
        f_relationships = output_dir / "relationships.parquet"
        f_reports = output_dir / "community_reports.parquet"
        f_text_units = output_dir / "text_units.parquet"
        required_files = [f_entities, f_communities, f_relationships, f_reports, f_text_units]
        if not all(f.exists() for f in required_files):
            return None

        import pandas as pd

        level = int(os.environ.get("GRAPHRAG_COMMUNITY_LEVEL", "2"))
        entities = read_indexer_entities(pd.read_parquet(f_entities), pd.read_parquet(f_communities), level)
        relationships = read_indexer_relationships(pd.read_parquet(f_relationships))
        reports = read_indexer_reports(pd.read_parquet(f_reports), pd.read_parquet(f_communities), level)
        text_units = read_indexer_text_units(pd.read_parquet(f_text_units))

        context_builder = LocalSearchMixedContext(
            community_reports=reports,
            text_units=text_units,
            entities=entities,
            relationships=relationships,
            entity_text_embeddings=vector_store,
            text_embedder=embedding_model,
        )

        local_search = LocalSearch(
            model=chat_model,
            context_builder=context_builder,
            tokenizer=None,
            model_params={
                "max_tokens": 4000,
                "temperature": 1.0,
                "top_p": 0.95,
            },
            context_builder_params={
                "text_unit_prop": 0.5,
                "community_prop": 0.1,
                "conversation_history_max_turns": 5,
                "top_k_mapped_entities": 10,
                "top_k_relationships": 10,
                "include_community_rank": True,
                "include_entity_rank": True,
                "include_community_reports": True,
                "include_relationships": True,
            },
            response_type="multiple paragraphs",
        )

        _graphrag_search = local_search
        return _graphrag_search
    except Exception as e:
        print(f"[WARN] GraphRAG index not available, fallback to CSV backend: {e}", flush=True)
        _graphrag_search = None
        return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 保持安静

    def _json_response(self, status: int, data: Any):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            graphrag_loaded = _load_graphrag_search() is not None
            return self._json_response(200, {
                "status": "ok",
                "graphrag_index_loaded": graphrag_loaded,
                "model": _health_model_name(),
                "index_built_at": _index_built_at(),
                "last_query_status": _LAST_QUERY_STATUS,
                "last_query_error": _LAST_QUERY_ERROR,
                "nodes": len(adapter.nodes),
                "edges": len(adapter.edges),
            })

        if path.startswith("/node/"):
            node_id = path[len("/node/"):]
            n = adapter.get_node(node_id)
            if not n:
                return self._json_response(404, {"error": "not found"})
            related = adapter.find_related(node_id)
            return self._json_response(200, {"node": n, "related": related})

        return self._json_response(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/query":
            return self._json_response(404, {"error": "not found"})

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}

        q = payload.get("query", "")
        if not q:
            return self._json_response(400, {"error": "query is required"})

        # 优先使用 GraphRAG 真实索引
        graphrag_search = _load_graphrag_search()
        if graphrag_search is not None:
            try:
                import asyncio

                result = asyncio.run(graphrag_search.search(q))
                response_text = result.response if hasattr(result, "response") else str(result)
                if response_text and response_text.strip():
                    _LAST_QUERY_STATUS = "ok"
                    _LAST_QUERY_ERROR = ""
                    return self._json_response(200, {
                        "query": q,
                        "source": "graphrag",
                        "result": response_text,
                    })
                # 空回答视为失败：降级 CSV，且不再按 graphrag 命中计
                _LAST_QUERY_STATUS = "empty"
                _LAST_QUERY_ERROR = "模型返回空回答"
                print("[WARN] GraphRAG empty response, fallback to CSV backend", flush=True)
            except Exception as e:
                # GraphRAG 查询失败则降级 CSV
                _LAST_QUERY_STATUS = "error"
                _LAST_QUERY_ERROR = str(e)
                print(f"[WARN] GraphRAG query failed: {e}", flush=True)

        # CSV 降级查询
        results = adapter.query_by_name(q)
        enriched = []
        for node in results:
            related = adapter.find_related(node.get("node_id", ""))
            enriched.append({"node": node, "related": related})

        return self._json_response(200, {
            "query": q,
            "source": "csv_fallback",
            "hits": len(results),
            "results": enriched,
        })


def run_server(host: str = "0.0.0.0", port: int = 9200, tables_dir: str | None = None):
    global adapter, TABLES_DIR
    if tables_dir:
        TABLES_DIR = tables_dir
        adapter = KnowledgeAdapter(Path(tables_dir))
        adapter.load()

    server = HTTPServer((host, port), Handler)
    print(f"graphrag-server listening on http://{host}:{port}")
    print("  GraphRAG index will be loaded lazily on first query/health check")
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
    parser.add_argument("--port", type=int, default=9200)
    parser.add_argument("--tables-dir", default=TABLES_DIR)
    args = parser.parse_args()
    run_server(args.host, args.port, args.tables_dir)


if __name__ == "__main__":
    main()