# GraphRAG 2.7.2 在 IS-IS 智能分析平台中的集成方式

> 本 reference 记录的是 Microsoft GraphRAG 2.7.2 与项目本地代码共存的实现细节。若使用的是旧版 GraphRAG 1.x 或手写 CSV 后端，请先参考 `templates/graphrag-settings.yaml` 与 `SKILL.md` 中的旧说明。

## 1. 两种后端架构

### 1.1 手写 CSV 后端（零依赖，默认兜底）

- 位置：`/home/hermes/workspace/graphrag/src/graphrag_server/server.py`
- 基于 Python 标准库 `http.server`，零第三方依赖
- 读取 `knowledge/tables/nodes.csv` + `edges.csv` 构建内存图
- 默认监听 `0.0.0.0:9200`

### 1.2 真实 Microsoft GraphRAG 后端（推荐）

- 安装：`pip install graphrag`（离线环境需提前准备完整 wheel 集合）
- 项目目录：`/home/hermes/workspace/graphrag/config/settings.yaml`、`input/`、`output/`、`cache/`、`logs/`、`prompts/`
- 推荐架构：**方案 B** —— 手写 HTTP 服务与官方索引流程分离
  - 保留 `graphrag_server.server` 作为查询/健康服务入口（监听 `0.0.0.0:9200`）
  - 新增 `graphrag_server.indexer` 复用 `graphrag.cli.index.index_cli` 构建真实索引
  - 服务启动时不预加载 GraphRAG 索引，延迟到首次 `/health` 或 `/query` 再加载，避免启动阻塞

启动方式：

```bash
cd /home/hermes/workspace/graphrag
PYTHONPATH=src python -m graphrag_server --port 9200
```

构建索引：

```bash
cd /home/hermes/workspace/graphrag
PYTHONPATH=src python -m graphrag_server.indexer --dry-run
PYTHONPATH=src python -m graphrag_server.indexer
```

## 2. 包名冲突：本地代码不能叫 `graphrag`

本地服务代码若放在 `src/graphrag/` 下，`import graphrag` 会优先解析本地包，导致无法调用官方的 `graphrag.cli`、`graphrag.config` 等模块。

- 做法：将本地源码目录从 `src/graphrag/` 重命名为 `src/graphrag_server/`
- 对应更新：
  - `from graphrag_server.server import main`
  - `from graphrag_server.local_embedding import LocalTfidfEmbeddingModel`
  - 启动服务：`python -m graphrag_server`
  - 构建索引：`python -m graphrag_server.indexer`

## 3. Kimi For Coding 参数限制

GraphRAG 通过 LiteLLM 调用 Kimi For Coding 时，Kimi 对生成参数有严格限制。在 `settings.yaml` 中必须显式声明：

```yaml
models:
  default_chat_model:
    type: chat
    model: kimi-for-coding
    temperature: 1.0
    top_p: 0.95
```

否则索引阶段会报错 `invalid temperature: only 1 is allowed for this model` 或 `invalid top_p: only 0.95 is allowed for this model`。

## 4. 本地 embedding provider（local_tfidf）

离线环境避免联网下载 embedding 模型，使用 scikit-learn TF-IDF 实现本地 embedding。

关键点：
- 实现类需符合 GraphRAG 2.7.2 的 `EmbeddingModel` 协议（`encode` 方法返回 `list[list[float]]`，`agenerate` 返回 embedding 列表）
- 在 `settings.yaml` 中，`type` 必须设为注册到 `graphrag.language_model.manager.ModelManager` 的 key（如 `local_tfidf`），而不是 `model_provider`
- 在 `graphrag_server/__init__.py` 中注册 provider，确保 `indexer.py` 和 `server.py` 在 import 时触发注册

正确示例：

```yaml
models:
  default_embedding_model:
    type: local_tfidf
    model_provider: local_tfidf
    auth_type: api_key
    api_key: local
    model: local_tfidf
    encoding_model: cl100k_base
    max_retries: 10
```

错误示例：

```yaml
# 错误！type 为 embedding 会触发 LiteLLM 调用，local_tfidf 不被识别
models:
  default_embedding_model:
    type: embedding
    model_provider: local_tfidf
```

## 5. Prompt 文件格式

GraphRAG 2.7.2 在索引阶段会读取以下 prompt 文件，路径相对于项目根目录，必须是 `.txt` 文件：

```
prompts/extract_graph.txt
prompts/summarize_descriptions.txt
prompts/extract_claims.txt
prompts/community_report_graph.txt
prompts/community_report_text.txt
prompts/local_search_system_prompt.txt
prompts/global_search_map_system_prompt.txt
prompts/global_search_reduce_system_prompt.txt
prompts/global_search_knowledge_system_prompt.txt
prompts/drift_search_system_prompt.txt
prompts/drift_reduce_prompt.txt
prompts/basic_search_system_prompt.txt
```

如果项目里原本是 `.py` 文件（变量定义），需要转换为 `.txt` 纯文本。参考脚本：

```python
import os, re
for subdir in ['index', 'query']:
    for name in os.listdir(f'prompts/{subdir}'):
        if not name.endswith('.py'):
            continue
        py_path = f'prompts/{subdir}/{name}'
        txt_name = name.replace('.py', '.txt')
        txt_path = f'prompts/{txt_name}'
        with open(py_path, 'r', encoding='utf-8') as f:
            content = f.read()
        m = re.search(r'[A-Z_]+\s*=\s*("""|"\')(.*)("""|"\')', content, re.DOTALL)
        if m:
            prompt = m.group(2).strip().strip('"""').strip('\n')
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(prompt)
```

## 6. 查询服务：GraphRAG 真实索引 + CSV 降级

`graphrag_server/server.py` 应同时支持两种路径：

1. 当 `output/lancedb/` 和必要 Parquet 文件存在时，加载真实 GraphRAG 索引并用 `LocalSearch` 回答
2. 当索引未构建或加载失败时，降级到 CSV 后端（`knowledge_adapter`）

降级接口示例：

```python
def _load_graphrag_search():
    try:
        # ... 加载 settings.yaml、初始化 model、读取 Parquet、构建 LocalSearch
        return local_search
    except Exception as e:
        print(f"[WARN] GraphRAG index not available, fallback to CSV: {e}")
        return None
```

请求处理：

```python
if graphrag_search is not None:
    try:
        result = graphrag_search.search(query)
        return {"source": "graphrag", "result": result}
    except Exception:
        pass

# CSV fallback
results = adapter.query_by_name(query)
```

## 7. `.env` 写入安全

通过脚本或代码写入 `graphrag/.env` 时，注意字符串转义：

- 不要构造包含未闭合引号或反斜杠的字面量字符串，否则会触发 `SyntaxError` 或文件内容不正确
- 推荐写入后读取，用 `repr()` 确认内容正确

正确示例：

```python
with open('/home/hermes/workspace/graphrag/.env', 'w', encoding='utf-8') as f:
    f.write(f'KIMI_API_KEY={api_key}\n')
    f.write('KIMI_BASE_URL=https://api.kimi.com/coding/v1\n')

with open('/home/hermes/workspace/graphrag/.env', 'r', encoding='utf-8') as f:
    content = f.read()
    assert 'KIMI_API_KEY=' in content and 'KIMI_BASE_URL=' in content
```

## 8. 网络不稳定时的处理策略

在客户端云平台、代理或网络受限环境中：
- 真实 `graphrag index` 的 `extract_graph` 步骤会调用 LLM API，可能因服务端断开而失败
- 不要自动反复重试可能触发网络请求的命令
- 先准备配置、脚本、输入文件到本地目录，再由用户确认后执行
- 索引失败后，查询服务仍可通过 CSV 降级路径继续工作

## 9. 常见错误与排查

| 错误 | 原因 | 处理 |
|------|------|------|
| `ModuleNotFoundError: No module named 'graphrag.cli'` | 本地包 `graphrag` 覆盖了官方包 | 重命名本地包为 `graphrag_server` |
| `invalid temperature: only 1 is allowed for this model` | Kimi 不接受 temperature != 1 | 在 settings.yaml 显式设置 `temperature: 1.0` |
| `invalid top_p: only 0.95 is allowed for this model` | Kimi 不接受 top_p != 0.95 | 显式设置 `top_p: 0.95` |
| `No such file or directory: 'prompts/extract_graph.txt'` | prompt 文件格式/位置不对 | 把 `.py` 转换为 `.txt` 并放在 `prompts/` 根目录 |
| `Maximum retries must be greater than or equal to 1` | embedding model 的 `max_retries` 为 0 | 设置 `max_retries: 10` |
| `Connection error` / `Server disconnected` | Kimi API 网络不稳定 | 准备配置后由用户确认执行，或降级 CSV 后端 |
| GraphRAG 服务启动极慢 | 启动时加载索引 | 改为延迟加载，首次查询时再初始化 |
