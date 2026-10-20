# IS-IS 诊断任务工作台

入口：直接打开 `dist/index.html`，或启动项目 `frontend/server.py` 后访问 `/workbench`。
页面呈现一条分析完成的任务；复盘只控制记录的展开节奏，不伪装实时执行。

任务从“R01–R02 邻接中断、业务探测无应答”开始。输入文件名和报障记录不包含根因。
抓包、日志、状态快照通过项目 `isis_simulator` 的 `adjacency-incident` 场景生成，
进入 `isis-simulator/output/incident_20261014_017/`，再由共享准备入口复制至
`agent-analysis/data/incoming/incident_20261014_017/`。
诊断使用项目 `AnalysisEngine`，报告、追踪和结果进入项目正常输出目录。
工作台的计数、命中规则、知识查询、执行时间和原始文件均从这一次运行读取。

## 查看与讲解

1. 在“任务复盘”中点击“从报障复盘”：先看到原始邻接中断和探测无应答。
   左侧选择环节，中间只显示当前环节；也可使用底部“上一步 / 下一步”或进度条切换。
   工作区高度随窗口固定，长内容在区域内部滚动，不会随复盘推进向下追加卡片。
   窄屏下执行链横向滚动，“执行详情”按钮打开本环节的输入、输出和产物。
2. 点击“输入接收”查看三份原始输入及 SHA-256。
3. 在“特征提取”查看正常/异常窗口：R02 的 Hello 类型变化，探测应答消失。
4. 在“知识查询”和各层检查中查看查询节点、规则材料、具体命中与证据。
5. 在“模型诊断”查看输入证据、候选原因比较和处置建议，并核对模型记录来源。
6. 在“诊断报告”打开项目实际生成的报告与独立审查。
7. “Skills 与执行”显示真实知识维护命令、诊断阶段与对应技能定义。

## 数据与模型来源

网络输入是受控合成场景，并非甲方现场数据；未操作任何真实设备。
输入只含正常与异常窗口，没有修复后的恢复样例。
知识维护在演示副本中执行，诊断随后实际加载这个副本；正式知识表保持不变。
采用 CSV 知识查询，没有宣称本次进行了 GraphRAG 索引重建或长期学习。

当前如果标注“模型解读示例”，表示该解读按项目提示和证据编写，未调用配置的模型接口。
替换为可用模型后运行：

```bash
python3 demo/client-diagnosis/run_case.py --with-model
python3 demo/client-diagnosis/build_workbench.py
```

真实模型调用会保存完整提示、返回、模型名、请求时间与耗时；不保存 API 密钥。
只有真实成功调用才会显示“模型真实返回”。调用失败会显示失败原因。
离线讲解阶段不再发起模型请求，避免网络和额度影响现场展示。

## 重建与验证

```bash
python3 demo/client-diagnosis/prepare_case.py
python3 demo/client-diagnosis/run_case.py --illustrative-model
python3 demo/client-diagnosis/build_workbench.py
python3 demo/client-diagnosis/verify_workbench.py
```

场景模块可独立使用：`PYTHONPATH=isis-simulator/src python3 -m isis_simulator adjacency-incident --output <目录>`。
独立审查由执行代理按 workspace-orchestrator 的要求调用 isis-critic 子代理完成；
这份审查与配置模型的诊断输出分别标明来源。
