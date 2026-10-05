#!/usr/bin/env python3
"""Fresh whole original STAT menus versus readable C, with real keys.

Direct CEB0 and installed-provider D9D2 calls are separately labeled prepared
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
FIXTURE='analysis/native-fixtures/statistics-menu/inputs.json'
SUPPORT=['tools/statistics_menu_support/adapter.c','tools/statistics_menu_support/native.c']
SOURCE='csrc/ui/fx_statistics_menu_controller.c'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def seed(rom,row):
    from test_distribution_menu_controller_c import seed as base_seed
    image=bytearray(base_seed(rom,dict(row,mode=row.get("mode",3),context=row.get("context",18 if row["page"]==29 else 1))))
    image[0x80fa]=row.get("old_kind",1)
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
    out=(a.output_dir or ROOT/'analysis/build/statistics-menu-controller'/uuid.uuid4().hex).resolve()
    if out.is_relative_to(ROOT/'analysis/c-verification'):ap.error('Private runs cannot replace canonical reports')
    fp=a.fixture.resolve() if a.fixture else ROOT/FIXTURE
    fixture_bytes=fp.read_bytes();fixture=json.loads(fixture_bytes)
    assert set(fixture)=={'schema','scope','rows'} and fixture['schema']==1
    for row in fixture['rows']:
        assert {'label','page','flag','keys'}<=set(row)<={'label','page','flag','keys','mode','context','math','wrapped','rows','reserved','top','part','frequency','constraint','old_kind'}
        assert type(row['page'])is int and 0<=row['page']<=255
        for key in row['keys']:
            assert key is None or type(key)is int and 0<key<256 or isinstance(key,dict) and set(key)=={'pair'} and key['pair'][1]==128 and key['pair'][0] in (16,32,64,128)
    cmake=(candidate/'csrc/CMakeLists.txt').read_bytes()
    sources=['csrc/'+p for p in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',cmake.decode().split('target_include_directories')[0])]
    sources=list(dict.fromkeys(sources+[SOURCE]))
    inputs=SUPPORT+['tools/parameter_menu_oracle.c',
        'tools/test_runtime_parameter_c.py','tools/test_distribution_menu_controller_c.py','tools/c_build_inputs.py','tools/nxu8/machine.py',
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
        compiled_sources=[str(candidate/p) for p in sources])
    artifacts={}
    def stable():assert all(sha(ROOT/p if not Path(p).is_absolute() else p)==h for p,h in pins.items()),'Source attribution drift'
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rd=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    raw={rom[0x7fe+8*c+r]:(1<<c,1<<r) for c in range(8) for r in range(8)}
    try:
        for opt in ([a.optimization] if a.optimization else ('O2','O3')):
            stable();so=out/('controller-'+opt+'.so')
            subprocess.run(['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined','-I',str(candidate/'csrc'),*[str(candidate/p) for p in sources],str(ROOT/SUPPORT[0]),'-o',str(so)],check=True)
            lib=C.CDLL(str(so));artifacts[str(so)]=sha(so)
            lib.statistics_state_size.restype=C.c_size_t
            lib.statistics_abi.argtypes=[C.c_uint];lib.statistics_abi.restype=C.c_size_t
            lib.statistics_begin.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_uint8,C.c_uint8,C.c_uint8]
            for name in ('tick','timer'):getattr(lib,'statistics_'+name).argtypes=[C.POINTER(Platform),C.c_void_p]
            lib.statistics_finish.argtypes=[C.c_void_p,C.POINTER(C.c_uint8)]
            for name in ('export','period'):getattr(lib,'statistics_'+name).argtypes=[C.c_void_p]
            lib.statistics_field.argtypes=[C.c_void_p,C.c_uint]
            lib.statistics_main_complete.argtypes=[C.POINTER(Platform),C.c_uint8,C.POINTER(C.c_uint8),C.POINTER(C.c_uint8)]
            lib.fx_take_callback.argtypes=[C.POINTER(Platform)];lib.fx_take_callback.restype=C.c_uint8
            abi=[C.sizeof(Platform),*[getattr(Platform,n).offset for n in ('rom','rom_size','ram','callback_pending','status')]]
            assert abi==[lib.statistics_abi(i) for i in range(len(abi))];report['guards']+=len(abi)
            nd=out/('cpu-'+opt);m=Machine(rom,nd);ns=out/('original-'+opt+'.so')
            subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(ROOT/SUPPORT[1]),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(ns)],check=True)
            n=C.CDLL(str(ns));artifacts[str(ns)]=sha(ns);artifacts[str(nd/'nxu8-harness.so')]=sha(nd/'nxu8-harness.so')
            for name in ('harness_init','harness_set_pc','harness_get_pc','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_ram','harness_run'):
                getattr(n,name).argtypes=getattr(m.lib,name).argtypes;getattr(n,name).restype=getattr(m.lib,name).restype
            n.harness_callback.restype=C.c_uint32;n.parameter_menu_observe.argtypes=[C.c_uint64,C.c_int,C.c_int]
            n.statistics_original_to.argtypes=[C.c_uint32,C.c_uint64]
            m.lib=n;m.ram=n.harness_ram().contents;mask=(C.c_uint8*65536).in_dll(n,'parameter_menu_frame_mask')
            for row in fixture['rows']:
                wrapped=row.get('wrapped',0);image=seed(rom,row)
                ram=(C.c_uint8*65536).from_buffer_copy(image);p=Platform(rd,len(rom),ram,0,0)
                state=C.create_string_buffer(lib.statistics_state_size())
                m.reset();C.memmove(m.ram,image,65536);n.harness_set_sp(0x8dee);n.harness_set_lr(0x2fffe)
                n.harness_set_pc(0xd9d2 if wrapped else 0xceb0);m.reg(0,row['page']);m.reg(1,row.get('constraint',0));m.reg(5,1);m.reg(4,0)
                n.parameter_menu_observer_clear();report['original_calls']+=1;events=[]
                def skip():assert n.harness_run(1,0x2fffe,False)==103
                def to(pc):
                    if n.harness_get_pc()==pc:skip()
                    assert n.statistics_original_to(pc,3000000)==100,(row['label'],hex(pc),hex(n.harness_get_pc()))
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
                status=lib.statistics_begin(C.byref(p),state,row['page'],row.get('constraint',0),wrapped)
                if status==5:
                    assert wrapped and n.parameter_menu_observe(3000000,0,1)==300 and n.harness_get_pc()==0xcfa8
                    assert [lib.statistics_field(state,i) for i in (5,6,7)]==[2,m.reg(0),m.reg(1)]
                    compare('real-unowned-child-arrival',status,300);old=bytes(ram)
                    for _ in range(3):
                        assert lib.statistics_tick(C.byref(p),state)==5 and lib.statistics_timer(C.byref(p),state)==5
                        assert lib.statistics_finish(state,None)==-1 and bytes(ram)==old;report['guards']+=1
                    report['pending']+=1
                else:
                    assert status==0 and n.parameter_menu_observe(3000000,0,0)==200
                    compare('whole-entry',status,200)
                    old=bytes(ram);assert lib.statistics_finish(state,None)==-1 and bytes(ram)==old;report['guards']+=1
                    for i,key in enumerate(row['keys']):
                        assert status in (0,3),(row['label'],i,status)
                        pair=tuple(key['pair']) if isinstance(key,dict) else (0,0) if key is None else raw[key]
                        for addr,v in zip((0x8e01,0x8e02),pair):ram[addr]=m.ram[addr]=v
                        status=lib.statistics_tick(C.byref(p),state)
                        if key is None:to(0x1d8a6);skip();to(0x1d8d2);stop=204
                        else:skip();stop=n.parameter_menu_observe(3000000,0,0)
                        if status==0:assert stop==(204 if key is None else 200)
                        compare('physical-key-'+str(i),status,stop);release()
                        if status==3:
                            assert stop==200 and lib.statistics_export(state)==(1 if pair[0]==32 else 7);report['exports']+=1
                        elif status==2:
                            assert stop==203 and lib.statistics_export(state)==1;report['resets']+=1
                        elif status==4:
                            assert stop==202 and lib.statistics_period(state)==0x770
                            old=bytes(ram);assert lib.statistics_tick(C.byref(p),state)==4 and bytes(ram)==old;report['guards']+=1
                            status=lib.statistics_timer(C.byref(p),state);skip();stop=n.parameter_menu_observe(3000000,0,0)
                            if status==0:assert stop==200
                            compare('actual-timer-ready-'+str(i),status,stop);report['timers']+=1
                    returned=None
                    if status==1:
                        assert stop==(250 if wrapped else 100),(row['label'],'terminal',stop)
                        byte=C.c_uint8();assert lib.statistics_finish(state,C.byref(byte))==1 and byte.value==m.reg(0)
                        returned=byte.value;report['complete']+=1
                        assert lib.statistics_export(state)==0 and lib.statistics_tick(C.byref(p),state)==-1;report['guards']+=1
                        if wrapped:
                            last=C.c_uint8();wait=C.c_uint8()
                            assert lib.statistics_main_complete(C.byref(p),byte.value,C.byref(last),C.byref(wait))==1
                            to(0xd980);compare('actual-provider-caller-completion',1,100)
                            assert (last.value,wait.value)==(m.reg(4),m.reg(5));report['main']+=1
                    else:
                        assert status==2 and stop==203,(row['label'],'unfinished',status,stop)
                        assert lib.statistics_finish(state,None)==2
                    events.append(dict(returned=returned))
                report['rows'].append(dict(input=row,optimization=opt,events=events))
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
