#!/usr/bin/env python3
"""Prepared CLEAR child and actual runtime/provider differential proof.

Each path sets its original PC once. The caller path enters D7B4 and supplies
physical SHIFT/9 packets and invokes the actual retained runtime/provider
CLEAR sibling. Direct paths enter D426. Only real key packets and timer readiness
advance either implementation. Actual CPU-stack writes are the sole RAM mask.
Reset recipes stop at the original reset request before the reset body; normal
caller recipes retain the real parameter and MAIN return sequence. No physical
key-matrix scan, boot, or arbitrary corrupted-controller claim.
"""
import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import zlib
TOOL=Path(__file__).resolve()
HERE=TOOL.parent
ROOT=next(p for p in TOOL.parents if (p/'tools/nxu8/machine.py').is_file() and
          (p/'firmware/fx-991es-plus-c-ver4.bin').is_file())
PACKAGE=HERE.parent
FIXTURE_SHA='916f799d2f7475049ff6468426ce5bdbe0424ba1a7c7181349bcfa1d985590cd'
CANONICAL_FIXTURE=ROOT/'analysis/native-fixtures/clear-controller/inputs.json'
DEFAULT_FIXTURE=CANONICAL_FIXTURE if HERE==ROOT/'tools' else PACKAGE/'analysis/native-fixtures/clear-controller/inputs.json'
sys.path.insert(0,str(ROOT/'tools'))
from c_build_inputs import implementation_inputs
from nxu8.machine import Machine

class Platform(C.Structure):
    _fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),
              ('ram',C.POINTER(C.c_uint8)),('callback_pending',C.c_uint8),('status',C.c_int)]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def initial(rom,r):
    ram=bytearray(65536)
    ram[0x8dee:0x8e00]=rom[0x1f8be:0x1f8d0]
    values={0x80f2:0x5a,0x80f3:0xc3,0x80f9:r['mode'],0x80fa:1,0x80fb:0,
        0x80fc:r['screen'],0x80fd:3,0x80fe:1,0x8112:17,0x8117:1,0x8119:1,
        0x811a:0x7c,0x811b:10,0x811c:3,0x811d:2,0x811e:2,0x811f:10,
        0x8105:4,0x8106:1,0x8121:1,0x812a:0xaa,0x8130:5,0x8137:r.get('list',0),
        0x8138:0x55,0xf040:255}
    for a,v in values.items():ram[a]=v
    ram[0x812c:0x8130]=bytes.fromhex('54815481')
    ram[0x8154:0x8158]=b'1+2\0';ram[0x81b8:0x81bc]=b'7+8\0'
    one=bytes.fromhex('01000000000000000001');two=bytes.fromhex('02000000000000000001')
    for i in range(11):ram[0x8226+10*i:0x8230+10*i]=one
    for i in range(10):ram[0x8408+10*i:0x8412+10*i]=two
    ram[0x8140:0x8154]=one+two
    if 'result' in r:ram[0x8140:0x8154]=bytes.fromhex(r['result'])
    ram[0x8000:0x80dc]=bytes([0xad])*220
    ram[0x8a16:0x8a19]=bytes.fromhex('b4b5b6')
    ram[0x8840:0x8a00]=bytes((11+37*i)&255 for i in range(448))
    return bytes(ram)
def schema(doc):
    assert type(doc)is dict and set(doc)=={'schema','rows'} and type(doc['schema'])is int and doc['schema']==1
    assert type(doc['rows'])is list and doc['rows']
    assert len({r['label'] for r in doc['rows']})==len(doc['rows'])
    for r in doc['rows']:
        assert {'label','entry','mode','screen','keys'}<=set(r)<={'label','entry','mode','screen','keys','list','result'}
        assert r['entry'] in ('child','caller') and type(r['label'])is str and r['label']
        assert type(r['keys'])is list
        if 'list' in r:assert type(r['list'])is int and 0<=r['list']<=255
        assert all(type(r[n])is int and 0<=r[n]<=255 for n in ('mode','screen'))
        assert all(t is None or type(t)is int and 0<t<256 or
            type(t)is dict and set(t)=={'pair'} and len(t['pair'])==2 and
            all(type(v)is int and 0<=v<=255 for v in t['pair']) for t in r['keys'])
        if 'result' in r:assert type(r['result'])is str and re.fullmatch('[0-9a-f]{40}',r['result'])

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fixture',type=Path,default=DEFAULT_FIXTURE)
    ap.add_argument('--source-root',type=Path,default=ROOT)
    ap.add_argument('--no-report',action='store_true')
    ap.add_argument('--optimization',choices=('O2','O3'))
    ap.add_argument('--output-dir',type=Path)
    a=ap.parse_args()
    if sys.flags.optimize:ap.error('Python -O disables proof assertions; refusing before any build or native call')
    a.source_root=a.source_root.resolve();a.fixture=a.fixture.resolve()
    if not a.no_report and (TOOL!=ROOT/'tools/test_clear_controller_c.py' or
        a.source_root!=ROOT or a.fixture!=CANONICAL_FIXTURE or a.optimization):
        ap.error('Publication requires canonical tool/fixture/source root and both O2/O3; use --no-report for private/subset runs')
    data=a.fixture.read_bytes();fixture=json.loads(data);schema(fixture)
    if not a.no_report and (sha(a.fixture)!=FIXTURE_SHA or len(fixture['rows'])!=48):
        ap.error('Canonical fixture identity/count mismatch')
    if not a.no_report:
        from c_verification import write_report
    source_root=a.source_root
    out=a.output_dir or ROOT/'analysis/build/clear-controller'/('proof-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    out.mkdir(parents=True,exist_ok=False);(out/'tmp').mkdir();os.environ['TMPDIR']=str(out/'tmp')
    cmake=source_root/'csrc/CMakeLists.txt';cm=cmake.read_bytes()
    sources=list(dict.fromkeys('csrc/'+x for x in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',cm.decode().split('target_include_directories')[0])))
    inputs=[source_root/x for x in implementation_inputs(source_root,sources)]
    inputs += [cmake,a.fixture,Path(__file__).resolve(),source_root/'csrc/ui/fx_clear_controller.c',
        source_root/'csrc/ui/fx_clear_controller.h',HERE/'clear_controller_support/adapter.c',HERE/'clear_controller_support/native.c',
        ROOT/'tools/c_build_inputs.py',ROOT/'tools/c_verification.py',ROOT/'tools/nxu8/machine.py',ROOT/'tools/parameter_menu_oracle.c',
        ROOT/'tools/nxu8/harness.c',ROOT/'tools/nxu8/isa.txt',ROOT/'tools/nxu8/decoder.py',
        ROOT/'tools/nxu8/vendor/SimU8/core.c',ROOT/'firmware/fx-991es-plus-c-ver4.bin',
        ROOT/'analysis/disassembly/complete.asm']
    inputs += list((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h'))
    inputs += [p for p in (ROOT/'tools/nxu8/vendor/SimU8').glob('*') if p.name.lower() in ('copying','license','provenance.json')]
    inputs += [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools')]
    inputs += list((HERE/'clear_controller_support').glob('*.h'))
    # No report/prefix execution supplies expectations. Pin all actual helper imports.
    pins={str(p.resolve()):sha(p) for p in sorted(set(inputs))}
    assert pins[str(a.fixture.resolve())]==hashlib.sha256(data).hexdigest()
    gcc=Path(shutil.which('gcc')).resolve()
    cc1=Path(subprocess.check_output([str(gcc),'-print-prog-name=cc1'],text=True).strip()).resolve()
    compilers={str(p):sha(p) for p in (gcc,cc1)}
    report={'schema':1,'status':'running','scope':__doc__,'source_sha256_pre':pins,
        'compiler_sha256_pre':compilers,'compiler_version':subprocess.check_output([str(gcc),'--version'],text=True),
        'compiled_sources':sources,'source_root':str(source_root),'fixture_sha256':sha(a.fixture),'publication_requested':not a.no_report,'commands':[],'artifacts_pre':{},'observations':[],
        'rows':[],'checks':0,'original_calls':0,'observer_advances':0,'instructions':0,'timers':0,'exports':0,'resets':0,'host_guards':0}
    (out/'inputs.json').write_bytes(data)
    # Actual refusal controls precede any candidate/original library load.
    guard_dir=out/'guard-controls';guard_dir.mkdir()
    guard_rows=[]
    base=[sys.executable,str(TOOL),'--no-report','--source-root',str(source_root),
          '--fixture',str(a.fixture),'--optimization','O2']
    cases=[('python-O',[sys.executable,'-O',*base[1:]],None),
           ('private-publication',[sys.executable,str(TOOL),'--source-root',str(source_root),
                                   '--fixture',str(a.fixture),'--optimization','O2'],None)]
    malformed=[
        ('schema-extra',dict(fixture,expected=[])),
        ('schema-bool',dict(fixture,schema=True)),
        ('row-extra',{'schema':1,'rows':[dict(fixture['rows'][0],expected='no')]}),
        ('bad-mode',{'schema':1,'rows':[dict(fixture['rows'][0],mode=True)]}),
        ('bad-result',{'schema':1,'rows':[dict(fixture['rows'][0],result='zz'*20)]}),
        ('bad-key',{'schema':1,'rows':[dict(fixture['rows'][0],keys=[True])]}),
        ('duplicate-label',{'schema':1,'rows':[fixture['rows'][0],fixture['rows'][0]]}),
    ]
    for label,doc in malformed:
        path=guard_dir/(label+'.json');path.write_text(json.dumps(doc)+'\n')
        cmd=[*base];cmd[cmd.index('--fixture')+1]=str(path)
        cases.append((label,cmd,path))
    for label,cmd,path in cases:
        target=guard_dir/(label+'-must-not-exist')
        completed=subprocess.run([*cmd,'--output-dir',str(target)],capture_output=True,text=True)
        guard_rows.append({'label':label,'command':cmd,'returncode':completed.returncode,
                          'stdout':completed.stdout,'stderr':completed.stderr,
                          'no_build_directory':not target.exists()})
        assert completed.returncode!=0 and not target.exists(),('rejection guard',label)
    report['publication_schema_controls']=guard_rows;report['checks']+=len(guard_rows)

    def stable():assert all(sha(p)==h for p,h in {**pins,**compilers}.items()),'Source/compiler drift'
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rd=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    raw={rom[0x7fe+8*c+r]:(1<<c,1<<r) for c in range(8) for r in range(8)}
    try:
      for opt in ([a.optimization] if a.optimization else ('O2','O3')):
        stable();so=out/('candidate-'+opt+'.so');ns=out/('original-'+opt+'.so')
        commands=[
            [str(gcc),'-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined',
             '-I',str(source_root/'csrc'),*[str(source_root/p) for p in sources],
             str(HERE/'clear_controller_support/adapter.c'),'-o',str(so)],
            [str(gcc),'-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(ROOT/'tools'),
             str(HERE/'clear_controller_support/native.c'),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(ns)]]
        for command in commands:
            report['commands'].append(command)
            dependencies=subprocess.check_output([*command[:1],'-MM',*command[command.index('-I'):command.index('-o')]],text=True)
            for name in dependencies.replace(chr(92)+chr(10),' ').split():
                if name.endswith(':'):continue
                path=Path(name)
                if path.is_file():
                    key=str(path.resolve())
                    if key not in pins:
                        pins[key]=sha(path)
            stable()
            subprocess.run(command,check=True)
        report['artifacts_pre'].update({str(p):sha(p) for p in (so,ns)})
        lib=C.CDLL(str(so.resolve()));n=C.CDLL(str(ns.resolve()))
        lib.clear_test_size.restype=C.c_size_t;lib.clear_test_child_size.restype=C.c_size_t;lib.clear_test_abi.argtypes=[C.c_uint];lib.clear_test_abi.restype=C.c_size_t
        lib.clear_test_field.argtypes=[C.c_void_p,C.c_uint]
        lib.clear_test_custody.argtypes=[C.c_void_p]
        lib.clear_test_legacy_provider.argtypes=[C.POINTER(Platform)]
        lib.clear_test_child.argtypes=[C.c_void_p];lib.clear_test_child.restype=C.c_void_p
        lib.clear_test_service.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_uint,C.c_uint]
        lib.clear_test_main_begin.argtypes=[C.c_void_p]
        for name in ('clear_test_tick','clear_test_timer','clear_test_main_tick'):
            getattr(lib,name).argtypes=[C.POINTER(Platform),C.c_void_p]
        lib.clear_test_begin.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_int]
        lib.clear_test_finish.argtypes=[C.c_void_p,C.POINTER(C.c_uint8)]
        lib.clear_test_main_return.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_uint8]
        lib.fx_take_callback.argtypes=[C.POINTER(Platform)];lib.fx_take_callback.restype=C.c_uint8
        for name in ('fx_clear_controller_begin','fx_clear_controller_tick','fx_clear_controller_resume_timer'):
            getattr(lib,name).argtypes=[C.POINTER(Platform),C.c_void_p]
        lib.fx_clear_controller_finish.argtypes=[C.c_void_p,C.POINTER(C.c_uint8)]
        abi=[C.sizeof(Platform),*[getattr(Platform,k).offset for k in ('rom','rom_size','ram','callback_pending','status')],0,1,2,3,4,C.c_size_t(-1).value,C.c_size_t(-2).value,4,4]
        assert abi==[lib.clear_test_abi(i) for i in range(len(abi))];report['checks']+=len(abi)
        assert lib.clear_test_abi(15)>lib.clear_test_abi(23) and lib.clear_test_abi(16)==0;report['checks']+=2
        assert lib.clear_test_abi(25)>=lib.clear_test_abi(24)+lib.clear_test_abi(26)
        assert lib.clear_test_abi(28)>lib.clear_test_abi(27);report['checks']+=2
        n.harness_init.argtypes=[C.c_void_p,C.c_size_t];n.harness_set_pc.argtypes=[C.c_uint32];n.harness_get_pc.restype=C.c_uint32
        n.harness_set_reg.argtypes=[C.c_uint,C.c_uint8];n.harness_get_reg.argtypes=[C.c_uint];n.harness_get_reg.restype=C.c_uint8
        n.harness_set_sp.argtypes=[C.c_uint16];n.harness_get_sp.restype=C.c_uint16;n.harness_set_lr.argtypes=[C.c_uint32]
        n.harness_ram.restype=C.POINTER(C.c_uint8*65536);n.harness_run.argtypes=[C.c_uint64,C.c_uint32,C.c_bool]
        n.harness_callback.restype=C.c_uint32;n.parameter_menu_observe.argtypes=[C.c_uint64,C.c_int,C.c_int]
        n.clear_run_to.argtypes=[C.c_uint32,C.c_uint64]
        m=object.__new__(Machine);m.rom=rom;m.lib=n;m.ram=n.harness_ram().contents
        mask=(C.c_uint8*65536).in_dll(n,'parameter_menu_frame_mask')
        for r in fixture['rows']:
            seeded=initial(rom,r);ram=(C.c_uint8*65536).from_buffer_copy(seeded)
            p=Platform(rd,len(rom),ram,0,0);state=C.create_string_buffer(lib.clear_test_size())
            lib.clear_test_main_begin(state);m.reset();C.memmove(m.ram,seeded,65536)
            n.harness_set_sp(0x8dee);n.harness_set_lr(0x2fffe)
            parent=r['entry']=='caller';n.harness_set_pc(0xd7b4 if parent else 0xd426)
            if parent:m.reg(5,1);m.reg(4,0)
            n.parameter_menu_observer_clear();report['original_calls']+=1
            def step():assert n.harness_run(1,0x2fffe,False)==103
            def to(pc):
                if n.harness_get_pc()==pc:step()
                assert n.clear_run_to(pc,3000000)==100,(r['label'],hex(pc),hex(n.harness_get_pc()))
            def compare(label,status):
                actual=bytes(ram);expected=bytes(m.ram)
                diff=[i for i in range(65536) if actual[i]!=expected[i] and not mask[i]]
                nc=n.harness_callback();cc=lib.fx_take_callback(C.byref(p))
                row={'recipe':r['label'],'optimization':opt,'stage':label,'status':status,'pc':n.harness_get_pc(),
                    'fields':[lib.clear_test_field(state,i) for i in range(16)],'differences':[(i,actual[i],expected[i]) for i in diff],
                    'native_return_byte':m.reg(0),'native_callback':nc,'c_callback':cc,'candidate_ram_zlib_hex':zlib.compress(actual).hex(),
                    'native_ram_zlib_hex':zlib.compress(expected).hex(),'frame_mask_zlib_hex':zlib.compress(bytes(mask)).hex()}
                report['observations'].append(row);report['checks']+=2
                assert not diff,(r['label'],label,row['differences'][:25])
                assert nc==cc,(r['label'],label,'callback',nc,cc)
            def submit(token):
                pair=tuple(token['pair']) if isinstance(token,dict) else (0,0) if token is None else raw[token]
                ram[0x8e01],ram[0x8e02]=pair;m.ram[0x8e01],m.ram[0x8e02]=pair
                return pair
            if parent:
                assert lib.clear_test_main_tick(C.byref(p),state)==0;to(0x1d8a4);compare('MAIN-wait',0)
                for i,token in enumerate((0xe9,0x39)):
                    submit(token);v=lib.clear_test_main_tick(C.byref(p),state)
                    assert v==(0 if i==0 else 4)
                    to(0x1d8a4 if i==0 else 0xd9d2);compare('SHIFT9-'+str(i),v);submit(None)
                assert lib.clear_test_field(state,10)==4;report['checks']+=1
            status=lib.clear_test_begin(C.byref(p),state,parent)
            stop=n.parameter_menu_observe(3000000,0,0);assert status==0 and stop==200
            compare('child-open',status)
            assert lib.clear_test_custody(state);report['checks']+=1
            before_ram=bytes(ram);assert lib.clear_test_legacy_provider(C.byref(p))==1 and bytes(ram)==before_ram
            report['host_guards']+=1
            child=lib.clear_test_child(state)
            before=(bytes(ram),bytes(state));outbyte=C.c_uint8(0xad)
            guards=[lib.fx_clear_controller_begin(None,child),lib.fx_clear_controller_begin(C.byref(p),None),
                lib.fx_clear_controller_tick(None,child),lib.fx_clear_controller_tick(C.byref(p),None),
                lib.fx_clear_controller_resume_timer(None,child),lib.fx_clear_controller_resume_timer(C.byref(p),None),
                lib.fx_clear_controller_resume_timer(C.byref(p),child),
                lib.fx_clear_controller_finish(child,C.byref(outbyte)),lib.fx_clear_controller_finish(None,C.byref(outbyte)),
                lib.clear_test_service(C.byref(p),state,4,5)]
            assert guards==[-1]*len(guards) and outbyte.value==0xad and before==(bytes(ram),bytes(state))
            report['host_guards']+=len(guards)
            for j,token in enumerate(r['keys']):
                assert status in (0,3),(r['label'],'key after completion',j,status)
                pair=submit(token);status=lib.clear_test_tick(C.byref(p),state)
                if token is None:
                    to(0x1d8a6);step();to(0x1d8d2);stop=204
                else:step();stop=n.parameter_menu_observe(3000000,0,0)
                assert status>=0,(r['label'],j,status,hex(n.harness_get_pc()))
                assert stop in (100,200,202,203,204,250),(r['label'],j,stop,hex(n.harness_get_pc()))
                compare('key-'+str(j),status);submit(None)
                if status==4:
                    assert stop==202 and lib.clear_test_field(state,7)==0x770;report['checks']+=1;report['timers']+=1
                    before=(bytes(ram),C.string_at(child,lib.clear_test_child_size()));assert lib.clear_test_tick(C.byref(p),state)==4 and before==(bytes(ram),C.string_at(child,lib.clear_test_child_size()));report['host_guards']+=1
                    status=lib.clear_test_timer(C.byref(p),state);step();stop=n.parameter_menu_observe(3000000,0,0)
                    compare('timer-'+str(j),status)
                elif status==3:
                    assert stop==200 and lib.clear_test_field(state,6)==(1 if pair[0]==32 else 7);report['checks']+=1;report['exports']+=1
                elif status==2:
                    assert stop==203;report['checks']+=1;report['resets']+=1
                if status in (1,2):break
            assert status in (1,2),(r['label'],'unfinished',status)
            value=C.c_uint8(0xAD);assert lib.clear_test_finish(state,C.byref(value))==status;report['checks']+=1
            if status==1:
                assert stop==(250 if parent else 100) and value.value==m.reg(0);report['checks']+=2
                if parent:
                    assert lib.clear_test_main_return(C.byref(p),state,value.value)==1
                    to(0xd980);compare('MAIN-return',1)
                    assert [lib.clear_test_field(state,i) for i in (9,8)]==[m.reg(4),m.reg(5)];report['checks']+=1
            report['rows'].append({'input':r,'optimization':opt,'returned':value.value,'status':status})
            report['observer_advances']+=C.c_uint64.in_dll(n,'parameter_menu_steps').value
            report['instructions']+=sum((C.c_uint64*0x18000).in_dll(n,'execution_counts'))
            before=(bytes(ram),bytes(state));outbyte=C.c_uint8(0xad)
            assert lib.clear_test_finish(state,C.byref(outbyte))==-1 and outbyte.value==0xad and before==(bytes(ram),bytes(state))
            assert lib.fx_clear_controller_tick(C.byref(p),child)==-1 and before==(bytes(ram),bytes(state))
            report['host_guards']+=2
            before_ram=bytes(ram)
            assert [lib.clear_test_service(C.byref(p),state,k,1) for k in range(4)]==[5,5,5,-1]
            assert bytes(ram)==before_ram and lib.clear_test_field(state,4)==0
            report['host_guards']+=5
        stable()
        assert all(sha(p)==h for p,h in report['artifacts_pre'].items());report['checks']+=2
      report['status']='pass'
    except Exception as e:
        report['status']='failed';report['failure']=repr(e);raise
    finally:
        report['source_sha256_post']={p:sha(p) for p in pins}
        report['source_changes']={p:[h,report['source_sha256_post'][p]] for p,h in pins.items() if h!=report['source_sha256_post'][p]}
        report['compiler_sha256_post']={p:sha(p) for p in compilers}
        report['compiler_changes']={p:[h,report['compiler_sha256_post'][p]] for p,h in compilers.items() if h!=report['compiler_sha256_post'][p]}
        report['artifacts_post']={p:sha(p) for p in report['artifacts_pre']}
        report['artifact_changes']={p:[h,report['artifacts_post'][p]] for p,h in report['artifacts_pre'].items() if h!=report['artifacts_post'][p]}
        (out/'proof.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['status']=='pass' and not a.no_report:
        assert not report['source_changes'] and not report['compiler_changes'] and not report['artifact_changes']
        declared=[str(Path(p).relative_to(ROOT)) for p in pins if Path(p).is_relative_to(ROOT)
            and (Path(p).suffix.lower() in ('.c','.h','.py','.json','.bin') or Path(p).name=='CMakeLists.txt')]
        canonical=ROOT/'analysis/c-verification/clear_controller.json'
        write_report(canonical,report,declared,'tools/test_clear_controller_c.py')
        report['canonical_report']=str(canonical);report['canonical_report_sha256']=sha(canonical)
        (out/'proof.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','original_calls','instructions','checks','host_guards','timers','exports','resets','source_changes','compiler_changes','artifact_changes')})+' '+str(out/'proof.json'),flush=True)
if __name__=='__main__':main()
