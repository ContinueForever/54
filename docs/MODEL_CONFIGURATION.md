# 模型配置教程

> 最后更新：2026-07-30（已实测验证文中全部命令）
>
> 本文档说明平台中**所有 LLM 的配置方法**，包括三层：Hermes Agent 本体、诊断引擎（agent-analysis）、GraphRAG 知识检索服务。
> 当前生产配置为 **kimi-k3**，甲方交付时可整体切换为内网自部署模型（如 vLLM + Qwen），本文给出迁移步骤。

---

## 0. 三层模型架构总览

```
┌─────────────────────────────────────────────────────────────┐
│ 第 1 层：Hermes Agent 本体（对话/编排层）                      │
│   配置：~/.hermes/config.yaml                                │
│   当前：kimi-k3 @ https://api.kimi.com/coding                 │
├─────────────────────────────────────────────────────────────┤
│ 第 2 层：诊断引擎 LLM（agent-analysis，生成诊断结论）           │
│   配置：agent-analysis/.env.project                          │
│   当前：kimi-k3 @ https://api.kimi.com/coding（Anthropic 格式）│
├─────────────────────────────────────────────────────────────┤
│ 第 3 层：GraphRAG 服务（graphrag，知识语义检索）                │
│   配置：graphrag/config/settings.yaml                        │
│   当前：chat=kimi-k3 @ coding/v1（OpenAI 格式）               │
│         embedding=local_tfidf（本地离线，无需 API）            │
└─────────────────────────────────────────────────────────────┘
```

三层配置**相互独立**：换任何一层不影响其他层。诊断引擎即使 LLM 不可用也会自动降级到规则引擎；GraphRAG 不可用时降级到 CSV 关键词检索。

---

## 1. 第 1 层：Hermes Agent 本体

Hermes 有官方 CLI 命令管理模型，无需手工编辑文件（以下命令均已实测验证）：

```bash
# 直接命令设置（key 用点号路径）
hermes config set model.default kimi-k3
hermes config set model.provider kimi-coding
hermes config set model.base_url https://api.kimi.com/coding

# 查看当前生效配置
hermes config get model
# 输出示例：
#   default: kimi-k3
#   provider: kimi-coding
#   base_url: https://api.kimi.com/coding

# 查看/编辑配置文件位置
hermes config path        # /home/hermes/.hermes/config.yaml
hermes config env-path    # /home/hermes/.hermes/.env
hermes config edit        # 在编辑器中打开 config.yaml
```

API key 存放在 `~/.hermes/.env`（如 `KIMI_API_KEY=sk-...`）。
该文件无对应 set 子命令，用编辑器直接修改即可：

```bash
# 找到 .env 路径后编辑，修改 KIMI_API_KEY= 一行
$(hermes config env-path)
```

> 注意：Hermes 的模型配置只影响 Agent 对话本身，**不影响**第 2、3 层的项目内模型。

---

## 2. 第 2 层：诊断引擎 LLM（agent-analysis）

配置文件：`agent-analysis/.env.project`

`llm_client.py` 的 provider 解析优先级：

```
LLM_PROVIDER=openai/openrouter（显式指定）
    → 否则 KIMI_API_KEY 存在 → kimi（Anthropic Messages API）
    → 否则 OPENAI_COMPATIBLE_CHAT_ENDPOINT 存在 → openai
    → 都没有 → 返回 None，引擎降级到规则诊断
```

### 2.1 当前配置（kimi-k3）

```bash
LLM_PROVIDER=kimi
KIMI_BASE_URL=https://api.kimi.com/coding
KIMI_API_KEY=sk-kimi-***        # 实际值见 .env.project
KIMI_MODEL_NAME=kimi-k3
```

- 请求格式：Anthropic Messages API（`POST {KIMI_BASE_URL}/v1/messages`）
- 响应中的 `thinking` 块会被自动过滤，报告只保留最终文本
- 验证方法（前端界面或）：

```bash
curl -s http://localhost:8080/api/llm_info
```

### 2.2 切换到甲方自部署模型（OpenAI-compatible / vLLM）

甲方内网通常用 vLLM 部署 Qwen 等模型，提供 OpenAI 兼容端点。修改 `.env.project`：

```bash
# 1) 删除或注释掉全部 KIMI_* 三行
# 2) 改为：
LLM_PROVIDER=openai
OPENAI_COMPATIBLE_CHAT_ENDPOINT=http://<甲方IP>:<端口>/v1/chat/completions
OPENAI_COMPATIBLE_CHAT_API_KEY=none     # vLLM 默认不校验时可填 none
DEFAULT_MODEL_NAME=Qwen3.5-35B-A3B      # 换成甲方实际模型名
```

切换后重启前端服务即可生效（诊断引擎每次分析时重新读取 `.env.project`，无需其他操作）。

---

## 3. 第 3 层：GraphRAG 服务（重点）

配置文件：`graphrag/config/settings.yaml`

GraphRAG 内部需要**两类模型**，配置时必须成对考虑：

| 模型 | 用途 | 当前配置 |
|------|------|----------|
| `default_chat_model` | 建索引时抽取实体/关系/社区报告；查询时生成语义答案 | kimi-k3（OpenAI 格式） |
| `default_embedding_model` | 文本向量化，供 LocalSearch 检索 | **local_tfidf**（本地 TF-IDF，零 API 依赖） |

### 3.1 当前配置（kimi-k3 + local_tfidf）

```yaml
models:
  default_chat_model:
    type: chat
    model_provider: openai            # GraphRAG/fnllm 只支持 OpenAI 格式
    auth_type: api_key
    api_key: ${KIMI_API_KEY}          # 从环境变量读取，勿把 key 写进文件
    model: kimi-k3
    api_base: https://api.kimi.com/coding/v1   # 注意带 /v1，OpenAI 兼容端点
    model_supports_json: true
    request_timeout: 180
    concurrent_requests: 2
    async_mode: threaded

  default_embedding_model:
    type: local_tfidf                 # 自定义 provider，见下
    model_provider: local_tfidf
    api_key: local
    model: local_tfidf
```

关键说明：

1. **GraphRAG 只接受 OpenAI 格式的 chat API**。kimi 的 coding 端点同时提供
   `/v1/messages`（Anthropic 格式）和 `/v1/chat/completions`（OpenAI 格式），
   GraphRAG 必须用后者，即 `api_base: https://api.kimi.com/coding/v1`。
2. **embedding 选择 local_tfidf 是刻意为之**：kimi coding 端点不提供 embedding API。
   本地 TF-IDF provider 由 `graphrag/src/graphrag_server/local_embedding.py` 实现、
   `__init__.py` 注册，完全离线运行，**换任何 chat 模型都不需要重新向量化**。
3. API key 通过环境变量传入（`${KIMI_API_KEY}`），systemd 单元文件中配置，
   避免明文 key 进入 git。

### 3.2 启动常驻服务（systemd）

服务单元文件：`~/.config/systemd/user/isis-graphrag.service`

```bash
# 启动并设置开机自启
systemctl --user daemon-reload
systemctl --user enable --now isis-graphrag.service

# 查看状态 / 日志
systemctl --user status isis-graphrag.service
journalctl --user -u isis-graphrag.service -f

# 健康检查
curl -s http://localhost:9200/health
# 期望返回: {"status":"ok","graphrag_index_loaded":true,"nodes":N,"edges":M}
```

服务配置 `Restart=always`，崩溃后 5 秒自动拉起。如服务器重启后用户级服务未启动，
执行一次 `loginctl enable-linger hermes` 即可免登录常驻。

### 3.3 重建 / 更新索引

知识文档（`graphrag/input/*.txt`）变更后需要重建索引：

```bash
cd /home/hermes/workspace/graphrag
KIMI_API_KEY=sk-*** PYTHONPATH=src \
  .venv/bin/python -m graphrag_server.indexer --verbose
```

- 产物：`output/*.parquet`（entities/relationships/community_reports 等，graphrag 2.7.2 **无** `create_final_` 前缀）+ `output/lancedb/` + `output/tfidf_vectorizer.pkl`
- 重建完成后**重启 GraphRAG 服务**以加载新索引：
  `systemctl --user restart isis-graphrag.service`
- 索引过程会多次调用 chat 模型，耗时与文档量成正比（当前 12KB 语料约 5-10 分钟）
- 配置校验：`... indexer --dry-run`（结尾的 TypeError 是 GraphRAG 2.7.2 已知日志 bug，可忽略）

### 3.4 切换到甲方自部署模型

甲方交付时，GraphRAG 的 chat 模型改为内网 vLLM：

```yaml
models:
  default_chat_model:
    type: chat
    model_provider: openai
    auth_type: api_key
    api_key: ${VLLM_API_KEY}              # 或写 none（vLLM 默认不校验）
    model: Qwen3.5-35B-A3B                # 甲方实际模型名
    api_base: http://<甲方IP>:<端口>/v1    # OpenAI 兼容端点
    model_supports_json: true
    request_timeout: 180
    concurrent_requests: 2
    async_mode: threaded
  # default_embedding_model 保持 local_tfidf 不变 —— 离线可用，无需甲方提供 embedding 服务
```

步骤：

1. 修改 `graphrag/config/settings.yaml` 的 `default_chat_model` 三项（api_key/model/api_base）
2. 修改 systemd 单元的环境变量：`systemctl --user edit isis-graphrag.service` 添加
   `[Service]\nEnvironment=VLLM_API_KEY=...`
3. 重建索引（见 3.3）—— **chat 模型变更后必须重建**，实体抽取结果随模型变化
4. `systemctl --user restart isis-graphrag.service`
5. `curl -s http://localhost:9200/health` 确认 `graphrag_index_loaded: true`

若甲方同时提供 embedding 服务（如 bge-m3），也可将 `default_embedding_model`
改为 openai provider 指向甲方端点，替换后同样需要重建索引。

### 3.5 常见坑

| 现象 | 原因 | 解决 |
|------|------|------|
| `No InputFileType.text files found` | `file_pattern` 正则转义错误 | settings.yaml 中应为 `".*\\.txt$$"`（两个反斜杠） |
| health 返回 `graphrag_index_loaded: false` | 索引未构建或 parquet 命名是旧版格式 | 用 2.7.2 重建索引，产物为 `output/*.parquet`（无 `create_final_` 前缀）+ `output/lancedb/` |
| 查询报 401/403 | `api_key` 环境变量未传入服务进程 | 检查 systemd 单元的 `Environment=` 行 |
| 查询超时 | kimi-k3 是 thinking 模型，首 token 较慢 | `request_timeout` 保持 ≥180s，并发保持 1-2 |
| 诊断报告里 GraphRAG 显示 CSV fallback | 9200 服务未启动 | `systemctl --user start isis-graphrag.service` |
| 查询报 `query dim(256) doesn't match ... dim(2331)` | 查询进程 TF-IDF vectorizer 未拟合，与索引时词汇表不一致 | `local_embedding.py` 已将拟合好的 vectorizer 持久化到 `output/tfidf_vectorizer.pkl`，查询时自动加载；若仍出现则删除该 pkl 并重建索引 |

---

## 4. 三层模型一致性检查清单

交付或迁移后，逐项确认：

- [ ] `hermes config get model` → kimi-k3 / 甲方模型
- [ ] `curl -s localhost:8080/api/llm_info` → 诊断引擎模型正确
- [ ] `curl -s localhost:9200/health` → `graphrag_index_loaded: true`
- [ ] 跑一次完整分析，报告中 "LLM 诊断结论" 段落非空、GraphRAG 章节非 CSV fallback：
  `python3 scripts/generate_and_analyze.py link-down`

---

## 5. 附：当前环境变量一览

| 变量 | 用途 | 存放位置 |
|------|------|----------|
| `KIMI_API_KEY` | 诊断引擎 + GraphRAG chat | `~/.hermes/.env`、`.env.project`、systemd 单元 |
| `KIMI_BASE_URL` | 诊断引擎 Anthropic 端点 | `.env.project` |
| `KIMI_MODEL_NAME` | 诊断引擎模型名 | `.env.project` |
| `OPENAI_COMPATIBLE_CHAT_ENDPOINT` | 甲方 vLLM 端点（备用） | `.env.project` |
| `DEFAULT_MODEL_NAME` | 甲方 vLLM 模型名（备用） | `.env.project` |
| `GRAPHRAG_HOST/PORT` | GraphRAG 服务地址 | `.env.project` |
