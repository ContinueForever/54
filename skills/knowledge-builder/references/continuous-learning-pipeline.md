# 持续学习流水线（knowledge-builder）

本文件记录从长期运行数据中发现未知故障并补充知识图谱的完整流程。

## 触发条件

- 历史 trace 数量超过 50 个
- 用户要求"分析有没有新故障模式"
- 定时任务（例如每周一次）扫描最近数据

## 数据输入

- `agent-analysis/data/traces/*.json` — 分析引擎生成的结构化追踪
- `agent-analysis/output/reports/*.md` — 诊断报告（人工复核参考）
- `agent-analysis/config/diagnosis_rules/*.json` — 当前规则库，用于比对哪些事件未覆盖

## 输出产物

- `knowledge/learnings/candidates/<YYYYMMDD_HHMMSS>.json` — 候选新故障
- `knowledge/tables/nodes.csv` — 确认合并后的节点
- `knowledge/tables/edges.csv` — 确认合并后的关系
- `graphrag/input/knowledge_graph.txt` — 重新生成的 GraphRAG 输入
- `graphrag/output/` — 重新构建的 GraphRAG 索引

## 标准操作序列

```bash
# 1. 发现候选未知故障
python -m knowledge_builder discover --days 30

# 2. 查看候选文件
python -m knowledge_builder candidates

# 3. 人工审查候选文件 knowledge/learnings/candidates/<id>.json

# 4. 合并确认后的候选到主图谱
python -m knowledge_builder apply-candidates --candidate <id>

# 5. 可选：启动 GraphRAG 服务供后续诊断查询
python -m graphrag_server.server --port 9200
```

## 候选文件格式示例

```json
{
  "candidate_id": "20260706_143052",
  "created_at": "2026-07-06T14:30:52",
  "traces_analyzed": 120,
  "days": 30,
  "unknown_events_count": 2,
  "candidates": [
    {
      "node_id": "isis_lsp_checksum_error",
      "node_type": "fault_candidate",
      "name": "isis_lsp_checksum_error",
      "description": "Unknown event discovered from traces (count=8)",
      "source": "learning",
      "occurrence": 8,
      "sample_trace_ids": ["run_20260610_112233", "run_20260615_143000"]
    }
  ]
}
```

## 注意事项

- 候选节点只是机器聚类结果，必须人工确认后才能合并
- 合并前会备份 `knowledge/tables/` 到 `knowledge/learnings/snapshots/`
- 合并后会自动重新生成 GraphRAG 输入并构建索引（除非 `--no-index`）
- 若发现的事件只是已有规则的别名或同义词，应修改规则 indicators 而不是新增节点
