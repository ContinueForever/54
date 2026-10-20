---
name: knowledge-bridge
description: "知识桥接技能 — 将甲方提供的表格形态知识图谱加载为可用知识"
version: 1.0.0
author: agent-analysis team
---

# knowledge-bridge

## 触发条件

- 用户提到"知识库"、"知识图谱"、"规则查询"
- 诊断过程中需要查询与某异常相关的知识
- 甲方更新了知识表格

## 执行步骤

1. **检查表格**: 确认 `config/knowledge_tables/` 下是否有有效表格
2. **加载解析**: 调用 `analysis/knowledge_adapter.py` 加载 CSV 表格
3. **构建图谱**: 在内存中构建节点-边关系图
4. **提供查询**: 响应知识查询请求，返回相关知识

## 表格格式约定

甲方提供的知识图谱表格需符合以下格式：

### nodes.csv
```csv
node_id,node_type,name,description,layer
N001,anomaly,lsp_seq_wrap,LSP序列号异常环绕,L3
N002,symptom,neighbor_flap,邻居关系频繁震荡,L2
```

### edges.csv
```csv
source_id,target_id,relation,strength
N001,N002,causes,0.8
N002,N003,indicates,0.9
```

## 注意事项

- 表格更新后无需重启，下次查询自动加载最新版本
- 当前仅支持 CSV 格式，未来可能扩展为 GraphRAG
- 知识查询结果供诊断引擎参考，不作为唯一依据

## 示例

```
用户：查询与 LSP 序列号异常相关的知识
Hermes：
  1. 加载 knowledge_tables/
  2. 查询节点 N001 (lsp_seq_wrap)
  3. 返回：相关症状、可能原因、影响范围、修复建议
```
