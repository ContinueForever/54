#!/usr/bin/env python3
"""54所 IS-IS 智能分析平台无头工作流脚本。

用途：
- 无头环境（CI、定时任务、演示）下一键跑完完整流程
- 会重新构建知识图谱和 GraphRAG 索引，然后启动服务、运行分析、启动前端

注意：本脚本是"完成一切"的黑盒脚本，适合定时演示。
开发人员的日常交互诊断，请使用 workspace-orchestrator skill。
知识图谱的持续构建/更新，请使用 knowledge-builder skill。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ.get("WORKSPACE", SOURCE_ROOT)).resolve()
SCRIPTS_LIB = SOURCE_ROOT / "scripts_lib"
sys.path.insert(0, str(SCRIPTS_LIB))

from runner import (
    build_graphrag_index,
    build_graphrag_input,
    build_knowledge_graph,
    run_material_to_csv,
    validate_knowledge,
    generate_isis_scenario,
    prepare_analysis_input,
    run_analysis,
    start_frontend,
    start_graphrag_server,
    pythonpath_env,
)


def main():
    parser = argparse.ArgumentParser(description="54所 IS-IS 智能分析平台无头工作流")
    parser.add_argument("scenario", nargs="?", default=None, help="指定场景，如 link-down")
    parser.add_argument("--graphrag-port", type=int, default=9200)
    parser.add_argument("--frontend-port", type=int, default=8080)
    parser.add_argument("--skip-frontend", action="store_true", help="不启动前端")
    parser.add_argument("--skip-knowledge", action="store_true", help="不重新构建知识图谱")
    parser.add_argument("--knowledge-batch", help="合并已审阅的素材候选批次，再构建索引")
    args = parser.parse_args()
    if args.knowledge_batch and args.skip_knowledge:
        parser.error("--knowledge-batch 不能与 --skip-knowledge 同时使用")

    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir = WORKSPACE / "isis-simulator" / "output" / run_id
    graphrag_proc = None

    try:
        # 1. 生成数据
        generate_isis_scenario(args.scenario, output_dir)
        input_dir = prepare_analysis_input(output_dir, run_id)

        # 2. 构建知识图谱 + GraphRAG 索引
        if not args.skip_knowledge:
            if args.knowledge_batch:
                run_material_to_csv(["merge", args.knowledge_batch])
            else:
                build_knowledge_graph()
            build_graphrag_input()
            build_graphrag_index()

        # 3. 启动 GraphRAG 服务
        graphrag_proc = start_graphrag_server(args.graphrag_port)
        validate_knowledge(graphrag_url=f"http://localhost:{args.graphrag_port}")

        # 4. 运行分析
        env = pythonpath_env()
        env["GRAPHRAG_ENABLED"] = "true"
        report = run_analysis(input_dir)

        # 5. 启动前端
        if not args.skip_frontend:
            frontend_proc = start_frontend(args.frontend_port)
            print(f"[DONE] 工作流完成。前端: http://localhost:{args.frontend_port}")
            if report:
                print(f"[REPORT] {report}")
            try:
                frontend_proc.wait()
            except KeyboardInterrupt:
                pass
            finally:
                frontend_proc.terminate()
                try:
                    frontend_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    frontend_proc.kill()

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] 工作流失败: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("[INFO] 用户中断")
    finally:
        if graphrag_proc:
            graphrag_proc.terminate()
            try:
                graphrag_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                graphrag_proc.kill()


if __name__ == "__main__":
    main()
