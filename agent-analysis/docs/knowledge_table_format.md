# 知识表格格式规范

## 概述

甲方使用大模型将内部文档总结为知识图谱，产物为表格形态（CSV）。本系统通过 `knowledge_adapter.py` 加载这些表格，供诊断引擎查询使用。

## 表格文件

### nodes.csv — 节点定义表

| 字段 | 说明 | 示例 |
|------|------|------|
| node_id | 节点唯一标识 | N001 |
| node_type | 节点类型（anomaly/symptom/cause/fix） | anomaly |
| name | 节点名称（英文，用于程序识别） | lsp_seq_wrap |
| description | 节点描述（中文，用于展示） | LSP序列号异常环绕 |
| layer | 所属网络层级（L1/L2/L3/L4） | L3 |

**示例：**
```csv
node_id,node_type,name,description,layer
N001,anomaly,lsp_seq_wrap,LSP序列号异常环绕,L3
N002,symptom,neighbor_flap,邻居关系频繁震荡,L2
N003,cause,config_error,配置错误,L3
N004,fix,reset_isis,重置IS-IS进程,L3
```

### edges.csv — 边关系表

| 字段 | 说明 | 示例 |
|------|------|------|
| source_id | 源节点ID | N001 |
| target_id | 目标节点ID | N002 |
| relation | 关系类型（causes/indicates/requires/fixes） | causes |
| strength | 关系强度（0.0-1.0） | 0.8 |

**示例：**
```csv
source_id,target_id,relation,strength
N001,N002,causes,0.8
N002,N003,indicates,0.9
N003,N004,requires,1.0
```

### node_attributes.csv — 节点属性表（可选）

| 字段 | 说明 |
|------|------|
| node_id | 节点ID |
| attribute_key | 属性名 |
| attribute_value | 属性值 |

## 元数据格式（metadata.json）

每次数据采集时附带的元信息：

```json
{
  "source": "甲方云平台",
  "collection_time": "2025-06-02T14:30:52Z",
  "network_state": "fault_injected",
  "fault_scenario": "link-down",
  "affected_nodes": ["s1"],
  "affected_links": ["s1-s2"],
  "data_files": [
    {"type": "pcap", "path": "capture.pcap", "size_bytes": 1048576},
    {"type": "json", "path": "neighbor_status.json", "size_bytes": 4096}
  ]
}
```
