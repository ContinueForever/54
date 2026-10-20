---
name: material-to-csv
description: "54所 IS-IS 素材转 CSV 知识表格技能：将 RFC 文本、日志、厂商文档等素材转换为项目标准 CSV 知识表格（nodes/edges/node_attributes），自动去重、冲突检测，输出候选表格供 knowledge-builder 合并"
version: 1.0.0
author: agent-analysis team
---

# material-to-csv

## 角色定位

本 skill 是知识管线的**入料口**，负责把各种原始素材转换成项目标准的三张
CSV 知识表格，与现有知识管线无缝衔接：

```
素材（RFC文本/日志/文档/甲方表格）
   │  material-to-csv（本 skill）
   ▼
候选 CSV（knowledge/incoming/）── 去重/冲突检测 ──► 合并进 knowledge/tables/
                                                          │  knowledge-builder
                                                          ▼
                                              knowledge_graph.json → GraphRAG 索引
                                                          │  kg-validator
                                                          ▼
                                                     准确性验证
```

合并后自动调用项目构建入口重建本地图谱，并委托 kg-validator 校验；
`merge --index` 可继续委托共享工具构建 GraphRAG 索引。不做故障诊断。

## 触发条件

- 用户要求"把这份 RFC/文档/日志转成知识表格"、"提取成 CSV"
- 甲方提供新的知识素材（RFC 全文、厂商故障手册、历史工单日志）
- knowledge-builder discover 发现候选知识后需要格式化为表格
- 批量导入甲方 `config/knowledge_tables/` 提供的新 CSV 前的格式规整

## 执行原则

1. **Schema 严格对齐**：输出必须符合现有三张表的列定义（见下），
   这是与 knowledge-builder / kg-validator 衔接的契约
2. **候选制，不直改**：默认输出到 `knowledge/incoming/` 作为候选，
   经人工确认后用 `merge` 子命令才合并进 `knowledge/tables/`
3. **去重优先**：与现有 nodes.csv 比对，已有节点只补充不覆盖；
   冲突（同 ID 不同描述）单列报告交人工裁决
4. **来源必填**：每个提取的节点必须标注 source（RFC 编号 / 文件名 / 工单号），
   否则 kg-validator D 类检查会失败
5. **可重现**：同一素材重复运行产生相同候选输出（幂等），合并有快照可回滚
6. **Python 环境一致性**：使用 `python3`，跨项目模块需 PYTHONPATH 包含
   `agent-analysis/src:isis-simulator/src:graphrag/src:knowledge`

## CSV Schema 契约（与项目现有表格一致）

**nodes.csv**：`node_id,node_type,name,description,source`
- node_id：snake_case，如 `hello_timer_mismatch`、`combo_auth_area`
- node_type：fault / state / device / symptom / protocol / rule / composite_fault / tlv
- source：RFC 编号（RFC1195/RFC3358/RFC5301）/ `rule:<file>.json` /
  `scenario` / `combo_lib` / 素材文件名

**edges.csv**：`source_id,relation,target_id,description`
- 常用 relation：causes / prevents / indicates / has_state / combines
- 复合故障必须用 combines 分解到各子故障节点（kg-validator B 类强制）

**node_attributes.csv**：`node_id,attribute,value`
- 用于 TLV 编码等属性，如 `TLV_AREA_ADDR,code,1`

## 使用方法

```bash
cd /home/hermes/workspace

# 1. 从素材提取候选表格（不修改现有知识库）
python3 skills/material-to-csv/run.py extract <素材文件> --source RFC5301

# 2. 查看与现有知识库的差异（新增/重复/冲突）
python3 skills/material-to-csv/run.py diff knowledge/incoming/<批次目录>

# 3. 人工确认后合并进 knowledge/tables/（自动快照备份）
python3 skills/material-to-csv/run.py merge knowledge/incoming/<批次目录>

# 4. merge 已自动重建本地图谱、校验并刷新检索输入
# 如需同时更新索引，加 --index（需要模型服务）
python3 skills/material-to-csv/run.py merge knowledge/incoming/<批次目录> --index
```

## 支持的素材类型与提取策略

| 素材类型 | 识别方式 | 提取策略 |
|---------|---------|---------|
| RFC 摘要/全文（.txt/.md） | --source RFC* | 正则提取"症状→原因"句式、TLV 定义表、状态机条目 |
| IS-IS 日志（.log） | --source log:<文件名> | 提取事件类型，映射到已有 fault/state 节点；未知事件标 candidate |
| 既有 CSV/表格 | --source table:<文件名> | 列名映射到标准 schema，校验后直通 |
| 诊断规则 JSON | --source rule:<文件名> | 提取规则名/描述为 rule 类型节点 |

LLM 辅助提取：正则覆盖不了的自由文本，由 Hermes（即执行者本人）按
`references/extraction-guide.md` 的句式清单人工/LLM 判读后补写候选行，
排障与验证流程见 `references/verification-walkthrough.md`（含"提取不生效"三类根因与六步验证法），
写入批次目录的 `manual_nodes.csv` / `manual_edges.csv`，merge 时一并处理。

## 输出结构

```
knowledge/incoming/<batch_ts>/
  candidate_nodes.csv      # 提取出的候选节点
  candidate_edges.csv      # 提取出的候选边
  manual_nodes.csv         # （可选）人工/LLM 补写
  diff_report.md           # 与现有库的 新增/重复/冲突 对比
  merge_snapshot/          # merge 时自动备份合并前的 tables/
```

## 冲突处置

- **完全重复**（node_id 相同且描述一致）：跳过，不计入合并
- **同 ID 不同内容**：列入 diff_report 的"冲突"段，merge 时默认保留旧值，
  `--prefer-new` 才覆盖；每次覆盖记录到批次目录
- **新节点**：正常合并；若 node_type=composite_fault 而无 combines 边，
  给出 WARN（合并后 kg-validator B 类会报 MAJOR）

## 注意事项

- 本 skill 幂等：重复 extract 同一素材产生相同候选文件（覆盖写）
- merge 前自动快照 `knowledge/tables/` 到批次目录，回滚 = 快照拷回
- 合并后自动重跑 `knowledge/scripts/build.py` 和 `kg-validator`，并刷新检索输入；
  默认不构建 GraphRAG 索引，用 `merge --index` 或 knowledge-builder 的 graphrag-index 更新索引
- 后续构建/校验失败返回非零，但已合并表格保留，可用 merge_snapshot 回滚
- 路径默认由脚本位置确定，可用 WORKSPACE 环境变量指定数据工作区
- 甲方离线环境素材通常经由 U 盘导入 `config/knowledge_tables/`，
  用 `extract --source table:<文件>` 规整格式
