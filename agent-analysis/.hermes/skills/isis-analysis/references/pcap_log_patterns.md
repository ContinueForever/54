# 常见 pcap 和日志模式

## IS-IS PDU 类型

| 类型值 | 名称 | 说明 |
|--------|------|------|
| 0x0F | L1 LAN Hello | Level-1 LAN Hello |
| 0x10 | L2 LAN Hello | Level-2 LAN Hello |
| 0x11 | P2P Hello | Point-to-Point Hello |
| 0x12 | L1 LSP | Level-1 Link State PDU |
| 0x13 | L2 LSP | Level-2 Link State PDU |
| 0x14 | L1 CSNP | Level-1 Complete Sequence Number PDU |
| 0x15 | L2 CSNP | Level-2 Complete Sequence Number PDU |
| 0x16 | L1 PSNP | Level-1 Partial Sequence Number PDU |
| 0x17 | L2 PSNP | Level-2 Partial Sequence Number PDU |

## 常见日志模式

### 邻居建立
```
%ISIS-5-ADJCHANGE: Interface eth0, Neighbor s2 Up
%ISIS-5-ADJCHANGE: Interface eth0, Neighbor s2 Down, holdtime expired
```

### LSP 相关
```
%ISIS-4-LSP_TOO_LARGE: LSP from s2 too large for interface eth0
%ISIS-5-LSPDBOverload: LSP database overload detected
```

### 认证失败
```
%ISIS-4-AUTH_FAILURE: Authentication failed on interface eth0
```

## pcap 过滤表达式

```bash
# 过滤所有 IS-IS 报文
is-is

# 过滤特定类型的 IS-IS 报文
isis.pdu_type == 0x11    # P2P Hello
isis.pdu_type == 0x12    # L1 LSP

# 过滤特定源或目的
isis.system_id == "0000.0000.0002"
```
