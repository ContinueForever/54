"""Execute the actual project analyzer and export traceable workbench artifacts.

--with-model is an explicit opt-in. No network request is made otherwise.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse, json, os, shutil, sys, time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path[:0]=[str(ROOT/'agent-analysis/src'),str(ROOT/'isis-simulator/src')]
from agent_analysis.engine import AnalysisEngine
from agent_analysis.knowledge_adapter import KnowledgeAdapter
from agent_analysis.tracer import Tracer

class IllustrativeModel:
    """Explicit demonstration adapter; never contacts a model endpoint."""
    def info(self):
        return {'provider':'demonstration','model':'证据解读示例（未调用配置模型）','endpoint':'not_called'}
    def _system_prompt(self):
        return '基于项目提示与已测量证据生成的演示解读；不是配置模型的真实返回。'
    def chat_safe(self, prompt, **kwargs):
        response=(HERE/'model-example.md').read_text(encoding='utf-8')
        return {**self.info(),'success':True,'result':response,'error':None,
                'execution_mode':'illustrative','source':'Codex 根据本次证据编写的示例',
                'remote_request_made':False}

def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def now():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()

def run(with_model, illustrative=False):
    e=AnalysisEngine()
    # Use the project's normal trace/report directories, not a separate display run.
    e.knowledge=KnowledgeAdapter(HERE/'workspace/knowledge/tables')
    if illustrative:e.llm_client=IllustrativeModel()
    os.environ['GRAPHRAG_ENABLED']='false'
    for step in e.pipeline_config['steps']:
        if step['id']=='llm':step['enabled']=with_model or illustrative
    operations=[]
    original_record=e.tracer.record_step
    def record(layer,action,status,detail='',anomaly_id='',duration_ms=0):
        original_record(layer,action,status,detail,anomaly_id,duration_ms)
        if status=='RUNNING':
            operations.append({'id':layer,'name':action,'started_at':now(),'tick':time.perf_counter()})
        else:
            op=next((x for x in reversed(operations) if x['id']==layer and 'completed_at' not in x),None)
            if op:
                op.update({'completed_at':now(),'duration_ms':round((time.perf_counter()-op.pop('tick'))*1000,2),'status':status,'detail':detail,'rule_ids':anomaly_id.split(',') if anomaly_id else []})
    e.tracer.record_step=record
    case_source=json.loads((HERE/'case-source.json').read_text())
    result=e.run(case_source['input_dir'])
    result['case_source']=case_source
    ev=HERE/'dist/evidence';ev.mkdir(parents=True,exist_ok=True)
    result['model_requested']=with_model
    result['model_execution_mode']='illustrative' if illustrative else 'real' if with_model else 'not_requested'
    result['knowledge_stats']=e.knowledge.get_stats()
    result['llm_diagnosis']=e.llm_diagnosis
    result['stage_records']=operations
    result['case_origin']='synthetic_demo; actual project execution'
    save(ev/'analysis-result.json',result)
    result_dir=e.output_dir/'results';result_dir.mkdir(parents=True,exist_ok=True)
    save(result_dir/f'{e.trace_id}.json',result)
    save(ev/'features.json',result['features'])
    save(ev/'knowledge-query.json',{'mode':'local_csv','queries':e.knowledge_queries,'hits':e.knowledge_results,'stats':e.knowledge.get_stats(),'table_source':'workspace/knowledge/tables','queried_during_actual_run':True})
    save(ev/'execution.json',operations)
    shutil.copy2(result['trace_file'],ev/'analysis-trace.json')
    shutil.copy2(e.output_dir/'reports'/f'{e.trace_id}.md',ev/'diagnosis-report.md')
    if with_model or illustrative:
        shutil.copy2(e.output_dir/'model_calls'/f'{e.trace_id}.json',ev/'model-call.json')
        (ev/'model-response.md').write_text(e.llm_diagnosis,encoding='utf-8')
    elif (ev/'model-call.json').exists():
        raise RuntimeError('Do not mix a model-free rerun with a previous model artifact.')
    # Store an execution-facing skill handoff audit, separate from engine events.
    audit={'kind':'skill execution and responsibility audit','started_at':operations[0]['started_at'],'completed_at':now(),
           'orchestrator':{'skill':'workspace-orchestrator','executor':'Codex agent','actions':['检查输入来源与完整性','在副本准备并校验知识','调用项目诊断引擎','检查规则归因与模型证据','独立审查并交付工作台'],
                           'entrypoint':'demo/client-diagnosis/run_case.py','note':'技能由本次执行代理按 SKILL.md 应用；不是声称引擎独立调用了 skill API。'},
           'stage_skills':{s['id']:('knowledge-bridge' if s['id']=='knowledge' else 'isis-analysis') for s in operations},
           'tracer':{'skill':'flow-tracer','entrypoint':'agent_analysis.tracer.Tracer','trace_file':'evidence/analysis-trace.json'},
           'knowledge_preparation':'evidence/preparation.json'}
    save(ev/'skill-audit.json',audit)
    print('Saved actual execution',e.trace_id,'model success:',e.llm_record.get('success','not requested'))

if __name__=='__main__':
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group()
    group.add_argument('--with-model',action='store_true');group.add_argument('--illustrative-model',action='store_true');args=parser.parse_args()
    run(args.with_model,args.illustrative_model)
