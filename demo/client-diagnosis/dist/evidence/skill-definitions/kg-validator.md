---
name: kg-validator
description: "54所 IS-IS 知识图谱提取准确性验证技能：校验 knowledge/tables CSV、knowledge_graph.json 与 GraphRAG 索引的一致性、引用完整性、来源真实性与提取准确性，输出分级验证报告"
version: 1.0.0
author: agent-analysis team
---

# kg-validator

## 角色定位

本 skill 是知识管线的**质量门禁**，负责验证"从素材（RFC 摘要 / 诊断规则 /
仿真场景 / 学习快照）提取到知识图谱"这一过程的**准确性**，回答三个问题：

1. **结构对不对**：CSV / JSON 是否符合 schema，引用是否完整（悬空边、重复节点）
2. **内容真不真**：每个节点的 source 标注是否真实存在，描述是否与来源素材一致
3. **同步没同步**：tables → knowledge_graph.json → GraphRAG 索引 三级是否一致

本 skill **只验证、不修改**。发现的问题输出为分级报告，由人工或
`knowledge-builder` / `material-to-csv` 修复后重新验证。

与项目其他 skill 的关系：

```
material-to-csv ──> knowledge/tables ──> knowledge-builder(build+index) ──> GraphRAG
                            │                                              │
                            └──────────── kg-validator 全程验证 ◄──────────┘
workspace-orchestrator 的诊断质量依赖本 skill 保证的知识准确性
```

## 触发条件

- 用户要求"验证知识图谱"、"检查知识库准确性"、"知识图谱对不对"
- `material-to-csv` 合并新素材后（自动执行本地校验）
- `knowledge-builder` 重建图谱后、构建索引前（自动执行本地校验）
- 完整工作流运行分析前（自动执行，含服务检查）
- GraphRAG 查询结果出现张冠李戴、引用不存在实体等疑似知识错误时
- 交付甲方前的例行质量检查

## 执行原则

1. **只读验证**：绝不修改 knowledge/ 与 graphrag/ 下任何文件；报告写入
   `knowledge/learnings/validation/`（该目录专为验证报告保留）
2. **证据驱动**：每条 FAIL/WARN 必须给出文件位置与具体内容，不允许"可能有问题"
3. **分级处置**：CRITICAL（结构损坏/悬空引用，会直接导致诊断或索引出错）/
   MAJOR（来源不实、描述与来源矛盾）/ MINOR（命名不规范、冗余）/
   INFO（改进建议）
4. **Python 环境一致性**：使用 `python3`，跨项目模块需 PYTHONPATH 包含
   `agent-analysis/src:isis-simulator/src:graphrag/src:knowledge`
5. **GraphRAG 检查可降级**：服务未启动时相关检查标记 SKIP 而非 FAIL

## 验证项总览

详见 `references/validation-checklist.md`。六大类：

| 类别 | 内容 | 典型问题 |
|------|------|---------|
| A. Schema | CSV 列名/必填列/编码/JSON 合法性 | 列缺失、BOM、非法 JSON |
| B. 引用完整性 | 边两端节点存在、combines 指向 fault 节点 | 悬空边、combines 指向不存在子故障 |
| C. 去重 | node_id 重复、边重复、名称近似重复 | 同义节点（auth_mismatch vs auth_failure） |
| D. 来源真实性 | source 字段可溯源（RFC 文件/规则 JSON/scenario 注册表） | source 标注的文件不存在 |
| E. 三级一致性 | CSV ↔ knowledge_graph.json ↔ GraphRAG /health 计数 | 索引陈旧（改了表没重建） |
| F. 提取准确性抽检 | 节点描述与来源素材内容比对 | 描述张冠李戴、TLV 编号错误 |

## 使用方法

```bash
cd /home/hermes/workspace

# 全量验证（六大类）
python3 skills/kg-validator/run.py

# 只跑某几类
python3 skills/kg-validator/run.py --checks A,B,E

# 含 GraphRAG 服务一致性（服务需在运行）
python3 skills/kg-validator/run.py --graphrag-url http://localhost:9200

# 输出 JSON 供程序消费
python3 skills/kg-validator/run.py --json
```

退出码：0 = 无 CRITICAL；1 = 存在 CRITICAL（适合接入 CI / cron 门禁）。

## 输出

- 终端：分级摘要 + 每条问题的证据
- 文件：`knowledge/learnings/validation/kg_validation_<ts>_<微秒>.md`
  （完整报告，含各类逐项结果与修复建议）

## 与其他 skill 的衔接

- 发现 CRITICAL（如悬空边）→ 提示用 `material-to-csv` 或手工修表后
  重跑 `knowledge-builder` 的 build 阶段
- 发现 E 类不一致（索引陈旧）→ 提示重跑 `knowledge-builder` 的 index 阶段
- 验证通过是把新知识交付给 `workspace-orchestrator` 诊断使用的前提

## 注意事项

- F 类抽检默认抽 10 个节点（`--sample N` 调整），全量比对用 `--sample 0`
- 描述比对是**关键词级**核对（来源文本中是否包含描述的核心术语），
  不做语义级判断；语义存疑的标 INFO 交由人工或 LLM 复核
- node_attributes.csv 的 TLV code 会与 `isis_simulator/isis_pdu.py`
  中实际使用的 TLV 常量交叉核对（如存在该模块）
