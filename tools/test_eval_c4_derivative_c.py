#!/usr/bin/env python3
"""Compare complete C4 derivative expressions and finalizer controls with ROM171F4."""
import argparse
import ctypes as C
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

SCRIPT_REPO=Path(__file__).resolve().parents[1]
COHORTS={'derivative_initial':170,'derivative_aliases':112,'derivative_syntax':28,'finalizer':20}
DEFAULT_FIXTURE_SHA256='46b975c9179abb598676047a5281e7f83fa32120992ab31997f800189fd818bb'
DEFAULT_INVENTORY_SHA256='970755e7a6b3924d41177a0712ccea9f8ba40abf45deb114976fcd8bfa5f700e'
REQUIRED={'body','point','imaginary','point_mate','tolerance','tolerance_mate','abort','poison'}
OPTIONAL={'coefficient','mode_call','mode_value','source','output','cursor_address','tokens'}
BODIES={'X','A','i','X+0','A+0','1/0'}

class Number(C.Structure):_fields_=[('bytes',C.c_uint8*10)]
class Pair(C.Structure):_fields_=[('real',Number),('imaginary',Number)]
class Result(C.Structure):_fields_=[('value',Number*2),('consumed',C.c_size_t),('unsupported_token',C.c_uint8)]
class Storage(C.Structure):_fields_=[('ram',C.POINTER(C.c_uint8)),('ram_size',C.c_size_t),('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t)]
class Effects(C.Structure):_fields_=[('equation_used',C.c_uint8),('restricted_state',C.c_uint8)]
class Options(C.Structure):_fields_=[('calculation_context',C.c_uint8),('math_output',C.c_uint8),('angle_unit',C.c_uint8)]
BeforeSample=C.CFUNCTYPE(None,C.POINTER(Storage),C.c_uint16,C.c_uint16,C.c_void_p)
Cancel=C.CFUNCTYPE(C.c_int,C.c_void_p)
class Control(C.Structure):_fields_=[('cancelled',Cancel),('userdata',C.c_void_p)]
class Transport(C.Structure):_fields_=[('input_address',C.c_uint16),('cursor_address',C.c_uint16),('output_address',C.c_uint16),('before_sample',BeforeSample),('userdata',C.c_void_p)]
class Event(C.Structure):_fields_=[('pc',C.c_uint32),('caller',C.c_uint32),('sink',C.c_uint16),('cursor',C.c_uint16),('workspace',C.c_uint8*0x180),('x',C.c_uint8*20)]

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pins(paths):return {str(p.resolve()):digest(p)for p in sorted(set(map(Path,paths)))}
def inventory_hash(fixture):return hashlib.sha256(json.dumps(fixture,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def number(value):
    if type(value)is not str:raise ValueError('number recipes must be strings')
    if value.startswith('raw:'):
        if not re.fullmatch(r'raw:[0-9a-fA-F]{20}',value):raise ValueError('raw number must contain exactly10 bytes')
        return bytes.fromhex(value[4:])
    if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',value):raise ValueError('invalid finite decimal recipe')
    d=Decimal(value)
    if not d:return bytes(10)
    t=d.as_tuple();digits=''.join(map(str,t.digits));exponent=len(digits)-1+t.exponent
    if len(digits)>15 or not -99<=exponent<=99:raise ValueError('decimal recipe exceeds exact finite-record domain')
    digits=digits.ljust(15,'0')
    return bytes([int(digits[0]),*[int(digits[i:i+2],16)for i in range(1,15,2)],int(f'{exponent if exponent>=0 else exponent+100:02}',16),(6 if t.sign else 1)-(exponent<0)])
def tokens_for(case):
    if 'tokens'in case:
        value=case['tokens']
        if type(value)is not str or not value or not re.fullmatch(r'(?:[0-9a-fA-F]{2})+',value):raise ValueError('tokens must be nonempty hexadecimal bytes')
        tokens=bytes.fromhex(value)
        if tokens[-1]!=0:raise ValueError('tokens must include their terminating zero')
        return tokens
    body=b'\x80'if case['body']=='i'else b'1\x4f0'if case['body']=='1/0'else case['body'].encode()
    return b'\x6b'+body+b',B'+(b',C'if case['tolerance']is not None else b'')+b')\0'
def integer(value,low,high,label):
    if type(value)is not int or not low<=value<=high:raise ValueError(label+' is outside its integer input domain')
def validate_fixture(fixture,canonical,path):
    if type(fixture)is not dict or set(fixture)!={'version',*COHORTS}:raise ValueError('fixture requires exact version/cohort input-only keys')
    if type(fixture['version'])is not int or fixture['version']!=1:raise ValueError('unsupported fixture version')
    total=0
    for cohort,count in COHORTS.items():
        cases=fixture[cohort]
        if type(cases)is not list:raise ValueError(cohort+' must be a list of input recipes')
        if canonical and len(cases)!=count:raise ValueError(cohort+' differs from its guarded default count')
        for case in cases:
            if type(case)is not dict or not REQUIRED<=set(case) or set(case)-REQUIRED-OPTIONAL:raise ValueError('case requires exact input-only schema keys')
            if type(case['body'])is not str or case['body']not in BODIES:raise ValueError('unsupported body recipe')
            for key in ['point','imaginary','point_mate','tolerance_mate']:
                number(case[key])
            if case['tolerance']is not None:number(case['tolerance'])
            if 'coefficient'in case:number(case['coefficient'])
            integer(case['abort'],0,8192,'abort');integer(case['poison'],0,255,'poison')
            if ('mode_call'in case)!=('mode_value'in case):raise ValueError('mode_call and mode_value must appear together')
            if 'mode_call'in case:
                integer(case['mode_call'],1,8192,'mode_call');integer(case['mode_value'],0,255,'mode_value')
            source=case.get('source',0x8a00);output=case.get('output',0x8900);cursor=case.get('cursor_address',0x8190)
            integer(source,0x8000,65535,'source');integer(output,0x8000,65516,'output');integer(cursor,0x8000,65534,'cursor_address')
            if len(tokens_for(case))>65536-source:raise ValueError('input recipe wraps calculator RAM')
        total+=len(cases)
    if not total:raise ValueError('fixture must contain a native input')
    if canonical and(total!=330 or digest(path)!=DEFAULT_FIXTURE_SHA256 or inventory_hash(fixture)!=DEFAULT_INVENTORY_SHA256):raise ValueError('default330 input-only inventory differs from its guarded hashes')
def compiler_closure(sources,includes):
    found=set()
    for source in sources:
        deps=subprocess.check_output(['gcc','-std=c99','-MM',*includes,str(source)],text=True).replace('\\\n',' ')
        found.update(Path(p).resolve()for p in deps.partition(':')[2].split())
    return found

def host_controls(lib,rom_buffer):
    ram=(C.c_uint8*65536)(*([0xa5]*65536));ram[0x80f9]=0xc4
    storage=Storage(ram,65536,rom_buffer,len(rom_buffer));transport=Transport(0x8a00,0x8190,0x8900,BeforeSample(),None)
    result=Result();effects=Effects();C.memset(C.byref(result),0xb6,C.sizeof(result));C.memset(C.byref(effects),0xc7,C.sizeof(effects))
    cases=[]
    def check(name,changes):
        s=Storage(storage.ram,storage.ram_size,storage.rom,storage.rom_size);t=Transport(transport.input_address,transport.cursor_address,transport.output_address,transport.before_sample,None)
        length=1;sp=C.byref(s);tp=C.byref(t);rp=C.byref(result);op=None
        for key,value in changes.items():
            if key=='null_storage':sp=None
            elif key=='null_transport':tp=None
            elif key=='null_result':rp=None
            elif key=='length':length=value
            elif key=='context':op=C.byref(Options(value,1,4))
            elif key in ['ram','ram_size']:setattr(s,key,value)
            else:setattr(t,key,value)
        before=(bytes(ram),bytes(result),bytes(effects));status=lib.fx_evaluate_prepared_physical(length,op,None,None,None,None,sp,tp,C.byref(effects),rp)
        okay=status==-1 and before==(bytes(ram),bytes(result),bytes(effects));cases.append(dict(name=name,status=status,pass_=okay))
    for name,change in [('NULL storage',{'null_storage':True}),('NULL RAM',{'ram':None}),('short RAM',{'ram_size':65535}),('oversized RAM',{'ram_size':65537}),('NULL transport',{'null_transport':True}),('NULL result',{'null_result':True}),('empty input',{'length':0}),('ROM input',{'input_address':0x7fff}),('wrapping input',{'input_address':65535,'length':2}),('ROM cursor',{'cursor_address':0x7fff}),('wrapping cursor',{'cursor_address':65535}),('ROM output',{'output_address':0x7fff}),('wrapping output',{'output_address':65517}),('mismatched mode',{'context':0xc1})]:check(name,change)
    return cases

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root',type=Path,default=SCRIPT_REPO)
    parser.add_argument('--source-root',type=Path,help='custom csrc tree requires --no-report')
    parser.add_argument('--fixture',type=Path,help='custom input-only fixture requires --no-report')
    parser.add_argument('--build-dir',type=Path)
    parser.add_argument('--no-report',action='store_true')
    parser.add_argument('--private-report',type=Path)
    args=parser.parse_args();ROOT=args.repo_root.resolve();DEP=(args.source_root or ROOT/'csrc').resolve()
    private_tool=Path(__file__).resolve()!=(ROOT/'tools/test_eval_c4_derivative_c.py').resolve()
    if(private_tool or args.source_root or args.fixture)and not args.no_report:parser.error('private tool/source/custom fixture requires --no-report')
    if args.private_report and not args.no_report:parser.error('--private-report requires --no-report')
    if args.private_report and args.private_report.resolve().is_relative_to(ROOT/'analysis/c-verification'):parser.error('private report may not target canonical analysis/c-verification')
    fixture_path=(args.fixture or SCRIPT_REPO/'analysis/native-fixtures/eval-c4-derivative/inputs.json').resolve()
    try:
        fixture=json.loads(fixture_path.read_text());validate_fixture(fixture,args.fixture is None,fixture_path)
    except (ValueError,OSError,InvalidOperation)as error:parser.error(str(error))
    if not(ROOT/'firmware/fx-991es-plus-c-ver4.bin').is_file():parser.error('repo root lacks original ROM')
    OUT=(args.build_dir or (SCRIPT_REPO if private_tool else ROOT)/'analysis/build/eval-c4-derivative').resolve();OUT.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(ROOT/'tools'))
    from test_eval_variables_c import SOURCES
    from nxu8.machine import Machine
    if not args.no_report:
        from c_verification import write_report
    observer=Path(__file__).resolve().parent/'nxu8/eval_c4_derivative_events.c';abi=Path(__file__).resolve().parent/'nxu8/eval_c4_derivative_abi.c'
    sources=[DEP/name for name in dict.fromkeys([*SOURCES,'numeric/fx_c4_derivative_storage.c'])]+[abi]
    includes=['-I',str(DEP)];oracle_sources=[observer,ROOT/'tools/nxu8/vendor/SimU8/core.c'];oracle_includes=['-I',str(ROOT/'tools/nxu8')]
    closure=compiler_closure(sources,includes)|compiler_closure(oracle_sources,oracle_includes)
    inputs=closure|{Path(__file__).resolve(),fixture_path,ROOT/'firmware/fx-991es-plus-c-ver4.bin',ROOT/'tools/nxu8/isa.txt'}
    inputs.update((ROOT/'tools/nxu8').rglob('*.py'))
    for module in list(sys.modules.values()):
        path=getattr(module,'__file__',None)
        if path and Path(path).suffix=='.py'and Path(path).resolve().is_relative_to(ROOT/'tools'):inputs.add(Path(path).resolve())
    pre=pins(inputs);libs={};compile_commands={};compiled=[]
    abi_expected=[C.sizeof(Number),Number.bytes.offset,10,C.sizeof(Pair),Pair.real.offset,Pair.imaginary.offset,C.sizeof(Transport),Transport.input_address.offset,Transport.cursor_address.offset,Transport.output_address.offset,Transport.before_sample.offset,Transport.userdata.offset,C.sizeof(Storage),Storage.ram.offset,Storage.ram_size.offset,Storage.rom.offset,Storage.rom_size.offset,C.sizeof(Result),Result.value.offset,20,Result.consumed.offset,Result.unsupported_token.offset,C.sizeof(Effects),Effects.equation_used.offset,Effects.restricted_state.offset,C.sizeof(Control),Control.cancelled.offset,Control.userdata.offset,C.sizeof(Options),Options.calculation_context.offset,Options.math_output.offset,Options.angle_unit.offset]
    for opt in ['O2','O3']:
        so=OUT/('parser-'+opt+'.so');command=['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-pedantic','-shared','-fPIC','-Wl,--no-undefined',*includes,*map(str,sources),'-o',str(so)];subprocess.run(command,check=True);compile_commands[opt]=command;compiled.append(so)
        lib=C.CDLL(str(so));lib.fx_evaluate_prepared_physical.argtypes=[C.c_size_t]+[C.c_void_p]*9;lib.fx_evaluate_prepared_physical.restype=C.c_int;lib.eval_c4_derivative_abi.argtypes=[C.c_uint];lib.eval_c4_derivative_abi.restype=C.c_size_t
        actual=[lib.eval_c4_derivative_abi(i)for i in range(len(abi_expected))]
        if actual!=abi_expected:raise RuntimeError('compiled parser ABI mismatch: '+repr(actual))
        libs[opt]=lib
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();m=Machine(rom,OUT/'native');old=m.lib
    oracle=OUT/'observer.so';oracle_command=['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',*oracle_includes,*map(str,oracle_sources),'-o',str(oracle)];subprocess.run(oracle_command,check=True)
    nl=C.CDLL(str(oracle))
    for name in ['harness_init','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_set_pc','harness_get_pc','harness_ram']:
        getattr(nl,name).argtypes=getattr(old,name).argtypes;getattr(nl,name).restype=getattr(old,name).restype
    m.lib=nl;m.ram=nl.harness_ram().contents;nl.c4_stage.argtypes=[C.c_uint64,C.c_uint32]
    nl.eval_c4_derivative_observer_abi.argtypes=[C.c_uint];nl.eval_c4_derivative_observer_abi.restype=C.c_size_t
    observer_expected=[C.sizeof(Event),Event.pc.offset,Event.caller.offset,Event.sink.offset,Event.cursor.offset,Event.workspace.offset,Event.x.offset,0x180,20]
    observer_actual=[nl.eval_c4_derivative_observer_abi(i)for i in range(len(observer_expected))]
    if observer_expected!=observer_actual:raise RuntimeError('compiled observer ABI mismatch')
    artifacts=pins([*compiled,oracle,OUT/'native/nxu8-harness.so'])
    def count(name):return C.c_uint.in_dll(nl,'c4_'+name)
    rb=(C.c_uint8*len(rom)).from_buffer_copy(rom);ram=(C.c_uint8*65536)();storage=Storage(ram,65536,rb,len(rom))
    host={opt:host_controls(lib,rb)for opt,lib in libs.items()};rows=[];checks={opt:len(abi_expected)+len(host[opt])for opt in libs};failures=[]
    with gzip.open(OUT/'observations.jsonl.gz','wt')as stream, gzip.open(OUT/'events.jsonl.gz','wt')as event_stream:
        for cohort,cases in ((key,fixture[key])for key in COHORTS):
            for cohort_index,case in enumerate(cases):
                index=len(rows);m.reset();nl.c4_reset();count('abort').value=case['abort'];count('mode_call').value=case.get('mode_call',0);count('mode_value').value=case.get('mode_value',0)
                for a,v in [(0x80f9,0xc4),(0x80fc,1),(0x80f5,0xf0),(0x8105,4),(0x8106,1),(0x8121,1)]:m.ram[a]=v
                for a in range(0x8500,0x8680):m.ram[a]=(a*73+case['poison']*31)&255 if case['poison']else 0
                for a,v in [(0x823a,case.get('coefficient','2')),(0x8244,case['point']),(0x824e,case['tolerance']or'0'),(0x8276,'37'),(0x841c,case['imaginary']),(0x8426,case['point_mate']),(0x8430,case['tolerance_mate']),(0x8458,'3')]:m.ram[a:a+10]=number(v)
                tokens=tokens_for(case);source=case.get('source',0x8a00);output=case.get('output',0x8900);cursor=case.get('cursor_address',0x8190)
                m.ram[source:source+len(tokens)]=tokens;m.word(cursor,source);m.word(0x812c,source);m.ram[output:output+20]=b'\xee'*20
                initial=bytes(m.ram);m.er(0,cursor);m.er(2,output);nl.harness_set_sp(0x8dee);nl.harness_set_lr(0x2fffe);nl.harness_set_pc(0x171f4)
                stop=nl.c4_stage(100000000,0x2fffe);after=bytes(m.ram);floor=count('floor').value;event_count=count('event_count').value
                if event_count>8192 or event_count!=count('callbacks').value+count('polls').value:raise RuntimeError('native event buffer exceeded')
                n_events=[dict(kind='poll'if e.pc==0x5564 else'callback',workspace=bytes(e.workspace).hex(),x=bytes(e.x).hex())for e in (Event*8192).in_dll(nl,'c4_events')[:event_count]]
                native=dict(status=m.reg(0),cursor=(m.word(cursor)-source)&65535,pair=after[output:output+20].hex(),callbacks=count('callbacks').value,polls=count('polls').value)
                counts=(C.c_uint64*0x18000).in_dll(nl,'execution_counts');instructions=sum(counts);variants=[]
                for opt,lib in libs.items():
                    C.memmove(ram,initial,65536);c_events=[];c_polls=[0];c_callbacks=[0]
                    @Cancel
                    def cancel(_):
                        c_polls[0]+=1;c_events.append(dict(kind='poll',workspace=bytes(ram[0x8500:0x8680]).hex(),x=(bytes(ram[0x8276:0x8280])+bytes(ram[0x8458:0x8462])).hex()));return int(case['abort']==c_polls[0])
                    @BeforeSample
                    def before_sample(_storage,_cursor,_sink,_):
                        c_callbacks[0]+=1;c_events.append(dict(kind='callback',workspace=bytes(ram[0x8500:0x8680]).hex(),x=(bytes(ram[0x8276:0x8280])+bytes(ram[0x8458:0x8462])).hex()))
                        if c_callbacks[0]==case.get('mode_call',0):ram[0x80f9]=case['mode_value']
                    control=Control(cancel,None);transport=Transport(source,cursor,output,before_sample,None);result=Result();effects=Effects()
                    status=lib.fx_evaluate_prepared_physical(len(tokens),None,None,None,C.byref(control),None,C.byref(storage),C.byref(transport),C.byref(effects),C.byref(result));actual=bytes(ram)
                    diffs=[[f'{a:04x}',after[a],actual[a]]for a in range(0x80dc,65536)if not floor<=a<0x8dee and after[a]!=actual[a]]
                    returned=dict(status=status,cursor=result.consumed,pair=actual[output:output+20].hex(),callbacks=c_callbacks[0],polls=c_polls[0]);events_match=n_events==c_events
                    okay=stop==100 and m.lib.harness_get_pc()==0x2fffe and native==returned and not diffs and events_match
                    checks[opt]+=2+len(native)+(65536-0x80dc-(0x8dee-max(floor,0x80dc)))+3*len(n_events)
                    variant=dict(optimization=opt,pass_=okay,actual=returned,unsupported=result.unsupported_token,ram_differences=diffs,events_match=events_match)
                    if not okay:variant['actual_events']=c_events
                    event_stream.write(json.dumps(dict(index=index,cohort=cohort,optimization=opt,native=n_events,actual=c_events))+'\n')
                    variants.append(variant)
                    stream.write(json.dumps(dict(index=index,cohort=cohort,optimization=opt,initial=initial.hex(),native=after.hex(),actual=actual.hex()))+'\n')
                row=dict(index=index,cohort=cohort,cohort_index=cohort_index,input=case,tokens=tokens.hex(),stop=stop,stop_pc=hex(nl.harness_get_pc()),cpu_local_floor=floor,instructions=instructions,native=native,native_event_count=len(n_events),variants=variants)
                if not all(v['pass_']for v in variants):row['native_events']=n_events
                rows.append(row)
                if not all(v['pass_']for v in variants):failures.append(row)
                if index%20==0 or row in failures:print(json.dumps(dict(index=index,cohort=cohort,status='pass'if row not in failures else'fail',native_status=native['status'])),flush=True)
    for opt,controls in host.items():
        failures.extend(dict(optimization=opt,host_control=c)for c in controls if not c['pass_'])
    changes={p:{'before':h,'after':digest(p)}for p,h in pre.items()if digest(p)!=h};achanges={p:{'before':h,'after':digest(p)}for p,h in artifacts.items()if digest(p)!=h}
    report=dict(suite='eval_c4_derivative',cases=len(rows),native_calls=len(rows),cohorts={key:len(fixture[key])for key in COHORTS},native_instructions=sum(r['instructions']for r in rows),checks=sum(checks.values())+len(observer_expected),checks_per_build=checks,compiled_abi_checks_per_build=len(abi_expected),compiled_observer_abi_checks=len(observer_expected),host_controls_per_build={opt:len(cases)for opt,cases in host.items()},host_controls=host,failures=failures,native_nonreturns=sum(r['stop']!=100 or r['stop_pc']!='0x2fffe'for r in rows),status='pass'if not failures and not changes and not achanges else'fail',fixture_sha256=pre[str(fixture_path)],input_only_inventory_sha256=inventory_hash(fixture),before_execution_inputs_sha256=pre,compiled_artifacts_before_sha256=artifacts,source_changes=changes,artifact_changes=achanges,compile_commands=compile_commands,oracle_compile_command=oracle_command,abi_values=abi_expected,observer_abi_values=observer_actual,rows=rows,observation_archives_sha256=pins([OUT/'observations.jsonl.gz',OUT/'events.jsonl.gz']),scope='Whole prepared171F4 C4 derivative expressions plus separate finalizer compatibility controls: native status/cursor/output, every persistent RAM80DC..FFFF byte outside the original observed CPU frame, ordered callback/poll X/workspace events and counts',limits=['Original CPU-local frame [observed floor,8DEE) is excluded; no CPU state equivalence claim','Prepared host outputs are separate from calculator RAM','This input inventory is bounded evidence, not whole firmware completeness'],full_firmware_complete=False)
    if args.private_report:
        args.private_report.parent.mkdir(parents=True,exist_ok=True);args.private_report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key]for key in ['status','native_calls','cohorts','native_instructions','checks','native_nonreturns','source_changes','artifact_changes']}),flush=True)
    if failures or changes or achanges:return 1
    if not args.no_report:
        dependencies=sorted(str(p.resolve().relative_to(ROOT))for p in inputs if p.suffix in ['.c','.h','.py','.json','.bin'])
        isa_key='tools/nxu8/isa.txt';isa_hash=pre[str((ROOT/isa_key).resolve())]
        if digest(ROOT/isa_key)!=isa_hash:raise RuntimeError('ISA changed before publication')
        published=write_report(OUT/'publication-staging.json',report,dependencies,'tools/test_eval_c4_derivative_c.py')
        if digest(ROOT/isa_key)!=isa_hash:raise RuntimeError('ISA changed during publication')
        published['tested_inputs_sha256'][isa_key]=isa_hash
        canonical=ROOT/'analysis/c-verification/eval_c4_derivative.json'
        canonical.parent.mkdir(parents=True,exist_ok=True)
        canonical.write_text(json.dumps(published,indent=2)+'\n')
    return 0
if __name__=='__main__':raise SystemExit(main())
