---
name: isis-analysis
description: "IS-IS 网络数据分析主技能 — 分层诊断、规则匹配、LLM辅助"
version: 1.0.0
author: agent-analysis team
---

# isis-analysis

## 触发条件

- 用户提到"分析"、"诊断"、"检查"、"排查"等关键词
- 用户提供了 pcap、log、或网络状态数据
- 用户询问某个节点或链路的状态

## 执行步骤

1. **确认数据**: 检查 `data/incoming/` 是否有待分析的数据，或询问用户提供
2. **加载配置**: 读取 `config/analysis_pipeline/default_pipeline.json` 和 `config/diagnosis_rules/`
3. **分层检查**: 按流水线配置顺序执行各层检查（L1物理层 → L2链路层 → L3路由层 → L4应用层）
4. **规则匹配**: 每层调用对应的 JSON 规则文件进行匹配
5. **异常处理**: 
   - 规则命中 → 直接输出诊断结论
   - 规则未覆盖 → 调用甲方本地 vLLM 辅助诊断
6. **生成追踪**: 记录每个步骤的执行结果到 `data/traces/`
7. **输出报告**: 生成 Markdown 报告和 Mermaid 时序流程图到 `output/`

## 注意事项

- 分析过程中**只读**甲方数据，不修改原始文件
- 优先使用确定性规则，LLM仅作为补充
- 每次分析生成唯一的 trace_id，便于后续追溯
- 磁盘使用率超过95%时停止写入并告警

## 示例

```
用户：请分析刚才收到的 s1-s2 链路数据
Hermes：
  1. 发现 data/incoming/20250602/143052/ 下的数据
  2. 执行分层检查...
  3. L1: 接口状态正常 ✅
  4. L2: 邻居发现异常 ❌（Hello报文丢失）
  5. L3: 规则匹配 — L2链路层故障
  6. 生成诊断报告和时序流程图
  7. 输出：output/reports/report_20250602_143052.md
```

## 参考文档

- `references/analysis_framework.md` — 分析框架详细说明
- `references/isis_rfc_quickref.md` — IS-IS RFC 速查
- `references/pcap_log_patterns.md` — 常见报文和日志模式
