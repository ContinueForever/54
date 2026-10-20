# 54所卫星网络 IS-IS 智能分析平台 — 重构完成报告

## 重构目标

将 `/home/hermes/workspace` 重构为可支持以下完整工作流的统一平台：

1. 生成 IS-IS 正常 / 故障场景 pcap、log
2. 基于 RFC 与本地数据构建知识图谱，用于 GraphRAG
3. 部署零依赖 GraphRAG 查询服务
4. 构建前端演示界面
5. 通过 Hermes native skill 串联整条工作流

## 重构后的目录结构

```
/home/hermes/workspace/
├── README.md                          # 项目总览
├── docs/
│   └── STATUS_AND_ROADMAP.md          # 状态与路线图
├── scripts/
│   ├── generate_and_analyze.py        # 轻量工作流：生成+分析
│   └── run_pipeline.py                # 完整工作流：生成+知识+GraphRAG+分析+前端
├── skills/
│   └── workspace-orchestrator/SKILL.md  # Hermes native skill
├── isis-simulator/                    # 数据生成器
│   ├── src/isis_simulator/
│   │   ├── __init__.py
│   │   ├── __main__.py                # python -m isis_simulator
│   │   ├── generate.py                # 统一生成入口
│   │   ├── isis_pdu.py
│   │   ├── isis_topology.py
│   │   ├── pcap_writer.py
│   │   ├── scenario_lib.py
│   │   ├── verify.py
│   │   ├── log_generator.py
│   │   └── scenarios/                 # 10 个场景脚本
│   ├── scenarios/                     # 旧场景目录（保留未删除）
│   └── output/                        # 生成产物
├── knowledge/                         # 知识图谱
│   ├── rfc/                           # RFC 摘要
│   ├── tables/                        # CSV 节点/边表
│   ├── scripts/build.py               # 从场景/RFC 构建图谱
│   └── knowledge_graph.json
├── graphrag/                          # GraphRAG 服务
│   ├── src/graphrag/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── server.py
│   │   └── indexer.py
│   └── data/tables/                   # 旧数据目录（保留未删除）
├── agent-analysis/                    # 智能分析引擎
│   ├── src/agent_analysis/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── engine.py
│   │   ├── pcap_feature.py
│   │   ├── log_feature.py
│   │   ├── rules.py
│   │   ├── knowledge_adapter.py
│   │   └── llm_client.py
│   ├── config/
│   ├── data/incoming/                 # 分析输入
│   ├── data/traces/                   # 执行追踪
│   └── output/reports/                # 诊断报告
└── frontend/                          # 前端演示
    ├── __init__.py
    ├── index.html                     # 白底浅色调 + 滚轮导航
    └── server.py
```

## 已完成验证

| 模块 | 验证命令 | 状态 |
|------|----------|------|
| 数据生成 | `python -m isis_simulator link-down` | ✅ 生成 pcap + log |
| 知识构建 | `python -m knowledge.scripts.build` | ✅ 18 nodes / 24 edges |
| GraphRAG | `python -m graphrag --port 9209` | ✅ 查询正常 |
| 分析引擎 | `python -m agent_analysis --input ...` | ✅ 报告 + 追踪 |
| 前端 | `python frontend/server.py --port 8084` | ✅ API + 页面正常 |
| 轻量工作流 | `python scripts/generate_and_analyze.py link-down` | ✅ 端到端 |
| 完整工作流 | `python scripts/run_pipeline.py link-down --skip-frontend` | ✅ 端到端 |

## 关键调整

- `isis_simulator` 改为 Python 包结构，场景脚本位于 `src/isis_simulator/scenarios/`
- `generate.py` 默认输出目录统一为 `output/`（含 `pcapng/` 和 `logs/` 子目录）
- 命令行场景名支持连字符（如 `link-down`），内部自动映射为下划线模块名
- `agent_analysis` 的 `PROJECT_ROOT` 修正为 `agent-analysis/`（非 `src/`）
- `graphrag` 默认读取 `knowledge/tables/` 的 CSV
- `frontend` 通过 `python frontend/server.py` 启动，API 提供 `/api/health`、`/api/latest`、`/api/query`
- 创建 Hermes native skill `workspace-orchestrator`，脚本位于 `workspace/scripts/`

## 使用方式

### 1. 手动分别运行

```bash
cd /home/hermes/workspace
export PYTHONPATH="agent-analysis/src:isis-simulator/src:graphrag/src:knowledge:frontend"

# 生成数据
python -m isis_simulator link-down --output isis-simulator/output/run_test

# 构建知识
python -m knowledge.scripts.build

# 启动 GraphRAG
python -m graphrag --port 9200

# 运行分析（另一个终端）
python -m agent_analysis --input agent-analysis/data/incoming/run_test

# 启动前端（另一个终端）
python3 frontend/server.py --port 8080
```

### 2. 轻量工作流

```bash
python3 scripts/generate_and_analyze.py link-down
```

### 3. 完整工作流（启动 GraphRAG + 前端）

```bash
python3 scripts/run_pipeline.py link-down
```

### 4. Hermes skill 调用

```bash
hermes -s workspace-orchestrator -q "生成并分析 link-down 场景，展示结果"
```

## 遗留说明

- 旧目录 `isis-simulator/scenarios/`、`agent-analysis/analysis/`、`graphrag-server/` 等未删除，作为历史备份保留
- 旧追踪文件 `agent-analysis/data/traces/` 中仍包含早期版本，不影响新流程

## 下一步建议

1. 接入真实 LLM 客户端（当前为占位）
2. 增强异常规则与根因定位精度
3. 前端增加时序图、拓扑图可视化
4. 将知识图谱迁移到更正式的 GraphRAG/OWL 格式
