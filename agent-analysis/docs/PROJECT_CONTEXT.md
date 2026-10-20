# 项目速查手册

## 项目信息

| 项目 | 内容 |
|------|------|
| 名称 | 54所卫星网络IS-IS智能分析系统 |
| 代号 | agent-analysis |
| 环境 | CentOS Stream 10, 完全离线 |
| 模型 | Qwen3.5-35B-A3B @ 192.168.1.80:9998 |
| 工作范围 | 接收甲方数据 → 分层分析 → 输出诊断报告和时序流程图 |

## 快速命令

```bash
# 环境预检
make check

# 执行分析
make diagnose

# 生成报告
make report

# 清理临时数据
make clean

# 重新加载skills
make skill-reload
```

## 关键路径

| 内容 | 路径 |
|------|------|
| 诊断规则 | `config/diagnosis_rules/*.json` |
| 分析流水线 | `config/analysis_pipeline/default_pipeline.json` |
| 阈值参数 | `config/thresholds/default_thresholds.json` |
| 知识表格 | `config/knowledge_tables/*.csv` |
| 输入数据 | `data/incoming/` |
| 追踪记录 | `data/traces/*.json` |
| 诊断报告 | `output/reports/*.md` |
| 时序流程图 | `output/sequence_diagrams/*.html` |
| Skills | `.hermes/skills/` |
| 项目指令 | `AGENTS.md` |

## 联系方式

- 开发团队：[待补充]
- 甲方对接人：[待补充]
