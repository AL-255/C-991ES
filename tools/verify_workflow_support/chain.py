#!/usr/bin/env python3
"""Private genuine138EE versus readable chain and actual137 scalar grammar."""
if not __debug__:
    raise SystemExit('Python optimization is unsupported')
import ast
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=Path(os.environ["VERIFY_ROOT"])
sys.path.insert(0,str(ROOT/'tools'))
from c_build_inputs import implementation_inputs
from nxu8.machine import Machine

class Storage(C.Structure):
    _fields_=[('ram',C.POINTER(C.c_uint8)),('ram_size',C.c_size_t),
              ('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t)]
class Result(C.Structure):
    _fields_=[('source',C.c_uint16),('operands',C.c_uint32),
        ('relations',C.c_uint32),('cancellation_checks',C.c_uint32),
        ('truth',C.c_uint8),('unsupported_token',C.c_uint8),('native_status',C.c_int)]
Callback=C.CFUNCTYPE(C.c_int,C.c_void_p)
class Control(C.Structure):
    _fields_=[('cancelled',Callback),('userdata',C.c_void_p)]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    snapshot=Path(os.environ['VERIFY_SOURCE_ROOT'])
    original_test=ROOT/'tools/test_eval_c.py'
    tree=ast.parse(original_test.read_text())
    sources=next(ast.literal_eval(n.value) for n in ast.walk(tree)
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='sources' for t in n.targets))
    sources=['csrc/'+s for s in sources]+[
        'csrc/parse/fx_verify_chain.c','csrc/numeric/fx_verify_relation.c']
    closure=implementation_inputs(snapshot,sources)
    fixture=Path(os.environ['VERIFY_FIXTURE_DIR'])/'chain-inputs.json';data=json.loads(fixture.read_text())
    assert data['schema']=='verify-chain-input-v2' and set(data)=={'schema','cases'}
    cases=data['cases'];assert len(cases)==180
    for i,row in enumerate(cases):
        assert set(row)=={'id','input','math','source','output','cancel_at'} and row['id']==i
        assert bytes.fromhex(row['input']).endswith(b'\0')
    paths=[snapshot/p for p in closure]+[Path(__file__),fixture,original_test,
        ROOT/'tools/c_build_inputs.py',ROOT/'analysis/disassembly/complete.asm',
        ROOT/'firmware/fx-991es-plus-c-ver4.bin']
    paths+=sorted(p for p in (ROOT/'tools/nxu8').rglob('*')
        if p.is_file() and p.suffix in ('.c','.h','.py','.txt'))
    pins={str(p):sha(p) for p in paths}
    build=Path(os.environ['VERIFY_BUILD_DIR'])/'chain';build.mkdir(exist_ok=True)
    temp=build/'compiler-tmp';temp.mkdir(exist_ok=True);os.environ['TMPDIR']=str(temp)
    rom_bytes=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom=(C.c_uint8*len(rom_bytes)).from_buffer_copy(rom_bytes)
    native=Machine(rom_bytes,build/'oracle');rows=[];failures=[];artifacts={}
    for optimization in os.environ['VERIFY_OPTIMIZATIONS'].split(','):
        library=build/(optimization+'.so')
        command=['gcc','-std=c99','-'+optimization,'-Wall','-Wextra','-Werror',
            '-shared','-fPIC','-Wl,--no-undefined',*(str(snapshot/s) for s in sources),'-o',str(library)]
        subprocess.run(command,check=True);lib=C.CDLL(str(library))
        fn=lib.fx_verify_chain
        fn.argtypes=[C.POINTER(Storage),C.c_uint16,C.c_uint16,C.c_size_t,
                     C.POINTER(Control),C.POINTER(Result)];fn.restype=C.c_int
        ap={str(library):sha(library),str(build/'oracle/nxu8-harness.so'):sha(build/'oracle/nxu8-harness.so')}
        for case in cases:
            native.reset();source=case['source'];output=case['output'];text=bytes.fromhex(case['input'])
            for address,value in {0x80f9:0x89,0x80fa:9,0x80fc:1,0x80fe:1,
                0x80f5:0xf0,0x8104:1,0x8105:4,0x8106:case['math'],
                0x811f:10,0x8121:1}.items():native.ram[address]=value
            native.ram[source:source+len(text)]=text;native.word(0x8900,source)
            native.ram[output:output+20]=bytes.fromhex('0900000000000000000107000000000000000001')
            seed=bytes(native.ram)
            native.lib.harness_set_sp(0x8dee);native.lib.harness_set_lr(0x2fffe)
            native.lib.harness_set_pc(0x138ee);native.er(0,0x8900);native.er(2,output)
            native_polls=0;outcome=103
            for step in range(2000000):
                pc=native.lib.harness_get_pc()
                if pc==0x2fffe:outcome=100;break
                if pc==0x5550:native_polls+=1
                if pc==0x5564:
                    assert native.ram[0x8e00]==2
                    native.ram[0x8e00]=1 if case['cancel_at']==native_polls else 0
                outcome=native.lib.harness_run(1,0x2fffe,False)
                if outcome!=103:break
            assert outcome==100,(case,outcome,native.lib.harness_get_pc())
            memory=(C.c_uint8*65536).from_buffer_copy(seed)
            storage=Storage(memory,65536,rom,len(rom_bytes));result=Result();calls=[0]
            @Callback
            def cancelled(_):
                calls[0]+=1
                return case['cancel_at']==calls[0]
            control=Control(cancelled,None)
            status=fn(C.byref(storage),source,output,1024,C.byref(control),C.byref(result))
            expected=(native.reg(0),native.word(0x8900),bytes(native.ram[output:output+20]),native_polls)
            actual=(status,result.source,bytes(memory[output:output+20]),calls[0])
            pool=bytes(memory[0x8640:0x867c])==bytes(native.ram[0x8640:0x867c])
            vars_match=bytes(memory[0x8226:0x828a])==bytes(native.ram[0x8226:0x828a])
            row={'id':case['id'],'optimization':optimization,'input':case['input'],
                'expected':[expected[0],expected[1],expected[2].hex(),expected[3]],
                'actual':[actual[0],actual[1],actual[2].hex(),actual[3]],
                'pool_match':pool,'variables_match':vars_match,
                'C_operands':result.operands,'native_operands':native.counts[0x171f4//2],
                'C_relations':result.relations,'native_relations':native.counts[0x13950//2]}
            rows.append(row)
            if actual!=expected or not pool or not vars_match or result.operands!=native.counts[0x171f4//2] or result.relations!=native.counts[0x13950//2]:failures.append(row)
        assert ap=={p:sha(Path(p)) for p in ap};artifacts[optimization]={'compiler':command,'sha256':ap}
    assert pins=={p:sha(Path(p)) for p in pins}
    report={'status':'pass' if not failures else 'fail','cases_per_build':len(cases),
        'rows':rows,'failures':failures,'source_pins':pins,'artifacts':artifacts,
        'source_drift':False,'scope':'Private actual137 scalaroperand grammar+138EE math/control proof. Records,status,cursor,polls,operand/predicate counts,realvariables and60-byteSURDpool; no wholeF12A/error-key/LCD/generalphysicalnumeric scratch claim.'}
    (build/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','source_pins','artifacts')},indent=2))
    return bool(failures)

if __name__=='__main__':raise SystemExit(main())
