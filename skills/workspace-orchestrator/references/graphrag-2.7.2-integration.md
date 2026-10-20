# GraphRAG 2.7.2 本地集成要点

## 背景

项目使用 `graphrag` 官方包（2.7.2）作为底层索引/查询引擎，但本地服务代码不能放在 `graphrag` 包名下，否则会与 `site-packages/graphrag` 冲突。

## 目录结构

```
graphrag/
├── config/
│   └── settings.yaml          # 核心配置
├── input/                     # GraphRAG 输入文本
├── output/                    # 索引输出（Parquet + lancedb）
├── prompts/                   # *.txt prompt 文件
├── src/
│   └── graphrag_server/       # 本地服务模块
│       ├── __init__.py        # 注册 local_tfidf provider
│       ├── __main__.py        # 旧入口，保持兼容
│       ├── indexer.py         # 调用官方 graphrag.index.index CLI
│       ├── local_embedding.py # 本地 TF-IDF embedding provider
│       └── server.py          # HTTP 查询服务（GraphRAG + CSV 降级）
├── .env                       # API key 等敏感配置
└── logs/                      # GraphRAG 日志
```

## 本地模块命名

必须使用 `graphrag_server` 而不是 `graphrag`。

错误：
```bash
PYTHONPATH=graphrag/src python -m graphrag.indexer
# 会报 ModuleNotFoundError: No module named 'graphrag.cli'
```

正确：
```bash
PYTHONPATH=graphrag/src python -m graphrag_server.indexer
```

## 自定义 Embedding Provider

GraphRAG 2.7.2 的模型创建由 `type` 字段驱动，而不是 `model_provider`。

在 indexer 入口顶部必须显式导入本地包以触发注册：

```python
import graphrag_server  # noqa: F401  触发 local_tfidf provider 注册
from graphrag.cli.index import index_cli
```

注册 `local_tfidf` provider：

```python
from graphrag_server.local_embedding import LocalTfidfEmbeddingModel
from graphrag.language_model.factory import ModelFactory

ModelFactory.register_embedding(
    "local_tfidf",
    lambda **kwargs: LocalTfidfEmbeddingModel(**kwargs)
)
```

配置：

```yaml
models:
  default_embedding_model:
    type: local_tfidf
    model_provider: local_tfidf
    auth_type: api_key
    api_key: local
    model: local_tfidf
    encoding_model: cl100k_base
```

`LocalTfidfEmbeddingModel` 必须实现 `graphrag.language_model.protocol.EmbeddingModel` 协议：

```python
class LocalTfidfEmbeddingModel:
    def __init__(self, **kwargs): ...
    async def aembed(self, text: str, **kwargs) -> list[float]: ...
    async def aembed_batch(self, texts: list[str], **kwargs) -> list[list[float]]: ...
    def encode(self, text: str, **kwargs) -> list[float]: ...
```

## 索引构建

```bash
cd /home/hermes/workspace/graphrag
PYTHONPATH=src python -m graphrag_server.indexer --verbose
```

等价于：

```python
from graphrag.cli.index import index_cli

index_cli(
    root_dir="/home/hermes/workspace/graphrag",
    verbose=True,
    resume=False,
    memprofile=False,
    cache_reuse=True,
    emit=None,
    dry_run=False,
    config=None,
)
```

## Prompt 文件格式

GraphRAG 2.7.2 期望 `prompts/*.txt` 文件，而不是 `.py` 文件。如果目录下只有 `.py`，会报：

```
FileNotFoundError: [Errno 2] No such file or directory: '.../prompts/extract_graph.txt'
```

需要把项目中原有的 `.py` prompt 转换成 `.txt` 文件。转换要点：
- 提取 `GRAPH_EXTRACTION_PROMPT = """..."""` 中的内容。
- 去掉首尾三引号。
- 保留原始模板占位符（如 `{entity_types}`、`{tuple_delimiter}`）。

## 配置 LLM（Kimi / SiliconFlow）

`settings.yaml` 示例：

```yaml
models:
  default_chat_model:
    type: chat
    model_provider: openai
    auth_type: api_key
    api_key: ${GRAPHRAG_API_KEY}
    model: Qwen/Qwen3.5-4B
    api_base: https://api.siliconflow.cn/v1
    model_supports_json: true
    temperature: 1.0
    top_p: 0.95
    concurrent_requests: 2
    async_mode: threaded
    request_timeout: 180
```

`.env` 示例：

```bash
GRAPHRAG_API_KEY=sk-...
GRAPHRAG_BASE_URL=https://api.siliconflow.cn/v1
```

## 查询服务延迟加载

`server.py` 启动时**不预加载** GraphRAG 索引。`LocalSearch` 对象在第一次 `/health` 或 `/query` 请求时通过 `_load_graphrag_search()` 创建。

原因：
- `import graphrag` 及其子模块较耗时。
- LanceDB 连接可能阻塞服务启动。
- 延迟加载让服务即使在没有索引的情况下也能快速启动，仅提供 CSV 降级查询。

## 查询降级策略

`POST /query` 逻辑：

1. 调用 `_load_graphrag_search()` 尝试加载真实 GraphRAG 查询引擎。
2. 如果加载成功，执行 `graphrag_search.search(query)`，返回 `source: graphrag`。
3. 如果加载失败或查询报错，降级到 `knowledge_adapter`（CSV 表格），返回 `source: csv_fallback`。

`GET /health` 同时返回 `graphrag_index_loaded` 和 CSV 节点/边数量。

## 常见错误

| 错误 | 原因 | 解决 |
|---|---|---|
| `ModuleNotFoundError: No module named 'graphrag.cli'` | 本地 `graphrag` 包覆盖了官方包 | 改名为 `graphrag_server` |
| `invalid temperature: only 1 is allowed for this model` | Kimi 对 temperature 有严格限制 | 显式设置 `temperature: 1.0` |
| `FileNotFoundError: prompts/extract_graph.txt` | 缺少 `.txt` prompt 文件 | 把 `.py` prompt 转成 `.txt` |
| `Connection error` / `Server disconnected` | LLM API 网络不稳定 | 检查 API key/base，或切换更稳定的模型/网络 |

## 硅基流动 API 测试

```bash
curl -X POST https://api.siliconflow.cn/v1/chat/completions \
  -H "Authorization: Bearer $GRAPHRAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen3.5-4B","messages":[{"role":"user","content":"hello"}],"temperature":1.0,"top_p":0.95}'
```
