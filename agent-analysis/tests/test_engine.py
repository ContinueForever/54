"""
分析引擎测试
"""

import json
import tempfile
from pathlib import Path

import pytest

from analysis.engine import AnalysisEngine
from analysis.knowledge_adapter import KnowledgeAdapter
from analysis.rule_engine import RuleEngine
from analysis.tracer import Tracer


class TestAnalysisEngine:
    """测试主分析引擎"""

    def test_engine_initialization(self):
        """测试引擎初始化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AnalysisEngine()
            assert engine.pipeline_config is not None
            assert engine.thresholds is not None

    def test_load_json(self):
        """测试 JSON 加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.json"
            test_data = {"key": "value"}
            with open(test_file, "w") as f:
                json.dump(test_data, f)

            engine = AnalysisEngine()
            result = engine._load_json(test_file)
            assert result == test_data


class TestKnowledgeAdapter:
    """测试知识适配器"""

    def test_load_empty(self):
        """测试空目录加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = KnowledgeAdapter(Path(tmpdir))
            assert adapter.load() is False

    def test_load_nodes(self):
        """测试节点加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            nodes_file = Path(tmpdir) / "nodes.csv"
            with open(nodes_file, "w") as f:
                f.write("node_id,node_type,name,description,layer\n")
                f.write("N001,anomaly,test,测试节点,L3\n")

            adapter = KnowledgeAdapter(Path(tmpdir))
            assert adapter.load() is True
            assert len(adapter.nodes) == 1
            assert adapter.get_node("N001")["name"] == "test"


class TestRuleEngine:
    """测试规则引擎"""

    def test_load_rules(self):
        """测试规则加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_file = Path(tmpdir) / "test_rules.json"
            rules_data = {
                "layer": "L3",
                "rules": [
                    {
                        "id": "L3-R001",
                        "name": "test_rule",
                        "indicators": ["test"],
                        "severity": "critical",
                    }
                ],
            }
            with open(rules_file, "w") as f:
                json.dump(rules_data, f)

            engine = RuleEngine(tmpdir)
            rules = engine.load_rules("test_rules.json")
            assert len(rules) == 1
            assert rules[0]["id"] == "L3-R001"


class TestTracer:
    """测试追踪器"""

    def test_trace_lifecycle(self):
        """测试追踪生命周期"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracer = Tracer(Path(tmpdir))
            tracer.start("test_trace")
            tracer.record_step("L1", "测试步骤", "PASS", "正常")
            tracer.finish()

            trace_file = Path(tmpdir) / "test_trace.json"
            assert trace_file.exists()

            with open(trace_file) as f:
                data = json.load(f)
            assert data["trace_id"] == "test_trace"
            assert len(data["steps"]) == 1

    def test_generate_mermaid(self):
        """测试 Mermaid 生成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracer = Tracer(Path(tmpdir))
            tracer.start("test_trace")
            tracer.record_step("L1", "物理层检查", "PASS", "正常")
            tracer.record_step("L3", "路由检查", "FAIL", "异常", "L3-R001")
            tracer.finish()

            html = tracer.generate_mermaid_html()
            assert "sequenceDiagram" in html
            assert "L1物理层" in html
            assert "L3-IS-IS路由层" in html
