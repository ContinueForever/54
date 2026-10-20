---
name: knowledge-builder
description: "54所 IS-IS 知识图谱构建与持续学习技能：从仿真/真实数据生成知识图谱，构建 GraphRAG 索引，发现未知故障并补充知识"
version: 1.0.0
author: agent-analysis team
---

# knowledge-builder

## 角色定位

本 skill 负责**知识图谱的生命周期管理**，包括：

1. 生成/收集 IS-IS pcap、log 数据（仿真或真实）
2. 结合已有 RFC 摘要和诊断规则，构建 CSV 表格知识图谱
3. 生成 GraphRAG 输入文本
4. 构建 GraphRAG 索引
5. 通过 material-to-csv 导入文档/日志素材，通过 kg-validator 自动校验图谱
6. 长期运行后，收集未知故障样本，通过聚类/规则比对发现新故障模式，
   经人工确认后补充到知识图谱中

本 skill **不负责**具体故障诊断。
诊断分析请使用 `workspace-orchestrator` skill。

## 触发条件

- 用户要求"构建知识图谱"、"更新知识库"、"生成 GraphRAG 索引"
- 用户要求"从真实数据补充知识"、"发现新故障模式"
- 用户运行"知识库初始化"、"知识库增量更新"
- 定时任务需要定期更新知识图谱（例如每日/每周）

## 执行原则

1. **规则优先**：已有 RFC 摘要和 JSON 诊断规则是知识的主要来源
2. **仿真补充**：从 `isis-simulator` 场景中提取故障定义作为补充
3. **真实数据驱动**：长期运行积累的真实 pcap/log 是发现未知故障的主要来源
4. **人工确认**：自动发现的新故障模式必须以"候选"形式保存，经确认后才合并入主图谱
5. **可回滚**：每次更新保留 `knowledge/tables/` 和 `knowledge/learnings/` 的历史快照
6. **Python 环境一致性**：本工作区使用 `python3`（`/usr/bin/python3`），且 `agent-analysis/src`、`isis-simulator/src`、`graphrag/src`、`knowledge` 等模块未安装到系统 site-packages，必须通过 `PYTHONPATH` 加载。运行任何跨项目命令前，先确认 `PYTHONPATH` 已包含上述路径；否则会出现 `No module named isis_simulator` 等导入错误。优先使用 `scripts_lib/runner.py` 中的 `pythonpath_env()` 和 `run()` 来统一执行环境。

## 环境要求

- 工作目录：`/home/hermes/workspace`
- `scripts_lib/runner.py` 提供共享工具函数
- `knowledge/tables/` 存放当前生效的 CSV 知识图谱
- `knowledge/learnings/` 存放未知故障样本和候选节点

## 工作流步骤

### 流程 A：从基础规则初始化知识图谱

1. **读取基础规则**：
   - `knowledge/rfc/` 中的 RFC 摘要
   - `agent-analysis/config/diagnosis_rules/` 中的 JSON 规则
   - `agent-analysis/config/knowledge_tables/` 中的初始 CSV（若存在）
2. **提取仿真场景**：从 `isis-simulator/src/isis_simulator/scenarios/*.py` 提取故障定义
3. **合并节点和边**：去重合并到 `knowledge/tables/nodes.csv` 和 `edges.csv`
4. **生成 JSON 中间文件**：`knowledge/knowledge_graph.json`
5. **生成 GraphRAG 输入文本**：`graphrag/input/knowledge_graph.txt`
6. **构建 GraphRAG 索引**：`python -m graphrag_server.indexer`
7. **启动 GraphRAG 服务**（可选）：供后续 `workspace-orchestrator` 查询使用

### 流程 B：从长期运行数据中发现新故障（持续学习）

1. **收集学习样本**：
   - 从 `agent-analysis/data/traces/` 读取历史 trace
   - 从 `agent-analysis/output/reports/` 读取历史报告
   - 从指定的历史数据目录读取 pcap/log
2. **识别未命中规则的样本**：
   - 提取 event_types
   - 与 `config/diagnosis_rules/` 中所有规则的 indicators 比对
   - 未匹配的记录为"未知事件"
3. **聚类未知事件**：
   - 按 event_type 聚类
   - 按出现频率、影响节点、时间窗口进一步分组
4. **生成候选节点/边**：
   - 写入 `knowledge/learnings/candidates/` 目录
   - 每个候选包含：事件名称、描述、出现次数、样例 trace_id、建议关系
5. **人工确认（推荐）**：
   - 由开发人员审查候选文件
   - 确认后调用 `knowledge-builder apply-candidates` 合并到主图谱
6. **重新构建 GraphRAG 索引**

### 流程 C：增量更新（已有新场景/新规则）

1. 重新运行 `knowledge.scripts.build`
2. 重新运行 `knowledge.scripts.build_graphrag_input`
3. 运行 `python3 skills/knowledge-builder/run.py graphrag-index`（先校验并刷新输入，再构建索引）
4. 启动/重启 GraphRAG 服务

## 与 Hermes 对话示例

### 示例 1：初始化知识图谱

```
用户：初始化知识图谱
Hermes：
  1. 读取 RFC 摘要和诊断规则
  2. 提取 10 个 isis-simulator 故障场景
  3. 合并生成 25 个节点、35 条边
  4. 写入 knowledge/tables/nodes.csv 和 edges.csv
  5. 生成 GraphRAG 输入文本（约 8000 字符）
  6. 构建 GraphRAG 索引...
  7. 索引构建完成，启动 GraphRAG 服务在 localhost:9200
```

### 示例 2：从真实数据发现未知故障

```
用户：分析最近一个月的 trace，看看有没有新故障模式
Hermes：
  1. 读取 agent-analysis/data/traces/ 下 120 个 trace
  2. 提取 event_types 并比对诊断规则
  3. 发现 3 类未命中规则的事件：
     - isis_lsp_checksum_error（出现 8 次）
     - isis_overload_bit_set（出现 5 次）
     - isis_mtu_propagation_fail（出现 2 次）
  4. 生成候选文件：
     - knowledge/learnings/candidates/20260706_143052.json
  5. 请人工确认后，调用 knowledge-builder apply-candidates
```

### 示例 3：合并候选故障到主图谱

```
用户：确认合并昨天发现的候选故障
Hermes：
  1. 读取 knowledge/learnings/candidates/20260706_143052.json
  2. 将确认的候选节点/边追加到 nodes.csv/edges.csv
  3. 重新生成 GraphRAG 输入并构建索引
  4. 候选文件已标记为 applied
```

## 常用命令速查

运行以下入口会自动配置项目环境，无需额外设置 PYTHONPATH：

```bash
python3 skills/knowledge-builder/run.py build
python3 skills/knowledge-builder/run.py build --no-index
python3 skills/knowledge-builder/run.py build-csv
python3 skills/knowledge-builder/run.py graphrag-index
python3 skills/knowledge-builder/run.py serve --port 9200
python3 skills/knowledge-builder/run.py discover --days 30
python3 skills/knowledge-builder/run.py candidates
python3 skills/knowledge-builder/run.py apply-candidates --candidate 20260706_143052

# 提取素材、审阅候选，再显式合并
python3 skills/knowledge-builder/run.py extract /path/to/material.csv --source table:material.csv --batch import_001
python3 skills/knowledge-builder/run.py diff knowledge/incoming/import_001
python3 skills/knowledge-builder/run.py merge knowledge/incoming/import_001
# --index 可在合并后继续更新检索索引
python3 skills/knowledge-builder/run.py merge knowledge/incoming/import_001 --index
python3 skills/knowledge-builder/run.py validate --graphrag-url ""
```

素材提取/合并实现位于 `skills/material-to-csv/run.py`，校验实现位于
`skills/kg-validator/run.py`。统一构建实现位于 `knowledge/scripts/build.py`。
构建前检查结构并备份，构建后自动校验，索引前再次校验。CRITICAL 停止后续步骤；
其他等级写入验证报告。`merge` 默认只更新本地图谱和检索输入，`--index` 更新索引并尝试重启已运行的项目 systemd 服务。

## 输出产物

- `knowledge/tables/nodes.csv` — 当前知识节点
- `knowledge/tables/edges.csv` — 当前知识关系
- `knowledge/knowledge_graph.json` — 中间 JSON
- `knowledge/learnings/` — 学习样本和候选节点
- `graphrag/input/knowledge_graph.txt` — GraphRAG 输入文本
- `graphrag/output/` — GraphRAG 索引产物

## 参考文档

- `references/continuous-learning-pipeline.md` — 从长期运行数据中发现未知故障并补充知识图谱的完整流程和候选文件格式

- 构建 GraphRAG 索引需要 LLM API 配置（`graphrag/.env` 和 `config/settings.yaml`），离线环境请使用本地 vLLM
- 大规模索引前建议先用 `--dry-run` 验证配置
- 真实数据中的未知事件可能包含噪声，候选节点需人工确认后再合并
- 定期备份 `knowledge/tables/` 目录，避免误操作导致知识丢失
