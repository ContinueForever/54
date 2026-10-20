"""Symptom-first adjacency incident, generated through the project simulator.

IEEE 802.3/LLC IS-IS and IPv4/ICMP; no recovery packets or root cause text
in the initial incident and syslog. All state is synthetic, never live devices.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json, struct
from isis_simulator import isis_pdu as pdu
from isis_simulator.isis_topology import mac_bytes, L1_MULTICAST_MAC, L2_MULTICAST_MAC
from isis_simulator.pcap_writer import PcapWriter
from isis_simulator.verify import read_pcap, decode_packet

def now():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def generate_case(output_dir):
    output_dir=Path(output_dir)
    (output_dir/"pcapng").mkdir(parents=True,exist_ok=True)
    (output_dir/"logs").mkdir(parents=True,exist_ok=True)
    INPUT=output_dir
    EVIDENCE=output_dir
    # Wall-clock timestamps match the human-readable log and state snapshots.
    base_dt = datetime(2026,10,14,14,30,0,tzinfo=ZoneInfo('Asia/Shanghai'))
    base = int(base_dt.timestamp()*1e6)
    frames = []
    for start, duration, fault in [(0,30,False),(40,30,True)]:
        for node, offset, interval in [(1,0,3),(2,1.5,3),(3,2,9),(4,2,9)]:
            t = start + offset
            while t < start + duration:
                is_l1 = fault and node == 2
                fn = pdu.build_l1_lan_iih if is_l1 else pdu.build_l2_lan_iih
                body = bytearray(fn(node,27))
                body[19] = 64  # LAN IIH priority is an unshifted octet.
                if not fault and node in [1,2]:
                    body.extend(pdu.tlv(6, mac_bytes(2 if node==1 else 1)))
                    body[17:19] = struct.pack('>H',len(body))
                payload = b'\xfe\xfe\x03' + bytes(body)
                frame = (L1_MULTICAST_MAC if is_l1 else L2_MULTICAST_MAC) + mac_bytes(node) + struct.pack('>H',len(payload)) + payload
                frames.append((base+int(t*1e6),frame.ljust(60,b'\0')))
                t += interval
        for seq in range(10):
            t = start + 0.5 + seq*3
            frames.append((base+int(t*1e6),pdu.build_icmp_echo(1,2,seq+start,src_ip='10.10.1.1',dst_ip='10.20.2.1')))
            if not fault:
                frames.append((base+int((t+0.008)*1e6),pdu.build_icmp_echo_reply(2,1,seq+start,src_ip='10.20.2.1',dst_ip='10.10.1.1')))
    with PcapWriter(str(INPUT/'pcapng/link-observation.pcap')) as writer:
        for ts, frame in sorted(frames): writer.write_packet(frame,ts)
    log = '\n'.join([
        'Oct 14 14:30:02 R01 ISIS: Adjacency to R02 on Gig0/0/0 is UP',
        'Oct 14 14:30:03 R02 ISIS: Adjacency to R01 on Gig0/0/0 is UP',
        'Oct 14 14:30:28 R01 MONITOR: Ping to 10.20.2.1: 0% packet loss',
        'Oct 14 14:30:40 R02 CONFIG: Configuration commit completed, revision 1042',
        'Oct 14 14:30:40 R02 ISIS: Adjacency to R01 on Gig0/0/0 is Down, local configuration changed',
        'Oct 14 14:30:44 R01 MONITOR: Probe to 10.20.2.1 timed out',
        'Oct 14 14:30:55 R01 ISIS: Adjacency to R02 on Gig0/0/0 is Down, neighbor hold time expired',
        'Oct 14 14:31:09 R01 MONITOR: Ping to 10.20.2.1: 100% packet loss',
    ])+'\n'
    (INPUT/'logs/device-events.log').write_text(log,encoding='utf-8')
    state = {
        'schema':'isis-observation-v1','data_origin':'synthetic_demo',
        'captured_at':'2026-10-14T14:31:09+08:00',
        'observation':'R01–R02 邻接中断；R01 到 R02 业务环回地址 10.20.2.1 的探测连续无应答。',
        'topology':{'link':['R01:Gig0/0/0','R02:Gig0/0/0'],'system_ids':{'R01':'000000000001','R02':'000000000002','R03':'000000000003','R04':'000000000004'},'service_target':'10.20.2.1'},
        'snapshots':[]
    }
    for stage,at,changed in [('before','14:30:25',False),('fault','14:31:05',True)]:
        nodes=[]
        for node in ['R01','R02']:
            level = 'level-1' if node=='R02' and changed else 'level-2-only'
            nodes.append({'node':node,'interface':'Gig0/0/0','physical_state':'UP','crc_errors':0,'input_errors':0,'mtu':1500,'authentication':'disabled','area_address':'49.0001',
                          'process_is_type':level,'interface_circuit_type':level,'neighbor': 'R02' if node=='R01' else 'R01','adjacency':'DOWN' if changed else 'UP','revision':1042 if node=='R02' and changed else 1041})
        state['snapshots'].append({'stage':stage,'at':f'2026-10-14T{at}+08:00','nodes':nodes,'route_to_10_20_2_1':'absent' if changed else 'via R02, IS-IS L2'})
    save(INPUT/'network-state.json',state)
    save(EVIDENCE/'incident.json',{'id':'INC-20261014-017','title':'R01–R02 邻接中断，业务探测无应答','reported_at':'2026-10-14T14:31:09+08:00','description':state['observation'],'source':'合成报障记录','status':'待诊断；此记录不包含根因'})
    packets=[]
    for i,(ts,frame,stage) in enumerate(read_pcap(str(INPUT/'pcapng/link-observation.pcap')),1):
        d=decode_packet(frame)
        packets.append({'frame':i,'relative_s':round((ts-base)/1e6,3),'stage':stage,'size':len(frame),**{k:v for k,v in d.items() if k!='tlvs'}})
    save(EVIDENCE/'packets.json',packets)
    save(EVIDENCE/'generation.json',{'generated_at':now(),'source':'isis_simulator.scenarios.adjacency_incident','synthetic':True,'encapsulation':'IEEE 802.3 + LLC FE FE 03; Ethernet IPv4/ICMP','capture_start':base_dt.isoformat(),'windows':{'before':[0,30],'fault':[40,70]},'recovery_capture':False,'packet_count':len(frames),'note':'受控合成报文与设备状态用于功能演示，未连接或操作真实网络设备。'})
    return str(INPUT/'pcapng/link-observation.pcap'),len(frames),str(INPUT/'logs/device-events.log')
