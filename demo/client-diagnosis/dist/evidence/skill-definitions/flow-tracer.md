---
name: flow-tracer
description: "流程追踪技能 — 记录分析执行过程，生成时序流程图"
version: 1.0.0
author: agent-analysis team
---

# flow-tracer

## 触发条件

- 分析流程开始/结束
- 用户要求"查看流程"、"生成时序图"、"追踪记录"
- 诊断完成后自动生成

## 执行步骤

1. **监听事件**: 在分析引擎各关键步骤插入追踪点
2. **记录状态**: 记录时间、层级、动作、结果、耗时
3. **生成追踪**: 将追踪记录写入 `data/traces/trace_<timestamp>.json`
4. **渲染图表**: 将追踪记录转为 Mermaid 序列图 HTML
5. **输出文件**: 保存到 `output/sequence_diagrams/`

## 追踪记录格式

```json
{
  "trace_id": "run_20250602_143052",
  "steps": [
    {"seq": 1, "timestamp": "14:30:53", "layer": "L1", "action": "物理层检查", "status": "PASS"},
    {"seq": 2, "timestamp": "14:30:55", "layer": "L2", "action": "链路层检查", "status": "PASS"},
    {"seq": 3, "timestamp": "14:30:58", "layer": "L3", "action": "IS-IS检查", "status": "FAIL", "anomaly_id": "L3-R001"}
  ]
}
```

## 时序图输出

生成 Mermaid 格式的序列图，可在浏览器中查看：

```bash
# 打开生成的 HTML 文件
firefox output/sequence_diagrams/run_20250602_143052.html
```

## 注意事项

- 追踪记录是诊断过程的关键证据，保留30天
- 时序图帮助开发人员快速定位问题出现的步骤
- 每个分析任务生成独立的追踪记录，不互相覆盖

## 示例

```
用户：显示上次分析的流程图
Hermes：
  1. 读取最新的 trace 文件
  2. 生成 Mermaid 序列图
  3. 输出 HTML 文件路径
  4. 用户可在浏览器中查看完整流程
```
