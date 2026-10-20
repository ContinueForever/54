# RFC 1195 - 在 OSI IS-IS 中携带 IP 和 ISO 路由

IS-IS 最初为 ISO CLNP 设计，RFC 1195 扩展了 IS-IS 以支持 IPv4/IPv6 路由，引入以下关键 TLV：

- **TLV 128 (IP Internal Reachability)**：宣告直连 IPv4 前缀。
- **TLV 129 (Protocols Supported)**：宣告支持的协议族（NLPID = 0xCC 表示 IPv4）。
- **TLV 130 (IP External Reachability)**：宣告外部引入的 IPv4 路由。
- **TLV 132 (IP Interface Address)**：宣告接口 IP 地址。

## 诊断相关要点

| 症状 | 可能原因 |
|------|----------|
| IP 路由不发布 | 缺少 Protocols Supported TLV 或 NLPID 不匹配 |
| 外部路由不可达 | IP External Reachability TLV 缺失或 down-bit 置位 |
| 邻居 UP 但无 IP 路由 | 接口未使能 IS-IS 或地址族未协商 |
