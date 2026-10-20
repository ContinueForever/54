"""Generate a symptom-first, standards-encapsulated synthetic diagnostic case.

Only local synthetic data is created. The scenario specification is deliberately
kept outside the analyzer input and model prompt.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import csv, hashlib, json, os, shutil, struct, subprocess, sys, time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = HERE / 'workspace'
DIST = HERE / 'dist'
EVIDENCE = DIST / 'evidence'
INPUT = HERE / 'input'
for p in [WORK, EVIDENCE, INPUT]: p.mkdir(parents=True, exist_ok=True)
sys.path[:0] = [str(ROOT/'isis-simulator/src'), str(ROOT/'agent-analysis/src')]
from isis_simulator import isis_pdu as pdu
from isis_simulator.isis_topology import mac_bytes, L1_MULTICAST_MAC, L2_MULTICAST_MAC
from isis_simulator.pcap_writer import PcapWriter
from isis_simulator.verify import read_pcap, decode_packet
from agent_analysis.pcap_feature import extract_features

def now(): return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
def save(path, obj): path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
def csv_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))

def generate():
    sys.path.insert(0,str(ROOT/'scripts_lib'))
    from runner import generate_isis_scenario, prepare_analysis_input
    run_id='incident_20261014_017'
    source=ROOT/'isis-simulator/output'/run_id
    generate_isis_scenario('adjacency-incident',source)
    prepared=prepare_analysis_input(source,run_id)
    save(HERE/'case-source.json',{'scenario_output':str(source),'input_dir':str(prepared),'scenario':'adjacency-incident','generated_through':'isis_simulator.generate.run_all','prepared_through':'scripts_lib.runner.prepare_analysis_input'})
    for path in prepared.iterdir():
        if path.is_file():shutil.copy2(path,INPUT/path.name);shutil.copy2(path,EVIDENCE/path.name)
    for name in ['incident.json','generation.json','packets.json']:
        shutil.copy2(source/name,EVIDENCE/name)
    features=extract_features(prepared/'link-observation.pcap')
    save(EVIDENCE/'packet-features.json',features)
    print('Prepared project input:',prepared)

def knowledge():
    if (EVIDENCE/'preparation.json').exists():
        print('Knowledge preparation already saved; keeping actual records.')
        return
    for rel in ['knowledge/tables','knowledge/rfc','isis-simulator/src','agent-analysis/config/diagnosis_rules','agent-analysis/config/knowledge_tables']:
        shutil.copytree(ROOT/rel,WORK/rel,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.env*'))
    shutil.copy2(ROOT/'knowledge/knowledge_graph.json',WORK/'knowledge/knowledge_graph.json')
    for p in (WORK/'knowledge/tables').glob('*.csv'):
        (EVIDENCE/'knowledge-before').mkdir(exist_ok=True);shutil.copy2(p,EVIDENCE/'knowledge-before'/p.name)
    source = WORK/'agent-analysis/config/diagnosis_rules/layer2_link.json'
    shutil.copy2(source,EVIDENCE/'source-rules.json')
    stages=[]
    env={**os.environ,'WORKSPACE':str(WORK),'GRAPHRAG_URL':''}
    for name,skill,args in [
        ('extract','material-to-csv',['extract',str(source),'--source','rule:layer2_link.json','--batch','client_rules']),
        ('diff','material-to-csv',['diff',str(WORK/'knowledge/incoming/client_rules')]),
        ('build','knowledge-builder',['merge',str(WORK/'knowledge/incoming/client_rules')]),
        ('validate','kg-validator',['validate','--json','--graphrag-url','','--sample','0'])]:
        started=now();tick=time.perf_counter()
        cmd=[sys.executable,str(ROOT/'skills/knowledge-builder/run.py'),*args]
        result=subprocess.run(cmd,cwd=ROOT,env=env,text=True,capture_output=True,timeout=60)
        (EVIDENCE/f'knowledge-{name}.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        stages.append({'id':name,'skill':skill,'started_at':started,'completed_at':now(),'duration_ms':round((time.perf_counter()-tick)*1000),'command':cmd,'returncode':result.returncode,'artifact':f'evidence/knowledge-{name}.log'})
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        if name=='validate':save(EVIDENCE/'knowledge-validation.json',json.loads(result.stdout))
    shutil.copytree(WORK/'knowledge/incoming/client_rules',EVIDENCE/'knowledge-candidates',dirs_exist_ok=True)
    shutil.copytree(WORK/'knowledge/tables',EVIDENCE/'knowledge-after',dirs_exist_ok=True)
    shutil.copy2(WORK/'knowledge/knowledge_graph.json',EVIDENCE/'knowledge-graph.json')
    shutil.copy2(WORK/'graphrag/input/knowledge_graph.txt',EVIDENCE/'knowledge-input.txt')
    validation=sorted((WORK/'knowledge/learnings/validation').glob('*.md'),key=lambda p:p.stat().st_mtime)[-1]
    shutil.copy2(validation,EVIDENCE/'knowledge-validation.md')
    save(EVIDENCE/'preparation.json',{'stages':stages,'before_nodes':len(csv_rows(EVIDENCE/'knowledge-before/nodes.csv')),'after_nodes':len(csv_rows(EVIDENCE/'knowledge-after/nodes.csv')),'scope':'演示副本的知识维护；随后该副本被诊断任务实际加载。','index_rebuilt':False})
    print('Knowledge preparation complete.')

if __name__=='__main__':
    generate()
    knowledge()
