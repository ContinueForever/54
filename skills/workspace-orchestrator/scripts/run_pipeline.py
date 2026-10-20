#!/usr/bin/env python3
"""兼容旧入口，统一执行项目主流程（含素材批次导入和知识校验）。"""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts/run_pipeline.py"), run_name="__main__")
