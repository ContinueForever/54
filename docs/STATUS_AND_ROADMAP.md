# Workspace 状态盘点与下一步计划

> 更新时间：2026-07-22（原 2025-07-02 版本已过期，本文档全面重写）
> 范围：`/home/hermes/workspace`

---

## 一、当前进展

### 1.1 已完成（可用）

| 模块 | 内容 | 验证状态 |
|------|------|----------|
| **isis-simulator** | 10 个 IS-IS 场景 pcap + log 生成；手写 PDU 构造器；无第三方依赖 | ✅ 可用 |
| **agent-analysis** | pcap/log 特征提取、4 层规则引擎、GraphRAG 集成、LLM 辅助诊断、追踪报告 | ✅ 可用 |
| **graphrag-server** | 本地 HTTP 查询服务（9200 端口），systemd 常驻，CSV + GraphRAG 索引双后端 | ✅ 常驻运行 |
| **frontend** | 6 屏演示界面（index.html + server.py），8080 端口 | ✅ 可用 |
| **Hermes Skills** | workspace-orchestrator / knowledge-builder 两个编排 skill | ✅ 已部署 |
| **scripts** | `generate_and_analyze.py`（轻量）+ `run_pipeline.py`（完整） | ✅ 可用 |
| **LLM 接入** | 诊断引擎 kimi-k3（Anthropic Messages API）；GraphRAG chat=kimi-k3（OpenAI 格式） | ✅ 已切换 |

### 1.2 模型配置现状（2026-07-22 统一为 kimi-k3）

| 层 | 组件 | 模型 | 配置文件 |
|----|------|------|----------|
| 1 | Hermes Agent 本体 | kimi-k3 @ api.kimi.com/coding | `~/.hermes/config.yaml`（`hermes model` 命令管理） |
| 2 | 诊断引擎 | kimi-k3（Anthropic `/v1/messages`） | `agent-analysis/.env.project` |
| 3 | GraphRAG | chat=kimi-k3（OpenAI `/v1/chat/completions`），embedding=local_tfidf 离线 | `graphrag/config/settings.yaml` |

完整配置教程与甲方自部署模型（vLLM）迁移步骤：`docs/MODEL_CONFIGURATION.md`。

---

## 二、已解决的历史问题（对照 2025-07-02 版）

| 原问题 | 现状 |
|--------|------|
| LLM 未接入，`_step_llm_assist` 为占位 | ✅ 已接入 kimi-k3，LLM 诊断结论写入报告 |
| 前端缺失 | ✅ frontend/ 6 屏界面完成，8080 端口 |
| 工作流未串联 | ✅ scripts + workspace-orchestrator skill 一键闭环 |
| GraphRAG 服务不常驻 | ✅ systemd user service（isis-graphrag.service），Restart=always |
| 免费模型（OpenRouter nemotron / SiliconFlow Qwen）限流 502 | ✅ 已切换 kimi-k3，不再依赖免费额度 |

---

## 三、遗留问题

1. **知识图谱规模偏小**：24 节点 / 53 边，需继续扩充 RFC 深度知识与甲方专家规则（knowledge-builder skill）。
2. **GraphRAG 索引与 chat 模型绑定**：切换 chat 模型后必须重建索引（实体抽取结果随模型变化），已在 MODEL_CONFIGURATION.md 3.4 节说明。
3. **kimi-k3 为 thinking 模型**：GraphRAG 索引构建较慢（12KB 语料约 5-10 分钟），属预期。
4. **规则引擎仍基于关键词**：置信度/权重机制未实现，存在跨场景误命中可能。

---

## 四、下一步优先级

### P0
1. GraphRAG 索引重建后验证 `graphrag_index_loaded: true`，确认语义检索生效（本次切换 kimi-k3 后的收尾动作）。

### P1
2. 扩充知识图谱：更多 RFC 知识点、甲方专家规则、故障处理建议（目标 100+ 节点）。
3. 规则引擎精准化：引入置信度，结合 pcap 阶段特征减少误命中。

### P2
4. 甲方交付演练：按 MODEL_CONFIGURATION.md 3.4 节实际演练一次 vLLM 迁移流程。
5. 测试覆盖：为规则引擎与 GraphRAG 适配层补充单元测试。
