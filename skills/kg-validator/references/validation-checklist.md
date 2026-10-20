# kg-validator 验证检查清单

本清单是 `run.py` 六大类检查的完整定义与判定标准，供人工审查或 LLM 复核时使用。

## 问题等级

| 等级 | 含义 | 处置 |
|------|------|------|
| CRITICAL | 结构损坏，会直接导致诊断出错或索引构建失败 | 修复前禁止重建索引/交付 |
| MAJOR | 来源不实、内容矛盾、索引陈旧 | 应修复 |
| MINOR | 命名/冗余问题，不影响正确性 | 建议修复 |
| INFO | 观察性建议 | 仅供参考 |

## A. Schema 校验

- [ ] nodes.csv 列名为 `node_id,node_type,name,description,source`
- [ ] edges.csv 列名为 `source_id,relation,target_id,description`
- [ ] node_attributes.csv 列名为 `node_id,attribute,value`
- [ ] 前 3 列无空值（逐行检查）
- [ ] knowledge_graph.json 为合法 JSON，含 nodes/edges 列表
- [ ] node_type 属于标准集合：fault/state/device/symptom/protocol/rule/composite_fault/tlv/interface

## B. 引用完整性

- [ ] 每条边的 source_id、target_id 都存在于 nodes.csv（无悬空边）
- [ ] combines 边：source 必须是 composite_fault 节点，target 必须是 fault 节点
- [ ] 每个 composite_fault 节点至少有 2 条 combines 出边（复合故障可分解）

## C. 去重

- [ ] node_id 无重复
- [ ] (source_id, relation, target_id) 三元组无重复边
- [ ] 同类型节点间无名称高度相似（>0.85）的疑似同义节点
  - 已知需人工甄别的对：auth_mismatch（RFC fault）vs auth_failure（规则），
    二者来源不同、用途不同，属于**合法共存**，不必合并

## D. 来源真实性

source 字段取值与核对方式：

| source 值 | 核对方式 |
|-----------|---------|
| `RFC1195` / `RFC3358` / `RFC5301` | knowledge/rfc/ 下存在对应文件 |
| `rule:<file>.json` | agent-analysis/config/diagnosis_rules/ 下存在该文件 |
| `scenario` | isis_simulator/generate.py 注册了同名场景（下划线转短横线） |
| `combo_lib` | generate.py 注册了对应 combo-* 场景 |
| `observational` 等约定值 | 不强制核对，计数即可 |

## E. 三级一致性

```
knowledge/tables/*.csv  →(build.py)→  knowledge_graph.json  →(索引重建)→  GraphRAG
```

- [ ] CSV 与 JSON 节点集合完全相同（差集为空）
- [ ] CSV 与 JSON 边数一致
- [ ] GraphRAG /health 的 nodes/edges 与 CSV 计数一致（不一致 = 索引陈旧，需重建）
- [ ] GraphRAG /health 的 graphrag_index_loaded 为 true

## F. 提取准确性抽检

- [ ] 抽检 RFC 来源节点：description 的核心术语（英文词/数字）在对应 RFC
  摘要文本中出现率 ≥ 50%，低于则判"描述与来源不符"
- [ ] rule: 来源节点的 node_id 能在对应规则 JSON 文本中找到同名定义
- [ ] node_attributes.csv 中 TLV code 值与 isis_simulator/isis_pdu.py
  实际使用的 TLV 常量交叉核对（十进制或 0x 十六进制形式出现）

## 与 critic-checklist 的分工

- `critic-checklist.md`（workspace-orchestrator）：审查**单次诊断报告**的质量
- 本清单：审查**知识图谱本身**的提取准确性，是诊断质量的上游保障
