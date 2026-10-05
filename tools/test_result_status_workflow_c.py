#!/usr/bin/env python3
"""Prepared B070/C060/equation status workflow against unchanged firmware.

Inputs carry only settings, source records and retained replay/caption data.
The C module never executes the independent original CPU used by this test.
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

DEFAULT_SOURCE=Path(__file__).resolve().parents[1]
REPO=DEFAULT_SOURCE
while not (REPO/'firmware/fx-991es-plus-c-ver4.bin').is_file():
    if REPO==REPO.parent:raise RuntimeError("Original test fixture root not found")
    REPO=REPO.parent
sys.path.insert(0,str(REPO/'tools'))
from c_build_inputs import implementation_inputs
from c_verification import write_report
from nxu8.machine import Machine

SOURCES=['csrc/render/fx_result_verify.c', 'csrc/render/fx_result_special.c', 'csrc/render/fx_result_complex.c', 'csrc/render/fx_render.c', 'csrc/render/fx_render_context.c', 'csrc/render/fx_render_memory.c', 'csrc/render/fx_layout.c', 'csrc/render/fx_layout_validate.c', 'csrc/render/fx_viewport.c', 'csrc/render/fx_result_format_state.c', 'csrc/render/fx_result_inequality.c', 'csrc/complex/fx_complex.c', 'csrc/complex/fx_complex_angle.c', 'csrc/format/fx_format.c', 'csrc/format/fx_format_budget.c', 'csrc/format/fx_format_base.c', 'csrc/trig/fx_trig.c', 'csrc/trig/fx_trig_math.c', 'csrc/trig/fx_trig_inverse.c', 'csrc/trig/fx_math_context.c', 'csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_surd_components.c', 'csrc/numeric/fx_raw_decimal_divide.c', 'csrc/numeric/fx_raw_decimal_multiply_add.c', 'csrc/numeric/fx_raw_decimal_parts.c', 'csrc/render/fx_result_pair.c', 'csrc/render/fx_result_status_workflow.c', 'csrc/platform/fx_persistent.c', 'csrc/platform/fx_host_bridge.c', 'csrc/platform/fx_platform.c', 'csrc/ui/fx_cursor.c']
FIXTURE='analysis/native-fixtures/result-status-workflow/inputs.json'
ADAPTER='tools/result_status_workflow_support/adapter.c'
CANONICAL_COUNT=2692

class Number(C.Structure):
    _fields_=[('bytes',C.c_uint8*10)]
class Render(C.Structure):
    _fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),
              ('memory',C.POINTER(C.c_uint8))]
class Result(C.Structure):
    _fields_=[('length',C.c_size_t),('kind',C.c_uint8),('recognized',C.c_uint8)]
class Box(C.Structure):
    _fields_=[('width',C.c_uint16),('height',C.c_uint8),('depth',C.c_uint8)]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate(corpus,canonical):
    assert set(corpus)=={'schema','declared_count','cases'}
    assert corpus['schema']=='result-status-workflow-input-v1'
    assert type(corpus['declared_count']) is int
    assert corpus['declared_count']==len(corpus['cases'])
    if canonical:assert corpus['declared_count']==CANONICAL_COUNT
    required={'id','group','settings','real','imaginary','source','entry','replay_count'}
    optional={'query','caption','cached'}
    for index,case in enumerate(corpus['cases']):
        assert required<=set(case)<=required|optional and case['id']==index
        assert type(case['id']) is int and isinstance(case['group'],str)
        assert case['entry'] in (0xb070,0xc060)
        assert type(case['source']) is int and 0<=case['source']<=0xffec
        assert type(case['replay_count']) is int and 0<=case['replay_count']<=17
        for key in ('real','imaginary'):
            assert isinstance(case[key],str) and len(case[key])==20
            assert len(bytes.fromhex(case[key]))==10
        assert isinstance(case['settings'],dict)
        for address,value in case['settings'].items():
            assert isinstance(address,str) and address.startswith('0x')
            assert 0x8000<=int(address,16)<=65535
            assert type(value) is int and 0<=value<=255
        if 'query' in case:
            assert isinstance(case['query'],list) and len(case['query'])==2
            assert case['query'][0] in (0,1) and type(case['query'][1]) is int
            assert 0<=case['query'][1]<=17 and case['entry']==0xb070
        if 'caption' in case:
            assert isinstance(case['caption'],str) and len(case['caption'])<=16
            assert all(0<ord(ch)<128 for ch in case['caption'])
        if 'cached' in case:
            assert isinstance(case['cached'],str) and len(case['cached'])<=512
            data=bytes.fromhex(case['cached']);assert data and data[-1]==0

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=DEFAULT_SOURCE)
    parser.add_argument('--fixture',type=Path)
    parser.add_argument('--build-dir',type=Path,default=REPO/'analysis/build/result-status-workflow/portable')
    parser.add_argument('--case-ids')
    parser.add_argument('--optimization',choices=('O2','O3','both'),default='both')
    parser.add_argument('--no-report',action='store_true')
    args=parser.parse_args()
    source=args.source_root.resolve()
    custom=source!=REPO or args.fixture or args.case_ids or args.optimization!='both'
    if custom and not args.no_report:
        parser.error('Custom sources/fixtures/cohorts/builds require --no-report')
    fixture=(args.fixture or source/FIXTURE).resolve()
    corpus=json.loads(fixture.read_text())
    validate(corpus,not args.fixture)
    cases=corpus['cases']
    if args.case_ids:
        selected={int(value) for value in args.case_ids.split(',')}
        assert selected<=set(range(len(cases)))
        cases=[case for case in cases if case['id'] in selected]
    build=args.build_dir.resolve();build.mkdir(parents=True,exist_ok=True)
    tmp=build/'compiler-tmp';tmp.mkdir(exist_ok=True)
    os.environ['TMPDIR']=str(tmp)
    env=dict(os.environ)
    closure=implementation_inputs(source,SOURCES)
    oracle=[p for p in (REPO/'tools/nxu8').rglob('*')
            if p.is_file() and p.suffix in ('.py','.c','.h','.txt')]
    executed=[Path(__file__),REPO/'tools/c_build_inputs.py',REPO/'tools/c_verification.py',
              fixture,source/ADAPTER,REPO/'firmware/fx-991es-plus-c-ver4.bin',*oracle]
    asm=REPO/'analysis/disassembly/complete.asm'
    all_paths=sorted(set([source/name for name in closure]+executed+[asm]))
    before={str(path):sha(path) for path in all_paths}
    rom=(REPO/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_buffer=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    memory=(C.c_uint8*65536)()
    render=Render(rom_buffer,len(rom),memory)
    native=Machine(rom,build/'oracle')
    failures=[];rows=[];builds={};checks=0;flush_calls=0;traces={}
    coverage_addresses=(0x37bc,0xb4b0,0xc2aa,0x382e,0xc060,0xaf5a,
                        0x1e9a0,0x18366,0x8000,0x158b8,0xb468)

    def put(address,data):
        for index,byte in enumerate(data):
            memory[(address+index)&65535]=native.ram[(address+index)&65535]=byte
    def word(address,value):
        put(address,value.to_bytes(2,'little'))
    def reset(case):
        native.reset();C.memset(memory,0,65536)
        for address,value in {0x80f9:69,0x80fa:4,0x80fc:1,0x80fd:0,
          0x80fe:1,0x8104:1,0x8105:4,0x8106:1,0x8108:1,0x811f:10,
          0x8121:1,0xf031:0x5a}.items():put(address,bytes([value]))
        word(0x812c,0x8200)
        put(0x8dee,rom[0x1f8be:0x1f8d0])
        put(0x87d0,bytes((n*17+3)&255 for n in range(384)))
        put(0xf800,bytes((n*7+17)&255 for n in range(512)))
        put(0x9800,bytes((n*31+5)&255 for n in range(512)))
        for address,value in case['settings'].items():put(int(address,16),bytes([value]))
        if case['source']:put(case['source'],bytes.fromhex(case['real']+case['imaginary']))
        count=case['query'][1] if 'query' in case else case['replay_count']
        for n in range(count):put(0x8406+14*n+13,b':')
        if 'cached' in case:
            mode=case['settings'].get('0x80f9',69)
            put(0x8398 if mode==137 else 0x8546,bytes.fromhex(case['cached']))
        if 'caption' in case:
            table=(0x8dfa+2*((case['settings']['0x8135']-1)&255))&65535
            word(table,0x9300);put(0x9300,case['caption'].encode()+b'\0')

    def compare(start,length,label,case,opt):
        nonlocal checks
        checks+=1
        a=bytes(memory[start:start+length]);b=bytes(native.ram[start:start+length])
        if a!=b:
            differences=[{'address':hex(start+n),'original':y,'C':x}
                         for n,(x,y) in enumerate(zip(a,b)) if x!=y]
            failures.append({'id':case['id'],'group':case['group'],
                'optimization':opt,'observable':label,'differences':differences[:16],
                'different_bytes':len(differences)})
    def terminated(ram,address):
        data=bytes(ram[address:address+512])
        return data[:data.index(0)]

    trace_groups={'eq-live-replay','caption-custom','verify-pair-natural',
                  'special-all-bit4','base-valid','cache-priority','polar'}
    traced=set()
    for opt in ('O2','O3') if args.optimization=='both' else (args.optimization,):
        library=build/f'workflow-{opt}.so'
        command=['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror',
            '-shared','-fPIC','-fvisibility=hidden','-ffunction-sections',
            '-fdata-sections','-Wl,--gc-sections','-Wl,--no-undefined',
            *(str(source/name) for name in SOURCES),str(source/ADAPTER),'-o',str(library)]
        subprocess.run(command,check=True,env=env)
        lib=C.CDLL(str(library));rp=C.POINTER(Render);byte=C.c_uint8
        lib.workflow_display.argtypes=[rp,C.c_uint16,C.POINTER(Box)]
        lib.workflow_query.argtypes=[rp,C.c_int,C.POINTER(byte)]
        lib.workflow_format.argtypes=[rp,C.POINTER(Number),byte,C.POINTER(byte),C.POINTER(Result)]
        lib.workflow_flush.argtypes=[rp]
        lib.workflow_abi.argtypes=[C.c_uint];lib.workflow_abi.restype=C.c_size_t
        for field,size in enumerate([C.sizeof(Number),C.sizeof(Render),Render.memory.offset,
                                    C.sizeof(Result),Result.kind.offset,C.sizeof(Box)]):
            checks+=1;assert lib.workflow_abi(field)==size
        artifacts={str(library):sha(library),
                   str(build/'oracle/nxu8-harness.so'):sha(build/'oracle/nxu8-harness.so')}
        group_counts={};start=len(rows)
        for case in cases:
            reset(case)
            record=bytes(memory[case['source']:case['source']+20]) if case['source'] else b''
            row={'id':case['id'],'group':case['group'],'optimization':opt}
            trace_path=None
            if opt=='O2' and case['group'] in trace_groups and case['group'] not in traced:
                traced.add(case['group'])
                trace_path=build/f"trace-{case['group']}-{case['id']}.jsonl"
                native.trace_open(trace_path,True)
            try:
                if 'query' in case:
                    which=case['query'][0]
                    native.call(0x382e if which else 0xc2aa,limit=4000000)
                    out=byte(0xa5)
                    status=lib.workflow_query(C.byref(render),which,C.byref(out))
                    checks+=2
                    row.update(native_result=native.reg(0),C_result=out.value,C_status=status)
                    if status or out.value!=native.reg(0):failures.append(row.copy())
                    compare(0x80dc,0x64,'persistent-query-state',case,opt)
                    compare(0x8406,250,'replay-readonly',case,opt)
                elif case['entry']==0xc060:
                    native.er(0,case['source']);native.er(2,0x9400);native.word(0x8dee,0)
                    native.call(0xc060,limit=4000000)
                    number=Number((byte*10).from_buffer_copy(bytes.fromhex(case['real'])))
                    buffer=(byte*516)(*([0xa5]*516));result=Result()
                    status=lib.workflow_format(C.byref(render),C.byref(number),0,
                                              C.cast(C.byref(buffer,2),C.POINTER(byte)),C.byref(result))
                    expected=terminated(native.ram,0x9400);actual=bytes(buffer[2:2+result.length])
                    checks+=4
                    okay=status==1 and result.kind==native.reg(0) and actual==expected
                    okay=okay and bytes(buffer[:2])==b'\xa5'*2 and bytes(buffer[514:])==b'\xa5'*2
                    if not okay:failures.append({'id':case['id'],'optimization':opt,
                        'native_kind':native.reg(0),'C_kind':result.kind,'C_status':status,
                        'native_tokens':expected.hex(),'C_tokens':actual.hex()})
                    row.update(native_kind=native.reg(0),C_kind=result.kind,C_status=status,
                               native_tokens=expected.hex(),C_tokens=actual.hex())
                    compare(0x80dc,0x64,'persistent-formatter-state',case,opt)
                    compare(0xf000,512,'formatter-MMIO',case,opt)
                else:
                    native.er(0,case['source']);native.call(0xb070,limit=4000000)
                    box=Box()
                    status=lib.workflow_display(C.byref(render),case['source'],C.byref(box))
                    checks+=1
                    row.update(C_status=status,native_return=native.reg(0))
                    if status!=1:failures.append(row.copy())
                    for first,length,label in ((0x80dc,0x64,'persistent-display-state'),
                      (0x87d0,384,'all-shadow-pixels'),(0xf800,512,'all-LCD-bytes'),
                      (0x9800,512,'complete-history-region'),(0xf000,512,'MMIO'),
                      (0x8546,128,'equation-output-inactive-tail'),
                      (0x8398,108,'verify-output-inactive-tail')):
                        compare(first,length,label,case,opt)
                    row['framebuffer_sha256']=hashlib.sha256(bytes(native.ram[0x87d0:0x8950])).hexdigest()
                    row['history_sha256']=hashlib.sha256(bytes(native.ram[0x9800:0x9a00])).hexdigest()
                    native.call(0x3cfc,limit=4000000);flush_calls+=1
                    lib.workflow_flush(C.byref(render))
                    compare(0xf800,512,'all-LCD-after-flush',case,opt)
                if case['group'] in ('ordinary-surd-pool','raw-surd-whole-guard'):
                    compare(0x8640,60,'six-ordered-surd-components',case,opt)
                checks+=1
                if record and bytes(memory[case['source']:case['source']+20])!=record:
                    failures.append({'id':case['id'],'optimization':opt,'source_changed':True})
                row['native_call_coverage']={hex(address):int(native.counts[address//2])
                    for address in coverage_addresses if native.counts[address//2]}
            except (RuntimeError,ValueError) as error:
                failures.append({'id':case['id'],'optimization':opt,'native_boundary':str(error)})
            finally:
                if trace_path:
                    native.trace_close();traces[str(trace_path)]=sha(trace_path)
            rows.append(row);group_counts[case['group']]=group_counts.get(case['group'],0)+1
        assert all(sha(Path(path))==digest for path,digest in artifacts.items())
        builds[opt]={'cases':len(rows)-start,'groups':group_counts,
                     'artifacts':artifacts,'compiler_command':command}
        print(json.dumps({'optimization':opt,'cases':len(rows)-start,
                          'checks':checks,'failures':len(failures)}),flush=True)
    after={str(path):sha(path) for path in all_paths}
    assert before==after
    proof={'status':'pass' if not failures else 'fail','full_firmware_complete':False,
       'input_cases':len(cases),'checks':checks,'native_calls':len(rows)+flush_calls,
       'primary_native_calls':len(rows),'flush_native_calls':flush_calls,
       'builds':builds,'failures':failures,'rows':rows,'traces_sha256':traces,
       'tested_inputs_sha256':before,'source_drift':False,
       'scope':'Prepared equation69 B070 ordinary/pair/caption, C2AA/382E live replay policy, VERIFY137/legacyMATRIX6/VECTOR7/BASE2 paired branches, and E844 paired budget/priority. Full exposed pixels/history/selection/MMIO and dormant output tails; native CPU is an independent test oracle only.',
       'limits':['Numeric scratch8000..80DB and pool beyond the explicitly compared ordinary SURD six-record cohort, inactive viewport scratch, and fixed prepared CPU stack8C00..8DEF are separate from this renderer API.',
          'Source/replay/caption strings must be disjoint from result/framebuffer/history/settings. Original CPU local/frame aliases are not modeled.',
          'Natural MATRIX6/VECTOR7/BASE2 output uses a native CPU-local token buffer and remains an explicit unsupported boundary.',
          'Legacy paired numeric strings wider than16 and special numeric strings>=26/captions>16 are explicit original local-field boundaries. Invalid BASE byte4 pilot is retained separately, not claimed as returned C parity.',
          'No top equation C236 caption, full key workflow or generalized physical numeric-workspace parity is claimed. Already-supported ordinary rendering is delegated.']}
    target=build/'proof.json';target.write_text(json.dumps(proof,indent=2)+'\n')
    if not failures and not args.no_report:
        public={key:value for key,value in proof.items() if key not in ('rows','tested_inputs_sha256')}
        dependencies=sorted(set(closure+[str(path.relative_to(REPO)) for path in executed
            if path.suffix in ('.c','.h','.py','.json','.bin')]))
        isa=REPO/'tools/nxu8/isa.txt';isa_hash=before[str(isa)]
        assert sha(isa)==isa_hash
        published=write_report(build/'publication-staging.json',public,dependencies,
                               str(Path(__file__).relative_to(REPO)))
        assert sha(isa)==isa_hash
        published['tested_inputs_sha256']['tools/nxu8/isa.txt']=isa_hash
        published['static_listing_sha256']=before[str(asm)]
        output=REPO/'analysis/c-verification/result_status_workflow.json'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(published,indent=2)+'\n')
    print(json.dumps({'status':proof['status'],'input_cases':len(cases),
                      'checks':checks,'native_calls':proof['native_calls'],
                      'proof':str(target),'failures':len(failures)},indent=2))
    return bool(failures)

if __name__=='__main__':raise SystemExit(main())
