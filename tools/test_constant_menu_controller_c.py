#!/usr/bin/env python3
"""Fresh D312, D3B6/D3EE and installed-provider D9D2 menu comparisons.

Prepared entry is assigned once per native call. Original CPU execution is
unmodified; authored RAM, physical packets and timer readiness are the only
shared inputs. Whole RAM/MMIO and callback comparisons exclude only individual
bytes actually written in live native CPU frames. Boot, raw MAIN admission and
following token insertion/evaluation are outside this standalone child proof.
"""
import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib,json,os,re,subprocess,sys,uuid,zlib
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'firmware/fx-991es-plus-c-ver4.bin').exists())
SOURCE=Path(__file__).resolve().parents[1]
if (SOURCE/'fx_constant_menu_controller.c').exists():
    SUPPORT=SOURCE/'support'
    DEFAULT_FIXTURE=SOURCE/'fixtures/inputs.json'
else:
    SOURCE=ROOT/'csrc/ui'
    SUPPORT=ROOT/'tools/constant_menu_support'
    DEFAULT_FIXTURE=ROOT/'analysis/native-fixtures/constant-menu/inputs.json'
sys.path.insert(0,str(ROOT/'tools'))
from c_build_inputs import implementation_inputs
from nxu8.machine import Machine
from test_runtime_parameter_c import Platform,initial

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir',type=Path)
    ap.add_argument('--fixture',type=Path)
    ap.add_argument('--optimization',choices=('O2','O3'))
    a=ap.parse_args()
    if sys.flags.optimize:ap.error('Optimized Python disables differential checks')
    if (a.fixture or a.optimization) and not a.output_dir:ap.error('Custom runs require private --output-dir')
    out=(a.output_dir or ROOT/'analysis/build/constant-conversion-menu'/uuid.uuid4().hex).resolve()
    fp=(a.fixture or DEFAULT_FIXTURE).resolve()
    fixture_bytes=fp.read_bytes();fixture=json.loads(fixture_bytes)
    assert set(fixture)=={'schema','entry_scope','rows'} and fixture['schema']==1
    assert fixture['entry_scope']=='prepared-D312/D3B6/D3EE/D9D2-once-no-boot-claim'
    if not a.fixture:assert len(fixture['rows'])==344
    labels=set()
    for row in fixture['rows']:
        assert {'label','entry','trigger','keys'}<=set(row)<={'label','entry','trigger','keys','mode','context','math','phase'}
        assert row['label'] not in labels;labels.add(row['label'])
        assert type(row['entry'])is int and 0<=row['entry']<=3
        assert type(row['trigger'])is int and row['trigger'] in (6,7)
        assert all(type(k)is int and 0<k<256 or isinstance(k,dict) and set(k)=={'pair'} and k['pair'][1]==128 and k['pair'][0] in (16,32,64,128) for k in row['keys'])
    cmake=(ROOT/'csrc/CMakeLists.txt').read_bytes()
    sources=list(dict.fromkeys('csrc/'+x for x in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',cmake.decode().split('target_include_directories')[0])))
    compiled_sources=list(dict.fromkeys([ROOT/p for p in sources]+[SOURCE/'fx_constant_menu_controller.c']))
    files=[ROOT/p for p in implementation_inputs(ROOT,sources)]
    files+=[ROOT/p for p in ('csrc/CMakeLists.txt','tools/parameter_menu_oracle.c','tools/c_build_inputs.py','tools/test_runtime_parameter_c.py','tools/nxu8/machine.py','tools/nxu8/harness.c','tools/nxu8/isa.txt','tools/nxu8/vendor/SimU8/core.c','firmware/fx-991es-plus-c-ver4.bin','analysis/disassembly/complete.asm')]
    files+=list((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h'))
    files+=[SOURCE/'fx_constant_menu_controller.c',SOURCE/'fx_constant_menu_controller.h',SUPPORT/'adapter.c',SUPPORT/'native.c',Path(__file__).resolve(),fp]
    pins={str(p):sha(p) for p in sorted(set(files))}
    assert pins[str(fp)]==hashlib.sha256(fixture_bytes).hexdigest()
    assert pins[str(ROOT/'csrc/CMakeLists.txt')]==hashlib.sha256(cmake).hexdigest()
    out.mkdir(parents=True,exist_ok=False);(out/'tmp').mkdir();os.environ['TMPDIR']=str(out/'tmp')
    (out/'inputs.json').write_bytes(fixture_bytes)
    report=dict(status='running',scope=__doc__,full_firmware_complete=False,original_calls=0,comparisons=0,guards=0,complete=0,main=0,resets=0,exports=0,timers=0,prefixes=0,rows=[],checkpoints=[],source_sha256_pre=pins)
    artifacts={}
    def stable():assert all(sha(p)==h for p,h in pins.items()),'Source attribution drift'
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rd=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    raw={rom[0x7fe+8*c+r]:(1<<c,1<<r) for c in range(8) for r in range(8)}
    try:
        for opt in ([a.optimization] if a.optimization else ('O2','O3')):
            stable();so=out/('controller-'+opt+'.so')
            subprocess.run(['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined','-I',str(ROOT/'csrc'),'-I',str(SOURCE),*[str(p) for p in compiled_sources],str(SUPPORT/'adapter.c'),'-o',str(so)],check=True)
            lib=C.CDLL(str(so));artifacts[str(so)]=sha(so)
            lib.constant_state_size.restype=C.c_size_t
            lib.constant_abi.argtypes=[C.c_uint];lib.constant_abi.restype=C.c_size_t
            lib.constant_begin.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_uint8,C.c_uint8]
            for method in ('tick','timer'):getattr(lib,'constant_'+method).argtypes=[C.POINTER(Platform),C.c_void_p]
            lib.constant_finish.argtypes=[C.c_void_p,C.POINTER(C.c_uint8)]
            for method in ('export','period'):getattr(lib,'constant_'+method).argtypes=[C.c_void_p]
            lib.constant_unknown_service.argtypes=[C.POINTER(Platform),C.c_uint8]
            lib.constant_main_complete.argtypes=[C.POINTER(Platform),C.c_uint8,C.POINTER(C.c_uint8),C.POINTER(C.c_uint8)]
            lib.fx_take_callback.argtypes=[C.POINTER(Platform)];lib.fx_take_callback.restype=C.c_uint8
            abi=[C.sizeof(Platform),*[getattr(Platform,name).offset for name in ('rom','rom_size','ram','callback_pending','status')]]
            assert abi==[lib.constant_abi(i) for i in range(len(abi))];report['guards']+=len(abi)
            nd=out/('cpu-'+opt);m=Machine(rom,nd);ns=out/('original-'+opt+'.so')
            subprocess.run(['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(ROOT/'tools'),str(SUPPORT/'native.c'),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(ns)],check=True)
            n=C.CDLL(str(ns));artifacts[str(ns)]=sha(ns);artifacts[str(nd/'nxu8-harness.so')]=sha(nd/'nxu8-harness.so')
            for name in ('harness_init','harness_set_pc','harness_get_pc','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_ram','harness_run'):
                getattr(n,name).argtypes=getattr(m.lib,name).argtypes;getattr(n,name).restype=getattr(m.lib,name).restype
            n.harness_callback.restype=C.c_uint32;n.constant_original_observe.argtypes=[C.c_uint64];n.constant_original_to.argtypes=[C.c_uint32,C.c_uint64]
            m.lib=n;m.ram=n.harness_ram().contents;mask=(C.c_uint8*65536).in_dll(n,'parameter_menu_frame_mask')
            for row in fixture['rows']:
                entry=row['entry'];trigger=row['trigger']
                image=bytearray(initial(rom,dict(mode=row.get('mode',193),context=row.get('context',1),math=row.get('math',1),phase=row.get('phase',1))))
                image[0x80f5]=trigger;image[0x80f7]=1
                ram=(C.c_uint8*65536).from_buffer_copy(image);p=Platform(rd,len(rom),ram,0,0)
                state=C.create_string_buffer(lib.constant_state_size())
                m.reset();C.memmove(m.ram,bytes(image),65536);n.harness_set_sp(0x8dee);n.harness_set_lr(0x2fffe)
                n.harness_set_pc((0xd312,0xd3b6,0xd3ee,0xd9d2)[entry]);m.reg(0,trigger);m.reg(5,1);m.reg(4,0)
                n.parameter_menu_observer_clear();report['original_calls']+=1;events=[]
                def skip():assert n.harness_run(1,0x2fffe,False)==103
                def to(pc):
                    if n.harness_get_pc()==pc:skip()
                    assert n.constant_original_to(pc,3000000)==100,(row['label'],hex(pc),hex(n.harness_get_pc()))
                def compare(label,status,stop):
                    actual=bytes(ram);expected=bytes(m.ram)
                    diffs=[i for i in range(65536) if actual[i]!=expected[i] and not mask[i]]
                    nc=n.harness_callback();cc=lib.fx_take_callback(C.byref(p))
                    checkpoint=dict(label=row['label']+':'+label,optimization=opt,status=status,native_stop=stop,native_pc=n.harness_get_pc(),differences=diffs,native_callback=nc,c_callback=cc,candidate_ram_zlib_hex=zlib.compress(actual).hex(),native_ram_zlib_hex=zlib.compress(expected).hex(),frame_mask_zlib_hex=zlib.compress(bytes(mask)).hex())
                    report['checkpoints'].append(checkpoint);report['comparisons']+=1
                    assert not diffs,(checkpoint['label'],[(hex(i),actual[i],expected[i]) for i in diffs[:20]])
                    assert nc==cc,(checkpoint['label'],'callback',nc,cc)
                    events.append({k:v for k,v in checkpoint.items() if not k.endswith('zlib_hex')})
                status=lib.constant_begin(C.byref(p),state,entry,trigger);stop=n.constant_original_observe(3000000)
                assert (status,stop) in ((0,200),(1,100),(1,250)),(row['label'],'entry',status,stop)
                compare('whole-entry',status,stop)
                if status==0:
                    old=bytes(ram);assert lib.constant_finish(state,None)==-1 and bytes(ram)==old;report['guards']+=1
                for i,key in enumerate(row['keys']):
                    assert status in (0,3),(row['label'],i,status)
                    pair=tuple(key['pair']) if isinstance(key,dict) else raw[key]
                    for addr,v in zip((0x8e01,0x8e02),pair):ram[addr]=m.ram[addr]=v
                    status=lib.constant_tick(C.byref(p),state);skip();stop=n.constant_original_observe(3000000)
                    assert (status,stop) in ((0,200),(1,100),(1,250),(2,203),(3,200),(4,202)),(row['label'],i,status,stop)
                    compare('physical-key-'+str(i),status,stop)
                    ram[0x8e01]=ram[0x8e02]=m.ram[0x8e01]=m.ram[0x8e02]=0
                    if status==3:
                        assert lib.constant_export(state)==(1 if pair[0]==32 else 7);report['exports']+=1
                    elif status==2:
                        assert lib.constant_export(state)==1;report['resets']+=1
                    elif status==4:
                        assert lib.constant_period(state)==0x129a
                        old=bytes(ram);assert lib.constant_tick(C.byref(p),state)==4 and bytes(ram)==old;report['guards']+=1
                        status=lib.constant_timer(C.byref(p),state);skip();stop=n.constant_original_observe(3000000)
                        assert (status,stop) in ((1,100),(1,250)),(row['label'],'timer',status,stop)
                        compare('actual-timer-ready-'+str(i),status,stop);report['timers']+=1
                returned=None
                if status==1:
                    byte=C.c_uint8();assert lib.constant_finish(state,C.byref(byte))==1 and byte.value==m.reg(0)
                    returned=byte.value;report['complete']+=1
                    assert lib.constant_export(state)==0 and lib.constant_tick(C.byref(p),state)==-1;report['guards']+=1
                    if entry==3:
                        assert stop==250
                        last=C.c_uint8();wait=C.c_uint8()
                        assert lib.constant_main_complete(C.byref(p),byte.value,C.byref(last),C.byref(wait))==1
                        to(0xd980);compare('actual-provider-caller-completion',1,100)
                        assert (last.value,wait.value)==(m.reg(4),m.reg(5));report['main']+=1
                elif status==2:assert lib.constant_finish(state,None)==2
                else:
                    assert status==0
                    report['prefixes']+=1
                    # WAIT ticks are real keyboard polls: they start129A and
                    # increment8224, so they are not no-write host guards.
                    for idle in range(3):
                        assert lib.constant_tick(C.byref(p),state)==0
                        to(0x1d8a6);skip();to(0x1d8d2)
                        compare('actual-idle-poll-'+str(idle),0,204)
                    old=bytes(ram)
                    assert lib.constant_finish(state,None)==-1
                    assert lib.constant_timer(C.byref(p),state)==-1 and bytes(ram)==old
                    report['guards']+=1
                events.append(dict(returned=returned));report['rows'].append(dict(input=row,optimization=opt,events=events))
            for kind in (0,1,2,5):
                image=initial(rom,dict(mode=193));ram=(C.c_uint8*65536).from_buffer_copy(image);p=Platform(rd,len(rom),ram,0,0)
                assert lib.constant_unknown_service(C.byref(p),kind)==5 and bytes(ram)==image;report['guards']+=1
            stable()
        report['status']='pass'
    except Exception as error:
        report['status']='failed';report['failure']=repr(error);raise
    finally:
        post={p:sha(p) for p in pins};artifact_post={p:sha(p) for p in artifacts}
        report.update(source_sha256_post=post,source_drift=pins!=post,artifact_sha256_pre=artifacts,artifact_sha256_post=artifact_post,artifact_drift=artifacts!=artifact_post,completed_utc=datetime.now(timezone.utc).isoformat())
        if report['source_drift'] or report['artifact_drift']:report['status']='failed'
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','original_calls','comparisons','guards','complete','main','resets','exports','timers','prefixes')}))
    return 0 if report['status']=='pass' else 1
if __name__=='__main__':raise SystemExit(main())
