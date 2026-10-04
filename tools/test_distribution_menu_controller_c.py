#!/usr/bin/env python3
"""Fresh whole original distribution menus versus readable C, with real keys.

Direct CFA8 and installed-provider D9D2 calls are separately labeled prepared
entries. Each native entry is assigned once; only independent authored RAM,
physical packets and timer readiness reach C. Whole RAM/MMIO and callbacks
are compared outside actually written native CPU-frame bytes. No original
menu outcome, partial RAM or returned byte is transplanted into C.
"""
import argparse
import ctypes as C
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import zlib
from c_build_inputs import implementation_inputs
from nxu8.machine import Machine
from test_runtime_parameter_c import Platform,initial

ROOT=Path(__file__).resolve().parents[1]
FIXTURE='analysis/native-fixtures/distribution-menu/inputs.json'
SUPPORT=['tools/distribution_menu_support/adapter.c','tools/distribution_menu_support/native.c']
SOURCE='csrc/ui/fx_distribution_menu_controller.c'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def seed(rom,row):
    image=bytearray(initial(rom,dict(mode=row.get('mode',12),context=row.get('context',18 if row['page']==58 else 9),math=row.get('math',1))))
    values={0x80fa:6,0x80fb:3,0x80f5:1,0x80f7:1,0x80de:row.get('rows',3),
        0x80df:row.get('reserved',1),0x811c:row.get('top',2),
        0x811d:row.get('part',1),0x811e:2,0x8137:row['flag'],
        0x8109:row.get('frequency',0),0x812a:0xaa}
    for a,v in values.items():image[a]=v
    image[0x81b8:0x821c]=bytes([0xad])*100
    image[0x82ee:0x860e]=bytes((i*37+11)&255 for i in range(800))
    image[0x82ed]=0x69;image[0x860e]=0x96
    return bytes(image)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir',type=Path)
    ap.add_argument('--fixture',type=Path)
    ap.add_argument('--optimization',choices=('O2','O3'))
    ap.add_argument('--candidate-root',type=Path)
    a=ap.parse_args()
    if sys.flags.optimize:ap.error('Optimized Python disables assertions')
    if (a.fixture or a.optimization or a.candidate_root) and not a.output_dir:ap.error('Custom runs require private --output-dir')
    candidate=a.candidate_root.resolve() if a.candidate_root else ROOT
    out=(a.output_dir or ROOT/'analysis/build/distribution-menu-controller'/uuid.uuid4().hex).resolve()
    if out.is_relative_to(ROOT/'analysis/c-verification'):ap.error('Private runs cannot replace canonical reports')
    fp=a.fixture.resolve() if a.fixture else ROOT/FIXTURE
    fixture_bytes=fp.read_bytes();fixture=json.loads(fixture_bytes)
    assert set(fixture)=={'schema','scope','rows','mode12_initialization'} and fixture['schema']==1
    for row in fixture['mode12_initialization']:
        assert set(row)=={'flag','mode'} and type(row['flag'])is int and 0<=row['flag']<=255
    for row in fixture['rows']:
        assert {'label','page','flag','keys'}<=set(row)<={'label','page','flag','keys','mode','context','math','wrapped','rows','reserved','top','part','frequency'}
        assert type(row['page'])is int and 0<=row['page']<=255
        for key in row['keys']:
            assert key is None or type(key)is int and 0<key<256 or isinstance(key,dict) and set(key)=={'pair'} and key['pair'][1]==128 and key['pair'][0] in (16,32,64,128)
    cmake=(candidate/'csrc/CMakeLists.txt').read_bytes()
    sources=['csrc/'+p for p in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',cmake.decode().split('target_include_directories')[0])]
    sources=list(dict.fromkeys(sources+[SOURCE]))
    inputs=SUPPORT+['tools/parameter_menu_oracle.c',
        'tools/test_runtime_parameter_c.py','tools/c_build_inputs.py','tools/nxu8/machine.py',
        'tools/nxu8/harness.c','tools/nxu8/isa.txt','tools/nxu8/vendor/SimU8/core.c',
        'firmware/fx-991es-plus-c-ver4.bin','analysis/disassembly/complete.asm',
        str(Path(__file__).resolve().relative_to(ROOT))]
    inputs += [str(p.relative_to(ROOT)) for p in (ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
    paths=[ROOT/p for p in inputs]+[candidate/p for p in implementation_inputs(candidate,sources)]+[candidate/'csrc/CMakeLists.txt',fp]
    pins={str(p):sha(p) for p in sorted(set(paths))}
    assert pins[str(candidate/'csrc/CMakeLists.txt')]==hashlib.sha256(cmake).hexdigest()
    assert pins[str(fp)]==hashlib.sha256(fixture_bytes).hexdigest()
    out.mkdir(parents=True,exist_ok=False);(out/'tmp').mkdir();os.environ['TMPDIR']=str(out/'tmp')
    (out/'inputs.json').write_bytes(fixture_bytes)
    report=dict(status='running',scope=__doc__,full_firmware_complete=False,
        source_sha256_pre=pins,rows=[],checkpoints=[],original_calls=0,
        comparisons=0,guards=0,complete=0,main=0,pending=0,resets=0,exports=0,timers=0,
        ordered_initialization=[],compiled_sources=[str(candidate/p) for p in sources])
    artifacts={}
    def stable():assert all(sha(ROOT/p if not Path(p).is_absolute() else p)==h for p,h in pins.items()),'Source attribution drift'
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rd=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    raw={rom[0x7fe+8*c+r]:(1<<c,1<<r) for c in range(8) for r in range(8)}
    try:
        for opt in ([a.optimization] if a.optimization else ('O2','O3')):
            stable();so=out/('controller-'+opt+'.so')
            subprocess.run(['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined','-Wl,--wrap=fx_data_write','-I',str(candidate/'csrc'),*[str(candidate/p) for p in sources],str(ROOT/SUPPORT[0]),'-o',str(so)],check=True)
            lib=C.CDLL(str(so));artifacts[str(so)]=sha(so)
            lib.distribution_state_size.restype=C.c_size_t
            lib.distribution_abi.argtypes=[C.c_uint];lib.distribution_abi.restype=C.c_size_t
            lib.distribution_begin.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_uint8,C.c_uint8]
            for name in ('tick','timer'):getattr(lib,'distribution_'+name).argtypes=[C.POINTER(Platform),C.c_void_p]
            lib.distribution_finish.argtypes=[C.c_void_p,C.POINTER(C.c_uint8)]
            for name in ('export','period'):getattr(lib,'distribution_'+name).argtypes=[C.c_void_p]
            lib.distribution_field.argtypes=[C.c_void_p,C.c_uint]
            lib.distribution_main_complete.argtypes=[C.POINTER(Platform),C.c_uint8,C.POINTER(C.c_uint8),C.POINTER(C.c_uint8)]
            lib.distribution_initialize_mode12.argtypes=[C.POINTER(Platform)]
            lib.fx_take_callback.argtypes=[C.POINTER(Platform)];lib.fx_take_callback.restype=C.c_uint8
            abi=[C.sizeof(Platform),*[getattr(Platform,n).offset for n in ('rom','rom_size','ram','callback_pending','status')]]
            assert abi==[lib.distribution_abi(i) for i in range(len(abi))];report['guards']+=len(abi)
            nd=out/('cpu-'+opt);m=Machine(rom,nd);ns=out/('original-'+opt+'.so')
            subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(ROOT/SUPPORT[1]),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(ns)],check=True)
            n=C.CDLL(str(ns));artifacts[str(ns)]=sha(ns);artifacts[str(nd/'nxu8-harness.so')]=sha(nd/'nxu8-harness.so')
            for name in ('harness_init','harness_set_pc','harness_get_pc','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_ram','harness_run'):
                getattr(n,name).argtypes=getattr(m.lib,name).argtypes;getattr(n,name).restype=getattr(m.lib,name).restype
            n.harness_callback.restype=C.c_uint32;n.parameter_menu_observe.argtypes=[C.c_uint64,C.c_int,C.c_int]
            n.distribution_original_to.argtypes=[C.c_uint32,C.c_uint64]
            m.lib=n;m.ram=n.harness_ram().contents;mask=(C.c_uint8*65536).in_dll(n,'parameter_menu_frame_mask')
            for row in fixture['rows']:
                wrapped=row.get('wrapped',0);image=seed(rom,row)
                ram=(C.c_uint8*65536).from_buffer_copy(image);p=Platform(rd,len(rom),ram,0,0)
                state=C.create_string_buffer(lib.distribution_state_size())
                m.reset();C.memmove(m.ram,image,65536);n.harness_set_sp(0x8dee);n.harness_set_lr(0x2fffe)
                n.harness_set_pc(0xd9d2 if wrapped else 0xcfa8);m.reg(0,row['page']);m.reg(5,1);m.reg(4,0)
                n.parameter_menu_observer_clear();report['original_calls']+=1;events=[]
                def skip():assert n.harness_run(1,0x2fffe,False)==103
                def to(pc):
                    if n.harness_get_pc()==pc:skip()
                    assert n.distribution_original_to(pc,3000000)==100,(row['label'],hex(pc),hex(n.harness_get_pc()))
                def compare(label,status,native_stop):
                    actual=bytes(ram);expected=bytes(m.ram)
                    diffs=[i for i in range(65536) if actual[i]!=expected[i] and not mask[i]]
                    nc=n.harness_callback();cc=lib.fx_take_callback(C.byref(p))
                    observation=dict(label=row['label']+':'+label,optimization=opt,status=status,native_stop=native_stop,native_pc=n.harness_get_pc(),differences=diffs,native_callback=nc,c_callback=cc,candidate_ram_zlib_hex=zlib.compress(actual).hex(),native_ram_zlib_hex=zlib.compress(expected).hex(),frame_mask_zlib_hex=zlib.compress(bytes(mask)).hex())
                    report['checkpoints'].append(observation);report['comparisons']+=1
                    assert not diffs,(observation['label'],[(hex(i),actual[i],expected[i]) for i in diffs[:20]])
                    assert nc==cc,(observation['label'],'callback',nc,cc)
                    events.append({k:v for k,v in observation.items() if not k.endswith('zlib_hex')})
                def release():ram[0x8e01]=ram[0x8e02]=m.ram[0x8e01]=m.ram[0x8e02]=0
                status=lib.distribution_begin(C.byref(p),state,row['page'],wrapped)
                if status==5:
                    assert wrapped and n.parameter_menu_observe(3000000,0,1)==300 and n.harness_get_pc()==0xceb0
                    assert [lib.distribution_field(state,i) for i in (5,6,7)]==[1,m.reg(0),m.reg(1)]
                    compare('real-unowned-child-arrival',status,300);old=bytes(ram)
                    for _ in range(3):
                        assert lib.distribution_tick(C.byref(p),state)==5 and lib.distribution_timer(C.byref(p),state)==5
                        assert lib.distribution_finish(state,None)==-1 and bytes(ram)==old;report['guards']+=1
                    report['pending']+=1
                else:
                    assert status==0 and n.parameter_menu_observe(3000000,0,0)==200
                    compare('whole-entry',status,200)
                    old=bytes(ram);assert lib.distribution_finish(state,None)==-1 and bytes(ram)==old;report['guards']+=1
                    for i,key in enumerate(row['keys']):
                        assert status in (0,3),(row['label'],i,status)
                        pair=tuple(key['pair']) if isinstance(key,dict) else (0,0) if key is None else raw[key]
                        for addr,v in zip((0x8e01,0x8e02),pair):ram[addr]=m.ram[addr]=v
                        status=lib.distribution_tick(C.byref(p),state)
                        if key is None:to(0x1d8a6);skip();to(0x1d8d2);stop=204
                        else:skip();stop=n.parameter_menu_observe(3000000,0,0)
                        if status==0:assert stop==(204 if key is None else 200)
                        compare('physical-key-'+str(i),status,stop);release()
                        if status==3:
                            assert stop==200 and lib.distribution_export(state)==(1 if pair[0]==32 else 7);report['exports']+=1
                        elif status==2:
                            assert stop==203 and lib.distribution_export(state)==1;report['resets']+=1
                        elif status==4:
                            assert stop==202 and lib.distribution_period(state)==0x770
                            old=bytes(ram);assert lib.distribution_tick(C.byref(p),state)==4 and bytes(ram)==old;report['guards']+=1
                            status=lib.distribution_timer(C.byref(p),state);skip();stop=n.parameter_menu_observe(3000000,0,0)
                            if status==0:assert stop==200
                            compare('actual-timer-ready-'+str(i),status,stop);report['timers']+=1
                    returned=None
                    if status==1:
                        assert stop==(250 if wrapped else 100),(row['label'],'terminal',stop)
                        byte=C.c_uint8();assert lib.distribution_finish(state,C.byref(byte))==1 and byte.value==m.reg(0)
                        returned=byte.value;report['complete']+=1
                        assert lib.distribution_export(state)==0 and lib.distribution_tick(C.byref(p),state)==-1;report['guards']+=1
                        if wrapped:
                            last=C.c_uint8();wait=C.c_uint8()
                            assert lib.distribution_main_complete(C.byref(p),byte.value,C.byref(last),C.byref(wait))==1
                            to(0xd980);compare('actual-provider-caller-completion',1,100)
                            assert (last.value,wait.value)==(m.reg(4),m.reg(5));report['main']+=1
                    else:
                        assert status==2 and stop==203,(row['label'],'unfinished',status,stop)
                        assert lib.distribution_finish(state,None)==2
                    events.append(dict(returned=returned))
                report['rows'].append(dict(input=row,optimization=opt,events=events))
            for control in fixture['mode12_initialization']:
                row=dict(label='mode12-order-'+str(control['mode'])+'-'+str(control['flag']),page=57,**control)
                image=bytearray(seed(rom,row))
                for addr,value in {0x8101:6,0x8100:7,0x8130:8,0x80fd:91,0x80fe:119,0x811c:0,0x811d:255,0x811e:200}.items():image[addr]=value
                ram=(C.c_uint8*65536).from_buffer_copy(image);p=Platform(rd,len(rom),ram,0,0);events=[]
                m.reset();C.memmove(m.ram,bytes(image),65536);n.harness_set_sp(0x8dee);n.harness_set_lr(0x2fffe);n.harness_set_pc(0x1df7e)
                n.parameter_menu_observer_clear();n.distribution_original_order_begin()
                lib.distribution_initialize_mode12(C.byref(p));to(0x2fffe);report['original_calls']+=1
                compare('ordered-dependency',0,100)
                ccount=C.c_uint.in_dll(lib,'distribution_c_order_count').value
                ncount=C.c_uint.in_dll(n,'distribution_native_order_count').value
                ca=(C.c_uint16*64).in_dll(lib,'distribution_c_order_address');cv=(C.c_uint8*64).in_dll(lib,'distribution_c_order_value')
                na=(C.c_uint16*64).in_dll(n,'distribution_native_order_address');nv=(C.c_uint8*64).in_dll(n,'distribution_native_order_value')
                candidate_writes=[(ca[i],cv[i]) for i in range(ccount)];native_writes=[(na[i],nv[i]) for i in range(ncount)]
                report['ordered_initialization'].append(dict(input=control,optimization=opt,candidate_writes=candidate_writes,native_writes=native_writes))
                assert ccount<64 and ncount<64 and candidate_writes==native_writes,(row['label'],candidate_writes,native_writes)
                report['guards']+=1
            stable()
        report['status']='pass'
    except Exception as error:
        report['status']='failed';report['failure']=repr(error);raise
    finally:
        post={p:sha(ROOT/p if not Path(p).is_absolute() else p) for p in pins}
        artifact_post={p:sha(p) for p in artifacts}
        report.update(source_sha256_post=post,source_drift=pins!=post,artifact_sha256_pre=artifacts,artifact_sha256_post=artifact_post,artifact_drift=artifact_post!=artifacts,completed_utc=datetime.now(timezone.utc).isoformat())
        if report['source_drift'] or report['artifact_drift']:report['status']='failed'
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','original_calls','comparisons','guards','complete','main','pending','resets','exports','timers')}))
    return 0 if report['status']=='pass' else 1
if __name__=='__main__':raise SystemExit(main())
