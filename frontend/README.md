# frontend — 54所 IS-IS 智能分析平台演示前端

白底浅色调、离线可用的单页演示应用，支持鼠标滚轮翻页。

## 功能

- **仪表盘**：展示 IS-IS 模拟器、知识图谱、分析引擎统计指标
- **最新诊断结果**：展示最新 trace、异常状态、Markdown 诊断报告
- **执行时序图**：加载并展示分析引擎生成的 HTML/Mermaid 序列图
- **知识图谱查询**：按关键词查询 CSV 知识图谱节点
- **知识图谱拓扑**：力导向图可视化节点与关系
- **工作流脚本参考**：一键运行命令

## 技术栈

- 纯 HTML / CSS / JavaScript（无构建工具）
- 轻量 Python HTTP 服务（标准库 `http.server`）
- 离线运行，无第三方依赖

## 启动

```bash
cd /home/hermes/workspace
python3 -m frontend.server --port 8080
```

访问 http://localhost:8080

## API

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 服务健康检查 |
| `/api/latest` | GET | 最新 trace、报告、序列图、知识图谱统计 |
| `/api/graph` | GET | 知识图谱节点与边数据 |
| `/api/reports` | GET | 报告文件列表 |
| `/api/query` | POST | 关键词查询知识图谱 |
| `/api/seq/<name>` | GET | 获取时序图 HTML |

## 数据来源

| 数据 | 来源 |
|------|------|
| 诊断报告 | `agent-analysis/output/reports/*.md` |
| 追踪记录 | `agent-analysis/data/traces/*.json` |
| 时序图 | `agent-analysis/output/sequence_diagrams/*.html` |
| 知识图谱 | `knowledge/tables/nodes.csv` + `edges.csv` |
