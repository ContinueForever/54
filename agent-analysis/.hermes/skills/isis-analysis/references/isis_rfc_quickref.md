# IS-IS RFC 速查

## 核心RFC文档

| RFC | 标题 | 关键章节 | 适用场景 |
|-----|------|---------|---------|
| RFC 1195 | Use of OSI IS-IS for Routing in TCP/IP and Dual Environments | §3.3, §4.4, §5.1-5.3 | 邻居建立、参数协商、区域配置 |
| RFC 5303 | Three-Way Handshake for IS-IS Point-to-Point Adjacencies | §1, §2.1, §3.2 | P2P邻居三次握手、状态机 |
| RFC 5304 | IS-IS Cryptographic Authentication | 全文 | 认证配置、密码匹配 |

## IS-IS 邻居状态机（RFC 5303）

```
Down ──Hello──→ Initializing ──Hello──→ Up
  ↑                                    │
  └─────────超时/错误──────────────────┘
```

合法状态迁移：
- Down → Down
- Down → Initializing
- Initializing → Up
- Initializing → Down
- Up → Down

## Hello 报文关键参数（RFC 1195 §5.1）

| 参数 | 说明 | 默认值 |
|------|------|--------|
| Holding Timer | 邻居保持时间 | 30秒 |
| Hello Interval | Hello发送间隔 | 10秒 |
| Circuit Type | 电路类型（L1/L2/L1L2） | L1L2 |
| Area Address | 区域地址 | 配置决定 |

## 常见故障与RFC对应

| 故障现象 | 相关RFC | 章节 |
|---------|---------|------|
| 邻居无法建立 | RFC 5303 | §2.1 |
| Hello定时器不匹配 | RFC 1195 | §5.1 |
| 区域地址不匹配 | RFC 1195 | §4.4 |
| 认证失败 | RFC 5304 | 全文 |
| LSP序列号异常 | RFC 1195 | §5.2 |
| System ID冲突 | RFC 1195 | §3.3 |
