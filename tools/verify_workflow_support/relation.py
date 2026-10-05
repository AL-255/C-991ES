#!/usr/bin/env python3
"""Private actual-ROM comparison of new finite VERIFY predicates."""
if not __debug__:
    raise SystemExit("Python optimization is unsupported")
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

class Number(C.Structure):
    _fields_=[('bytes',C.c_uint8*10)]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    source=Path(os.environ['VERIFY_SOURCE_ROOT'])
    names=['csrc/numeric/fx_verify_relation.c','csrc/numeric/fx_numeric.c',
       'csrc/numeric/fx_surd_components.c','csrc/numeric/fx_raw_fraction_convert.c',
       'csrc/numeric/fx_raw_decimal_parts.c','csrc/numeric/fx_raw_decimal_divide.c',
       'csrc/numeric/fx_raw_decimal_multiply_add.c']
    closure=implementation_inputs(source,names)
    fixture=Path(os.environ['VERIFY_FIXTURE_DIR'])/'relation-inputs.json'
    corpus=json.loads(fixture.read_text())
    assert set(corpus)=={'schema','cases'} and corpus['schema']=='verify-relation-input-v1'
    cases=corpus['cases']
    assert len(cases)==384
    for index,case in enumerate(cases):
        assert set(case)=={'id','entry','token','left','right','alias'}
        assert case['id']==index
        assert len(bytes.fromhex(case['left']))==len(bytes.fromhex(case['right']))==10
    paths=[source/f for f in closure]+[Path(__file__).resolve(),fixture,
        ROOT/'tools/c_build_inputs.py',ROOT/'analysis/disassembly/complete.asm',
        ROOT/'firmware/fx-991es-plus-c-ver4.bin']
    paths+=sorted(p for p in (ROOT/'tools/nxu8').rglob('*')
        if p.is_file() and p.suffix in ('.c','.h','.py','.txt'))
    before={str(p):sha(p) for p in paths}
    build=Path(os.environ['VERIFY_BUILD_DIR'])/'relation';build.mkdir(exist_ok=True)
    tmp=build/'compiler-tmp';tmp.mkdir(exist_ok=True);os.environ['TMPDIR']=str(tmp)
    native=Machine((ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes(),build/'oracle')
    rows=[];failures=[];checks=0;artifacts={}
    for optimization in os.environ['VERIFY_OPTIMIZATIONS'].split(','):
        library=build/(optimization+'.so')
        command=['gcc','-std=c99','-'+optimization,'-Wall','-Wextra','-Werror',
            '-shared','-fPIC','-Wl,--no-undefined',*(str(source/f) for f in names),'-o',str(library)]
        subprocess.run(command,check=True)
        lib=C.CDLL(str(library));fn=lib.fx_verify_relation
        fn.argtypes=[C.POINTER(Number),C.POINTER(Number),C.POINTER(Number),C.c_uint8,
                     C.POINTER(C.c_uint8),C.POINTER(C.c_uint8),C.POINTER(C.c_uint)]
        fn.restype=C.c_int
        pins={str(library):sha(library),str(build/'oracle/nxu8-harness.so'):sha(build/'oracle/nxu8-harness.so')}
        for case in cases:
            native.reset();native.ram[0x80f9]=0x89;native.ram[0x80fc]=1;native.ram[0x8106]=1
            a=bytes.fromhex(case['left']);b=bytes.fromhex(case['right'])
            native.ram[0x8500:0x850a]=a;native.ram[0x8520:0x852a]=b
            native.er(0,0x8500);native.er(2,0x8520)
            native.call(case['entry'],limit=2000000)
            lhs=Number((C.c_uint8*10).from_buffer_copy(a))
            rhs=Number((C.c_uint8*10).from_buffer_copy(b));out=Number()
            ram=(C.c_uint8*65536)();truth=C.c_uint8(0xad);status=C.c_uint(0xdead)
            result=fn(C.byref(out),C.byref(lhs),C.byref(rhs),case['token'],ram,
                      C.byref(truth),C.byref(status))
            expected=(native.reg(0),native.reg(1),bytes(native.ram[0x8500:0x850a]))
            actual=(status.value,truth.value,bytes(out.bytes))
            checks+=5
            row={'id':case['id'],'optimization':optimization,'host_status':result,
                 'native_status':expected[0],'C_status':actual[0],
                 'native_truth':expected[1],'C_truth':actual[1],
                 'native_record':expected[2].hex(),'C_record':actual[2].hex(),
                 'rhs_preserved':bytes(rhs.bytes)==b and bytes(native.ram[0x8520:0x852a])==b,
                 'pool_matches':bytes(ram[0x8640:0x867c])==bytes(native.ram[0x8640:0x867c])}
            if result!=0 or actual!=expected or not row['rhs_preserved'] or not row['pool_matches']:failures.append(row)
            rows.append(row)
        assert all(sha(Path(p))==v for p,v in pins.items())
        artifacts[optimization]={'sha256':pins,'compiler_command':command}
    assert before=={str(p):sha(p) for p in paths}
    report={'status':'pass' if not failures else 'fail','cases_per_build':len(cases),
        'native_calls':len(rows),'checks':checks,'failures':failures,'rows':rows,
        'source_pins':before,'source_drift':False,'artifacts':artifacts,
        'scope':'Prepared canonical natural/marked decimal, rational/marked-rational, compactSURD andFerror predicates; actual globalmode137; records,status,truth,RHS andordered60-byte SURDpool. No full138EE/F12A/controller or generalized physicalnumeric-scratch parity yet.'}
    (build/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','source_pins','artifacts')},indent=2))
    return bool(failures)

if __name__=='__main__':raise SystemExit(main())
