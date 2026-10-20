# 甲方自定义指南

## 快速自定义（无需编程）

### 1. 更新诊断规则

编辑 `config/diagnosis_rules/` 下的 JSON 文件：

```json
{
  "id": "L3-R005",
  "name": "my_new_rule",
  "description": "我的新规则",
  "indicators": ["指标1", "指标2"],
  "severity": "warning",
  "suggestion": "修复建议",
  "references": ["RFC 1195 Section 5.1"]
}
```

保存后立即生效，下次分析自动使用新规则。

### 2. 调整分析流程

编辑 `config/analysis_pipeline/default_pipeline.json`：

```json
{
  "id": "l4",
  "enabled": true    // 改为 true 启用应用层检查
}
```

### 3. 调整阈值

编辑 `config/thresholds/default_thresholds.json`：

```json
{
  "hello_timeout_ms": 5000,    // 修改 Hello 超时阈值
  "ping_success_rate_threshold": 0.90
}
```

### 4. 更新知识库

将大模型生成的知识图谱表格放入：

```
config/knowledge_tables/
├── nodes.csv
├── edges.csv
└── node_attributes.csv
```

表格格式见 `docs/knowledge_table_format.md`。

## 查看分析结果

```bash
# 文本报告
cat output/reports/report_*.md

# 时序流程图（用浏览器打开）
firefox output/sequence_diagrams/run_*.html
```
