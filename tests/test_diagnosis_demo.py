"""Regression checks for symptom-only inputs and cross-layer attribution."""
import json, struct, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'agent-analysis/src'),str(ROOT/'isis-simulator/src')]
from agent_analysis.engine import AnalysisEngine
from agent_analysis.knowledge_adapter import KnowledgeAdapter
from agent_analysis.log_parser import LogParser
from agent_analysis.llm_client import LLMClient
from isis_simulator.verify import decode_packet,read_pcap
from isis_simulator import isis_pdu as pdu
from isis_simulator.pcap_writer import PcapWriter
from isis_simulator.isis_topology import mac_bytes,L2_MULTICAST_MAC

class DiagnosisDemoTests(unittest.TestCase):
    def bare_engine(self):
        engine=AnalysisEngine.__new__(AnalysisEngine)
        engine.anomalies=[]
        return engine
    def test_cross_layer_hits_do_not_prove_composite_fault(self):
        engine=self.bare_engine()
        engine.anomalies=[{'layer':layer,'rule':{'id':rid,'name':'circuit_type_mismatch'}}
                          for layer,rid in [('L2','L2-R003'),('L3','L3-R004')]]
        summary=engine._composite_summary()
        self.assertIn('1 个候选模式',summary)
        self.assertNotIn('判定：复合故障',summary)
    def test_symptom_only_log_still_queries_packet_cause(self):
        engine=self.bare_engine()
        terms=engine._local_knowledge_terms({'log':{'events':{'event_types':['adjacency_down','packet_loss']}},
            'pcap':{'capture':{'pcap_signals':['CIRCUIT_TYPE_CHANGE','MIXED_HELLO_PDU_TYPES']}}})
        self.assertIn('circuit_type_mismatch',terms)
        self.assertEqual(1,terms.count('circuit_type_mismatch'))
    def test_standard_llc_and_arbitrary_capture_epoch(self):
        body=pdu.build_l2_lan_iih(2,27)
        payload=b'\xfe\xfe\x03'+body
        frame=L2_MULTICAST_MAC+mac_bytes(2)+struct.pack('>H',len(payload))+payload
        decoded=decode_packet(frame)
        self.assertEqual(decoded['source_id'],'000000000002')
        self.assertEqual(decoded['pdu_type_name'],'L2_IIH')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'capture.pcap';base=1_800_000_000_000_000
            with PcapWriter(str(path)) as w:
                w.write_packet(frame,base);w.write_packet(frame,base+41_000_000)
            packets=read_pcap(str(path))
            self.assertEqual([p[2] for p in packets],['before','fault'])
    def test_zero_loss_probe_is_not_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            log=Path(temp)/'events.log'
            log.write_text('R01 MONITOR: Ping to 10.20.2.1: 0% packet loss\n')
            features=LogParser().extract_features(log)
            self.assertNotIn('packet_loss',features['event_types'])
            self.assertIn('probe_healthy',features['event_types'])
    def test_empty_or_error_model_response_is_not_success(self):
        client=LLMClient.__new__(LLMClient)
        client.endpoint='http://local.invalid/v1/chat/completions'
        client.api_key='none';client.model='test';client.provider='openai'
        for response in [{'error':{'message':'no credits'}},{'choices':[{'message':{'content':'','reasoning_content':'private reasoning'}}]}]:
            client._post_json=lambda *args,r=response,**kwargs:json.dumps(r)
            result=client.chat_safe('合成测试提示')
            self.assertFalse(result['success'])
            self.assertEqual(result['result'],'')
    def test_fresh_case_contains_symptoms_and_no_recovery(self):
        ev=ROOT/'demo/client-diagnosis/dist/evidence'
        log=(ev/'device-events.log').read_text()
        self.assertIn('is Down',log)
        self.assertNotIn('Circuit type mismatch',log)
        packets=json.loads((ev/'packets.json').read_text())
        self.assertFalse(any(p['stage']=='after' for p in packets))
        by_stage={stage:[p for p in packets if p.get('source_id')=='000000000002' and p['stage']==stage]
                  for stage in ['before','fault']}
        self.assertEqual({p['pdu_type_name'] for p in by_stage['before']},{'L2_IIH'})
        self.assertEqual({p['pdu_type_name'] for p in by_stage['fault']},{'L1_IIH'})

if __name__=='__main__':unittest.main()
