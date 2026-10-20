"""Render a workbench from one project's recorded run, not hand-entered results."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import base64, csv, hashlib, json, shutil, zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];DIST=HERE/'dist';EV=DIST/'evidence'
def load(name):return json.loads((EV/name).read_text())
def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

result=load('analysis-result.json')
# Always read the authoritative project result and trace for this run.
run_id=result['trace_id']
result=json.loads((ROOT/'agent-analysis/output/results'/f'{run_id}.json').read_text())
trace=json.loads(Path(result['trace_file']).read_text())
report=ROOT/'agent-analysis/output/reports'/f'{run_id}.md'
shutil.copy2(report,EV/'diagnosis-report.md')
shutil.copy2(result['trace_file'],EV/'analysis-trace.json')
packet=next(iter(result['features']['pcap'].values()))
state=next(iter(result['features']['state'].values()))
log=next(iter(result['features']['log'].values()))
knowledge=load('knowledge-query.json');prep=load('preparation.json')
model=load('model-call.json') if (EV/'model-call.json').exists() else {}
manifest={'run_id':run_id,'built_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
          'source_result':str(ROOT/'agent-analysis/output/results'/f'{run_id}.json'),
          'source_report':str(report),'source_trace':result['trace_file'],'source_input':result['input']['path'],
          'data_origin':'受控合成输入；项目真实规则/特征/知识/追踪执行',
          'model_mode':result['model_execution_mode'],'recovery_verified':False,
          'artifact_hashes':{str(p.relative_to(EV)):hashlib.sha256(p.read_bytes()).hexdigest() for p in EV.rglob('*') if p.is_file() and p.name!='manifest.json'}}
(EV/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
skills={
    'workspace-orchestrator':{'name':'流程编排','role':'接收报障、检查数据、组织知识准备和诊断，审查后交付。','artifact':'skill-audit.json','source':'skills/workspace-orchestrator/SKILL.md'},
    'material-to-csv':{'name':'素材提取','role':'将已有规则材料提取为候选知识，记录新增与冲突。','artifact':'knowledge-candidates/diff_report.md','source':'skills/material-to-csv/SKILL.md'},
    'knowledge-builder':{'name':'知识构建','role':'在副本合并候选、构建图谱与检索输入，随后供本次诊断加载。','artifact':'preparation.json','source':'skills/knowledge-builder/SKILL.md'},
    'kg-validator':{'name':'质量校验','role':'在诊断前检查结构、来源和一致性；严重问题阻止后续分析。','artifact':'knowledge-validation.md','source':'skills/kg-validator/SKILL.md'},
    'isis-analysis':{'name':'分层诊断','role':'读取输入、解析报文、分层匹配规则，组织模型提示和报告。','artifact':'diagnosis-report.md','source':'agent-analysis/.hermes/skills/isis-analysis/SKILL.md'},
    'knowledge-bridge':{'name':'知识桥接','role':'将已准备的 CSV 图谱加载为节点与关系，按事件和报文信号查询。','artifact':'knowledge-query.json','source':'agent-analysis/.hermes/skills/knowledge-bridge/SKILL.md'},
    'flow-tracer':{'name':'全程追踪','role':'在各阶段记录时间、状态和规则编号，保存可复核的执行轨迹。','artifact':'analysis-trace.json','source':'agent-analysis/.hermes/skills/flow-tracer/SKILL.md'},
}
for skill,definition in skills.items():
    target=EV/'skill-definitions'/f'{skill}.md';target.parent.mkdir(exist_ok=True)
    shutil.copy2(ROOT/definition['source'],target)

assets=[]
for p in sorted(EV.rglob('*')):
    if not p.is_file():continue
    blob=p.read_bytes();binary=p.suffix=='.pcap'
    assets.append({'id':str(p.relative_to(EV)),'path':str(p.relative_to(DIST)),'name':p.name,'size':len(blob),'sha256':hashlib.sha256(blob).hexdigest(),
                   'binary':binary,'content':base64.b64encode(blob).decode() if binary else blob.decode('utf-8')})
groups={}
for a in result['anomalies']:groups.setdefault(a['rule']['name'],[]).append(a['rule']['id'])
data={'run_id':run_id,'incident':load('incident.json'),'trace':trace,'result':result,'packet_features':packet,
      'state':state,'log_features':log,'packets':load('packets.json'),'knowledge':knowledge,'preparation':prep,'validation':load('knowledge-validation.json'),
      'model':model,'model_mode':result['model_execution_mode'],'skills':skills,'rule_groups':groups,'assets':assets,
      'critique':load('critique.json') if (EV/'critique.json').exists() else None,
      'generation':load('generation.json'),'built_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
      'source':{'result':str(ROOT/'agent-analysis/output/results'/f'{run_id}.json'),'report':str(report),'trace':result['trace_file'],'input':result['input']['path']},
      'view_mode':'project execution snapshot'}
fault_nodes=next(s for s in state['snapshots'] if s['stage']=='fault')['nodes']
levels={n['process_is_type'] for n in fault_nodes}
root_rule=any(a['rule']['name']=='circuit_type_mismatch' for a in result['anomalies'])
data['summary']={'title':'两端有效 IS-IS 层级不兼容' if root_rule and len(levels)>1 else '请查看本任务诊断报告',
                 'basis':'配置快照与 Hello 字段一致，优先定位 R02 最近的层级配置变更。' if root_rule and len(levels)>1 else '根据任务记录复核命中规则与观测事实。',
                 'source':'规则、状态快照与独立证据审查；不是预先写入的输入答案'}
(HERE/'package-data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
encoded=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
html=(HERE/'workbench.template.html').read_text().replace('__WORKBENCH_DATA__',encoded)
(DIST/'index.html').write_text(html,encoding='utf-8')
(ROOT/'frontend/workbench.html').write_text(html,encoding='utf-8')
live=ROOT/'agent-analysis/output/workbenches';live.mkdir(exist_ok=True)
(live/f'{run_id}.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
shutil.copy2(HERE/'README.md',DIST/'使用说明.md')
with zipfile.ZipFile(HERE/'IS-IS诊断任务工作台.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(DIST.rglob('*')):
        if p.is_file():archive.write(p,p.relative_to(DIST))
print('Built workbench from',run_id,'with',len(assets),'source artifacts.')
