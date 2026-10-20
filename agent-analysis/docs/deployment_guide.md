# 部署指南

## 环境要求

- CentOS Stream 10 / RHEL 8+ / Ubuntu 20.04+
- Python 3.9+
- 内网 vLLM 服务可达（`192.168.1.80:9998`）

## 安装步骤

### 1. 解压项目

```bash
cd /opt
tar xzf agent-analysis.tar.gz
cd agent-analysis
```

### 2. 配置环境变量

```bash
cp .env.project.example .env.project
# 编辑 .env.project，确认 vLLM 端点地址
```

### 3. 安装依赖（离线环境）

```bash
pip install -r requirements.txt --no-index --find-links ./wheels/
```

### 4. 运行预检

```bash
make check
```

### 5. 启动 Hermes

```bash
hermes --workdir /opt/agent-analysis
```

## 验证安装

```bash
# 测试分析引擎
python3 analysis/engine.py --check

# 测试追踪器
python3 analysis/tracer.py data/traces

# 测试规则引擎
python3 analysis/rule_engine.py config/diagnosis_rules

# 测试知识适配器
python3 analysis/knowledge_adapter.py config/knowledge_tables
```
