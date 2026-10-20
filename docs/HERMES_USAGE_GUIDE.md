# Hermes IS-IS 智能分析平台使用指南

## 一、快速上手（一句话触发完整演示）

对 Hermes 说：

> **"请帮我演示 IS-IS link-down 故障的完整分析流程，启动前端界面。"**

Hermes 会自动调用 `workspace-orchestrator` skill，完成数据生成 → 知识图谱构建 → GraphRAG 索引 → LLM 诊断 → 前端展示的全流程。

---

## 二、Skill 调用方式

### 2.1 workspace-orchestrator（完整工作流）

```
调用格式：执行 workspace-orchestrator skill，场景为 <SCENARIO>，[启动前端]，[跳过知识图谱重建]
```

可用场景名：
| 场景名 | 描述 |
|--------|------|
| `link-down` | 链路断开，邻居丢失 |
| `auth-mismatch` | IS-IS 认证不匹配 |
| `area-mismatch` | Area 区域不一致 |
| `hello-timer-mismatch` | Hello 定时器不一致 |
| `mtu-mismatch` | MTU 不匹配 |
| `circuit-type-mismatch` | 链路类型不一致 |
| `netem-loss-delay` | 网络丢包/延迟 |
| `lsp-suppression` | LSP 抑制 |
| `duplicate-system-id` | 重复 System ID |
| `baseline` | 正常基线场景 |

复合故障场景（两个独立故障叠加，需分别识别）：
| 场景名 | 叠加故障 |
|--------|---------|
| `combo-auth-area` | auth_mismatch + area_mismatch |
| `combo-auth-mtu` | auth_mismatch + mtu_mismatch |
| `combo-auth-circuit` | auth_mismatch + circuit_type_mismatch |
| `combo-auth-hello` | auth_mismatch + hello_timer_mismatch |
| `combo-mtu-area` | mtu_mismatch + area_mismatch |
| `combo-mtu-hello` | mtu_mismatch + hello_timer_mismatch |
| `combo-mtu-circuit` | mtu_mismatch + circuit_type_mismatch |
| `combo-circuit-area` | circuit_type_mismatch + area_mismatch |
| `combo-hello-area` | hello_timer_mismatch + area_mismatch |
| `combo-duplicate-auth` | duplicate_system_id + auth_mismatch |
| `combo-link-netem` | link_down + netem_loss_delay |

**示例提示词：**

```
帮我跑一遍 IS-IS auth-mismatch 场景的完整分析，要求：
1. 重新生成模拟数据
2. 构建知识图谱和 GraphRAG 索引
3. 运行分析引擎生成诊断报告
4. 启动前端演示，端口 8080
```

---

### 2.2 knowledge-builder（仅构建/更新知识图谱）

```
帮我更新知识图谱，把最新的场景数据都纳入进去。
```

或：

```
知识图谱需要增量学习最新的分析结果，请执行 knowledge-builder skill。
```

---

## 三、分步对话模板

### 场景一：初次演示（完整流程，Hermes 分阶段推演）

```
【步骤1 — 生成数据 + Hermes 推演】
python3 skills/workspace-orchestrator/run.py link-down --run-id demo_run --stage generate
# Hermes 输出【推演】：基于文件清单预判异常注入阶段与可能的故障类型

【步骤2 — 准备输入 + Hermes 推演】
python3 skills/workspace-orchestrator/run.py link-down --run-id demo_run --stage prepare
# Hermes 核对 pcap/log 成对完整

【步骤3 — 构建知识图谱 + Hermes 推演】
python3 skills/workspace-orchestrator/run.py link-down --run-id demo_run --stage build_knowledge
# Hermes 阅读 knowledge/tables/nodes.csv，说明新增节点对诊断的帮助

【步骤4 — 构建 GraphRAG 索引】
python3 skills/workspace-orchestrator/run.py link-down --run-id demo_run --stage build_index

【步骤5 — 启动 GraphRAG 服务 + Hermes 推演】
python3 skills/workspace-orchestrator/run.py link-down --run-id demo_run --stage start_rag

【步骤6 — 运行分析 + Hermes 推演（规则匹配 + LLM 诊断）】
export GRAPHRAG_ENABLED=true
python3 -m agent_analysis --input agent-analysis/data/incoming/demo_run
# Hermes 逐条核对命中规则与 LLM 结论的证据链

【步骤7 — 批判性审查（必需）】
python3 skills/workspace-orchestrator/run.py link-down --run-id demo_run --stage critic
# Hermes 启动批判子智能体（isis-critic），按 critic-checklist.md 输出批判意见

【步骤8 — 汇总呈现 + Hermes 推演】
python3 skills/workspace-orchestrator/run.py link-down --run-id demo_run --stage report

【步骤9 — 前端展示（可选）】
python3 skills/workspace-orchestrator/run.py link-down --run-id demo_run --stage frontend
# 浏览器打开 http://localhost:8080
```

> 每个阶段之间，Hermes 必须输出【Hermes 推演 · 阶段名】记录（观察/判断/决策），
> 让甲方看到 LLM 在每个环节的思考过程，而不是只见最终报告。

---

### 场景二：快速复现已有故障（跳过知识图谱重建）

```
用 workspace-orchestrator 分析 mtu-mismatch 场景，
跳过知识图谱重建（使用已有索引），启动前端。

命令：
cd /home/hermes/workspace
python3 skills/workspace-orchestrator/run.py mtu-mismatch --skip-knowledge --frontend
```

---

### 场景三：查询诊断报告

```
我想查看最近 5 次分析的诊断报告摘要，重点关注有异常的运行。
报告目录：/home/hermes/workspace/agent-analysis/output/reports/
```

---

### 场景四：GraphRAG 知识问答

先启动 GraphRAG 服务，再向 Hermes 提问：

```
IS-IS 邻居状态从 UP 变为 DOWN 的常见原因有哪些？
请从知识图谱（GraphRAG）中检索相关规则，结合 RFC 标准给出诊断建议。
```

GraphRAG 服务提供的 API：
```bash
# 查询知识图谱
curl -X POST http://localhost:9200/query \
  -H "Content-Type: application/json" \
  -d '{"query": "adjacency down neighbor loss"}'

# 检查服务状态
curl http://localhost:9200/health
```

---

## 四、一键脚本（推荐日常使用）

```bash
cd /home/hermes/workspace

# 完整工作流（含前端）
python3 scripts/run_pipeline.py link-down

# 仅分析（不启动服务）
python3 scripts/generate_and_analyze.py link-down

# 指定场景 + 跳过知识图谱重建
python3 skills/workspace-orchestrator/run.py auth-mismatch --skip-knowledge --frontend
```

---

## 五、环境变量说明

| 变量 | 说明 | 当前值 |
|------|------|--------|
| `WORKSPACE` | 工作目录根路径 | `/home/hermes/workspace` |
| `LLM_PROVIDER` | 强制指定 LLM 路由（openai/kimi） | `kimi` |
| `KIMI_BASE_URL` | 诊断引擎 Kimi 端点 | `https://api.kimi.com/coding` |
| `KIMI_API_KEY` | 诊断引擎 + GraphRAG chat 模型 key | `sk-kimi-***` |
| `KIMI_MODEL_NAME` | 诊断模型 | `kimi-k3` |
| `GRAPHRAG_ENABLED` | 是否启用 GraphRAG 检索 | `true` |
| `GRAPHRAG_HOST` / `GRAPHRAG_PORT` | GraphRAG 服务地址 | `localhost:9200` |

以上变量统一由 `agent-analysis/.env.project` 管理，引擎启动时自动加载并强制覆盖全局环境变量。

GraphRAG 自身的 chat/embedding 模型配置在 `graphrag/config/settings.yaml`（chat=kimi-k3，
embedding=local_tfidf 本地离线）。三层模型的完整配置教程与甲方自部署迁移步骤见
`docs/MODEL_CONFIGURATION.md`。

---

## 六、前端界面说明

访问 `http://localhost:8080` 后，六屏内容依次为：

| 屏 | 内容 |
|----|------|
| 1 | 平台概览：模拟器/知识图谱/分析引擎/LLM 状态 |
| 2 | 最新诊断结果：异常类型、Trace ID、完整 Markdown 报告 |
| 3 | 执行时序图：引擎运行的 Mermaid 序列图 |
| 4 | 知识图谱查询：关键词搜索节点和关联关系 |
| 5 | **知识图谱拓扑**：力导向图，点击节点查看详情，GraphRAG 状态面板 |
| 6 | 工作流脚本：可复制的命令 + 模块状态表 |
