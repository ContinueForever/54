# material-to-csv 验证流程文档（辅助排障指南）

> 用途：当用户反映"extract 提取不生效 / 跑完没有 CSV"时，按本文档逐条定位。
> 本文档基于 2026-09-28 的一次完整排障验证整理，所有用例均已实测。

## 一、先搞清楚：extract 的产出去哪了

extract **从不直接写 `knowledge/tables/`**。它的产出在：

```
knowledge/incoming/<批次名>/
├── candidate_nodes.csv      # 候选节点（即使 0 行也会有表头）
├── candidate_edges.csv      # 候选边
├── candidate_attributes.csv # 候选属性（仅 TLV 类素材产生）
└── diff_report.md           # 与现有库的对比报告
```

之后需要 `diff` 审阅 → `merge` 才真正合并进 `knowledge/tables/`。
**如果你在 tables/ 里找新内容，那就是找错地方了。**

## 二、四种素材类型与预期行为

| 素材 | 命令中的 --source | 提取器 | 预期产出 |
|------|------------------|--------|----------|
| 日志（行内含 ISIS 关键词） | `log:<文件名>` | extract_log | 已知事件→映射节点；未知事件→candidate 节点；**不产生边** |
| CSV 表格 | `table:<文件名>` | extract_table | 边表（source_id,relation,target_id）→边；节点表（node_id/名称列）→节点 |
| 规则 JSON | `rule:<文件名>` | extract_rule_json | 每条规则→rule 节点 |
| 文本（RFC/md/txt） | 其他（如 RFC5301） | extract_rfc | 结构化条目→节点；因果句式→边；TLV 定义→tlv 节点+属性 |

判定逻辑：先看 --source 前缀，没有匹配前缀再按文件后缀（.log/.csv/.json/其他）。

## 三、"提取不生效"的三类真实原因（2026-09-28 实测确认）

### 原因 1：中文自由文本，正则天然覆盖不到（已部分修复 + 设计如此）

**复现**：对项目自带的 `knowledge/rfc/rfc1195_summary.md` 提取，修复前产出 **0 节点 0 边**，
只有两个只有表头的空 CSV——看起来就是"不生效"。

**根因**：修复前的条目正则要求英文大写字母开头（`[A-Z][A-Za-z]...`），
中文条目永远不匹配；因果关系正则只认识 causes/prevents/indicates 等英文动词。

**修复内容（run.py）**：
- 条目正则兼容中文（支持 `- 邻接中断：邻居关系丢失` 这类写法）；
- 新增中文因果句式（导致/引起/造成→causes，表明/指示→indicates，防止/避免→prevents）；
- 新增项目 RFC 摘要常用的 `TLV 128 (IP Internal Reachability)` 格式识别；
- **纯自由中文段落仍属于 LLM 判读轨道**：由 Hermes 按 references/extraction-guide.md
  读素材后手写 `manual_nodes.csv` / `manual_edges.csv` 放进批次目录，merge 会一并处理。
  这不是 bug，是双轨设计。

### 原因 2：CSV 表头不在识别清单里（已修复 + 加了告警）

**复现**：表头为 `故障名称,类型,说明` 的中文 CSV，修复前产出 0 行且**无任何提示**。

**根因**：extract_table 修复前只认 `node_id/id/ID` 三个列名，其他表头静默返回空。

**修复内容**：列名映射扩充到中文常见表头（名称/故障名称/类型/描述/说明/编号等），
纯中文名称用内容哈希生成 `zh_xxxxxxxxxx` 形式的 node_id；
表头完全无法识别时打印 WARN 并指向 extraction-guide.md。

### 原因 3：产出为空时没有任何提示（已修复）

修复前即使提取 0 行，工具也正常写空 CSV 并提示"下一步：人工审阅"，
用户无从判断是素材问题还是用法问题。

**修复内容**：extract 结果为 0 节点 0 边 0 属性时，打印 WARN 列出三类常见原因
和对应的解决办法（LLM 判读轨道 / 日志关键词 / 表头要求）。

## 四、标准验证流程（排障时按此顺序执行）

```bash
cd /home/hermes/workspace

# 第 1 步：日志素材（已知+未知事件混合）
cat > /tmp/t.log <<'EOF'
Jan 01 00:00:41 R02 ISIS: Authentication failed for IIH from 0001.0000.0001
Jan 01 00:00:43 R02 ISIS: Unknown LSP purge storm from 0000.0000.0009
EOF
python3 skills/material-to-csv/run.py extract /tmp/t.log --source log:t.log --batch v1
# 预期：auth 事件→冲突（保留旧值），未知事件→candidate_unknown_* 节点

# 第 2 步：中文表头 CSV
printf '故障名称,类型,说明\n认证超时,fault,邻居认证超时\n' > /tmp/t.csv
python3 skills/material-to-csv/run.py extract /tmp/t.csv --source table:t.csv --batch v2
# 预期：1 个节点（zh_ 哈希 ID 或英文 snake ID）

# 第 3 步：项目自带 RFC 摘要
python3 skills/material-to-csv/run.py extract knowledge/rfc/rfc1195_summary.md \
  --source RFC1195 --batch v3
# 预期：4 个 tlv_* 节点 + candidate_attributes.csv 含 code 128/129/130/132

# 第 4 步：英文结构化文本
printf '**Adjacency Timeout** — Hold timer expiry causes adjacency loss.\n' > /tmp/t.txt
python3 skills/material-to-csv/run.py extract /tmp/t.txt --source RFC5301 --batch v4
# 预期：1 个 symptom 节点 + 1 条 causes 边

# 第 5 步：merge + 回滚（验证合并链路和快照可回滚性）
md5sum knowledge/tables/*.csv > /tmp/before.md5
python3 skills/material-to-csv/run.py merge knowledge/incoming/v2
cp knowledge/incoming/v2/merge_snapshot/*.csv knowledge/tables/
md5sum -c /tmp/before.md5          # 必须全部 OK（字节级回滚）

# 第 6 步：清理测试批次
rm -rf knowledge/incoming/v1 knowledge/incoming/v2 knowledge/incoming/v3 knowledge/incoming/v4
```

## 五、验证后必做（merge 真正合入时）

merge 只改 CSV，后续三步缺一不可：

1. `python3 knowledge/scripts/build.py` — 重建 knowledge_graph.json
2. `python3 skills/kg-validator/run.py` — 六大类验证（B/E 类会发现不一致）
3. 重建 GraphRAG 索引（如需检索立即生效；chat 模型变更时也必须重建）

## 六、本次排障修改记录（2026-09-28）

文件：`skills/material-to-csv/run.py`（仅此一个文件，6 处修改）

1. RELATION_PATTERNS 增加 3 条中文因果句式
2. extract_rfc 条目正则兼容中文 + 纯中文名称哈希 ID + 中文故障关键词分类
3. extract_rfc 增加 `TLV <num> (<name>)` 格式识别（项目 RFC 摘要常用）
4. extract_table 列名映射扩充中文表头 + 无法识别时 WARN
5. cmd_extract 零提取时 WARN 并给出三类原因指引
6. cmd_merge 快照防覆盖：同批次重复 merge 时保留首次 merge 前的原始快照
   （修复前：二次 merge 会把"已合并状态"存成快照，回滚后数据不归位——
   交付前回归实测抓到的真实缺陷）

验证结论：修复前 4 类素材中 2 类产出为空且无任何提示；修复后 4 类全部
有正确产出或明确的 WARN 指引；merge 幂等（重复 merge 新增 0 跳过 N）；
快照经"merge→再 merge→回滚"压力测试 md5 校验字节级一致；
英文提取能力无回归（修复前后同为 4 节点 3 边）。
