"""
知识库适配器 — 将甲方提供的表格形态知识图谱加载为可用知识

当前支持：CSV 表格（nodes.csv + edges.csv）
未来扩展：GraphRAG、OWL 本体
"""

import csv
import json
from pathlib import Path
from typing import Dict, List, Optional, Any


class KnowledgeAdapter:
    """知识库适配器"""

    def __init__(self, tables_dir: Path):
        self.tables_dir = Path(tables_dir)
        self.nodes: Dict[str, Dict] = {}
        self.edges: List[Dict] = []
        self.loaded = False

    def load(self) -> bool:
        """
        加载知识表格

        Returns:
            是否成功加载
        """
        nodes_file = self.tables_dir / "nodes.csv"
        edges_file = self.tables_dir / "edges.csv"

        if not nodes_file.exists():
            return False

        # 加载节点
        self.nodes = {}
        with open(nodes_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                node_id = row.get("node_id", "").strip()
                if node_id:
                    self.nodes[node_id] = dict(row)

        # 加载边
        self.edges = []
        if edges_file.exists():
            with open(edges_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.edges.append(dict(row))

        self.loaded = True
        return True

    def get_node(self, node_id: str) -> Optional[Dict]:
        """获取指定节点"""
        if not self.loaded:
            self.load()
        return self.nodes.get(node_id)

    def find_nodes_by_type(self, node_type: str) -> List[Dict]:
        """按类型查找节点"""
        if not self.loaded:
            self.load()
        return [n for n in self.nodes.values() if n.get("node_type") == node_type]

    def find_related(self, node_id: str, relation: Optional[str] = None) -> List[Dict]:
        """
        查找与指定节点相关的节点

        Args:
            node_id: 节点ID
            relation: 关系类型过滤，None 则返回所有关系

        Returns:
            相关节点列表
        """
        if not self.loaded:
            self.load()

        related = []
        for edge in self.edges:
            if edge.get("source_id") == node_id:
                if relation is None or edge.get("relation") == relation:
                    target_id = edge.get("target_id")
                    if target_id and target_id in self.nodes:
                        related.append({
                            "node": self.nodes[target_id],
                            "relation": edge.get("relation"),
                            "strength": edge.get("strength", "1.0"),
                        })
        return related

    def query_by_name(self, name: str) -> List[Dict]:
        """按名称模糊查询节点"""
        if not self.loaded:
            self.load()

        results = []
        name_lower = name.lower()
        for node_id, node in self.nodes.items():
            node_name = node.get("name", "").lower()
            description = node.get("description", "").lower()
            if name_lower in node_name or name_lower in description:
                results.append(node)
        return results

    def get_stats(self) -> Dict[str, Any]:
        """获取知识库统计信息"""
        if not self.loaded:
            self.load()

        node_types = {}
        for node in self.nodes.values():
            t = node.get("node_type", "unknown")
            node_types[t] = node_types.get(t, 0) + 1

        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "node_types": node_types,
            "loaded": self.loaded,
        }


def main():
    """测试入口"""
    import sys

    if len(sys.argv) < 2:
        print("用法: python knowledge_adapter.py <tables_dir>")
        sys.exit(1)

    adapter = KnowledgeAdapter(Path(sys.argv[1]))
    if adapter.load():
        stats = adapter.get_stats()
        print(f"知识库加载成功:")
        print(f"  节点数: {stats['total_nodes']}")
        print(f"  边数: {stats['total_edges']}")
        print(f"  节点类型: {stats['node_types']}")
    else:
        print("知识库加载失败，检查表格文件是否存在")


if __name__ == "__main__":
    main()
