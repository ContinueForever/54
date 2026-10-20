"""Verify actual artifacts, source preservation and self-contained delivery."""
from pathlib import Path
from html.parser import HTMLParser
import base64, csv, hashlib, json, re, subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIST = HERE / 'dist'
DATA = json.loads((HERE/'package-data.json').read_text())
checks = []
def verify(name, condition, detail=''):
    if not condition: raise AssertionError(name + ': ' + detail)
    checks.append({'check':name,'passed':True,'detail':detail})

for asset in DATA['assets']:
    blob = base64.b64decode(asset['content']) if asset.get('binary') else asset['content'].encode()
    disk = (DIST/asset['path']).read_bytes()
    verify('Embedded artifact equals file: '+asset['path'],blob==disk)
    if asset.get('sha256'):verify('Artifact hash: '+asset['path'],hashlib.sha256(blob).hexdigest()==asset['sha256'])
verify('Historical report unchanged', (DIST/'evidence/original-report.md').read_bytes()==(ROOT/'agent-analysis/output/reports/run_20261013_200713.md').read_bytes())
verify('Historical trace unchanged', (DIST/'evidence/analysis-trace.json').read_bytes()==(ROOT/'agent-analysis/data/traces/run_20261013_200713.json').read_bytes())
verify('Original project tables unchanged',all((DIST/'evidence/before'/name).read_bytes()==(ROOT/'knowledge/tables'/name).read_bytes() for name in ['nodes.csv','edges.csv','node_attributes.csv']))
verify('Five real candidate nodes',len(DATA['candidate_nodes'])==5 and len(DATA['new_nodes'])==5)
verify('Node delta matches merge',len(DATA['after_nodes'])-len(DATA['before_nodes'])==len(DATA['new_nodes']))
graph=json.loads((DIST/'evidence/after/knowledge_graph.json').read_text())
verify('CSV and JSON node sets match', {n['node_id'] for n in DATA['after_nodes']}=={n['node_id'] for n in graph['nodes']})
verify('CSV and JSON edges match',DATA['after_edges']==graph['edges'])
verify('Merge snapshot preserves baseline',(DIST/'evidence/merge_snapshot/nodes.csv').read_bytes()==(DIST/'evidence/before/nodes.csv').read_bytes())
verify('Supplemental commands succeeded',all(c['returncode']==0 for c in DATA['manifest']['commands']))
verify('No model or index rebuild requested',all('--index' not in c['command'] and 'graphrag-index' not in c['command'] for c in DATA['manifest']['commands']))
verify('No CRITICAL errors',not any(i['level']=='CRITICAL' for i in DATA['validation']))
verify('Known source warnings preserved',any(i['level']=='MAJOR' and 'RFC 5305' in i['evidence'] for i in DATA['validation']))
verify('All 70 archived packets decoded',len(DATA['packets'])==70)
for stage,pdu in [('before','L2_IIH'),('fault','L1_IIH'),('after','L2_IIH')]:
    values={p['pdu_type_name'] for p in DATA['packets'] if p['source_id']=='000000000002' and p['stage']==stage}
    verify('R02 protocol type at '+stage,values=={pdu},str(values))
verify('Actual knowledge query hit',any(n['node_id']=='circuit_type_mismatch' for n in DATA['knowledge']['hits']))
verify('Skill-stage mapping does not invent call history',all('skill' not in step for step in DATA['trace']['steps']))
html=(DIST/'index.html').read_text()
class PageResources(HTMLParser):
    def __init__(self):super().__init__();self.resources=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ['script','img','iframe','link','video','audio','source']:
            for key in ['src','href']:
                if key in attrs:self.resources.append(attrs[key])
resources=PageResources();resources.feed(html)
verify('No external or local runtime resources',not resources.resources,str(resources.resources))
inline_data=re.search(r'<script id="replay-data" type="application/json">(.*?)</script>',html,re.S).group(1)
verify('Embedded data round trips exactly',json.loads(inline_data)==DATA)
client=re.findall(r'<script(?:[^>]*)>(.*?)</script>',html,re.S)[-1]
step_source=re.search(r'const STEP=\[(.*?)\];',client,re.S).group(1)
declared=re.findall(r"id:'([^']+)'",step_source)
expected=[event['layer'] for event in DATA['trace']['steps'] if event['status']!='RUNNING']
verify('Diagnosis timeline follows actual trace order',declared==expected,str(declared))
verify('Knowledge maintenance is a separate view',all(key in client for key in ["knowledge:maintenanceView", "view='case'", "data-maintenance"]))
verify('No runtime backend calls',not re.search(r'\b(fetch|XMLHttpRequest|WebSocket|EventSource)\b',client))
verify('No unresolved template tokens','__REPLAY_DATA__' not in html)
Path('/tmp/skill-replay-client.js').write_text(client)
subprocess.run(['node','--check','/tmp/skill-replay-client.js'],check=True)
verify('JavaScript syntax check',True)
try:
    download=Path('/home/hermes/下载/original-report.md')
    if download.exists():verify('Browser export preserves original bytes',download.read_bytes()==(DIST/'evidence/original-report.md').read_bytes())
except OSError:pass
verification={'status':'passed','check_count':len(checks),'checks':checks,
              'browser_verified':[],
              'browser_limit':'The in-app browser allows HTTP/HTTPS only; file:// opening is not browser-verified. Runtime resources and backend requests are absent.',
              'mode':'offline replay; existing report plus local supplemental knowledge processing'}
(DIST/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2))
print('Passed',len(checks),'artifact and delivery checks.')
