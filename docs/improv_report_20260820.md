# 改进报告 2026-08-20 — 复合故障诊断、LLM 全程参与、批判性审查

## 一、本轮目标

甲方要求：**Hermes（LLM）在分析流程每个关键环节参与思考与判断**，而不是"一键黑盒"跑脚本；
同时补齐**复合故障诊断**能力（两个独立故障叠加时需分别识别），并引入**批判性审查**环节确保结论质量。

## 二、关键决策（与甲方确认）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| LLM 参与方式 | 在 Hermes 执行 skills 流水线时多阶段介入（每阶段推演节点），脚本内保持单次 LLM 辅助诊断 | 体现 LLM 思考能力，避免脚本内重复调用 LLM 的黑盒化 |
| 诊断 LLM | 硅基流动 Qwen（Qwen/Qwen2.5-72B-Instruct） | kimi-k3 配额失效（401）；Qwen2.5 无思考模式、JSON 输出稳定 |
| 批判性审查 | 批判子智能体（isis-critic）按 checklist 独立审查 | 独立审查者立场，输出结构化批判意见 |

## 三、交付内容

### 1. 复合故障场景（11 组）

`isis-simulator/src/isis_simulator/scenarios/combo_lib.py` 定义 `COMBO_FAULTS`：

- auth+area / auth+mtu / auth+circuit / auth+hello / mtu+area / mtu+hello / mtu+circuit
- circuit+area / hello+area / duplicate+auth / link+netem

每组生成 pcap（两个故障叠加）+ 合并日志（双故障事件文本）。`generate.py` 注册全部 11 组。

### 2. 知识注入

- `knowledge/scripts/build.py`：为每个复合场景注入 `composite_fault` 节点与 `combines` 关系边
- 知识库现状：35 节点（含 11 个 composite_fault）、75 边（含 22 条 combines）
- GraphRAG 索引已重建并经查询验证（复合故障问答返回正确诊断流程）

### 3. LLM 全程参与（Hermes 推演节点）

`skills/workspace-orchestrator/SKILL.md`（3.0.0）将流水线拆为 9 个阶段，每阶段之间
Hermes 必须输出【Hermes 推演 · 阶段名】记录，包含三要素：看见什么（观察）/ 我的判断（推理）/ 下一步决策（决策）。
`run.py` 支持 `--stage` 分阶段执行。

### 4. 批判性子智能体（isis-critic）

- 检查清单：`skills/workspace-orchestrator/references/critic-checklist.md`
- 问题等级：CRITICAL / MAJOR / MINOR / INFO（含证据、风险、建议）
- 输出：`agent-analysis/output/reports/run_<ts>.critique.md`（critic 阶段自动生成模板）
- SKILL.md 规定：**批判性审查为必需步骤**，子智能体不可用时 Hermes 应停止并说明原因

## 四、验证结果

### 21 场景规则命中全量验证（本轮通过）

| 场景 | 命中规则 | 结论层 |
|------|---------|--------|
| baseline | 无 | normal |
| link-down | L1×1, L2×1 | L1 |
| auth-mismatch | L2×2 | L2 |
| mtu-mismatch | L2×2 | L2 |
| area-mismatch | L3×1 | L3 |
| hello-timer-mismatch | L2×2 | L2 |
| circuit-type-mismatch | L2×1, L3×1 | L2 |
| duplicate-system-id | L3×1 | L3 |
| netem-loss-delay | L4×1 | L4 |
| lsp-suppression | L2×1 | L2 |
| combo-auth-area | L2×2, L3×1 | L2 |
| combo-auth-circuit | L2×3, L3×1 | L2 |
| combo-auth-hello | L2×3 | L2 |
| combo-auth-mtu | L2×3 | L2 |
| combo-circuit-area | L2×1, L3×2 | L2 |
| combo-duplicate-auth | L2×2, L3×1 | L2 |
| combo-hello-area | L2×2, L3×1 | L2 |
| combo-link-netem | L1×1, L2×1, L4×1 | L1 |
| combo-mtu-area | L2×2, L3×1 | L2 |
| combo-mtu-circuit | L2×3, L3×1 | L2 |
| combo-mtu-hello | L2×3 | L2 |

**要点**：复合场景命中层跨两个子故障（如 combo-link-netem 同时命中 L1/L2 与 L4），
证明复合故障可分别识别；combo-auth-hello 与单 hello-timer 命中差异说明叠加故障均被检出。

### 其它验证

- GraphRAG 服务：/health 正常，新索引 loaded（114 实体 / 160 关系 / 8 社区），复合故障问答正确
- LLM 诊断链路：硅基 Qwen 端到端可用（规则 → 知识 → LLM 结论 → 报告）
- 组合日志正确性：combo-auth-area 日志同时含 auth 失败与 area 不匹配事件

## 五、过程修复（本轮发现并解决）

1. **场景名静默失败**：`hello-timer` 应为 `hello-timer-mismatch` 等精确名；CLI 未知场景静默跳过
2. **runner 路径解析**：`generate_isis_scenario` 相对路径导致输出落于
   `isis-simulator/isis-simulator/output/`，已 resolve 修复
3. **GraphRAG 解释器**：微软 GraphRAG 安装于 `graphrag/.venv`，runner 增加 `graphrag_python()`
   优先使用 venv 解释器
4. **Qwen 思考模式**：默认返回 reasoning_content 而 content 为空，客户端已加
   `enable_thinking: false` + 响应 JSON 解析回退
5. **脚本内多步 LLM 调用已回滚**：engine.py 维持单次 LLM 辅助诊断（含复合故障判定），
   LLM 参与体现在 Hermes 流水线各阶段推演而非脚本内多次调用

## 六、剩余事项

- [ ] 前端界面展示复合故障场景（combo-* 报告渲染）
- [ ] 知识发现（knowledge-builder discover）对 combo 场景未知组合的增量学习
- [ ] 迁移到甲方内网 vLLM 时统一替换三层模型配置（`docs/MODEL_CONFIGURATION.md` 3.4 节）