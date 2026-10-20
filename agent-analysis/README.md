# agent-analysis — 54所卫星网络 IS-IS 智能分析系统

> **项目代号**: agent-analysis
> **服务对象**: 中国电子科技集团公司第五十四研究所（54所）
> **核心定位**: 基于 Hermes Agent + 本地离线大模型的卫星网络 IS-IS 协议智能分析引擎
> **文档版本**: 2025-07-02（盘点更新版）
> **维护者**: 开发团队 + Hermes Agent

---

## 目录

1. [项目背景与目标](#1-项目背景与目标)
2. [目录结构说明](#2-目录结构说明)
3. [快速开始](#3-快速开始)
4. [核心概念](#4-核心概念)
5. [配置指南](#5-配置指南)
6. [当前状态与 TODO](#6-当前状态与-todo)

---

## 1. 项目背景与目标

### 1.1 背景

54所运营一个由 **66颗模拟卫星 + 16个终端** 组成的 IS-IS 路由协议仿真网络（共82节点）。网络运行中可能出现各类故障，需要快速定位并辅助修复。

### 1.2 我们的工作范围

| 我们负责 | 甲方云平台负责 |
|---------|--------------|
| 接收甲方提供的 pcap、log、状态数据 | 拓扑管理、故障注入、数据采集 |
| 智能分析、分层诊断 | 网络运维、配置变更 |
| 生成诊断报告和时序流程图 | 基础设施维护 |
| 辅助开发人员定位问题 | 专家经验输入 |

### 1.3 核心目标

1. **分层诊断**: 从物理层到应用层逐层分析，定位故障所在层级
2. **知识驱动**: 利用甲方提供的知识图谱（表格形态）辅助诊断推理
3. **流程可追溯**: 自动生成时序流程图，记录分析全过程，便于问题回溯
4. **低代码可配置**: 甲方可通过修改 JSON/CSV 文件调整诊断逻辑，无需改代码
5. **离线运行**: 完全适配甲方无互联网环境，依赖本地 vLLM 服务

> **2025-07-17 更新**: 当前开发/测试环境已接入 `kimi-for-coding`（Anthropic Messages API），作为本地 vLLM 部署就绪前的替代方案。正式部署时可通过 `.env.project` 切换为甲方内网 vLLM。

---

## 2. 目录结构说明

```
agent-analysis/
├── AGENTS.md                            # Hermes 项目级指令
├── .env.project                         # 项目环境变量（vLLM端点等）
├── README.md                            # 本文档
├── Makefile                             # 常用命令快捷方式
│
├── .hermes/                             # Hermes 局部 Skills
│   ├── skills/                          #   项目级 Skills
│   │   ├── isis-analysis/               #     IS-IS 数据分析主 Skill
│   │   ├── knowledge-bridge/            #     知识桥接 Skill
│   │   └── flow-tracer/                 #     流程追踪 Skill
│   └── rules/                           #   项目运行规则
│
├── config/                              # 甲方可配置区
│   ├── knowledge_tables/                # 知识图谱 CSV（甲方提供）
│   ├── diagnosis_rules/                 # 分层诊断规则 JSON
│   ├── analysis_pipeline/               # 分析流水线配置
│   └── thresholds/                      # 阈值参数
│
├── data/                                # 运行时数据（gitignore）
│   ├── incoming/                        # 待分析输入（pcap+log）
│   ├── processed/                       # 已处理数据
│   └── traces/                          # 追踪记录（执行时序）
│
├── analysis/                            # 分析引擎源码
│   ├── engine.py                        # 主入口
│   ├── knowledge_adapter.py             # 知识图谱适配器
│   ├── rule_engine.py                   # 规则匹配引擎
│   ├── tracer.py                        # 流程追踪器
│   ├── pcap_feature.py                  # pcap 特征提取
│   ├── log_parser.py                    # 日志解析
│   └── layers/                          # 分层检查占位
│
├── output/                              # 输出产物
│   ├── reports/                         # Markdown 诊断报告
│   ├── sequence_diagrams/               # 时序流程图 HTML
│   └── exports/                         # 导出数据
│
├── docs/                                # 项目文档
└── tests/                               # 测试
```

---

## 3. 快速开始

### 3.1 运行一次完整分析

```bash
cd /home/hermes/workspace/agent-analysis
python -m analysis.engine --input data/incoming/sample
```

输出：
- `data/traces/run_<timestamp>.json` — 执行追踪记录
- `output/reports/run_<timestamp>.md` — 诊断报告

### 3.2 常用命令

```bash
make setup        # 初始化目录
make diagnose     # 运行诊断
make report       # 生成报告
make test         # 运行测试
make clean        # 清理输出
```

### 3.3 使用 Hermes Skills

进入 `agent-analysis` 目录后，Hermes 会自动加载 `.hermes/skills/` 下的技能：

- `isis-analysis` — 主分析流程
- `knowledge-bridge` — 查询知识图谱
- `flow-tracer` — 生成时序图

---

## 4. 核心概念

### 4.1 分析流水线

配置：`config/analysis_pipeline/default_pipeline.json`

步骤：
1. `load` — 加载 pcap + log
2. `feature` — 特征提取
3. `knowledge` — 知识图谱查询
4. `L1` / `L2` / `L3` / `L4` — 分层规则检查
5. `llm` — LLM 辅助诊断（已接入 kimi-for-coding，可切换本地 vLLM）
6. `report` — 生成报告

### 4.2 知识图谱

以 CSV 表格形式维护：
- `nodes.csv` — 节点定义（协议 PDU、TLV、故障、状态、设备等）
- `edges.csv` — 节点关系（因果关系、包含关系等）
- `node_attributes.csv` — 节点属性（code、type 等）

当前：31 节点 / 22 边，覆盖基础 IS-IS PDU、TLV、常见故障模式。

### 4.3 诊断规则

JSON 规则，包含：
- `id` / `name` / `description`
- `indicators` — 匹配关键词
- `severity` / `affected_layers` / `suggestion` / `references`

---

## 5. 配置指南

### 5.1 LLM 后端配置

编辑 `.env.project`：

**方案 A：kimi-for-coding（当前默认）**
```bash
KIMI_BASE_URL=https://api.kimi.com/coding
KIMI_API_KEY=sk-***...n
- 使用 Anthropic Messages API 格式
- `llm_client.py` 会自动过滤 `thinking` 块，只保留最终诊断文本

**方案 B：本地 vLLM / OpenAI-compatible**
```bash
OPENAI_COMPATIBLE_CHAT_ENDPOINT=http://192.168.1.80:9998/v1/chat/completions
OPENAI_COMPATIBLE_CHAT_API_KEY=none
DEFAULT_MODEL_NAME=Qwen3.5-4B
```

### 5.2 调整诊断规则

直接编辑 `config/diagnosis_rules/*.json`，下次分析自动生效。

---

## 6. 当前状态与 TODO

| 模块 | 状态 | 备注 |
|:------------|:----:|:----|
| pcap 解析 | ✅ | 时间窗分段、IIH/LSP/ICMP 提取 |
| 日志解析 | ✅ | 基于关键词的事件提取 |
| 规则引擎 | ✅ | JSON 规则，关键词匹配 |
| 知识图谱 | ✅ | CSV 后端，31 节点 |
| 追踪记录 | ✅ | JSON 执行时序 |
| Markdown 报告 | ✅ | 规则命中列表 |
| 时序流程图 | ✅ | tracer.py 自动生成 Mermaid HTML |
| LLM 接入 | ✅ | 已接入 kimi-for-coding，支持切换 vLLM |
| 前端展示 | ✅ | `frontend/` 白底浅色调单页应用 |
| Hermes Skill 一键工作流 | ✅ | `workspace-orchestrator` Skill 已部署 |

**示例运行结果**：

```bash
python3 skills/workspace-orchestrator/run.py link-down --skip-knowledge --frontend
```

输出包含：
- pcap/log 仿真数据
- GraphRAG 知识图谱查询结果
- kimi-for-coding 生成的 LLM 诊断结论
- Markdown 报告：`output/reports/run_<timestamp>.md`
- 时序图：`output/sequence_diagrams/run_<timestamp>.html`
- 前端：`http://localhost:8080`
