# IS-IS 分析框架说明

## 分层诊断模型

系统将 IS-IS 网络故障分析划分为 4 个层次，从底层到顶层逐层排查：

```
L4 应用层    → 端到端连通性、业务流量、性能指标
L3 路由层    → IS-IS 邻居状态、LSP 数据库、路由表  ← 核心关注
L2 链路层    → 邻居发现、Hello 报文、链路参数
L1 物理层    → 接口状态、光功率、物理连通性
```

## 诊断流程

1. **数据加载**：读取甲方提供的 pcap、log、状态 JSON
2. **逐层检查**：按 L1 → L2 → L3 → L4 顺序检查
3. **规则匹配**：每层调用对应的 JSON 规则文件
4. **异常处理**：
   - 规则命中 → 直接输出结论
   - 规则未覆盖 → 调用 LLM 辅助
5. **追踪记录**：记录全过程到 data/traces/
6. **报告生成**：输出 Markdown 报告 + Mermaid 时序图

## 规则引擎工作原理

规则以 JSON 形式存储于 `config/diagnosis_rules/`，每条规则包含：
- `id`：规则唯一标识
- `indicators`：检测指标列表
- `severity`：严重级别（critical/warning/info）
- `suggestion`：修复建议
- `references`：RFC 引用

匹配时，系统将数据特征与 indicators 对比，命中则触发对应诊断结论。
