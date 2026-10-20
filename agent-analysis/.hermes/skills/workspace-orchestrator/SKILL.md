---
name: workspace-orchestrator
description: "54所 IS-IS 智能分析平台统一工作流编排技能：生成数据→构建知识→启动GraphRAG→运行分析→批判性审查→展示前端。执行各阶段之间，Hermes 必须以 LLM 推理身份介入，记录思考、判断与决策，体现分析能力"
version: 3.0.0
author: agent-analysis team
---

# workspace-orchestrator

## 触发条件

- 用户要求"生成并分析"、"跑一遍工作流"、"演示 IS-IS 故障分析"
- 用户提到"pcap"、"log"、"GraphRAG"、"前端"、"分析"等多个关键词
- 用户想验证某个场景（如 baseline、link-down、auth-mismatch、复合故障组合 combo-*）

## 核心原则：Hermes 全程 LLM 参与

本 skill 不是"照脚本跑一遍"的自动化：**Hermes 是执行者，更是分析者**。
每个阶段之间，Hermes 必须停下来、阅读中间产物、用自己的判断推进流程。
具体而言，Hermes 在每个阶段后都要输出一段"阶段推演记录"，包含三要素：

1. **看见了什么**（观察）：简明列出该阶段产物的关键数值、事件、信号
2. **我的判断**（推理）：基于观察给出初步判断、可能原因、风险点，不要复述脚本输出
3. **下一步决策**（决策）：说明为什么选择下一步、预期得到什么、如何验证

这些推演记录必须以 `【Hermes 推演 · 阶段名】` 为标题呈现给用户，
让甲方能看到 LLM 在每个环节的思考过程，而不是只见最终报告。

## 执行阶段

### 阶段一：生成数据（generate）

```bash
python3 skills/workspace-orchestrator/run.py <scenario> --run-id <run_id> --stage generate
```

- 支持单场景：`link-down`、`auth-mismatch`、`combo-auth-area` 等全部 20+ 场景
- 产物在 `isis-simulator/output/<run_id>/`（pcapng/ + logs/）
- 复合故障场景（combo-*）会同时生成叠加了两个故障特征的 pcap 与合并日志

**【Hermes 推演 · 生成数据】**：读取生成的 pcap/log 文件清单与大小，
先不运行分析，仅凭场景名与文件结构预估：本场景可能在哪个阶段（before/fault/after）
注入异常、日志事件会指向哪些故障类型。将判断写入推演记录。

### 阶段二：准备输入（prepare）

```bash
python3 skills/workspace-orchestrator/run.py <scenario> --run-id <run_id> --stage prepare
```

将 pcap/log 复制到 `agent-analysis/data/incoming/<run_id>/`。

**【Hermes 推演 · 准备输入】**：确认输入完整（pcap 与 log 成对、数量对得上）。
若发现缺文件，应先向用户说明并决定如何处理，再继续。

### 阶段三：构建知识（build_knowledge）

```bash
python3 skills/workspace-orchestrator/run.py <scenario> --run-id <run_id> --stage build_knowledge
```

- 更新 `knowledge/tables/nodes.csv`、`edges.csv`
- 生成 `graphrag/input/knowledge_graph.txt`

**【Hermes 推演 · 构建知识】**：阅读 `knowledge/tables/nodes.csv`，
确认本次场景的相关故障节点/复合故障节点（composite_fault）是否已在知识库中。
说明这些知识将如何辅助本次诊断。

### 阶段四：构建索引（build_index）

```bash
python3 skills/workspace-orchestrator/run.py <scenario> --run-id <run_id> --stage build_index
```

构建/更新 GraphRAG 索引（耗时较长，可复用已有索引则用 `--skip-knowledge`）。

**【Hermes 推演 · 构建索引】**：说明索引规模变化，预估查询时延与可能的降级路径。

### 阶段五：启动 GraphRAG 服务（start_rag）

```bash
python3 skills/workspace-orchestrator/run.py <scenario> --run-id <run_id> --stage start_rag
```

【Hermes 推演 · 启动服务】：确认 `/health` 正常、索引构建时间、模型配置
（chat 模型 / embedding 模型）。

### 阶段六：运行分析（analyze）

```bash
export GRAPHRAG_ENABLED=true
python3 -m agent_analysis --input agent-analysis/data/incoming/<run_id>
```

分析引擎依次执行：加载数据 → 特征提取（分层统计 + pcap 信号）→ 知识查询（GraphRAG）→
L1/L2/L3/L4 规则匹配 → LLM 辅助诊断 → 生成报告。

- 报告：`agent-analysis/output/reports/run_<timestamp>.md`
- 追踪：`agent-analysis/data/traces/run_<timestamp>.json`

**【Hermes 推演 · 规则匹配】**：读取报告中的"pcap 协议信号""命中规则"章节，
逐一核对：命中规则的依据是否强信号、有无误报、复合故障是否被完整识别。

**【Hermes 推演 · LLM 诊断】**：阅读"LLM 诊断结论"章节，评价结论是否与
命中规则、知识引用、证据链一致，指出结论中的推理环节与可能的缺陷。

### 阶段七：批判性审查（critic）— 必需步骤

```bash
python3 skills/workspace-orchestrator/run.py <scenario> --run-id <run_id> --stage critic
```

Hermes 必须启动一个**批判性子智能体（isis-critic）**对诊断报告进行独立审查。
批判子智能体职责：

- 读取 `skills/workspace-orchestrator/references/critic-checklist.md` 检查清单
- 逐项核查：数据完整性/特征提取/规则命中/知识引用/LLM 结论质量/复合故障专项
- 输出结构化批判意见（问题等级 CRITICAL/MAJOR/MINOR/INFO，含证据、风险、建议）
- 写入 `agent-analysis/output/reports/run_<timestamp>.critique.md`

**【Hermes 推演 · 批判审查】**：调用子智能体后，汇总批判子智能体发现的
问题清单，判断哪些必须修正、哪些是改进建议，并说明采纳/拒绝的理由。

### 阶段八：汇总呈现（report）

```bash
python3 skills/workspace-orchestrator/run.py <scenario> --run-id <run_id> --stage report
```

输出完整报告 + 批判意见。

**【Hermes 推演 · 总结交付】**：综合报告、批判意见与自身判断，输出给用户的
最终结论：根因、影响、排查步骤，并明确标注结论的可信度与剩余不确定项。

### 阶段九：前端展示（frontend，可选）

```bash
python3 skills/workspace-orchestrator/run.py <scenario> --run-id <run_id> --stage frontend
```

启动 `http://localhost:8080`。

## 一键全流程模式（供快速验证）

```bash
python3 skills/workspace-orchestrator/run.py <scenario> [--skip-knowledge] [--frontend]
```

全流程模式下，Hermes 仍须在脚本输出后补充推演记录与批判环节，
不得直接结束对话而不呈现分析过程。

## 环境要求

- 工作目录：`/home/hermes/workspace`
- Python 3.10+
- 纯离线/内网环境；GraphRAG chat 模型经 `graphrag/config/settings.yaml` 配置
- 甲方内网 vLLM 端点配置在 `agent-analysis/.env.project`

## 输出位置

| 产物 | 路径 |
|------|------|
| 诊断报告 | `agent-analysis/output/reports/run_<timestamp>.md` |
| 批判意见 | `agent-analysis/output/reports/run_<timestamp>.critique.md` |
| 执行时序图 | `agent-analysis/output/sequence_diagrams/run_<timestamp>.html` |
| 追踪记录 | `agent-analysis/data/traces/run_<timestamp>.json` |
| GraphRAG 索引 | `graphrag/output/` |
| 知识表 | `knowledge/tables/*.csv` |

## 注意事项

- GraphRAG 服务默认占用 9200 端口，前端默认占用 8080 端口
- 分析结果保存在 `agent-analysis/output/reports/` 和 `agent-analysis/data/traces/`
- 工作流结束后，前端服务保持运行；GraphRAG 服务会被关闭
- 若 LLM 不可达，诊断报告仍会继续生成，LLM 结论部分会提示连接失败
- **批判性审查为必需步骤**；若批判子智能体不可用，Hermes 应停止并说明原因
- **复合故障场景**：通过 `run.py combo-<故障A>-<故障B>` 触发，详见
  `isis-simulator/src/isis_simulator/scenarios/combo_lib.py` 的 `COMBO_FAULTS`