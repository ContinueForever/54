# 素材导入与知识校验接入说明

## 目录和入口

正式实现位于 `skills/material-to-csv/` 与 `skills/kg-validator/`。根目录同名路径是相对符号链接，旧命令继续可用。两个工具均使用 `WORKSPACE` 环境变量；未指定时根据脚本位置定位项目根目录。

统一入口：`python3 skills/knowledge-builder/run.py`。

| 命令 | 行为 |
|------|------|
| `extract <素材> --source <来源> [--batch <批次名>]` | 生成 knowledge/incoming 下的候选 CSV 与差异报告 |
| `diff <批次目录>` | 显示新增、重复、冲突，不修改正式知识表 |
| `merge <批次目录> [--prefer-new] [--index]` | 备份并合并正式表，自动重建 CSV/JSON、校验、刷新 GraphRAG 输入；可选继续构建索引 |
| `validate [--checks A,B,C,D,E,F] [--graphrag-url <URL>] [--sample N] [--json]` | 独立校验，JSON 模式供程序读取 |
| `build [--no-index]` | 构建本地图谱并校验，生成检索输入，可选构建索引 |
| `build-csv` | 构建本地 CSV/JSON 并校验 |
| `graphrag-index` | 校验本地图谱、刷新输入并构建索引；尝试重启已运行的 isis-graphrag.service |

## 导入流程

```bash
cd /home/hermes/workspace
python3 skills/knowledge-builder/run.py extract /path/to/material.csv --source table:material.csv --batch import_001
python3 skills/knowledge-builder/run.py diff knowledge/incoming/import_001
# 审阅候选后执行合并
python3 skills/knowledge-builder/run.py merge knowledge/incoming/import_001
# 若需要检索生效，更新索引（需配置模型服务）
python3 skills/knowledge-builder/run.py graphrag-index
```

提取支持文本/Markdown、IS-IS 日志、CSV、规则 JSON。规则式提取覆盖不了的文本可按 extraction-guide 手工补写批次内的 manual_nodes.csv、manual_edges.csv、manual_attributes.csv。提取结果需审阅后再合并。

## 主流程集成

完整流程支持合并已审阅的候选批次：

```bash
python3 scripts/run_pipeline.py link-down --knowledge-batch knowledge/incoming/import_001 --skip-frontend
python3 skills/workspace-orchestrator/run.py link-down --knowledge-batch knowledge/incoming/import_001
```

分阶段入口：

```bash
python3 skills/workspace-orchestrator/run.py --stage build_knowledge --knowledge-batch knowledge/incoming/import_001
python3 skills/workspace-orchestrator/run.py --stage validate --graphrag-port 9200
```

`--knowledge-batch` 不能与 `--skip-knowledge` 同时使用；分阶段模式仅允许在 build_knowledge 阶段传入批次。旧的 skills/workspace-orchestrator/scripts/run_pipeline.py 入口委托项目主脚本，避免两套工作流行为不同。

共享工具位于 scripts_lib/runner.py：build_knowledge_graph、run_material_to_csv、validate_knowledge。构建入口 knowledge/scripts/build.py 统一处理已有表格、规则、场景及复合故障关联。

## 校验和故障处置

- 构建前执行 A 类结构检查，并保存 CSV/JSON 快照；构建后执行 A–F 类本地校验。
- GraphRAG 索引构建前执行本地校验，随后刷新输入文本。
- 完整流程和 orchestrator 的 analyze 阶段在诊断前执行校验，包含 GraphRAG 服务检查。
- CRITICAL 返回非零并停止后续步骤；MAJOR/MINOR/INFO 保留供复核，不阻断现有流程。
- 服务不可达时标记 SKIP；`--graphrag-url ""` 显式禁用服务访问。
- Markdown 报告位于 knowledge/learnings/validation/；JSON 模式只输出结果、不保存 Markdown。

规则名称与规则 ID 都用于来源核对；指标症状不被误当成规则节点。指标节点依据原始规则补齐，属性节点依据已有初始知识表补齐，保留已有正式节点和关系。

## 快照和回滚

合并保存 `knowledge/incoming/<批次>/merge_snapshot/`，重复合并保留首次快照。构建保存 `knowledge/learnings/snapshots/<时间戳>/`，包含当时的 CSV 和已有 JSON。

合并后的构建、校验或索引失败会返回非零，但正式表已经合并；错误消息会提示快照位置。恢复时将所需快照的 CSV 拷回 knowledge/tables/，重新构建本地图谱、输入文本和索引。构建快照中的 JSON 可与对应 CSV 一起恢复。

普通 merge 不更新 GraphRAG 索引。`--index` 或 graphrag-index 才会更新索引；无 systemd 管理的常驻实例需要自行重启，以载入新索引。

## 验证结果（2026-10-13）

离线集成检查覆盖候选提取/差异不会修改正式表、合并后 JSON 与 CSV 同步、重复合并不重复入库及快照保留、悬空引用合并拒绝、严重错误阻断索引、初始属性及规则指标补齐、分阶段入口及旧路径兼容。

项目现有知识库重建完成，82 个节点、77 条关系，CRITICAL 为 0。初始表中的 RFC 5305 引用在 knowledge/rfc/ 缺少对应语料，两个节点仍有来源待补充的 MAJOR 提示；保留提示，未自动下载或编造来源。

本次验证未调用模型服务重建 GraphRAG 索引。索引接入通过流程检查及 CRITICAL 拦截检查验证，实际索引构建仍需项目原有模型环境。

```bash
python3 -m unittest discover -s tests -v
```
