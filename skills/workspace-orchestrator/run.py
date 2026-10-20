#!/usr/bin/env python3
"""workspace-orchestrator 可执行入口。

支持两种模式：
  - 全流程模式（默认）：生成数据 → 构建知识 → 启动 GraphRAG → 运行分析 → 可选前端
  - 分阶段模式（--stage）：每次只执行一个阶段，Hermes 可在每阶段之间进行 LLM 推理
    stage 可选: generate / prepare (生成+准备) / build_knowledge / build_index /
                start_rag / analyze / critic / report / frontend

运行结束后输出结构化结果供 Hermes 作为 LLM 诊断。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]
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

STAGES = (
    "generate", "prepare", "build_knowledge", "build_index",
    "start_rag", "validate", "analyze", "critic", "report", "frontend",
)


def main():
    parser = argparse.ArgumentParser(description="54所 IS-IS 智能分析平台统一工作流")
    parser.add_argument("scenario", nargs="?", default=None, help="指定场景，如 link-down / combo-auth-area")
    parser.add_argument("--graphrag-port", type=int, default=9200)
    parser.add_argument("--frontend-port", type=int, default=8080)
    parser.add_argument("--frontend", action="store_true", help="同时启动前端")
    parser.add_argument("--skip-knowledge", action="store_true", help="不重新构建知识图谱")
    parser.add_argument("--knowledge-batch", help="合并已审阅的素材候选批次")
    parser.add_argument("--run-id", default=None, help="指定 run_id（分阶段模式必填）")
    parser.add_argument("--stage", choices=STAGES, default=None,
                        help="只执行单个阶段（供 Hermes 逐步介入 LLM 推理）")
    args = parser.parse_args()
    if args.knowledge_batch and (args.skip_knowledge or args.stage not in (None, "build_knowledge")):
        parser.error("--knowledge-batch 仅用于全流程或 build_knowledge 阶段，不能跳过知识构建")

    run_id = args.run_id or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir = WORKSPACE / "isis-simulator" / "output" / run_id
    input_dir = WORKSPACE / "agent-analysis" / "data" / "incoming" / run_id

    graphrag_proc = None

    # 阶段执行辅助
    def do_generate():
        generate_isis_scenario(args.scenario, output_dir)
        print(f"[STAGE:generate] 完成。产物: {output_dir}")
        print(f"   pcap: {sorted(p.name for p in (output_dir/'pcapng').glob('*.pcap'))}")
        print(f"   log : {sorted(p.name for p in (output_dir/'logs').glob('*.log'))}")

    def do_prepare():
        input_dir = prepare_analysis_input(output_dir, run_id)
        print(f"[STAGE:prepare] 完成。输入目录: {input_dir}")
        print(f"   files: {sorted(p.name for p in input_dir.iterdir())}")

    def do_build_knowledge():
        if args.knowledge_batch:
            run_material_to_csv(["merge", args.knowledge_batch])
        else:
            build_knowledge_graph()
        build_graphrag_input()
        print(f"[STAGE:build_knowledge] 完成。知识表已更新至 knowledge/tables/*.csv")
        print("   GraphRAG 输入: graphrag/input/knowledge_graph.txt")

    def do_build_index():
        build_graphrag_index()
        print(f"[STAGE:build_index] 完成。索引位于 graphrag/output/")

    def do_start_rag():
        nonlocal graphrag_proc
        graphrag_proc = start_graphrag_server(args.graphrag_port)
        print(f"[STAGE:start_rag] GraphRAG 服务就绪于端口 {args.graphrag_port}")

    def do_analyze():
        do_validate()
        env = pythonpath_env()
        env["GRAPHRAG_ENABLED"] = "true"
        report_path = run_analysis(input_dir)
        print(f"[STAGE:analyze] 完成。报告: {report_path}")
        return report_path

    def do_validate():
        validate_knowledge(graphrag_url=f"http://localhost:{args.graphrag_port}")
        print("[STAGE:validate] 知识校验完成，报告位于 knowledge/learnings/validation/")

    def do_critic():
        # 生成批判意见模板，供 Hermes 批判子智能体填写
        report = sorted((WORKSPACE / "agent-analysis" / "output" / "reports").glob("*.md"), reverse=True)
        if not report:
            print("[STAGE:critic] 无报告，无法生成批判意见。先运行 analyze。")
            return
        report_path = report[0]
        critique_path = report_path.with_suffix(".critique.md")
        if not critique_path.exists():
            critique_path.write_text(
                "# 批判意见（由 Hermes 批判子智能体填写）\n\n"
                "审查对象: %s\n\n"
                "## 总体评级\n\n合格 / 有条件合格 / 不合格\n\n"
                "## 数据完整性\n\n## 特征提取\n\n## 规则命中与归因\n\n"
                "## 知识引用\n\n## LLM 结论质量\n\n## 复合故障\n\n## 结论建议\n" % report_path.name,
                encoding="utf-8")
        print(f"[STAGE:critic] 批判意见模板: {critique_path}")

    def do_report():
        report = sorted((WORKSPACE / "agent-analysis" / "output" / "reports").glob("*.md"), reverse=True)
        if not report:
            print("[STAGE:report] 无报告。")
            return
        report_path = report[0]
        print(f"[REPORT] {report_path}")
        print("---")
        print(report_path.read_text(encoding="utf-8"))
        critic = report_path.with_suffix(".critique.md")
        if critic.exists():
            print("---- 批判意见 ----")
            print(critic.read_text(encoding="utf-8"))
        print("---")

    def do_frontend():
        frontend_proc = start_frontend(args.frontend_port)
        print(f"[STAGE:frontend] 前端: http://localhost:{args.frontend_port}")

    try:
        if args.stage:
            fn = locals().get("do_" + args.stage)
            if fn is None:
                print(f"[ERROR] 未知阶段: {args.stage}")
                sys.exit(1)
            fn()
            if args.stage == "start_rag" and graphrag_proc:
                try:
                    graphrag_proc.wait()
                except KeyboardInterrupt:
                    pass
            sys.exit(0)

        # 全流程模式
        do_generate()
        do_prepare()

        if not args.skip_knowledge:
            do_build_knowledge()
            do_build_index()

        do_start_rag()
        do_analyze()
        do_critic()
        do_report()

        if args.frontend:
            do_frontend()
            print(f"[DONE] 工作流完成。前端: http://localhost:{args.frontend_port}")
        else:
            print(f"[DONE] 工作流完成。")

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
