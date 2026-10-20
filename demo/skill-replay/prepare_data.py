"""Build a self-contained replay package from real project artifacts and local supplemental runs."""
from pathlib import Path
import base64, csv, hashlib, json, os, shutil, subprocess, sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DIST = HERE / 'dist'
WORK = HERE / 'workspace'
EVIDENCE = DIST / 'evidence'
for p in [DIST, WORK, EVIDENCE]: p.mkdir(parents=True, exist_ok=True)

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream: return list(csv.DictReader(stream))

def snapshot_tables(target):
    target.mkdir(parents=True, exist_ok=True)
    for p in (WORK / 'knowledge/tables').glob('*.csv'): shutil.copy2(p, target / p.name)
    shutil.copy2(WORK / 'knowledge/knowledge_graph.json', target / 'knowledge_graph.json')

# Copy only data and standard-library scenario code; exclude credentials and model outputs.
for relative in ['knowledge/tables', 'knowledge/rfc', 'isis-simulator/src',
                 'agent-analysis/config/diagnosis_rules', 'agent-analysis/config/knowledge_tables']:
    shutil.copytree(ROOT / relative, WORK / relative, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.env*'))
shutil.copy2(ROOT / 'knowledge/knowledge_graph.json', WORK / 'knowledge/knowledge_graph.json')
snapshot_tables(EVIDENCE / 'before')
source = ROOT / 'agent-analysis/config/diagnosis_rules/layer2_link.json'
shutil.copy2(source, EVIDENCE / 'source-rules.json')
env = os.environ.copy()
env['WORKSPACE'] = str(WORK)
env['GRAPHRAG_URL'] = ''
commands = []

def run(arguments, label):
    cmd = [sys.executable, str(ROOT / 'skills/knowledge-builder/run.py'), *arguments]
    result = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, timeout=60)
    (EVIDENCE / f'{label}.log').write_text(result.stdout + result.stderr)
    commands.append({'stage': label, 'command': ['python3', 'skills/knowledge-builder/run.py', *arguments],
                     'returncode': result.returncode,
                     'ran_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()})
    if result.returncode != 0: raise RuntimeError(f'{label}: {result.stderr[:500]}')
    return result.stdout

run(['extract', str(source), '--source', 'rule:layer2_link.json', '--batch', 'demo_rules'], 'extract')
batch = WORK / 'knowledge/incoming/demo_rules'
run(['diff', str(batch)], 'diff')
shutil.copytree(batch, EVIDENCE / 'candidate', dirs_exist_ok=True, ignore=shutil.ignore_patterns('merge_snapshot'))
run(['merge', str(batch)], 'merge-and-build')
snapshot_tables(EVIDENCE / 'after')
shutil.copytree(batch / 'merge_snapshot', EVIDENCE / 'merge_snapshot', dirs_exist_ok=True)
run(['validate', '--graphrag-url', '', '--sample', '0'], 'validate-full')
validation_json = run(['validate', '--json', '--graphrag-url', '', '--sample', '0'], 'validate')
items = json.loads(validation_json)
(EVIDENCE / 'validation.json').write_text(json.dumps(items, ensure_ascii=False, indent=2))
validation_reports = sorted((WORK / 'knowledge/learnings/validation').glob('*.md'), key=lambda p:p.stat().st_mtime)
shutil.copy2(validation_reports[-1], EVIDENCE / 'validation.md')
shutil.copy2(WORK / 'graphrag/input/knowledge_graph.txt', EVIDENCE / 'knowledge_graph.txt')

# Original diagnosis and execution trace are copied unchanged.
trace_path = ROOT / 'agent-analysis/data/traces/run_20261013_200713.json'
report_path = ROOT / 'agent-analysis/output/reports/run_20261013_200713.md'
trace = json.loads(trace_path.read_text())
shutil.copy2(trace_path, EVIDENCE / 'analysis-trace.json')
shutil.copy2(report_path, EVIDENCE / 'original-report.md')
shutil.copy2(ROOT / 'agent-analysis/output/sequence_diagrams/run_20261013_200713.html', EVIDENCE / 'original-sequence.html')
case = ROOT / 'isis-simulator/output/verify_circuit_type'
pcap = case / 'pcapng/circuit-type-mismatch.pcap'
log = case / 'logs/circuit_type_mismatch.log'
shutil.copy2(pcap, EVIDENCE / pcap.name)
shutil.copy2(log, EVIDENCE / log.name)

# Read original packets; never regenerate or alter them.
sys.path[:0] = [str(ROOT / 'agent-analysis/src'), str(ROOT / 'isis-simulator/src')]
from agent_analysis.pcap_feature import extract_features
from isis_simulator.verify import read_pcap, decode_packet
from agent_analysis.knowledge_adapter import KnowledgeAdapter
features = extract_features(pcap)
(EVIDENCE / 'pcap-features.json').write_text(json.dumps(features, ensure_ascii=False, indent=2))
packets = []
raw = read_pcap(str(pcap));first = min(row[0] for row in raw)
for timestamp, frame, stage in raw:
    decoded = decode_packet(frame)
    packets.append({'relative_s': round((timestamp-first)/1e6, 3), 'stage': stage,
                    **{key:decoded.get(key) for key in ['source_id','pdu_type_name','circuit_type','holding_timer','src_mac','dst_mac']}})
(EVIDENCE / 'packets.json').write_text(json.dumps(packets, ensure_ascii=False, indent=2))
adapter = KnowledgeAdapter(ROOT / 'agent-analysis/config/knowledge_tables')
adapter.load()
query = 'circuit type mismatch'
hits = adapter.query_by_name(query)
knowledge = {'query':query, 'source':'agent-analysis/config/knowledge_tables',
             'queried_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
             'hits':hits, 'related':adapter.find_related('circuit_type_mismatch'),
             'incoming_edges':[e for e in adapter.edges if e.get('target_id')=='circuit_type_mismatch'],
             'incoming_edge_source':'agent-analysis/config/knowledge_tables/edges.csv'}
(EVIDENCE / 'knowledge-query.json').write_text(json.dumps(knowledge, ensure_ascii=False, indent=2))
correction = '''# 演示解读与原始报告勘误

案例：IS-IS 层级配置不匹配。历史分析时间：2026-10-13 20:07:13。

原报告中 L2-R003 与 L3-R004 都指向 circuit_type_mismatch，是同一故障在两个检查层命中。
演示采用「单个配置故障、跨层规则命中」解读，不采用原报告的「复合故障」结论。
原报告、追踪文件及其原始结论均未修改，下载区保留原件。

抓包证据：R02 在 before 段发送 L2 LAN IIH，在 fault 段发送 L1 LAN IIH，after 段恢复 L2 LAN IIH。
日志第二行记录 Circuit type mismatch，与该信号相符。
日志第一行中的接收方向表述与抓包不完全一致；诊断重点依据抓包字段和第二行日志。

展示的抓包与日志取自项目归档的同场景合成样例；原诊断输入位于已不再保留的临时路径，
因此这里不宣称归档文件就是该历史运行的逐字节输入。重新解析的字段与原报告列出的信号相符。

「恢复样例」仅表示合成抓包 after 段字段恢复，不是现场设备修复或业务恢复的验证。
历史诊断关闭了模型调用并使用 CSV 知识查询；本包不演示实时大模型或实时 GraphRAG 查询。
新增规则知识使用演示副本中的素材提取/合并/构建/校验，未自动变成新的诊断规则。
技能名称与引擎步骤的对应是职责解释；原 trace 并未记录独立的 skill 调用事件。
'''
(EVIDENCE / 'interpretation.md').write_text(correction)
(EVIDENCE / 'execution-record.json').write_text(json.dumps(commands, ensure_ascii=False, indent=2))

before_nodes = read_csv(EVIDENCE / 'before/nodes.csv')
after_nodes = read_csv(EVIDENCE / 'after/nodes.csv')
before_ids = {n['node_id'] for n in before_nodes}
new_nodes = [n for n in after_nodes if n['node_id'] not in before_ids]
assets = []
for path in sorted(EVIDENCE.rglob('*')):
    if not path.is_file() or path == EVIDENCE/'manifest.json': continue
    relative = str(path.relative_to(DIST))
    binary = path.suffix == '.pcap'
    blob = path.read_bytes()
    assets.append({'id':relative,'name':path.name,'path':relative,'size':len(blob),
                   'sha256':hashlib.sha256(blob).hexdigest(), 'binary':binary,
                   'content':base64.b64encode(blob).decode() if binary else blob.decode('utf-8')})
manifest = {'version':1,'title':'IS-IS 技能协作回放','prepared_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            'historical_run':'run_20261013_200713', 'mode':'offline_replay',
            'source_provenance':{'historical_trace':str(trace_path.relative_to(ROOT)),
              'historical_report':str(report_path.relative_to(ROOT)),
              'archive_pcap':str(pcap.relative_to(ROOT)), 'archive_log':str(log.relative_to(ROOT)),
              'supplemental_source':str(source.relative_to(ROOT))},
            'commands':commands, 'artifact_hashes':{a['path']:a['sha256'] for a in assets}}
(EVIDENCE / 'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
assets.append({'id':'evidence/manifest.json','path':'evidence/manifest.json','name':'manifest.json','size':(EVIDENCE/'manifest.json').stat().st_size,'binary':False,'content':json.dumps(manifest,ensure_ascii=False,indent=2)})
package = {'manifest':manifest, 'trace':trace,'features':features,'packets':packets,'source_rules':json.loads(source.read_text()),
           'candidate_nodes':read_csv(batch/'candidate_nodes.csv'),'before_nodes':before_nodes,
           'after_nodes':after_nodes,'new_nodes':new_nodes,'before_edges':read_csv(EVIDENCE/'before/edges.csv'),
           'after_edges':read_csv(EVIDENCE/'after/edges.csv'),'validation':items,'knowledge':knowledge,'assets':assets}
(HERE/'package-data.json').write_text(json.dumps(package,ensure_ascii=False,indent=2))
print(json.dumps({'packets':len(packets),'before_nodes':len(before_nodes),'after_nodes':len(after_nodes),
                  'new_nodes':[n['node_id'] for n in new_nodes], 'artifacts':len(assets),
                  'critical':sum(i['level']=='CRITICAL' for i in items)},ensure_ascii=False))
