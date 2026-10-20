# 标准分析流程

## 触发条件

- 收到新的分析数据
- 用户主动请求分析
- 定时任务触发（如配置）

## 执行步骤

1. **数据确认**
   - 检查 `data/incoming/` 是否有新数据
   - 验证数据完整性（metadata.json、pcap、状态文件）

2. **配置加载**
   - 读取 `config/analysis_pipeline/default_pipeline.json`
   - 读取各层规则文件 `config/diagnosis_rules/*.json`
   - 读取阈值 `config/thresholds/default_thresholds.json`

3. **分层检查**
   - 按流水线配置顺序执行启用的步骤
   - 每层调用对应规则文件进行匹配
   - 记录每个步骤的结果到追踪器

4. **异常处理**
   - 规则命中：直接输出诊断结论
   - 规则未覆盖：调用本地 vLLM 辅助诊断

5. **报告生成**
   - 生成 Markdown 诊断报告
   - 生成 Mermaid 时序流程图 HTML
   - 保存到 `output/` 目录

## 质量检查

每次分析完成后必须验证：
- [ ] 追踪记录 JSON 有效
- [ ] 时序流程图已生成
- [ ] 诊断报告已生成
- [ ] 磁盘使用率 < 95%
- [ ] 无异常报错
