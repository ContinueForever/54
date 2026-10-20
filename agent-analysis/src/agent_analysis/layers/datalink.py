"""
L2 链路层分析器

检查内容：
- IS-IS 邻居发现
- Hello 报文
- 链路参数一致性（Hello interval、Holding timer、认证）
"""

from typing import Dict, List, Any


def analyze(data: Dict) -> Dict[str, Any]:
    """
    执行链路层检查

    Args:
        data: 输入数据（包含邻居状态、Hello报文信息）

    Returns:
        检查结果
    """
    results = {
        "layer": "L2",
        "status": "PASS",
        "checks": [],
        "anomalies": [],
    }

    # TODO: 实现实际的链路层特征提取和检查
    # 这里使用模拟逻辑

    neighbor_status = data.get("neighbor_status", {})

    for neighbor, status in neighbor_status.items():
        check = {
            "neighbor": neighbor,
            "state": status.get("state", "unknown"),
        }

        if status.get("state") != "Up":
            check["result"] = "FAIL"
            check["detail"] = f"邻居状态为 {status.get('state')}"
            results["anomalies"].append(check)
            results["status"] = "FAIL"
        else:
            check["result"] = "PASS"
            check["detail"] = "邻居状态正常"

        results["checks"].append(check)

    return results
