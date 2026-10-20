"""离线验证素材导入、图谱构建和 CRITICAL 门禁的真实命令衔接。"""
import csv
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "skills/knowledge-builder/run.py"
NODE_COLS = ["node_id", "node_type", "name", "description", "source"]
EDGE_COLS = ["source_id", "relation", "target_id", "description"]
ATTR_COLS = ["node_id", "attribute", "value"]


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


class KnowledgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.env = {**os.environ, "WORKSPACE": str(self.workspace), "GRAPHRAG_URL": ""}
        tables = self.workspace / "knowledge/tables"
        write_csv(tables / "nodes.csv", NODE_COLS, [
            {"node_id": "adjacency_down", "node_type": "state", "name": "Adjacency Down",
             "description": "Neighbor down", "source": "observational"}])
        write_csv(tables / "edges.csv", EDGE_COLS, [])
        write_csv(tables / "node_attributes.csv", ATTR_COLS, [])
        (self.workspace / "knowledge/knowledge_graph.json").write_text(json.dumps({
            "nodes": self.read_csv("nodes.csv"), "edges": []}))

    def invoke(self, *arguments, script=BUILDER, expected=0):
        result = subprocess.run([sys.executable, str(script), *arguments],
                                cwd=self.workspace, env=self.env, text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def read_csv(self, name):
        with (self.workspace / "knowledge/tables" / name).open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    def table_bytes(self):
        return {p.name: p.read_bytes() for p in (self.workspace / "knowledge/tables").glob("*.csv")}

    def test_extract_diff_merge_rebuild_and_idempotent_snapshot(self):
        material = self.workspace / "material.csv"
        write_csv(material, ["id", "名称", "描述"], [
            {"id": "new_fault", "名称": "New fault", "描述": "Imported test fault"}])
        original = self.table_bytes()
        self.invoke("extract", str(material), "--source", "table:material.csv", "--batch", "batch1")
        batch = self.workspace / "knowledge/incoming/batch1"
        self.assertTrue((batch / "candidate_nodes.csv").exists())
        self.invoke("diff", str(batch))
        self.assertEqual(original, self.table_bytes())
        self.invoke("merge", str(batch))
        graph = json.loads((self.workspace / "knowledge/knowledge_graph.json").read_text())
        self.assertIn("new_fault", {node["node_id"] for node in graph["nodes"]})
        self.assertEqual(graph["edges"], self.read_csv("edges.csv"))
        self.assertTrue((self.workspace / "graphrag/input/knowledge_graph.txt").exists())
        snapshots = {p.name: p.read_bytes() for p in (batch / "merge_snapshot").glob("*.csv")}
        self.assertEqual(snapshots, original)
        self.invoke("merge", str(batch))
        self.assertEqual(snapshots, {p.name: p.read_bytes() for p in (batch / "merge_snapshot").glob("*.csv")})
        self.assertEqual(1, sum(n["node_id"] == "new_fault" for n in self.read_csv("nodes.csv")))
        result = self.invoke("validate", "--json", "--graphrag-url", "")
        self.assertFalse(any(item["level"] == "CRITICAL" for item in json.loads(result.stdout)))

    def test_dangling_candidate_rejected_without_writing_tables(self):
        batch = self.workspace / "knowledge/incoming/bad"
        write_csv(batch / "candidate_edges.csv", EDGE_COLS, [{
            "source_id": "adjacency_down", "relation": "indicates", "target_id": "missing",
            "description": "Invalid reference"}])
        before = self.table_bytes()
        self.invoke("merge", str(batch), expected=1)
        self.assertEqual(before, self.table_bytes())
        self.assertFalse((batch / "merge_snapshot").exists())

    def test_index_stops_on_critical_before_loading_indexer(self):
        write_csv(self.workspace / "knowledge/tables/edges.csv", EDGE_COLS, [{
            "source_id": "missing", "relation": "causes", "target_id": "adjacency_down",
            "description": "Broken existing graph"}])
        result = self.invoke("graphrag-index", expected=1)
        self.assertIn("CRITICAL", result.stdout)
        self.assertNotIn("graphrag_server.indexer", result.stdout)
        self.assertTrue(list((self.workspace / "knowledge/learnings/validation").glob("*.md")))

    def test_builder_fills_only_sourced_rule_and_attribute_references(self):
        rules = self.workspace / "agent-analysis/config/diagnosis_rules/example.json"
        rules.parent.mkdir(parents=True)
        rules.write_text(json.dumps({"rules": [{"id": "L1-R001", "name": "interface_down",
            "description": "Interface down", "indicators": ["Link Down"]}]}))
        seed = self.workspace / "agent-analysis/config/knowledge_tables/nodes.csv"
        write_csv(seed, NODE_COLS, [{"node_id": "TLV_AUTH", "node_type": "protocol_tlv",
             "name": "Auth TLV", "description": "Authentication", "source": "observational"}])
        write_csv(self.workspace / "knowledge/tables/node_attributes.csv", ATTR_COLS,
                  [{"node_id": "TLV_AUTH", "attribute": "code", "value": "10"}])
        self.invoke("build", "--no-index")
        nodes = {n["node_id"]: n for n in self.read_csv("nodes.csv")}
        self.assertEqual(nodes["TLV_AUTH"]["node_type"], "tlv")
        self.assertEqual(nodes["link_down"]["node_type"], "symptom")
        self.assertEqual(nodes["link_down"]["source"], "rule:example.json")
        result = self.invoke("validate", "--json", "--graphrag-url", "")
        self.assertFalse(any(item["level"] in ("CRITICAL", "MAJOR") for item in json.loads(result.stdout)))

    def test_stage_dispatch_runs_validation(self):
        result = self.invoke("--stage", "validate", script=ROOT / "skills/workspace-orchestrator/run.py")
        self.assertIn("[STAGE:validate]", result.stdout)

    def test_stage_imports_reviewed_batch(self):
        batch = self.workspace / "knowledge/incoming/reviewed"
        write_csv(batch / "candidate_nodes.csv", NODE_COLS, [{
            "node_id": "imported_fault", "node_type": "fault", "name": "Imported fault",
            "description": "Reviewed material", "source": "observational"}])
        self.invoke("--stage", "build_knowledge", "--knowledge-batch", str(batch),
                    script=ROOT / "skills/workspace-orchestrator/run.py")
        self.assertIn("imported_fault", {n["node_id"] for n in self.read_csv("nodes.csv")})

    def test_learning_candidate_also_syncs_json_before_marking_applied(self):
        candidate = self.workspace / "knowledge/learnings/candidates/example.json"
        candidate.parent.mkdir(parents=True)
        candidate.write_text(json.dumps({"candidates": [{"node_id": "learned_fault",
            "name": "Learned fault", "description": "Reviewed candidate"}]}))
        self.invoke("apply-candidates", "--candidate", "example", "--no-index")
        graph = json.loads((self.workspace / "knowledge/knowledge_graph.json").read_text())
        self.assertIn("learned_fault", {n["node_id"] for n in graph["nodes"]})
        self.assertTrue(candidate.with_suffix(".applied").exists())

    def test_pipeline_stops_before_analysis_and_cleans_service_on_critical(self):
        spec = importlib.util.spec_from_file_location("pipeline_test", ROOT / "scripts/run_pipeline.py")
        pipeline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pipeline)
        process = Mock()
        with patch.object(sys, "argv", ["run_pipeline.py", "--skip-knowledge", "--skip-frontend"]), \
             patch.object(pipeline, "generate_isis_scenario"), \
             patch.object(pipeline, "prepare_analysis_input"), \
             patch.object(pipeline, "start_graphrag_server", return_value=process), \
             patch.object(pipeline, "validate_knowledge", side_effect=subprocess.CalledProcessError(1, "validator")), \
             patch.object(pipeline, "run_analysis") as analyze:
            with self.assertRaises(SystemExit) as stopped:
                pipeline.main()
            self.assertEqual(stopped.exception.code, 1)
            analyze.assert_not_called()
            process.terminate.assert_called_once()

    def test_legacy_paths_remain_usable_and_batch_cannot_escape(self):
        self.invoke("--help", script=ROOT / "material-to-csv/run.py")
        self.invoke("--json", "--graphrag-url", "", script=ROOT / "kg-validator/run.py")
        material = self.workspace / "material.csv"
        write_csv(material, ["id", "名称"], [{"id": "x", "名称": "X"}])
        self.invoke("extract", str(material), "--source", "table:material.csv", "--batch", "../outside", expected=1)
        self.assertFalse((self.workspace / "knowledge/outside").exists())


if __name__ == "__main__":
    unittest.main()
