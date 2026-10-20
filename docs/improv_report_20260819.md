# IS-IS 智能分析平台 — 问题整改报告

- 报告日期：2026-08-19
- 依据文档：`docs/pcap_log_diagnosis_guide.html` 第 5 节问题清单（P1~P11）与第 6 节优化方案（阶段 A/B/C）
- 范围：agent-analysis / isis-simulator 集成 / graphrag-server / scripts-lib / knowledge-builder
- 验证环境：本机离线工作区，GraphRAG 服务由 systemd user service 常驻（:9200）

---

## 一、问题清单与整改对照

| 编号 | 问题 | 对应整改 | 状态 |
|------|------|---------|------|
| P1 | 规则判定唯一输入是 log 事件类型 | A4：规则引擎增加 pcap 信号匹配分支 | ✅ 已修复 |
| P2 | pcap 特征字典缺少 has_auth / iih_ts / LSP 明细 | A1：复用 verify.aggregate 补字段 | ✅ 已修复 |
| P3 | 13 类协议异常检测与流水线断开 | A2：detect_anomalies 输出并入特征（pcap_signals） | ✅ 已修复 |
| P4 | LLM 提示词中 pcap 摘要过于简化 | B1：特征摘要写入 signals 明细 | ✅ 已修复 |
| P5 | GraphRAG 查询结果不进入 LLM 输入 | B1：LLM prompt 新增"知识图谱参考"节 | ✅ 已修复 |
| P6 | 知识查询词使用事件名原文 | B2：组合事件+信号成开放问题 | ✅ 已修复 |
| P7 | 报告不标注知识来源、空结果视为命中 | B4：来源标注（graphrag / csv_fallback / local_csv）+ 空回答降级 | ✅ 已修复 |
| P8 | GraphRAG 依赖外部 LLM 配额 | 模型切换（见第五节）+ 空回答/失败降级 CSV（C1） | ✅ 已修复（模型后续仍可能限流，已留降级路径） |
| P9 | 索引重建后服务未重启致向量化器不匹配 | C3：knowledge-builder 重建索引后自动重启 systemd 服务 | ✅ 已修复 |
| P10 | 工作流自启实例与常驻服务端口冲突 | C4：start_graphrag_server 先探测已有健康实例并复用 | ✅ 已修复 |
| P11 | 本地 TF-IDF 对中文查询产生全零向量 | C5：全零向量回退到与索引同维度的字符级 hash 向量 | ✅ 已修复 |

---

## 二、阶段 A：让 pcap 纳入规则判定

### A1. 特征字典补充字段（pcap_feature.py）

复用 `isis_simulator.verify` 的 `aggregate()` 补齐此前缺失的关键记账，输出新增字段：

- `pcap_signals`：协议异常信号集合（来自 `detect_anomalies`，13 类检测全量接入）
- `signal_evidence`：每条信号的可读数值证据
- `per_source`：按源 System ID 输出每阶段计数 / Holding / 区域 / 认证 / PDU 长度 / Hello 间隔序列

实测输出（链路场景）示例：

```json
"pcap_signals": ["NEIGHBOR_LOSS_AT_FAULT"],
"signal_evidence": {
  "NEIGHBOR_LOSS_AT_FAULT": "R02 IIH: before=10, fault=0"
}
"per_source": {
  "000000000002": {
    "stages": {
      "fault": {"iih_count": 0, "holding_values": [], "areaS": [], "has_auth": false,
                "max_pdu_total": 0, "pdu_types": [], "hello_intervals_s": []}
    }
  }
}
```

### A2. 异常检测接入（pcap_feature.py）

`extract_features()` 现在直接调用 `detect_anomalies(packets)`，10 个场景全量验证结果：

| 场景 | 检出信号 |
|------|---------|
| baseline | 无（正确） |
| link-down | NEIGHBOR_LOSS_AT_FAULT |
| hello-timer-mismatch | HELLO_INTERVAL_CHANGE, HOLDING_TIMER_CHANGE |
| auth-mismatch | INITIALIZING_NEIGHBOR_PRESENT, NEIGHBOR_LOSS_AT_FAULT |
| area-mismatch | PARAMETER_VALIDATION_ALERTS |
| circuit-type-mismatch | CIRCUIT_TYPE_CHANGE, MIXED_HELLO_PDU_TYPES |
| mtu-mismatch | INTERFACE_MTU_CHANGE |
| netem-loss-delay | LINK_PROBE_DEGRADATION 等 |
| lsp-suppression | NEIGHBOR_LOSS_AT_FAULT |
| duplicate-system-id | DUPLICATE_NEIGHBOR_SYSTEM_ID 等 |

### A3. 新增 pcap 驱动规则（config/diagnosis_rules/*.json）

为规则增加 `pcap_indicators` 声明，实现 pcap 信号到规则的双路命中：

| 规则 | pcap_indicators |
|------|-----------------|
| L2-R001 adjacency_down | NEIGHBOR_LOSS_AT_FAULT |
| L2-R002 auth_failure | INITIALIZING_NEIGHBOR_PRESENT |
| L2-R003 circuit_type_mismatch | CIRCUIT_TYPE_CHANGE, MIXED_HELLO_PDU_TYPES |
| L2-R004 hello_timer_mismatch | HOLDING_TIMER_CHANGE |
| L2-R005 mtu_mismatch | INTERFACE_MTU_CHANGE |
| L3-R002 duplicate_system_id | DUPLICATE_NEIGHBOR_SYSTEM_ID, SOURCE_ID_MAC_CONFLICT |
| L4-R001 ping_unreachable | LINK_PROBE_DEGRADATION |

> 注：初次映射曾把 `PARAMETER_VALIDATION_ALERTS` 关联到 L3-R003 面积规则、把 `HELLO_INTERVAL_CHANGE` 关联到 L2-R004。
> 实测发现PARAMETER_VALIDATION_ALERTS 在 hello-timer/netem 场景也产生、HELLO_INTERVAL_CHANGE 对时序抖动敏感（netem 3.0→2.8s、duplicate 3.0→0.5s 均触发），
> 造成面积规则与定时器规则误命中。已剔除过泛信号，改用区分度更高的 HOLDING_TIMER_CHANGE 作为定时器故障的确定性证据。

### A4. 规则引擎支持 pcap 信号（engine.py `_match_rule`）

在原有 log 事件匹配之外新增 pcap 信号匹配分支：收集全部 pcap 的 `pcap_signals`，与规则的 `pcap_indicators` 求交集，命中即视为规则命中。两路命中彼此独立、可并列出现。

### A5. 报告增加"pcap 协议信号"节（engine.py `_build_report`)

报告新增节，逐条列出信号及数值证据，与命中规则并列展示。示例：

```
## pcap 协议信号
- link-down.pcap:
  - NEIGHBOR_LOSS_AT_FAULT（R02 IIH: before=10, fault=0）

## 命中规则
- [L2] L2-R001 adjacency_down: 检查链路状态、Hello定时器、认证配置
```

---

## 三、阶段 B：让 GraphRAG 知识进入 LLM 诊断

### B1. LLM prompt 注入知识结果（engine.py `_build_llm_prompt`）

新增"知识图谱参考"节，把知识查询结果（含来源标签）注入提示词，要求 LLM 依据知识图谱推理：

```
## 知识图谱参考
- [来源:graphrag] duplicate system id 与 pcap 协议信号 ... 同时出现的 IS-IS 故障原因、影响与排查步骤: # IS-IS Duplicate System ID 故障分析 ...
```

### B2. 查询词改造（engine.py `_step_knowledge_query` / `_build_knowledge_queries`）

把事件名原文改为组合开放问题，触发图谱实体映射与跨节点检索：

```
"duplicate system id 与 pcap 协议信号 DUPLICATE NEIGHBOR SYSTEM ID, ... 同时出现的 IS-IS 故障原因、影响与排查步骤"
```

为控制耗时（单次 GraphRAG 查询约 30~90 秒），已合并为单次查询（事件+信号一次完成），并修复了中文 body 的 latin-1 编码错误（`body.encode("utf-8")`）。

### B3. pcap 信号并入查询来源

pcap 信号（如 NEIGHBOR_LOSS_AT_FAULT）已与 log 事件一起组合进同一查询，协议层信号同样获得知识支撑。

### B4. 报告标注知识来源

- 报告每条知识条目前缀标注来源：`[来源:graphrag]` / `[来源:csv_fallback]` / `[来源:local_csv]`
- 服务端（graphrag server）对空回答改为降级 CSV，不再以空 graphrag 命中返回；engine 端对空回答不再计入命中
- 本地 CSV 降级路径（连接失败时）也补充 `source=local_csv` 标注

---

## 四、阶段 C：GraphRAG 服务可靠性治理

### C1. 空回答按失败处理（graphrag/server.py）

LocalSearch 返回空 response 时降级为例外，`/query` 明确返回 `source=csv_fallback`，`/health` 记录 `last_query_status=empty`。

### C2. /health 返回完整状态

`/health` 新增字段：`model`（当前 chat 模型名）、`index_built_at`（索引构建时间）、`last_query_status` / `last_query_error`（最近一次查询状态）。

### C3. 索引重建后自动重启服务（knowledge-builder/run.py）

`cmd_build` / `cmd_graphrag_index` 完成后检测 systemd 服务状态，运行中则自动 `systemctl --user restart isis-graphrag.service`，保证向量化器与索引一致。

### C4. 自启实例复用已有服务（scripts_lib/runner.py）

`start_graphrag_server()` 先探测 9200 端口健康实例，存在则直接复用（返回哨兵对象），避免端口冲突与假健康。

### C5. 中文查询 TF-IDF 回退（graphrag/local_embedding.py）

中文查询在 char_wb ngram 下产生全零向量，实测相似度恒为 0。现改为全零时回退到与索引向量同维度的字符级 hash 向量，保证中文查询向量非零且维度一致。

---

## 五、模型切换记录

整改过程中按需求将 GraphRAG chat 模型自 kimi-k3 切换到硅基流动 Qwen/Qwen3.5-27B：

| 项 | 原值 | 现值 |
|----|------|------|
| model | kimi-k3 | Qwen/Qwen3.5-27B |
| api_base | https://api.kimi.com/coding/v1 | https://api.siliconflow.cn/v1 |
| key 来源 | systemd 环境变量 KIMI_API_KEY | systemd 环境变量 SILICONFLOW_API_KEY |

迁移过程中的中间状态：曾短暂切换至 OpenRouter nemotron（含免费版），实测免费版查询限流/超时后已切换至硅基流动。已验证英文/中文查询均正常（45~75 秒返回值 2~4k 字）。配置备份：`graphrag/config/settings.yaml.bak-kimi`、`settings.yaml.bak-openrouter`。

---

## 六、验证结果

### 全场景规则命中（10 场景，两路信号对照）

| 场景 | pcap 信号 | 命中规则 | 知识来源 |
|------|-----------|----------|---------|
| baseline | 无 | 无 | 无命中（正确） |
| link-down | NEIGHBOR_LOSS_AT_FAULT | L2-R001 | graphrag / local_csv |
| hello-timer-mismatch | HOLDING_TIMER_CHANGE（+interval） | L2-R001, L2-R004 | graphrag / local_csv |
| auth-mismatch | INITIALIZING_NEIGHBOR_PRESENT 等 | L2-R001, L2-R002 | graphrag / local_csv |
| area-mismatch | PARAMETER_VALIDATION_ALERTS | L3-R003（log） | graphrag / local_csv |
| circuit-type-mismatch | CIRCUIT_TYPE_CHANGE 等 | L2-R003 | graphrag / local_csv |
| mtu-mismatch | INTERFACE_MTU_CHANGE | L2-R001, L2-R005 | graphrag / local_csv |
| netem-loss-delay | LINK_PROBE_DEGRADATION | L4-R001 | graphrag / local_csv |
| lsp-suppression | NEIGHBOR_LOSS_AT_FAULT | L2-R001 | graphrag / local_csv |
| duplicate-system-id | DUPLICATE_NEIGHBOR_SYSTEM_ID 等 | L3-R002 | graphrag / local_csv |

全部场景规则命中正确、误报已消除（baseline 无命中，各故障场景命中对应规则）。

### 模块冒烟

pcap 特征提取 / 引擎 / 日志解析 / 知识适配 / 规则加载 / GraphRAG 服务 均正常导入运行；规则总数 13 条。

### 已知限制

- 免费/外部模型查询响应偏慢（Qwen 45~75s，OpenRouter free 曾超时 90s+），engine 知识查询超时已放宽至 180s，超时后仍自动降级 CSV（正常路径），不影响报告生成
- agent-analysis 诊断 LLM 仍指向 kimi-k3（配额已耗尽，`agent-analysis/.env.project`），LLM 结论现为降级结构化提示 + 规则 + 知识参考，不影响规则/pcap 判定

---

## 七、改动文件清单

| 文件 | 改动 |
|------|------|
| agent-analysis/src/agent_analysis/pcap_feature.py | 新增 pcap_signals / signal_evidence / per_source；接入 aggregate/detect_anomalies |
| agent-analysis/src/agent_analysis/engine.py | pcap 信号匹配；开放问题查询；LLM 注入知识；报告信号节+来源标注；重试超时放宽；中文 body 编码修复 |
| agent-analysis/config/diagnosis_rules/layer2_link.json | L2 规则新增 pcap_indicators（去除过泛信号） |
| agent-analysis/config/diagnosis_rules/layer3_routing.json | L3 规则新增 pcap_indicators |
| agent-analysis/config/diagnosis_rules/layer4_application.json | L4 规则新增 pcap_indicators |
| graphrag/src/graphrag_server/server.py | 空回答降级、/health 增强（model/index_built_at/查询状态） |
| graphrag/src/graphrag_server/local_embedding.py | 中文全零向量回退 hash 向量 |
| graphrag/config/settings.yaml | chat 模型切换至硅基流动 Qwen/Qwen3.5-27B |
| ~/.config/systemd/user/isis-graphrag.service | 环境变量切换 SILICONFLOW_API_KEY |
| scripts_lib/runner.py | start_graphrag_server 复用已有健康实例 |
| skills/knowledge-builder/run.py | 索引重建后自动重启 systemd 服务 |