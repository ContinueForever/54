# GraphRAG Server 双路径查询设计

## 设计目标

在 54 所 IS-IS 故障诊断系统中，GraphRAG 服务必须同时满足：
1. 在真实 Microsoft GraphRAG 2.7.2 索引构建完成后，优先使用高质量图查询（LocalSearch）。
2. 在索引尚未构建、LLM API 不稳定或受限环境中，自动降级到 CSV 知识图谱后端，保证分析链路不中断。
3. 服务启动迅速，不因 GraphRAG 索引加载阻塞。

## 实现要点

### 1. 延迟加载

`server.py` 启动时**不预加载** GraphRAG 索引。`LocalSearch` 对象在第一次 `/health` 或 `/query` 请求时通过 `_load_graphrag_search()` 创建：

```python
_graphrag_search = None
_graphrag_load_error = None

def _load_graphrag_search():
    global _graphrag_search, _graphrag_load_error
    if _graphrag_search is not None:
        return _graphrag_search
    if _graphrag_load_error is not None:
        raise _graphrag_load_error
    try:
        from graphrag.query.factory import get_local_search_engine
        from graphrag.config.load_config import load_config
        root = Path(ROOT)
        config = load_config(config_path, root, {})
        search_engine = get_local_search_engine(config)
        _graphrag_search = search_engine
        return search_engine
    except Exception as exc:
        _graphrag_load_error = exc
        raise
```

原因：
- `import graphrag` 及其子模块较耗时。
- LanceDB 连接可能阻塞服务启动。
- 延迟加载让服务即使在没有索引的情况下也能快速启动，仅提供 CSV 降级查询。

### 2. 查询降级策略

`POST /query` 逻辑：

1. 调用 `_load_graphrag_search()` 尝试加载真实 GraphRAG 查询引擎。
2. 如果加载成功，执行 `graphrag_search.search(query)`，返回 `source: graphrag`。
3. 如果加载失败或查询报错，降级到 `knowledge_adapter`（CSV 表格），返回 `source: csv_fallback`。

```python
try:
    graphrag_search = _load_graphrag_search()
    result = graphrag_search.search(query)
    response = {"source": "graphrag", "result": result.response}
except Exception:
    csv_results = csv_adapter.query(query)
    response = {"source": "csv_fallback", "results": csv_results}
```

### 3. 响应格式

- `source: graphrag`：返回 `result` 字符串，由分析引擎包装为节点写入报告。
- `source: csv_fallback`：返回 `results` 列表，每个元素包含 `node` 字典（`node_id`, `name`, `description`, `node_type`）。

分析引擎 `agent_analysis/engine.py` 需要同时处理两种格式：

```python
source = data.get("source")
if source == "graphrag":
    self.knowledge_results.append({
        "node_id": "graphrag_answer",
        "name": event_type,
        "description": data.get("result", "")[:500],
        "node_type": "graphrag_response",
        "source": source,
    })
elif source == "csv_fallback":
    for item in data.get("results", [])[:3]:
        node = item.get("node", {})
        if node:
            node["source"] = source
            self.knowledge_results.append(node)
```

### 4. 健康检查

`GET /health` 返回：

```json
{
  "status": "ok",
  "graphrag_index_loaded": true,
  "csv_nodes": 42,
  "csv_edges": 38
}
```

`graphrag_index_loaded` 表示当前是否成功加载真实 GraphRAG 索引；`csv_nodes`/`csv_edges` 表示降级后端数据规模。

## 何时使用哪种路径

| 场景 | 使用路径 | 说明 |
|------|---------|------|
| 真实索引已构建，API 可用 | `source: graphrag` | 推荐，查询质量最高 |
| 真实索引未构建 | `source: csv_fallback` | 自动降级，保证工作流可用 |
| LLM API 不稳定导致索引失败 | `source: csv_fallback` | 服务不崩溃，等索引成功后自动切换 |
| 临时验证/演示 | `source: csv_fallback` | 无需等待 LLM 索引即可验证端到端链路 |
