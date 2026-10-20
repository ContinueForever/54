# RFC 3358 - IS-IS 邻接关系与状态机

IS-IS 邻接按如下状态机演进：

```
Down -> Init -> Up
```

## 关键状态

- **Down**：未收到任何 IIH 或 Hold Timer 超时。
- **Init**：收到 IIH，但邻居列表中未看到自己 System ID。
- **Up**：双向通信确认，邻居列表中包含自己 System ID。

## 影响邻接的常见故障

| 故障类型 | 典型现象 |
|----------|----------|
| 区域不匹配 | 收到 IIH 但 Area Address TLV 不一致，邻接无法到达 Up |
| 认证失败 | IIH 被丢弃，序列中看不到任何邻接状态变更 |
| Hello 定时器不匹配 | 短期可能不影响邻接，长期导致保活抖动 |
| Circuit Type 不匹配 | L1/L2 级别不一致，邻接状态停滞 |
| 重复 System ID | LSP 冲突、多次邻接震荡 |
| MTU 不匹配 | LSP 分片交互异常，邻接反复 Init |
| 链路物理 down | 对端停止发送 IIH，本端 Hold Timer 超时后 Down |

## 诊断规则

- 若 fault 段 src_ids 减少且邻接日志出现 adjacency_down，判定为 NEIGHBOR_LOSS_AT_FAULT。
- 若 fault 段持续收到 IIH 但邻接不 Up，检查 Area、Auth、Circuit Type、MTU。
- 若出现 duplicate_system_id 标志且多个节点共享同一 System ID，判定为 DUPLICATE_SYSTEM_ID。
