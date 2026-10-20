# material-to-csv 提取句式指南

当 `run.py extract` 的正则策略覆盖不了素材内容时（自由文本、中文故障手册、
工单记录），由 Hermes 按本指南判读后，将候选行写入批次目录的
`manual_nodes.csv` / `manual_edges.csv`，merge 时会一并处理。

## 一、节点提取句式

### fault（故障）
- "X 会导致/引起/造成 Y 故障" → X、Y 均可能是 fault/state 节点
- "故障现象：……"段落的标题 → fault 节点
- 日志中反复出现的 ERROR/WARN 事件类型 → fault 或 symptom

### state（状态）
- "邻接关系进入/离开某状态" → state（如 adjacency_up / adjacency_down）
- 状态机条目（RFC3358 邻接状态机）→ state

### symptom（症状）
- "表现为/可见/观察到……" → symptom
- 只描述现象不指明根因的条目

### rule（规则）
- agent-analysis/config/diagnosis_rules/*.json 中每条规则 → rule 节点，
  source 标 `rule:<文件名>`

### composite_fault（复合故障）
- 两个以上独立故障同窗口叠加 → composite_fault 节点，
  并**必须**配 combines 边分解到各子故障（见下）

## 二、边提取句式（relation 取值）

| 句式 | relation | 示例 |
|------|----------|------|
| A 导致/引起/造成 B | causes | mtu_mismatch causes adjacency_down |
| A 阻止/使 B 无法达成 | prevents | auth_mismatch prevents adjacency_up |
| A 表明/提示/可能意味着 B | indicates | neighbor_loss indicates link_down |
| 设备 X 通常处于状态 Y | has_state | r01 has_state adjacency_up |
| 复合故障 C 由子故障 A、B 叠加 | combines | combo_auth_area combines auth_mismatch |

## 三、人工判读规范

1. **node_id 一律 snake_case 英文**，与现有库风格一致；name 可中文
2. **source 必填**：素材来源（RFC 编号 / 日志文件名 / 工单号），
   留空会导致 kg-validator D 类检查 MAJOR
3. **拿不准 node_type 时用 unknown**，并在 description 注明"待人工确认"，
   不要猜测——kg-validator 会把 unknown 类型列为 MINOR 提醒
4. **与现有节点疑似同义时**（如素材的 "认证失败" vs 现有 auth_mismatch），
   优先复用现有 node_id 建边，不要新建同义节点；确需新建的在
   diff_report 冲突段说明理由
5. 每条提取记录**保留原文片段**在 description 或括号注释中，便于
   kg-validator F 类抽检回溯

## 四、典型示例

素材（厂商故障手册节选）：
> 当 Hello 报文中的 Area Address 与本地配置不一致时，邻居无法建立，
> 日志提示 "area mismatch"。该问题常与认证配置错误同时出现。

人工判读写入 manual_edges.csv：
```csv
source_id,relation,target_id,description
area_mismatch,prevents,adjacency_up,Area Address 不一致导致邻居无法建立（厂商手册）
```

不需要新建节点：area_mismatch、adjacency_up 已存在，只补边即可。
