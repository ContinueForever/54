"""
规则引擎 — 加载和执行 JSON 诊断规则

规则文件格式：
{
  "layer": "L3",
  "rules": [
    {
      "id": "L3-R001",
      "name": "lsp_seq_num_wrap",
      "indicators": [...],
      "severity": "critical",
      "suggestion": "...",
      "references": [...]
    }
  ]
}
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any


class RuleEngine:
    """诊断规则引擎"""

    def __init__(self, rules_dir: Path):
        self.rules_dir = Path(rules_dir)
        self._cache: Dict[str, Dict] = {}

    def load_rules(self, rules_file: Optional[str] = None) -> List[Dict]:
        """
        加载规则文件

        Args:
            rules_file: 规则文件路径，None 则加载所有规则

        Returns:
            规则列表
        """
        if rules_file is None:
            # 加载所有规则文件
            all_rules = []
            for f in self.rules_dir.glob("*.json"):
                rules = self._load_single_file(f)
                all_rules.extend(rules.get("rules", []))
            return all_rules

        # 加载指定文件
        path = Path(rules_file)
        if not path.is_absolute():
            path = self.rules_dir / path

        rules = self._load_single_file(path)
        return rules.get("rules", [])

    def _load_single_file(self, path: Path) -> Dict:
        """加载单个规则文件（带缓存）"""
        file_key = str(path.resolve())

        if file_key in self._cache:
            return self._cache[file_key]

        if not path.exists():
            return {"rules": []}

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._cache[file_key] = data
        return data

    def match(self, data: Dict, rules: List[Dict]) -> List[Dict]:
        """
        将数据与规则进行匹配

        Args:
            data: 待检查的数据特征
            rules: 规则列表

        Returns:
            匹配的规则列表
        """
        matched = []
        for rule in rules:
            if self._check_rule(data, rule):
                matched.append(rule)
        return matched

    def _check_rule(self, data: Dict, rule: Dict) -> bool:
        """
        检查单条规则是否匹配

        TODO: 实现实际的特征匹配逻辑
        当前为占位实现
        """
        indicators = rule.get("indicators", [])
        if not indicators:
            return False

        # 简化匹配：检查数据中是否包含指标关键词
        data_str = json.dumps(data, ensure_ascii=False).lower()
        for indicator in indicators:
            if indicator.lower() in data_str:
                return True

        return False

    def get_rule_by_id(self, rule_id: str) -> Optional[Dict]:
        """按ID查找规则"""
        all_rules = self.load_rules()
        for rule in all_rules:
            if rule.get("id") == rule_id:
                return rule
        return None

    def get_rules_by_layer(self, layer: str) -> List[Dict]:
        """按层级查找规则"""
        all_rules = self.load_rules()
        return [r for r in all_rules if r.get("layer") == layer]

    def get_rules_by_severity(self, severity: str) -> List[Dict]:
        """按严重级别查找规则"""
        all_rules = self.load_rules()
        return [r for r in all_rules if r.get("severity") == severity]

    def reload(self):
        """清除缓存，重新加载规则"""
        self._cache.clear()


def main():
    """测试入口"""
    import sys

    if len(sys.argv) < 2:
        print("用法: python rule_engine.py <rules_dir>")
        sys.exit(1)

    engine = RuleEngine(Path(sys.argv[1]))
    rules = engine.load_rules()

    print(f"已加载 {len(rules)} 条规则:")
    for rule in rules[:5]:  # 只显示前5条
        print(f"  [{rule.get('id')}] {rule.get('name')} ({rule.get('severity')})")

    if len(rules) > 5:
        print(f"  ... 还有 {len(rules) - 5} 条")


if __name__ == "__main__":
    main()
