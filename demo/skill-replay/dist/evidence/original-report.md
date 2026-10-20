# IS-IS 诊断报告 — run_20261013_200713

## 输入数据
- pcap: 1
- log: 1

## pcap 协议信号
- circuit-type-mismatch.pcap:
  - CIRCUIT_TYPE_CHANGE（R02 PDU类型: [18] -> [17]）
  - MIXED_HELLO_PDU_TYPES

## 命中规则
- [L2] L2-R003 circuit_type_mismatch: 统一isis circuit-type配置
- [L3] L3-R004 circuit_type_mismatch: 统一两端isis circuit-type配置

## 复合故障判定
- 检测到 2 条独立故障规则同时命中：L2-R003, L3-R004
- 判定：复合故障（多因素叠加），需按规则逐项排查，避免单一归因。

## GraphRAG 知识图谱结果
- [来源:RFC 1195] circuit_type_mismatch Circuit Type Mismatch: L1/L2 circuit-type mismatch prevents adjacency formation

## LLM 诊断结论
模型: openai/Qwen/Qwen3.5-27B

（LLM 未返回结论）