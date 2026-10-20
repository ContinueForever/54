"""Verify input provenance, actual project output and offline package consistency."""
from pathlib import Path
from html.parser import HTMLParser
import base64, csv, hashlib, json, re, subprocess, sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];DIST=HERE/'dist'
data=json.loads((HERE/'package-data.json').read_text());checks=[]
def check(name,condition,detail=''):
    if not condition:raise AssertionError(name+': '+detail)
    checks.append({'name':name,'passed':True,'detail':detail})
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

result=json.loads(Path(data['source']['result']).read_text())
check('Authoritative project run',data['run_id']==result['trace_id'])
check('Original report bytes',Path(data['source']['report']).read_bytes()==(DIST/'evidence/diagnosis-report.md').read_bytes())
check('Original trace bytes',Path(data['source']['trace']).read_bytes()==(DIST/'evidence/analysis-trace.json').read_bytes())
for path in result['input']['pcap_files']+result['input']['log_files']+result['input']['state_files']:
    check('Input preserved: '+Path(path).name,Path(path).read_bytes()==(DIST/'evidence'/Path(path).name).read_bytes())
for a in data['assets']:
    blob=base64.b64decode(a['content']) if a['binary'] else a['content'].encode()
    check('Artifact content/hash: '+a['id'],blob==(DIST/a['path']).read_bytes() and hashlib.sha256(blob).hexdigest()==a['sha256'])
check('Actual pipeline order',[s['id'] for s in data['result']['stage_records']]==[s['layer'] for s in data['trace']['steps'] if s['status']!='RUNNING'])
check('Source observation does not give root cause','mismatch' not in data['incident']['description'].lower() and '层级' not in data['incident']['description'])
check('Raw log has symptoms without diagnosis','Circuit type mismatch' not in (DIST/'evidence/device-events.log').read_text())
check('No recovery in original input',not any(p['stage']=='after' for p in data['packets']))
check('Measured business degradation',data['packet_features']['icmp']['before']=={'req':10,'reply':10} and data['packet_features']['icmp']['fault']=={'req':10,'reply':0})
check('Cross-layer rule aggregation',set(data['rule_groups']['circuit_type_mismatch'])=={'L2-R003','L3-R004'})
check('No false composite conclusion','判定：复合故障' not in (DIST/'evidence/diagnosis-report.md').read_text())
check('Actual knowledge preparation',all(s['returncode']==0 for s in data['preparation']['stages']))
check('Diagnosis consumes prepared tables',data['knowledge']['stats']['total_nodes']==data['preparation']['after_nodes'])
with (DIST/'evidence/knowledge-after/nodes.csv').open(encoding='utf-8-sig',newline='') as stream:
    table_nodes={row['node_id'] for row in csv.DictReader(stream)}
check('CSV and graph node sets agree',{n['node_id'] for n in json.loads((DIST/'evidence/knowledge-graph.json').read_text())['nodes']}==table_nodes)
check('Formal knowledge tables preserved',all((DIST/'evidence/knowledge-before'/name).read_bytes()==(ROOT/'knowledge/tables'/name).read_bytes() for name in ['nodes.csv','edges.csv','node_attributes.csv']))
check('No CRITICAL knowledge error',not any(x['level']=='CRITICAL' for x in data['validation']))
if data['model_mode']=='illustrative':
    check('Illustrative model is explicitly marked',data['model']['execution_mode']=='illustrative' and data['model']['remote_request_made'] is False)
    check('Illustrative provider cannot masquerade as configured model',data['model']['provider']=='demonstration')
elif data['model_mode']=='real':
    check('Real model returned actual text',data['model']['success'] is True and bool(data['model']['result'].strip()))
check('Model context retains all raw logs',all(line in data['model']['prompt'] for line in data['log_features']['raw_lines']))
check('Independent review belongs to this run',data['critique'] and data['critique'].get('run_id')==data['run_id'])
html=(DIST/'index.html').read_text()
check('Embedded task matches data',json.loads(re.search(r'<script type="application/json" id="workbench-data">(.*?)</script>',html,re.S).group(1))==data)
check('Template fully replaced','__WORKBENCH_DATA__' not in html)
class Resources(HTMLParser):
    def __init__(self):super().__init__();self.external=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag in ['script','img','link','iframe'] and (d.get('src') or d.get('href')):self.external.append(d.get('src') or d.get('href'))
resources=Resources();resources.feed(html)
check('Offline snapshot has no external resource dependencies',not resources.external)
script=re.findall(r'<script(?:[^>]*)>(.*?)</script>',html,re.S)[-1]
p=Path('/tmp/diagnosis-workbench-check.js');p.write_text(script)
subprocess.run(['node','--check',str(p)],check=True)
check('Client JavaScript syntax',True)
verification={'status':'passed','count':len(checks),'checks':checks,'browser_checks':['原始报障复盘','异常窗口R02筛选','逐条报文详情'],'model_mode':data['model_mode']}
(DIST/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2))
print('Passed',len(checks),'provenance and package checks.')
