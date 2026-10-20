# Workspace — 54所卫星网络 IS-IS 智能分析平台

## 下载后先查看离线演示

本仓库包含项目源码、知识表格和可直接查看的离线演示。
从 GitHub 的 **Code → Download ZIP** 下载并解压，或使用 Git 克隆。

直接用浏览器打开 `demo/client-diagnosis/dist/index.html`，即可查看 IS-IS 诊断任务工作台。
离线回放不需要安装依赖，也不调用外部模型；页面中的网络输入来自受控合成场景。
历史案例回放入口为 `demo/skill-replay/dist/index.html`。

需要启动 Python 前端服务时，在项目根目录设置 `WORKSPACE` 后启动：

```bash
# Linux / macOS
export WORKSPACE="$PWD"
python3 -m frontend.server --port 8080
```

```powershell
# Windows PowerShell（已安装 Python）
$env:WORKSPACE = (Get-Location).Path
python -m frontend.server --port 8080
```

然后访问 `http://localhost:8080/workbench`。
真实模型诊断和 GraphRAG 索引构建需要另外配置模型服务，详见 `docs/MODEL_CONFIGURATION.md`。
真实密钥、虚拟环境、GraphRAG 缓存和索引未纳入仓库；保留了离线演示及其明确标注的合成案例。
可参考 `agent-analysis/.env.project.example` 和 `graphrag/.env.example` 配置自己的环境。
保存的回放证据保留原始运行路径；在新机器上重新生成案例后再验证原始运行文件。


重构后的统一工作区，支持从 IS-IS 数据生成、知识图谱构建、GraphRAG 部署、智能分析到前端演示的完整闭环。

## 设计理念

本 workspace 不是"一键黑盒"，而是支持**开发人员和 Hermes 对话协作**的开放式环境：

- **workspace-orchestrator**（Hermes skill）：对话式辅助开发人员完成故障诊断
- **knowledge-builder**（Hermes skill）：负责知识图谱构建、GraphRAG 索引、长期学习
- **scripts/**：无头/定时任务脚本，不替代日常交互诊断

## 目录结构

| 目录 | 职责 |
|------|------|
| `scripts_lib/` | 共享工作流工具模块（runner.py） |
| `isis-simulator/` | 生成 IS-IS 正常/故障场景的 pcap、log |
| `knowledge/` | RFC 摘要 + CSV 知识图谱 + 学习样本 |
| `graphrag/` | 零依赖 GraphRAG 查询服务 |
| `agent-analysis/` | pcap/log 特征提取、规则诊断、追踪报告 |
| `frontend/` | 白底浅色调、鼠标滚轮导航的演示界面 |
| `scripts/` | 无头/定时一键脚本 |
| `skills/` | 项目技能：流程编排、知识构建、素材转 CSV、知识校验 |

## LLM 配置

> 完整教程见 `docs/MODEL_CONFIGURATION.md`（含甲方自部署模型迁移步骤）。

平台三层模型（Hermes 本体 / 诊断引擎 / GraphRAG）当前统一为 **硅基流动 Qwen（Qwen/Qwen2.5-72B-Instruct）**。

### 诊断引擎（agent-analysis/.env.project）

```bash
LLM_PROVIDER=openai
OPENAI_COMPATIBLE_CHAT_ENDPOINT=https://api.siliconflow.cn/v1/chat/completions
OPENAI_COMPATIBLE_CHAT_API_KEY=sk-***
DEFAULT_MODEL_NAME=Qwen/Qwen2.5-72B-Instruct
```

- OpenAI 兼容格式（`/v1/chat/completions`）
- Qwen 思考模式已在客户端禁用（`enable_thinking: false`），保证直接返回诊断文本

### GraphRAG 服务（graphrag/config/settings.yaml）

- chat 模型：`Qwen/Qwen2.5-72B-Instruct`，OpenAI 兼容格式（`api_base: https://api.siliconflow.cn/v1`）
- embedding 模型：`local_tfidf` 本地离线向量化（免去外部 embedding 依赖）
- 常驻运行：`systemctl --user enable --now isis-graphrag.service`

### 甲方自部署迁移（OpenAI-compatible / vLLM）

诊断引擎：删除 `OPENAI_COMPATIBLE_*` 配置，改配指向甲方 vLLM 的 `OPENAI_COMPATIBLE_CHAT_ENDPOINT` + `DEFAULT_MODEL_NAME`。
GraphRAG：修改 settings.yaml 中 `default_chat_model` 的 api_base/model/api_key 后重建索引。
详细步骤见 `docs/MODEL_CONFIGURATION.md` 第 3.4 节。

## 快速开始（对话式）

```bash
# 查看当前状态
python -m workspace_orchestrator status

# 生成场景并分析
python -m workspace_orchestrator simulate link-down

# 分析最新已有数据
python -m workspace_orchestrator analyze

# 解释最新报告
python -m workspace_orchestrator explain

# 启动前端演示
python -m workspace_orchestrator frontend
```

## 构建知识图谱（独立 skill）

```bash
# 初始化或重建知识图谱（含 GraphRAG 索引）
python3 skills/knowledge-builder/run.py build --scenario link-down

# 仅构建 CSV 知识图谱
python3 skills/knowledge-builder/run.py build-csv

# 从历史 trace 发现未知故障
python3 skills/knowledge-builder/run.py discover --days 30

# 查看候选新故障
python3 skills/knowledge-builder/run.py candidates

# 合并候选到主图谱
python3 skills/knowledge-builder/run.py apply-candidates --candidate 20260706_143052
```

## 素材导入与知识校验

两个工具已归入 `skills/material-to-csv/` 和 `skills/kg-validator/`；项目根目录的同名路径是兼容符号链接。统一使用 `knowledge-builder` 入口：

```bash
# 提取候选，不修改正式知识表；--batch 为批次目录名
python3 skills/knowledge-builder/run.py extract /path/to/material.csv --source table:material.csv --batch import_001

# 审阅候选与正式知识表之间的新增、重复、冲突
python3 skills/knowledge-builder/run.py diff knowledge/incoming/import_001

# 确认后合并；自动备份、重建 CSV/JSON、校验并刷新 GraphRAG 输入文本
python3 skills/knowledge-builder/run.py merge knowledge/incoming/import_001

# 合并后继续构建 GraphRAG 索引（需要已配置的模型服务）
python3 skills/knowledge-builder/run.py merge knowledge/incoming/import_001 --index

# 单独校验本地知识库，禁用服务访问
python3 skills/knowledge-builder/run.py validate --graphrag-url ""

# 同时核对已运行的 GraphRAG 服务
python3 skills/knowledge-builder/run.py validate --graphrag-url http://localhost:9200
```

`extract`/`diff` 只生成或读取候选；只有显式 `merge` 才更新正式知识表。默认保留旧节点，`--prefer-new` 可覆盖冲突。每次合并保存首次合并前的 `merge_snapshot/`；每次构建另存 CSV/JSON 快照。

本地图谱构建后、GraphRAG 索引构建前、完整工作流的分析前都会运行校验。CRITICAL 返回非零并停止后续流程；MAJOR/MINOR/INFO 保留在报告中供复核。服务不可达时服务检查标记 SKIP。本地报告写入 `knowledge/learnings/validation/`，`validate --json` 只输出 JSON。

普通 `merge` 更新本地图谱和检索输入文本；检索索引需要 `--index` 或随后执行 `graphrag-index` 才更新。详见 [接入说明](docs/KNOWLEDGE_IMPORT_VALIDATION.md)。

## 无头/定时任务

```bash
# 轻量：生成并分析，不依赖 GraphRAG
python3 scripts/generate_and_analyze.py link-down

# 完整：生成 → 知识图谱 → GraphRAG → 分析 → 前端
python3 scripts/run_pipeline.py link-down

# 使用已审阅的素材批次运行完整流程
python3 scripts/run_pipeline.py link-down --knowledge-batch knowledge/incoming/import_001
```

## 服务端口

- GraphRAG 服务：默认 `9200`
- 前端演示：默认 `8080`

## 故障分析过程离线可视化

已提供独立的任务工作台，展示已完成故障分析的处理轨迹、字段证据、规则命中与报告。
素材提取、知识构建和质量校验作为独立知识维护记录展示。
直接用浏览器打开 [诊断任务工作台](demo/client-diagnosis/dist/index.html)，不需要现场重新调用模型。
新工作台从原始邻接中断与业务探测现象开始，读取项目本次实际运行的输入、特征、知识查询、规则、追踪与报告。
启动前端服务后，`/workbench` 通过 API 读取保存的任务；`/legacy` 保留原前端。
现场讲解步骤、模型记录来源和重建方式见 [使用说明](demo/client-diagnosis/README.md)。
此前的 [历史案例回放](demo/skill-replay/dist/index.html) 保留供对照。

## 更多文档

- `docs/KNOWLEDGE_IMPORT_VALIDATION.md` — 素材导入、自动校验与回滚说明

- `docs/MODEL_CONFIGURATION.md` — 三层模型配置教程（Hermes / 诊断引擎 / GraphRAG，含甲方迁移）
- `docs/REFACTOR_REPORT.md` — 重构过程与验证结果
