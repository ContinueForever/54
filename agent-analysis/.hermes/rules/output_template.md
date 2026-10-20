# 输出报告模板

## 诊断报告结构（Markdown）

```markdown
# IS-IS 故障诊断报告

## 基本信息
- 分析ID: {trace_id}
- 分析时间: {timestamp}
- 数据来源: {source}
- 网络状态: {network_state}

## 执行摘要
- 总步骤数: {total_steps}
- 通过步骤: {pass_count}
- 异常步骤: {fail_count}
- 诊断结论: {conclusion}

## 分层检查结果

### L1 物理层
- 状态: {PASS/FAIL}
- 详情: {detail}

### L2 链路层
- 状态: {PASS/FAIL}
- 详情: {detail}

### L3 IS-IS路由层
- 状态: {PASS/FAIL}
- 详情: {detail}
- 异常规则: {rule_id}

### L4 应用层（如启用）
- 状态: {PASS/FAIL}
- 详情: {detail}

## 诊断结论
- 故障层级: {fault_layer}
- 故障类型: {fault_type}
- 影响节点: {affected_nodes}
- 严重级别: {severity}

## 修复建议
{suggestion}

## 参考文档
{references}

## 时序流程图
见: output/sequence_diagrams/{trace_id}.html
```

## 时序流程图（Mermaid HTML）

生成包含 Mermaid 序列图的 HTML 文件，可直接在浏览器中查看。

## 输出位置

- 报告: `output/reports/report_{trace_id}.md`
- 时序图: `output/sequence_diagrams/{trace_id}.html`
- 结构化数据: `output/exports/{trace_id}.json`
