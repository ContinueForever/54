"""解析设备日志并提取关键事件。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List


class LogParser:
    """解析 syslog / IS-IS 日志。"""

    PATTERNS = {
        "adjacency_up": re.compile(r"Adjacency to (\S+) .* is UP", re.I),
        "adjacency_down": re.compile(r"Adjacency to (\S+) .* (?:is Down|going Down)", re.I),
        "auth_fail": re.compile(r"Authentication failed", re.I),
        "area_mismatch": re.compile(r"area mismatch", re.I),
        "circuit_type_mismatch": re.compile(r"Circuit type mismatch", re.I),
        "holding_timer_mismatch": re.compile(r"Holding timer mismatch", re.I),
        "mtu_mismatch": re.compile(r"MTU mismatch", re.I),
        "duplicate_system_id": re.compile(r"Duplicate System-ID", re.I),
        "link_down": re.compile(r"Interface (\S+) is Down", re.I),
        "packet_loss": re.compile(r"Ping to (\S+):?\s+(\d+)% packet loss", re.I),
    }

    def parse(self, log_path: str | Path) -> List[Dict[str, Any]]:
        events = []
        for line in Path(log_path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            for event_type, pat in self.PATTERNS.items():
                match = pat.search(line)
                if match:
                    # A successful probe is a baseline event, not packet loss.
                    parsed_type = "probe_healthy" if event_type == "packet_loss" and int(match.group(2)) == 0 else event_type
                    events.append({
                        "type": parsed_type,
                        "raw": line,
                    })
                    break
        return events

    def extract_features(self, log_path: str | Path) -> Dict[str, Any]:
        events = self.parse(log_path)
        return {
            "log_path": str(log_path),
            "event_count": len(events),
            "event_types": sorted(list({e["type"] for e in events})),
            "events": events,
            "raw_lines": Path(log_path).read_text(encoding="utf-8").splitlines(),
        }


def main():
    import sys, json
    path = sys.argv[1] if len(sys.argv) > 1 else "../isis-simulator/logs/auth_mismatch.log"
    print(json.dumps(LogParser().extract_features(path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
