# isis-simulator — IS-IS 数据生成器

用于生成 IS-IS 路由协议正常/故障场景的合成 pcap 和设备日志。

## 生成内容

- `pcapng/*.pcap`：经典 pcap 格式，含 IIH、LSP、CSNP、ICMP 探测等
- `pcap/*.pcap`：经典 pcap 格式（兼容旧路径）
- `logs/*.log`：模拟设备侧 syslog/IS-IS 日志

## 场景列表

| 场景 | 说明 | 关键异常 |
|------|------|----------|
| baseline | 正常 IIH/LSP 收发 | 无 |
| area-mismatch | 区域地址不一致 | PARAMETER_VALIDATION_ALERTS |
| auth-mismatch | IIH 认证不匹配 | NEIGHBOR_LOSS, INITIALIZING_NEIGHBOR |
| circuit-type-mismatch | L1/L2 电路类型不一致 | CIRCUIT_TYPE_CHANGE |
| link-down | 链路物理中断 | NEIGHBOR_LOSS |
| hello-timer-mismatch | Hello/Holding 定时器不一致 | HELLO_INTERVAL_CHANGE, HOLDING_TIMER_CHANGE |
| netem-loss-delay | 丢包/延迟 | LINK_PROBE_DEGRADATION |
| mtu-mismatch | 接口 MTU 不一致 | INTERFACE_MTU_CHANGE |
| lsp-suppression | LSP 抑制/接口退出 IS-IS | NEIGHBOR_LOSS |
| duplicate-system-id | 重复 System-ID | DUPLICATE_NEIGHBOR, MAC_CONFLICT |

## 快速开始

```bash
cd /home/hermes/workspace/isis-simulator
python generate.py
# 仅生成指定场景
python generate.py link-down auth-mismatch
```

## 与 agent-analysis 集成

生成后，将 pcap + log 复制到 `agent-analysis/data/incoming/` 下的某个子目录，即可运行分析引擎。

```bash
cp -r pcapng /home/hermes/workspace/agent-analysis/data/incoming/run_$(date +%Y%m%d_%H%M%S)
cp -r logs /home/hermes/workspace/agent-analysis/data/incoming/run_$(date +%Y%m%d_%H%M%S)
```

## 依赖

纯 Python 标准库，无第三方依赖。
