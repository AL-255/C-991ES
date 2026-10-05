#!/usr/bin/env python3
"""Fresh integrated raw-key MAIN -> owned STAT/DIST/CONSTANT/CONVERSION -> MAIN.

The complete71 authored legacy inputs remain byte-for-byte in a separate
fixture. All67 authored DIST additions are also preserved byte-for-byte. New STAT and
CONSTANT/CONVERSION recipes enter through physical SHIFT/1, SHIFT/7 or SHIFT/8. This
does not re-label the prepared CFA8 child proof as runtime integration.

Prepared entry is original D7B4 with authored R5=1/R4=0, not a boot claim.
The matching C entry has named MAIN state only. Each native PC is set once;
after that only authored physical packets and timer readiness advance either
path. No native checkpoint, return value or CPU local is supplied to C.
"""
import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import zlib
SCRIPT_ROOT=Path(__file__).resolve().parents[1]
ROOT=SCRIPT_ROOT if (SCRIPT_ROOT/"tools/nxu8/machine.py").is_file() else Path.cwd().resolve()
sys.path.insert(0,str(ROOT/"tools"))
from c_build_inputs import implementation_inputs
from nxu8.machine import Machine

FIXTURE=SCRIPT_ROOT/'analysis/native-fixtures/runtime-parameter-services/inputs.json'
LEGACY=SCRIPT_ROOT/'analysis/native-fixtures/runtime-parameter-services/legacy-inputs.json'
DISTRIBUTION=SCRIPT_ROOT/'analysis/native-fixtures/runtime-parameter-services/distribution-inputs.json'
SUPPORT=[Path(__file__).resolve().parent/'runtime_parameter_services_support/adapter.c',
         Path(__file__).resolve().parent/'runtime_parameter_services_support/native.c']
class Platform(C.Structure):
    _fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),
        ('ram',C.POINTER(C.c_uint8)),('callback_pending',C.c_uint8),('status',C.c_int)]
class Pair(C.Structure):
    _fields_=[('columns',C.c_uint8),('rows',C.c_uint8)]
def digest(data):return hashlib.sha256(data).hexdigest()
def sha(path):return digest(Path(path).read_bytes())
def initial(rom,row):
    ram=bytearray(65536)
    ram[0x8dee:0x8e00]=rom[0x1f8be:0x1f8d0]
    values={0x80f9:row['mode'],0x80fa:row.get('submode',1),0x80fb:0,
        0x80fc:row.get('context',1),0x80fe:row.get('phase',1),0x80f5:0,
        0x80f7:0,0x811e:row.get('column',1),0x8105:4,
        0x8106:row.get('math',1),0x8112:17,0x8117:1,0x8119:1,
        0x811a:0x7c,0x811b:10,0x811f:10,0x8121:1,0xf040:255}
    for a,v in values.items():ram[a]=v
    ram[0x812c:0x8130]=bytes.fromhex('54815481')
    ram[0x8154]=0x31;ram[0x81b8]=0x32
    if 'distribution_seed' in row or 'statistics_seed' in row:
        d=row.get('distribution_seed',row.get('statistics_seed'))
        values={0x80fb:3,0x80de:d.get('rows',3),0x80df:d.get('reserved',1),
            0x811c:d.get('top',2),0x811d:d.get('part',1),0x811e:2,
            0x8137:d['flag'],0x8109:d.get('frequency',0),0x812a:0xaa}
        for a,v in values.items():ram[a]=v
        ram[0x81b8:0x821c]=bytes([0xad])*100
        ram[0x82ee:0x860e]=bytes((i*37+11)&255 for i in range(800))
        ram[0x82ed]=0x69;ram[0x860e]=0x96
    return bytes(ram)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir',type=Path)
    ap.add_argument('--fixture',type=Path)
    ap.add_argument('--candidate-root',type=Path)
    ap.add_argument('--optimization',choices=('O2','O3'))
    args=ap.parse_args()
    if sys.flags.optimize:ap.error('Optimized Python disables differential assertions')
    if (args.fixture or args.optimization or args.candidate_root) and not args.output_dir:
        ap.error('Custom inputs or single optimization require --output-dir')
    candidate=(args.candidate_root or SCRIPT_ROOT).resolve()
    out=(args.output_dir or ROOT/'analysis/build/parameter-services-runtime'/uuid.uuid4().hex).resolve()
    if out.is_relative_to(ROOT/'analysis/c-verification'):
        ap.error('Private proof cannot replace canonical reports')
    fp=args.fixture.resolve() if args.fixture else FIXTURE
    fixture_bytes=fp.read_bytes();fixture=json.loads(fixture_bytes)
    assert set(fixture)=={'schema','entry','legacy_sha256','legacy_recipes','distribution_sha256','distribution_recipes','rows'} and fixture['schema']==1
    legacy_bytes=LEGACY.read_bytes();legacy=json.loads(legacy_bytes)
    assert digest(legacy_bytes)==fixture['legacy_sha256']
    assert legacy_bytes==(ROOT/'analysis/native-fixtures/runtime-parameter/inputs.json').read_bytes()
    assert fixture['legacy_recipes']==71 and len(legacy['rows'])==71
    distribution_bytes=DISTRIBUTION.read_bytes();distribution=json.loads(distribution_bytes)
    assert digest(distribution_bytes)==fixture['distribution_sha256']
    assert distribution_bytes==(ROOT/'analysis/native-fixtures/runtime-distribution/inputs.json').read_bytes()
    assert fixture['distribution_recipes']==67 and len(distribution['rows'])==67
    additions=fixture['rows']
    fixture['rows']=legacy['rows']+distribution['rows']+additions
    assert fixture['entry']=='prepared-MAIN-D7B4-wait1-last0'
    for row in fixture['rows']:
        assert {'label','mode','opening','keys'}<=set(row)<={'label','mode','opening','keys','math','context','phase','column','submode','distribution_seed','statistics_seed','control'}
        assert row['opening'] and all(type(x)is int and 0<x<256 for x in row['opening'])
        assert all(x is None or type(x)is int and 0<x<256 or isinstance(x,dict) and set(x)=={'pair'} and x['pair'][1]==128 and x['pair'][0] in (16,32,64,128) for x in row['keys'])
    cmake_bytes=(candidate/'csrc/CMakeLists.txt').read_bytes()
    sources=['csrc/'+n for n in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',cmake_bytes.decode().split('target_include_directories')[0])]
    sources=list(dict.fromkeys(sources))
    inputs=[str(candidate/p) for p in implementation_inputs(candidate,sources)]+[
        'tools/parameter_menu_oracle.c','tools/c_build_inputs.py',
        'tools/nxu8/machine.py','tools/nxu8/harness.c','tools/nxu8/isa.txt',
        'tools/nxu8/vendor/SimU8/core.c','csrc/CMakeLists.txt',
        'firmware/fx-991es-plus-c-ver4.bin','analysis/disassembly/complete.asm',
        str(Path(__file__).resolve()),str(LEGACY),str(DISTRIBUTION),str(ROOT/'analysis/native-fixtures/runtime-distribution/inputs.json'),str(candidate/'csrc/CMakeLists.txt'),str(ROOT/'analysis/native-fixtures/runtime-parameter/inputs.json'),
        str(ROOT/'tools/test_runtime_parameter_c.py')] + [str(p) for p in SUPPORT]
    inputs += [str(p.relative_to(ROOT)) for p in (ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
    pins={p:sha(ROOT/p) for p in sorted(set(inputs))};pins[str(fp)]=sha(fp)
    assert pins[str(candidate/'csrc/CMakeLists.txt')]==digest(cmake_bytes) and pins[str(fp)]==digest(fixture_bytes)
    out.mkdir(parents=True,exist_ok=False);(out/'tmp').mkdir();os.environ['TMPDIR']=str(out/'tmp')
    (out/'inputs.json').write_bytes(fixture_bytes)
    report=dict(scope=__doc__,status='running',full_firmware_complete=False,
        source_sha256_pre=pins,rows=[],checkpoints=[],comparisons=0,guards=0,
        completed_main=0,pending=0,owned_prefixes=0,legacy_recipes=71,distribution_recipes=67,additional_recipes=len(additions),compiled_sources=[str(candidate/p) for p in sources],compiler_commands=[],zero_returns=0,ff_returns=0,successful_body_replies=0,resets=0,exports=0,timers=0,original_calls=0)
    artifacts={}
    def stable():
        assert all(sha(ROOT/p if not Path(p).is_absolute() else p)==h for p,h in pins.items()),'Source attribution drift'
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rd=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    raw={rom[0x7fe+8*c+r]:(1<<c,1<<r) for c in range(8) for r in range(8)}
    try:
        for opt in ([args.optimization] if args.optimization else ('O2','O3')):
            stable();so=out/('runtime-'+opt+'.so')
            command=['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined','-I',str(candidate/'csrc'),*[str(candidate/p) for p in sources],str(ROOT/SUPPORT[0]),'-o',str(so)]
            report['compiler_commands'].append(command)
            subprocess.run(command,check=True)
            lib=C.CDLL(str(so));artifacts[str(so)]=sha(so)
            lib.parameter_runtime_size.restype=C.c_size_t
            lib.parameter_runtime_abi.argtypes=[C.c_uint];lib.parameter_runtime_abi.restype=C.c_size_t
            lib.parameter_runtime_field.argtypes=[C.c_void_p,C.c_uint]
            lib.parameter_runtime_constant.argtypes=[C.c_uint]
            lib.parameter_runtime_target.argtypes=[C.c_void_p]
            lib.parameter_runtime_provider_custody.argtypes=[C.c_void_p]
            lib.parameter_runtime_main_entry.argtypes=[C.c_void_p]
            lib.fx_runtime_step.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_void_p,C.c_uint8]
            lib.fx_runtime_accept_body.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_uint8,C.c_uint8]
            lib.fx_runtime_submit_pair.argtypes=[C.POINTER(Platform),Pair]
            lib.fx_take_callback.argtypes=[C.POINTER(Platform)];lib.fx_take_callback.restype=C.c_uint8
            abi=[C.sizeof(Platform),*[getattr(Platform,n).offset for n in ('rom','rom_size','ram','callback_pending','status')],C.sizeof(Pair),Pair.columns.offset,Pair.rows.offset]
            assert abi==[lib.parameter_runtime_abi(i) for i in range(len(abi))];report['guards']+=len(abi)
            nd=out/('cpu-'+opt);m=Machine(rom,nd)
            ns=out/('original-'+opt+'.so')
            command=['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(ROOT/'tools'),str(ROOT/SUPPORT[1]),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(ns)]
            report['compiler_commands'].append(command)
            subprocess.run(command,check=True)
            n=C.CDLL(str(ns));artifacts[str(ns)]=sha(ns);artifacts[str(nd/'nxu8-harness.so')]=sha(nd/'nxu8-harness.so')
            for name in ('harness_init','harness_set_pc','harness_get_pc','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_ram','harness_run'):
                getattr(n,name).argtypes=getattr(m.lib,name).argtypes;getattr(n,name).restype=getattr(m.lib,name).restype
            n.harness_callback.restype=C.c_uint32
            n.parameter_menu_observe.argtypes=[C.c_uint64,C.c_int,C.c_int]
            n.runtime_parameter_run_to.argtypes=[C.c_uint32,C.c_uint64]
            m.lib=n;m.ram=n.harness_ram().contents
            mask=(C.c_uint8*65536).in_dll(n,'parameter_menu_frame_mask')
            constants=[lib.parameter_runtime_constant(i) for i in range(7)]
            for recipe in fixture['rows']:
                seeded=initial(rom,recipe);ram=(C.c_uint8*65536).from_buffer_copy(seeded)
                p=Platform(rd,len(rom),ram,0,0);state=C.create_string_buffer(lib.parameter_runtime_size())
                lib.parameter_runtime_main_entry(state);m.reset();C.memmove(m.ram,seeded,65536)
                n.harness_set_sp(0x8dee);n.harness_set_lr(0x2fffe);n.harness_set_pc(0xd7b4);m.reg(5,1);m.reg(4,0)
                n.parameter_menu_observer_clear();report['original_calls']+=1
                events=[]
                def field(i):return lib.parameter_runtime_field(state,i)
                def skip():
                    assert n.harness_run(1,0x2fffe,False)==103
                def to(stop):
                    if n.harness_get_pc()==stop:skip()
                    assert n.runtime_parameter_run_to(stop,3000000)==100,(recipe['label'],hex(stop),hex(n.harness_get_pc()))
                def compare(label,status):
                    expected=bytes(m.ram);actual=bytes(ram)
                    differences=[i for i in range(65536) if actual[i]!=expected[i] and not mask[i]]
                    nc=n.harness_callback();cc=lib.fx_take_callback(C.byref(p))
                    record=dict(label=recipe['label']+':'+label,optimization=opt,status=status,phase=field(0),event=field(1),pc=n.harness_get_pc(),differences=differences,native_callback=nc,c_callback=cc,
                        candidate_ram_zlib_hex=zlib.compress(actual).hex(),native_ram_zlib_hex=zlib.compress(expected).hex(),frame_mask_zlib_hex=zlib.compress(bytes(mask)).hex())
                    report['checkpoints'].append(record);report['comparisons']+=1
                    assert not differences,(record['label'],[(hex(a),actual[a],expected[a]) for a in differences[:20]])
                    assert nc==cc,(record['label'],'callback',nc,cc)
                    events.append({k:v for k,v in record.items() if not k.endswith('zlib_hex')})
                def submit(token):
                    pair=tuple(token['pair']) if isinstance(token,dict) else (0,0) if token is None else raw[token]
                    lib.fx_runtime_submit_pair(C.byref(p),Pair(*pair));m.ram[0x8e01],m.ram[0x8e02]=pair
                    return pair
                def release():submit(None)
                status=lib.fx_runtime_step(C.byref(p),state,None,0);assert status==0;to(0x1d8a4);compare('MAIN-wait',status)
                for i,token in enumerate(recipe['opening']):
                    submit(token);status=lib.fx_runtime_step(C.byref(p),state,None,0)
                    if i+1<len(recipe['opening']):assert status==0;to(0x1d8a4)
                    else:assert status==1 and field(0)==constants[1] and field(2)==constants[6];to(0xd9d2)
                    compare('opening-'+str(i),status);release()
                status=lib.fx_runtime_step(C.byref(p),state,None,0)
                assert lib.parameter_runtime_provider_custody(state)==1
                report['guards']+=1
                if status==4:
                    assert field(0)==constants[4] and field(9)==constants[5]
                    assert (field(10),field(11),field(12))==(field(13),field(14),field(15))
                    to(lib.parameter_runtime_target(state));compare('typed-pending-arrival',status)
                    old=bytes(ram);oldstate=bytes(state)
                    for a in (0,1,255):
                        assert lib.fx_runtime_accept_body(C.byref(p),state,a,a)==-1
                        assert bytes(ram)==old and bytes(state)==oldstate;report['guards']+=1
                    assert lib.fx_runtime_step(C.byref(p),state,None,0)==4 and bytes(ram)==old;report['guards']+=1
                    kind,page,arg=field(13),field(15),field(14)
                    if kind in (1,2,3,4):
                        assert n.parameter_menu_observe(3000000,0,1)==300
                        if kind in (1,2):assert n.harness_get_pc() in (0xceb0,0xcfa8) and (page,arg)==(m.reg(0),m.reg(1))
                        else:assert n.harness_get_pc()==0xd312 and arg==m.reg(0)
                    else:
                        to(0xdfde);assert kind==5 and page==m.ram[m.er(0)]==1
                    report['guards']+=1;report['pending']+=1
                else:
                    stop=n.parameter_menu_observe(3000000,0,0);assert stop in (200,250)
                    compare('parameter-entry',status)
                    for i,token in enumerate(recipe['keys']):
                        assert status in (0,2),(recipe['label'],i,status)
                        pair=submit(token);status=lib.fx_runtime_step(C.byref(p),state,None,0)
                        if token is None:
                            to(0x1d8a6);skip();to(0x1d8d2);stop=204
                        else:skip();stop=n.parameter_menu_observe(3000000,0,0)
                        if status==5:
                            assert stop==203;to(0xd7ae);report['resets']+=1
                        compare('menu-key-'+str(i),status);release()
                        if status==2:
                            assert stop==200 and field(7)==(1 if pair[0]==32 else 7);report['exports']+=1
                        if status==3:
                            assert stop==202 and field(5)==1 and field(6)==(0x129a if field(13) in (3,4) else 0x770)
                            old=bytes(ram);assert lib.fx_runtime_step(C.byref(p),state,None,0)==3 and bytes(ram)==old;report['guards']+=1
                            status=lib.fx_runtime_step(C.byref(p),state,None,1);skip();stop=n.parameter_menu_observe(3000000,0,0)
                            compare('timer-ready-'+str(i),status);report['timers']+=1
                        if status==5:break
                    if status==1:
                        assert stop==250 and field(0)==constants[3]
                        assert field(16)==m.reg(0)
                        if recipe['mode']==12:
                            assert field(16) in (0,255)
                            report['zero_returns' if field(16)==0 else 'ff_returns']+=1
                        status=lib.fx_runtime_step(C.byref(p),state,None,0);assert status==1 and field(0)==constants[0]
                        to(0xd980);compare('real-MAIN-return',status)
                        assert (field(4),field(3))==(m.reg(4),m.reg(5));report['completed_main']+=1
                    elif status==0:
                        # Preserve all exact former owned-child arrival inputs.
                        # The installed genuine child now owns this raw wait;
                        # this is a prefix witness, not a completed menu.
                        assert stop==200 and field(0)==constants[2]
                        assert field(13) in (1,2,3,4)
                        report['owned_prefixes']+=1
                    else:assert status==5,(recipe['label'],'unfinished',status)
                report['rows'].append(dict(input=recipe,optimization=opt,events=events,request=[field(i) for i in (9,10,11,12)],returned=field(8),distribution=[field(i) for i in range(17,23)],owned_provider=[field(i) for i in range(23,35)],
                    live_kind=ram[0x80fa],live_flag=ram[0x8137],table_rows=ram[0x80de],
                    table_sha256=digest(bytes(ram[0x82ee:0x860e])),seed_sha256=digest(seeded)))
            stable()
        assert report['original_calls']==len(fixture['rows'])*(1 if args.optimization else 2)
        if not args.optimization:
            def without_optimization(value):
                if isinstance(value,dict):
                    return {key:without_optimization(item) for key,item in value.items() if key!='optimization'}
                if isinstance(value,list):
                    return [without_optimization(item) for item in value]
                return value
            arows=[without_optimization(r) for r in report['rows'] if r['optimization']=='O2']
            brows=[without_optimization(r) for r in report['rows'] if r['optimization']=='O3']
            assert arows==brows,'O2/O3 observations differ'
        report['status']='pass'
    except Exception as error:
        report['status']='failed';report['failure']=repr(error);raise
    finally:
        post={p:sha(ROOT/p if not Path(p).is_absolute() else p) for p in pins}
        artifacts_post={p:sha(p) for p in artifacts}
        report.update(source_sha256_post=post,source_drift=post!=pins,
            artifact_sha256_pre=artifacts,artifact_sha256_post=artifacts_post,
            artifact_drift=artifacts_post!=artifacts,completed_utc=datetime.now(timezone.utc).isoformat())
        if report['source_drift'] or report['artifact_drift']:report['status']='failed'
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','original_calls','comparisons','guards','completed_main','pending','owned_prefixes','resets','exports','timers','legacy_recipes','distribution_recipes','additional_recipes','zero_returns','ff_returns')}))
    return 0 if report['status']=='pass' else 1
if __name__=='__main__':raise SystemExit(main())
