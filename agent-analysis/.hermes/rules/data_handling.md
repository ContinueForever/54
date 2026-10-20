# 数据处理规范

## 数据来源

所有数据由甲方云平台提供，通过以下方式之一接收：
- SSH 推送文件到 `data/incoming/`
- API 接口接收
- 共享目录挂载

## 数据目录结构

```
data/incoming/
├── YYYYMMDD/
│   ├── HHMMSS/
│   │   ├── metadata.json          # 数据采集元信息
│   │   ├── capture.pcap           # 抓包文件
│   │   ├── neighbor_status.json   # 邻居状态
│   │   └── interface_status.json  # 接口状态
```

## 数据只读原则

- 对 `data/incoming/` 下的原始数据**只读**
- 分析结果写入 `output/` 和 `data/traces/`
- 处理后的数据可移动到 `data/processed/`

## 元数据格式

见 `docs/knowledge_table_format.md` 中的 metadata.json 规范。
