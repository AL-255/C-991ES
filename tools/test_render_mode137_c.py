#!/usr/bin/env python3
"""VERIFY-mode Boolean result formatting and display versus unchanged ROM.

The C renderer never executes firmware. The independently instrumented
original CPU is a test oracle only. Fixtures contain inputs, not outcomes.
"""
if not __debug__:
    raise SystemExit("Python optimization is unsupported: assertion guards are required")

import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
# A private source copy uses the original tools only as its test oracle.
while not (REPO/'firmware/fx-991es-plus-c-ver4.bin').is_file():
    REPO = REPO.parent
sys.path.insert(0, str(REPO/'tools'))
from c_build_inputs import implementation_inputs
from c_verification import write_report
from nxu8.machine import Machine

SOURCES = [
 'csrc/render/fx_result_verify.c', 'csrc/render/fx_result_special.c',
 'csrc/render/fx_result_complex.c', 'csrc/render/fx_render.c',
 'csrc/render/fx_render_context.c', 'csrc/render/fx_render_memory.c',
 'csrc/render/fx_layout.c', 'csrc/render/fx_layout_validate.c',
 'csrc/render/fx_viewport.c', 'csrc/render/fx_result_format_state.c',
 'csrc/render/fx_result_inequality.c', 'csrc/complex/fx_complex.c',
 'csrc/complex/fx_complex_angle.c', 'csrc/format/fx_format.c',
 'csrc/format/fx_format_budget.c', 'csrc/format/fx_format_base.c',
 'csrc/trig/fx_trig.c', 'csrc/trig/fx_trig_math.c',
 'csrc/trig/fx_trig_inverse.c', 'csrc/trig/fx_math_context.c',
 'csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_surd_components.c',
 'csrc/numeric/fx_raw_decimal_divide.c',
 'csrc/numeric/fx_raw_decimal_multiply_add.c',
 'csrc/numeric/fx_raw_decimal_parts.c']
FIXTURE = 'analysis/native-fixtures/render-mode137/inputs.json'
CANONICAL_COUNT = 7048

class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8*10)]
class Render(C.Structure):
    _fields_ = [('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t),
               ('memory', C.POINTER(C.c_uint8))]
class Result(C.Structure):
    _fields_ = [('length', C.c_size_t), ('kind', C.c_uint8), ('recognized', C.c_uint8)]
class Box(C.Structure):
    _fields_ = [('width', C.c_uint16), ('height', C.c_uint8), ('depth', C.c_uint8)]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-root',type=Path,default=REPO)
    ap.add_argument('--fixture',type=Path)
    ap.add_argument('--build-dir',type=Path,default=REPO/'analysis/build/render-mode137')
    ap.add_argument('--case-ids')
    ap.add_argument('--optimization',choices=('O2','O3','both'),default='both')
    ap.add_argument('--no-report',action='store_true')
    args=ap.parse_args()
    source=args.source_root.resolve()
    if (source!=REPO or args.fixture or args.case_ids or args.optimization!='both') and not args.no_report:
        ap.error('Custom sources/fixtures/cohorts/builds require --no-report')
    fixture=(args.fixture or source/FIXTURE).resolve()
    corpus=json.loads(fixture.read_text())
    assert set(corpus)=={'schema','declared_count','cases'}
    assert corpus['schema']=='render-mode137-input-v1'
    assert corpus['declared_count']==len(corpus['cases'])
    if not args.fixture:assert len(corpus['cases'])==CANONICAL_COUNT
    allowed={'id','group','entry','real','imaginary','source','labels','settings',
             'ordinary_regression','cached_tokens'}
    for index,case in enumerate(corpus['cases']):
        assert set(case)<=allowed and case['id']==index
        assert len(bytes.fromhex(case['real']))==10
        assert len(bytes.fromhex(case['imaginary']))==10
        assert case['entry'] in (0x8000,0xc060,0x37bc,0xb070)
        assert 0<=case['source']<=0xffec
    cases=corpus['cases']
    if args.case_ids:
        selected={int(value) for value in args.case_ids.split(',')}
        assert selected<=set(range(len(cases)))
        cases=[case for case in cases if case['id'] in selected]
    build=args.build_dir.resolve();build.mkdir(parents=True,exist_ok=True)
    tmp=build/'compiler-tmp';tmp.mkdir(exist_ok=True)
    env=dict(os.environ,TMPDIR=str(tmp))
    os.environ['TMPDIR']=str(tmp) # unchanged native oracle compiler inherits this scratch path
    python_paths=[Path(__file__),REPO/'tools/c_build_inputs.py',REPO/'tools/c_verification.py']
    python_paths += [path for path in (REPO/'tools/nxu8').rglob('*.py') if path.is_file()]
    oracle_paths=[path for path in (REPO/'tools/nxu8').rglob('*') if path.is_file() and path.suffix in ('.c','.h','.txt')]
    closure=implementation_inputs(source,SOURCES)
    c_pins={name:sha(source/name) for name in closure}
    additional={str(path):sha(path) for path in python_paths+oracle_paths+[fixture,source/'tools/render_mode137_support/adapter.c',REPO/'firmware/fx-991es-plus-c-ver4.bin']}
    before={**c_pins,**additional}
    rom=(REPO/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rbuf=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    memory=(C.c_uint8*65536)();render=Render(rbuf,len(rom),memory)
    native=Machine(rom,build/'oracle')
    builds={};all_rows=[];failures=[];checks=0;flush_calls=0;host_rows=[]

    def put(address,data):
        for offset,byte in enumerate(data):memory[(address+offset)&65535]=native.ram[(address+offset)&65535]=byte
    def word(address,value):put(address,value.to_bytes(2,'little'))
    def reset(case):
        native.reset();C.memset(memory,0,65536)
        for address,value in {0x80f9:137,0x80fc:1,0x80fe:1,0x8104:1,
            0x8105:4,0x8106:1,0x8108:1,0x811f:10,0x8121:1,0xf031:0x5a}.items():put(address,bytes([value]))
        word(0x812c,0x8200)
        put(0x8dee,rom[0x1f8be:0x1f8d0])
        put(0x87d0,bytes((n*17+3)&255 for n in range(384)))
        put(0xf800,bytes((n*7+17)&255 for n in range(512)))
        put(0x9800,bytes((n*31+5)&255 for n in range(256)))
        for name,value in case['settings'].items():put(int(name,16),bytes([value]))
        if case['source']:put(case['source'],bytes.fromhex(case['real']+case['imaginary']))
        if 'cached_tokens' in case:put(0x8398,bytes.fromhex(case['cached_tokens']))
        label=case['labels']
        if label=='swap':word(0x8df2,0x1937);word(0x8df4,0x1931)
        elif label=='ram':
            put(0x9100,b'NO\0');put(0x9140,b'YES\0');word(0x8df2,0x9100);word(0x8df4,0x9140)
        elif label=='length25':
            put(0x9100,b'F'*25+b'\0');put(0x9140,b'T'*25+b'\0');word(0x8df2,0x9100);word(0x8df4,0x9140)
        elif label=='structured':
            put(0x9100,bytes.fromhex('5eb832b900'));put(0x9140,bytes.fromhex('5eb833b900'));word(0x8df2,0x9100);word(0x8df4,0x9140)
        elif label=='raw_suffix':
            put(0x9100,bytes.fromhex('9091a100'));put(0x9140,bytes.fromhex('e0e13200'));word(0x8df2,0x9100);word(0x8df4,0x9140)
        elif label=='null_false':word(0x8df2,0)
        elif label=='null_true':word(0x8df4,0)
        else:assert label=='startup'

    def tokens_at(ram,address,limit=512):
        data=bytes(ram[address:address+limit]);return data[:data.index(0)]
    def run_to(pc):
        status=native.lib.harness_run(2000000,pc,False)
        if status!=100:raise RuntimeError(f'original status{status} at{native.lib.harness_get_pc():x}, wanted{pc:x}')
    def native_display(case,special):
        native.er(0,case['source'])
        if not special:
            native.call(case['entry'],limit=2000000);return None
        native.lib.harness_set_sp(0x8dee);native.lib.harness_set_lr(0x2fffe)
        native.lib.harness_set_pc(case['entry'])
        run_to(0x37c2);frame=native.er(14)
        run_to(0x37ee);text=tokens_at(native.ram,frame-26,26)
        run_to(0x2fffe);return text
    def compare_region(start,length,label,case,opt):
        nonlocal checks
        checks+=1
        a=bytes(memory[start:start+length]);b=bytes(native.ram[start:start+length])
        if a!=b:
            offset=next(n for n,(x,y) in enumerate(zip(a,b)) if x!=y)
            failures.append({'id':case['id'],'group':case['group'],'optimization':opt,
                'observable':label,'address':hex(start+offset),'native':b[offset],'C':a[offset]})

    for opt in ('O2','O3') if args.optimization=='both' else (args.optimization,):
        library=build/f'mode137-{opt}.so'
        subprocess.run(['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined',
            *(str(source/name) for name in SOURCES),str(source/'tools/render_mode137_support/adapter.c'),'-o',str(library)],check=True,env=env)
        lib=C.CDLL(str(library));rp=C.POINTER(Render);byte=C.c_uint8
        lib.mode137_format_address.argtypes=[rp,C.c_uint16,C.c_int,C.POINTER(byte),C.c_size_t,C.POINTER(Result)]
        lib.mode137_display.argtypes=[rp,C.c_uint16,C.c_uint,C.POINTER(Box)]
        lib.mode137_abi.argtypes=[C.c_uint];lib.mode137_abi.restype=C.c_size_t
        for field,value in enumerate([C.sizeof(Number),C.sizeof(Render),Render.memory.offset,C.sizeof(Result),Result.kind.offset,C.sizeof(Box)]):
            checks+=1;assert lib.mode137_abi(field)==value
        lib.fx_flush_framebuffer.argtypes=[rp]
        art_before=sha(library);native_before=sha(build/'oracle/nxu8-harness.so')
        # Bounded output writes, required length, terminator and unchanged
        # renderer state are tested independently from the original oracle.
        lib.fx_format_verify_result.argtypes=[rp,C.POINTER(Number),C.POINTER(byte),C.c_size_t,C.POINTER(Result)]
        lib.fx_display_special_real_number.argtypes=[rp,C.POINTER(Number),C.POINTER(Box)]
        for zero,spelling in ((True,b'FALSE'),(False,b'TRUE')):
            reset(corpus['cases'][0]);number=Number((byte*10).from_buffer_copy(bytes.fromhex('00000000000000000000' if zero else '01000000000000000001')))
            before_memory=bytes(memory)
            for capacity in range(8):
                buffer=(byte*12)(*([0xa5]*12));result=Result()
                status=lib.fx_format_verify_result(C.byref(render),C.byref(number),C.cast(C.byref(buffer,2),C.POINTER(byte)),capacity,C.byref(result))
                expected=0 if len(spelling)<capacity else -2
                okay=status==expected and result.length==len(spelling) and not result.kind and not result.recognized and bytes(buffer[:2])==b'\xa5'*2 and bytes(buffer[2+capacity:])==b'\xa5'*(10-capacity) and bytes(memory)==before_memory
                if capacity:okay=okay and buffer[2+min(len(spelling),capacity-1)]==0 and bytes(buffer[2:2+min(len(spelling),capacity-1)])==spelling[:max(capacity-1,0)]
                checks+=1;host_rows.append({'optimization':opt,'control':'capacity','zero':zero,'capacity':capacity,'pass':okay})
                if not okay:failures.append(host_rows[-1])
        reset(corpus['cases'][0]);number=Number((byte*10).from_buffer_copy(bytes.fromhex('01000000000000000001')));buffer=(byte*16)(*([0xa5]*16));result=Result(0xa5,0xa5,0xa5)
        invalid_render=Render(None,len(rom),memory);status=lib.fx_format_verify_result(C.byref(invalid_render),C.byref(number),buffer,len(buffer),C.byref(result))
        okay=status==-1 and bytes(buffer)==b'\xa5'*16 and result.length==0xa5 and result.kind==0xa5 and result.recognized==0xa5;checks+=1;host_rows.append({'optimization':opt,'control':'NULL-ROM-nonzero-size-invalid','pass':okay})
        if not okay:failures.append(host_rows[-1])
        put(0x9100,b'YES\0');word(0x8df4,0x9100);ram_render=Render(None,0,memory);status=lib.fx_format_verify_result(C.byref(ram_render),C.byref(number),buffer,len(buffer),C.byref(result))
        okay=status==0 and result.length==3 and bytes(buffer[:4])==b'YES\0';checks+=1;host_rows.append({'optimization':opt,'control':'NULL-ROM-zero-size-RAM-label','pass':okay})
        if not okay:failures.append(host_rows[-1])
        reset(corpus['cases'][0]);put(0x9100,b'T'*26+b'\0');word(0x8df4,0x9100);number=Number((byte*10).from_buffer_copy(bytes.fromhex('01000000000000000001')));before_memory=bytes(memory)
        status=lib.fx_display_special_real_number(C.byref(render),C.byref(number),C.byref(Box()))
        okay=status==-1 and bytes(memory)==before_memory;checks+=1;host_rows.append({'optimization':opt,'control':'special26-static-frame-boundary','pass':okay})
        if not okay:failures.append(host_rows[-1])
        rows=[];group_counts={}
        for case in cases:
            reset(case);entry=case['entry'];record_before=bytes(memory[case['source']:case['source']+20]) if case['source'] else b''
            row={'id':case['id'],'group':case['group'],'optimization':opt}
            try:
                if entry in (0x8000,0xc060):
                    native.er(0,case['source']);native.er(2,0x9000);native.word(0x8dee,0)
                    native.call(entry,limit=2000000)
                    out=(byte*512)();result=Result()
                    status=lib.mode137_format_address(C.byref(render),case['source'],entry==0x8000,out,len(out),C.byref(result))
                    expected=tokens_at(native.ram,0x9000)
                    actual=bytes(out[:result.length])
                    checks+=4
                    if status!=0 or expected!=actual or result.kind!=0 or result.recognized!=0:
                        failures.append({'id':case['id'],'optimization':opt,'group':case['group'],'native_tokens':expected.hex(),'C_tokens':actual.hex(),'status':status,'kind':result.kind})
                    row.update(native_tokens=expected.hex(),C_tokens=actual.hex(),C_status=status,native_return=native.reg(0))
                    compare_region(0x8100,0x60,'selection/cache/settings',case,opt)
                    compare_region(0xf000,0x200,'MMIO',case,opt)
                else:
                    special=entry==0x37bc or bool(memory[0x80fc]&0x10 and memory[0x80fe] in (0,3,5))
                    native_text=native_display(case,special)
                    status=lib.mode137_display(C.byref(render),case['source'],entry,C.byref(Box()))
                    checks+=1
                    if status!=1:failures.append({'id':case['id'],'optimization':opt,'group':case['group'],'C_status':status,'native_return':native.reg(0)})
                    for start,length,label in [(0x80dc,0x5c,'globals'),(0x8100,0x100,'settings'),(0x829e,0x3a2,'retained values'),
                        (0x87d0,384,'RAMframebuffer'),(0x8950,0x2b0,'RAMafterframe'),(0x8df0,0x6210,'persistentRAMandLCD')]:
                        compare_region(start,length,label,case,opt)
                    if not special and memory[0x8126]:
                        # Only the active viewport metric descriptors are public.
                        compare_region(0x8000,6,'viewportstate',case,opt)
                        compare_region(0x8007,4,'viewportcounts',case,opt)
                        if memory[0x8008]:compare_region(0x8640,memory[0x8008]*4,'active metrics',case,opt)
                    if special and memory[0x80f9]==137:
                        out=(byte*512)();result=Result()
                        if case['source']:
                            lib.mode137_format_address(C.byref(render),case['source'],0,out,len(out),C.byref(result))
                            actual=bytes(out[:result.length])
                        else:actual=b''
                        checks+=1
                        if native_text!=actual:failures.append({'id':case['id'],'optimization':opt,'group':case['group'],'native_tokens':native_text.hex(),'C_tokens':actual.hex()})
                        row['native_tokens']=native_text.hex();row['C_tokens']=actual.hex()
                    row.update(C_status=status,native_return=native.reg(0),
                        framebuffer_sha256=hashlib.sha256(bytes(native.ram[0x87d0:0x8950])).hexdigest(),
                        history_sha256=hashlib.sha256(bytes(native.ram[0x9800:0x9900])).hexdigest())
                    native.call(0x3cfc);flush_calls+=1;lib.fx_flush_framebuffer(C.byref(render))
                    compare_region(0xf800,512,'allLCDafterflush',case,opt)
                checks+=1
                if record_before and bytes(memory[case['source']:case['source']+20])!=record_before:
                    failures.append({'id':case['id'],'optimization':opt,'group':case['group'],'source_mutated':True})
            except (RuntimeError,ValueError) as error:
                failures.append({'id':case['id'],'optimization':opt,'group':case['group'],'native_boundary':str(error)})
            rows.append(row);group_counts[case['group']]=group_counts.get(case['group'],0)+1
            if len(failures)>40:break
        assert art_before==sha(library) and native_before==sha(build/'oracle/nxu8-harness.so')
        builds[opt]={'cases':len(rows),'groups':group_counts,'C_library_sha256':art_before,'native_library_sha256':native_before}
        all_rows+=rows
        print(json.dumps({'optimization':opt,'cases':len(rows),'checks_so_far':checks,'failures_so_far':len(failures)}),flush=True)
        if failures:break
    after={name:sha(source/name) for name in closure}
    after.update({str(path):sha(path) for path in python_paths+oracle_paths+[fixture,source/'tools/render_mode137_support/adapter.c',REPO/'firmware/fx-991es-plus-c-ver4.bin']})
    assert before==after
    proof={'status':'pass' if not failures else 'fail','full_firmware_complete':False,
        'checks':checks,'native_calls':len(all_rows)+flush_calls,'primary_native_calls':len(all_rows),'flush_native_calls':flush_calls,'input_cases':len(cases),'host_controls':host_rows,'builds':builds,
        'failures':failures,'rows':all_rows,'tested_inputs_sha256':before,'source_drift':False,
        'scope':'Original8000/C060 Boolean tokens;37BC and B070 complete exposed settings/framebuffer/history/LCD state. C projection preserves raw class1 semantics rather than numerical-zero recognition.',
        'limits':['Native numeric workspace8000..80DB excluded except active viewport fields; inactive8640..877F pool/metric scratch excluded.',
                  'Prepared CPU stack8C00..8DEF and arbitrary overlap of numeric scratch with label/source strings are outside the record renderer API.',
                  'Finite canonical prepared labels and default startup strings; native call-frame corruption from special labels>=26 is a separate architectural boundary.',
                  '80FFbit4 ordinary paired/status labels remain outside this ordinary API; E844special branch precedes them and is tested.']}
    report=build/'proof.json';report.write_text(json.dumps(proof,indent=2)+'\n')
    if not failures and not args.no_report:
        public={key:value for key,value in proof.items() if key not in ('rows','tested_inputs_sha256')}
        dependencies=sorted(set(closure+[str(path.resolve().relative_to(REPO)) for path in python_paths+oracle_paths+[fixture,source/'tools/render_mode137_support/adapter.c',REPO/'firmware/fx-991es-plus-c-ver4.bin'] if path.suffix in ('.c','.h','.py','.json','.bin')]))
        isa_key='tools/nxu8/isa.txt';isa_path=REPO/isa_key;isa_hash=additional[str(isa_path)]
        assert sha(isa_path)==isa_hash
        published=write_report(build/'publication-staging.json',public,dependencies,str(Path(__file__).relative_to(REPO)))
        assert sha(isa_path)==isa_hash
        published['tested_inputs_sha256'][isa_key]=isa_hash
        target=REPO/'analysis/c-verification/render_mode137.json';target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(published,indent=2)+'\n')
    print(json.dumps({key:value for key,value in proof.items() if key not in ('rows','tested_inputs_sha256')},indent=2))
    return bool(failures)

if __name__=='__main__':raise SystemExit(main())
