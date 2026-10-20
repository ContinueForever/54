.PHONY: setup check diagnose report clean test skill-reload

# 默认项目目录
PROJECT_ROOT ?= /opt/agent-analysis
PYTHON ?= python3

setup:
	@echo "初始化项目环境..."
	@mkdir -p data/{incoming,processed,traces}
	@mkdir -p output/{reports,sequence_diagrams,exports}
	@echo "目录结构已创建"

check:
	@echo "运行环境预检..."
	@echo "检查 vLLM 连通性..."
	@curl -s -o /dev/null -w "%{http_code}" $(shell grep OPENAI_COMPATIBLE_CHAT_ENDPOINT .env.project | cut -d= -f2)/models || echo "vLLM 不可达"
	@echo "检查磁盘空间..."
	@df -h . | tail -1

diagnose:
	@echo "执行 IS-IS 故障分析..."
	$(PYTHON) analysis/engine.py --input data/incoming/

report:
	@echo "生成诊断报告..."
	$(PYTHON) -c "from analysis.tracer import generate_reports; generate_reports()"

clean:
	@echo "清理临时数据..."
	rm -rf data/traces/*
	rm -rf output/reports/*
	rm -rf output/sequence_diagrams/*
	@echo "已清理（保留 incoming 和 processed）"

test:
	@echo "运行测试..."
	$(PYTHON) -m pytest tests/ -v

skill-reload:
	@echo "重新加载 Hermes skills..."
	@hermes --workdir $(PROJECT_ROOT) -q "/reload-skills"

help:
	@echo "可用命令:"
	@echo "  make setup        - 初始化项目目录"
	@echo "  make check        - 环境预检"
	@echo "  make diagnose     - 执行故障分析"
	@echo "  make report       - 生成报告"
	@echo "  make clean        - 清理临时数据"
	@echo "  make test         - 运行测试"
	@echo "  make skill-reload - 重新加载 skills"
