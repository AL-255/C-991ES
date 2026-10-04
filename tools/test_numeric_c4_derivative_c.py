#!/usr/bin/env python3
"""Fresh original-ROM C4 derivative preparation/core proof. GPL-3.0-or-later.
Production uses readable C only; original CPU and ROM are test oracles.
"""
import argparse,ctypes as C,gzip,hashlib,json,subprocess,sys
from decimal import Decimal,InvalidOperation
from pathlib import Path
SCRIPT_REPO=Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY_SHA256='ad8ca41dc17c0249d95d09b90a7f8b7e3c0a036673ef2f18dc26d6d9bcfdd0a4'
DEFAULT_PARSER_CASES=170
DEFAULT_PREPARED_CASES=84
class Number(C.Structure):_fields_=[('bytes',C.c_uint8*10)]
class Pair(C.Structure):_fields_=[('real',Number),('imaginary',Number)]
class Storage(C.Structure):_fields_=[('ram',C.POINTER(C.c_uint8)),('ram_size',C.c_size_t)]
Function=C.CFUNCTYPE(C.c_int,C.POINTER(Pair),C.POINTER(Pair),C.c_void_p)
Publish=C.CFUNCTYPE(None,C.POINTER(Pair),C.c_void_p)
Cancel=C.CFUNCTYPE(C.c_int,C.c_void_p)
class Control(C.Structure):_fields_=[('cancelled',Cancel),('userdata',C.c_void_p)]
class Event(C.Structure):_fields_=[('pc',C.c_uint32),('caller',C.c_uint32),('sink',C.c_uint16),('cursor',C.c_uint16),('workspace',C.c_uint8*0x180),('x',C.c_uint8*20)]
def number(value):
 if str(value).startswith('raw:'):return bytes.fromhex(value[4:])
 d=Decimal(str(value))
 if not d:return bytes(10)
 t=d.as_tuple();digits=''.join(map(str,t.digits));e=len(digits)-1+t.exponent
 assert len(digits)<=15 and -99<=e<=99
 digits=digits.ljust(15,'0')
 return bytes([int(digits[0]),*[int(digits[i:i+2],16)for i in range(1,15,2)],int(f'{e if e>=0 else e+100:02}',16),(6 if t.sign else 1)-(e<0)])

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pins(paths):return {str(p):digest(p)for p in sorted(set(map(Path,paths)))}
def inventory_hash(fixture):return hashlib.sha256(json.dumps(fixture,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def exact_keys(value,required,optional,label):
    if type(value)is not dict or not set(required)<=set(value)or set(value)-set(required)-set(optional):
        raise ValueError(label+': required input-only schema keys are missing or unexpected keys are present')
def numeric_literal(value,label,raw=True):
    if type(value)is not str:raise ValueError(label+': numeric recipe must be a string')
    if value.startswith('raw:'):
        if not raw:raise ValueError(label+': raw tolerance is outside this recipe schema')
        try:data=bytes.fromhex(value[4:])
        except ValueError:raise ValueError(label+': invalid hexadecimal record')from None
        if len(data)!=10:raise ValueError(label+': raw record must contain 10 bytes')
        return
    try:
        d=Decimal(value)
        if not d.is_finite():raise ValueError(label+': finite numeric value required')
        if d and(len(d.as_tuple().digits)>15 or not -99<=d.adjusted()<=99):raise ValueError(label+': decimal recipe exceeds stored 15 digits/exponent range')
    except InvalidOperation:raise ValueError(label+': invalid decimal literal')from None
def hex_record(value,label):
    if type(value)is not str:raise ValueError(label+': hexadecimal record must be a string')
    try:data=bytes.fromhex(value)
    except ValueError:raise ValueError(label+': invalid hexadecimal record')from None
    if len(data)!=10:raise ValueError(label+': record must contain 10 bytes')
def validate_fixture(fixture,canonical):
    exact_keys(fixture,['version','parser','prepared'],[],'fixture')
    if type(fixture['version'])is not int or fixture['version']!=1:raise ValueError('fixture version must be integer 1')
    for kind in ['parser','prepared']:
        if type(fixture[kind])is not list:raise ValueError(kind+' must be an input-only list')
    for index,case in enumerate(fixture['parser']):
        label='parser row '+str(index)
        exact_keys(case,['body','point','imaginary','point_mate','tolerance','tolerance_mate','abort','poison'],['coefficient','mode_call','mode_value'],label)
        if type(case['body'])is not str or case['body']not in ['X','A','i','X+0','A+0','1/0']:raise ValueError(label+': unsupported body recipe')
        for field in ['point','imaginary','point_mate','tolerance_mate']:
            numeric_literal(case[field],label+'/'+field)
        if case['tolerance']is not None:numeric_literal(case['tolerance'],label+'/tolerance',False)
        if 'coefficient'in case:numeric_literal(case['coefficient'],label+'/coefficient')
        for field in ['abort','poison']:
            if type(case[field])is not int or not 0<=case[field]<=255:raise ValueError(label+'/'+field+': unsigned byte required')
        if('mode_call'in case)!=('mode_value'in case):raise ValueError(label+': mode_call/mode_value must be supplied together')
        if 'mode_call'in case:
            if type(case['mode_call'])is not int or not 1<=case['mode_call']<=255 or type(case['mode_value'])is not int or case['mode_value']!=0xc1:raise ValueError(label+': mode mutation recipes require a positive callback count and C1 target')
    for index,case in enumerate(fixture['prepared']):
        label='prepared row '+str(index)
        exact_keys(case,['stage','record','mate'],[],label)
        if type(case['stage'])is not str or case['stage']not in ['point','tolerance']:raise ValueError(label+': invalid stage')
        hex_record(case['mate'],label+'/mate')
        record=case['record']
        if type(record)is not dict or len(record)!=1:raise ValueError(label+': one input record recipe required')
        if 'rom_address'in record:
            address=record['rom_address']
            if type(address)is not int or address not in [10792,10802,10812,10822,10832,10882,10892,10902,10912]:raise ValueError(label+': only the independently stored ROM table records are admitted')
        elif 'raw'in record:hex_record(record['raw'],label+'/raw')
        else:raise ValueError(label+': only rom_address/raw input record keys are admitted')
    if canonical:
        if len(fixture['parser'])!=DEFAULT_PARSER_CASES or len(fixture['prepared'])!=DEFAULT_PREPARED_CASES:raise ValueError('default workload count must be 170 parser + 84 prepared calls')
        if inventory_hash(fixture)!=DEFAULT_INVENTORY_SHA256:raise ValueError('default input-only inventory differs from its declared guarded workload')
    elif not fixture['parser']and not fixture['prepared']:raise ValueError('custom fixture must contain a native input')
def compiler_closure(sources,include_flags):
    closure=set(map(Path,sources))
    for source in sources:
        output=subprocess.check_output(['gcc','-std=c99','-MM',*include_flags,str(source)],text=True).replace('\\\n',' ')
        closure.update(Path(s)for s in output.partition(':')[2].split())
    return closure
def bind_library(lib):
    lib.fx_c4_derivative_point.argtypes=[C.POINTER(Storage),C.POINTER(Pair)]
    lib.fx_c4_derivative_tolerance.argtypes=[C.POINTER(Storage),C.POINTER(Pair),C.POINTER(C.c_uint)]
    lib.fx_c4_derivative_run.argtypes=[C.POINTER(Pair),C.POINTER(Storage),Function,C.c_void_p,Publish,C.POINTER(Control),C.POINTER(C.c_uint)]
    lib.fx_complex_binary.argtypes=[C.POINTER(Pair)]*3+[C.c_int]
    lib.c4_derivative_abi.argtypes=[C.c_uint];lib.c4_derivative_abi.restype=C.c_size_t
    return lib

def host_controls(lib):
    abi_expected=[C.sizeof(Number),Number.bytes.offset,C.sizeof(C.c_uint8*10),C.sizeof(Pair),Pair.real.offset,Pair.imaginary.offset,C.sizeof(Storage),Storage.ram.offset,Storage.ram_size.offset,C.sizeof(Control),Control.cancelled.offset,Control.userdata.offset,C.sizeof(C.c_uint)]
    actual=[lib.c4_derivative_abi(i)for i in range(13)];assert actual==abi_expected
    ram=(C.c_uint8*65536)();ram[0x80f9]=0xc4;s=Storage(ram,65536);value=Pair.from_buffer_copy(bytes([0xad])*20);out=Pair.from_buffer_copy(bytes([0xef])*20);status=C.c_uint(0xaabbccdd)
    @Function
    def fn(y,x,u):C.memmove(y,x,20);return 0
    @Publish
    def pub(x,u):pass
    null_fn=Function();null_pub=Publish()
    host_cases=[]
    def test(name,call,wanted=-1,immutable_ram=True):
     before=bytes(ram);oldout=bytes(out);oldstatus=status.value;observed=call();assert observed==wanted,(name,observed,wanted);assert bytes(out)==oldout,(name,'output commit');assert status.value==oldstatus,(name,'status commit')
     if immutable_ram:assert bytes(ram)==before,(name,'RAM mutation')
     host_cases.append(dict(name=name,status=observed,pass_=True))
    test('point NULL storage',lambda:lib.fx_c4_derivative_point(None,C.byref(value)))
    test('point NULL value',lambda:lib.fx_c4_derivative_point(C.byref(s),None))
    test('tolerance NULL storage',lambda:lib.fx_c4_derivative_tolerance(None,None,C.byref(status)))
    test('tolerance NULL native status',lambda:lib.fx_c4_derivative_tolerance(C.byref(s),None,None))
    test('run NULL output',lambda:lib.fx_c4_derivative_run(None,C.byref(s),fn,None,pub,None,C.byref(status)))
    test('run NULL storage',lambda:lib.fx_c4_derivative_run(C.byref(out),None,fn,None,pub,None,C.byref(status)))
    test('run NULL function',lambda:lib.fx_c4_derivative_run(C.byref(out),C.byref(s),null_fn,None,pub,None,C.byref(status)))
    test('run NULL native status',lambda:lib.fx_c4_derivative_run(C.byref(out),C.byref(s),fn,None,pub,None,None))
    for bad_size in [0,65535,65537]:
     bad=Storage(ram,bad_size)
     test('point invalid size '+str(bad_size),lambda:lib.fx_c4_derivative_point(C.byref(bad),C.byref(value)))
     test('tolerance invalid size '+str(bad_size),lambda:lib.fx_c4_derivative_tolerance(C.byref(bad),None,C.byref(status)))
     test('run invalid size '+str(bad_size),lambda:lib.fx_c4_derivative_run(C.byref(out),C.byref(bad),fn,None,pub,None,C.byref(status)))
    bad=Storage(None,65536)
    test('point NULL RAM',lambda:lib.fx_c4_derivative_point(C.byref(bad),C.byref(value)))
    test('tolerance NULL RAM',lambda:lib.fx_c4_derivative_tolerance(C.byref(bad),None,C.byref(status)))
    test('run NULL RAM',lambda:lib.fx_c4_derivative_run(C.byref(out),C.byref(bad),fn,None,pub,None,C.byref(status)))
    for context in [0,6,7,0xc1,0xff]:
     ram[0x80f9]=context
     test('point unsupported mode '+str(context),lambda:lib.fx_c4_derivative_point(C.byref(s),C.byref(value)),-3)
     test('tolerance unsupported mode '+str(context),lambda:lib.fx_c4_derivative_tolerance(C.byref(s),None,C.byref(status)),-3)
     test('run unsupported mode '+str(context),lambda:lib.fx_c4_derivative_run(C.byref(out),C.byref(s),fn,None,pub,None,C.byref(status)),-3)
    ram[0x80f9]=0xc4
    for offset in [-19,-10,0,0x85f0,65526,65535]:
     alias=C.cast(C.addressof(ram)+offset,C.POINTER(Pair))
     test('point RAM overlap '+str(offset),lambda:lib.fx_c4_derivative_point(C.byref(s),alias))
     test('tolerance RAM overlap '+str(offset),lambda:lib.fx_c4_derivative_tolerance(C.byref(s),alias,C.byref(status)))
     test('run output RAM overlap '+str(offset),lambda:lib.fx_c4_derivative_run(alias,C.byref(s),fn,None,pub,None,C.byref(status)))
    for offset in [-3,0,0x85f0,65535]:
     alias=C.cast(C.addressof(ram)+offset,C.POINTER(C.c_uint))
     test('tolerance status RAM overlap '+str(offset),lambda:lib.fx_c4_derivative_tolerance(C.byref(s),None,alias))
     test('run status RAM overlap '+str(offset),lambda:lib.fx_c4_derivative_run(C.byref(out),C.byref(s),fn,None,pub,None,alias))
    for host_error in [-1,-2,-3]:
     @Function
     def negative(y,x,u):C.memset(y,0xb4,20);return host_error
     test('callback negative '+str(host_error),lambda:lib.fx_c4_derivative_run(C.byref(out),C.byref(s),negative,None,null_pub,None,C.byref(status)),host_error,False)
    return dict(abi_checks=13,abi=actual,negative_controls=len(host_cases),controls=host_cases,checks=len(host_cases)+13)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root',type=Path,default=SCRIPT_REPO,help='repository root containing firmware and original CPU tools')
    parser.add_argument('--source-root',type=Path,help='candidate csrc root; a custom candidate requires --no-report')
    parser.add_argument('--fixture',type=Path,help='custom input-only fixture; requires --no-report')
    parser.add_argument('--build-dir',type=Path,help='isolated compiled artifacts and native observations')
    parser.add_argument('--no-report',action='store_true',help='do not publish a canonical verification report')
    parser.add_argument('--private-report',type=Path,help='write diagnostic JSON outside canonical verification paths; requires --no-report')
    args=parser.parse_args();ROOT=args.repo_root.resolve();DEP=(args.source_root or ROOT/'csrc').resolve()
    private_tool=Path(__file__).resolve()!=(ROOT/'tools/test_numeric_c4_derivative_c.py').resolve()
    if(args.fixture is not None or args.source_root is not None or private_tool)and not args.no_report:parser.error('custom fixture/source or private tool placement requires --no-report')
    if args.private_report and not args.no_report:parser.error('--private-report requires --no-report')
    if args.private_report:
        target=args.private_report.resolve()
        if target.is_relative_to(ROOT/'analysis/c-verification'):parser.error('private reports may not target canonical analysis/c-verification')
    fixture_path=(args.fixture or SCRIPT_REPO/'analysis/native-fixtures/c4-derivative/inputs.json').resolve()
    try:
        fixture=json.loads(fixture_path.read_text());validate_fixture(fixture,args.fixture is None)
    except (ValueError,OSError)as error:parser.error(str(error))
    if not(ROOT/'firmware/fx-991es-plus-c-ver4.bin').is_file():parser.error('repo root does not contain the required original ROM')
    OUT=(args.build_dir or (SCRIPT_REPO if private_tool else ROOT)/'analysis/build/numeric/c4-derivative').resolve();OUT.mkdir(parents=True,exist_ok=True)
    if not args.no_report:
        sys.path.insert(0,str(ROOT/'tools'))
        from c_verification import write_report
    sys.path.insert(0,str(ROOT/'tools'))
    from nxu8.machine import Machine
    observer=Path(__file__).resolve().parent/'nxu8/derivative_c4_events.c'
    abi=Path(__file__).resolve().parent/'nxu8/derivative_c4_abi.c'
    numeric=['fx_numeric.c','fx_raw_fraction_convert.c','fx_raw_decimal_parts.c','fx_raw_decimal_divide.c','fx_raw_decimal_multiply_add.c','fx_surd_components.c']
    sources=[DEP/'numeric/fx_c4_derivative_storage.c',abi]+[DEP/'numeric'/name for name in numeric]+[DEP/'complex/fx_complex.c']
    includes=['-I',str(DEP),'-I',str(DEP/'numeric'),'-I',str(ROOT/'tools/nxu8')]
    oracle_sources=[observer,ROOT/'tools/nxu8/vendor/SimU8/core.c']
    inputs=compiler_closure(sources+oracle_sources,includes)|{Path(__file__).resolve(),fixture_path,ROOT/'firmware/fx-991es-plus-c-ver4.bin',ROOT/'tools/nxu8/isa.txt'}
    inputs.update((ROOT/'tools/nxu8').rglob('*.py'))
    if not args.no_report:inputs.update([ROOT/'tools/c_verification.py',ROOT/'tools/c_build_inputs.py'])
    for module in list(sys.modules.values()):
        path=getattr(module,'__file__',None)
        if path and Path(path).suffix=='.py'and Path(path).resolve().is_relative_to(ROOT):inputs.add(Path(path).resolve())
    pre_pins=pins(inputs);libs={};commands={};guards={};compiled_artifacts=[]
    for opt in ['O2','O3']:
        target=OUT/f'bounded-{opt}.so'
        command=['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-pedantic','-shared','-fPIC','-Wl,--no-undefined',*includes,*map(str,sources),'-o',str(target)]
        subprocess.run(command,check=True);libs[opt]=bind_library(C.CDLL(str(target)));commands[opt]=command;compiled_artifacts.append(target)
    oracle_target=OUT/'bounded-oracle.so'
    oracle_command=['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-pedantic','-shared','-fPIC',*includes,*map(str,oracle_sources),'-o',str(oracle_target)]
    subprocess.run(oracle_command,check=True)
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();m=Machine(rom,OUT/'native');old=m.lib;nl=C.CDLL(str(oracle_target))
    for name in ['harness_init','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_set_pc','harness_get_pc','harness_ram']:
        getattr(nl,name).argtypes=getattr(old,name).argtypes;getattr(nl,name).restype=getattr(old,name).restype
    m.lib=nl;m.ram=nl.harness_ram().contents;nl.c4_stage.argtypes=[C.c_uint64,C.c_uint32]
    def count(name):return C.c_uint.in_dll(nl,'c4_'+name)
    compiled_artifacts.extend([oracle_target,OUT/'native/nxu8-harness.so']);artifacts_before=pins(compiled_artifacts)
    for opt,lib in libs.items():guards[opt]=host_controls(lib)
    cases=fixture['parser'];rows=[];checks={'O2':0,'O3':0}
    with gzip.open(OUT/'bounded-observations.jsonl.gz','wt')as stream:
     for index,case in enumerate(cases):
      m.reset();nl.c4_reset();count('abort').value=case['abort'];count('mode_call').value=case.get('mode_call',0);count('mode_value').value=case.get('mode_value',0)
      for a,v in [(0x80f9,0xc4),(0x80fc,1),(0x80f5,0xf0),(0x8105,4),(0x8106,1),(0x8121,1)]:m.ram[a]=v
      for a in range(0x8500,0x8680):m.ram[a]=(a*73+case['poison']*31)&255 if case['poison'] else 0
      for a,v in [(0x823a,case.get('coefficient','2')),(0x8244,case['point']),(0x824e,case['tolerance'] or '0'),(0x8276,'37'),(0x841c,case['imaginary']),(0x8426,case['point_mate']),(0x8430,case['tolerance_mate']),(0x8458,'3')]:m.ram[a:a+10]=number(v)
      body=b'\x80'if case['body']=='i' else b'1\x4f0'if case['body']=='1/0' else case['body'].encode()
      tokens=b'\x6b'+body+b',B'+(b',C'if case['tolerance']is not None else b'')+b')\0'
      m.ram[0x8a00:0x8a00+len(tokens)]=tokens;m.word(0x8190,0x8a00);m.word(0x812c,0x8a00);m.ram[0x8900:0x8914]=b'\xee'*20
      initial=bytes(m.ram);m.er(0,0x8190);m.er(2,0x8900)
      nl.harness_set_sp(0x8dee);nl.harness_set_lr(0x2fffe);nl.harness_set_pc(0x171f4)
      stage_rows=[];stage_states=[];boundary=None
      stages=[('point',0x4b1e,0x4b2e),('tolerance',0x4b40 if case['tolerance']is not None else 0x4b6a,0x4b94)]
      for name,start,end in stages:
       stop=nl.c4_stage(10000000,start)
       if stop!=100 or nl.harness_get_pc()!=start:
        boundary=dict(stage=name,stop=stop,pc=hex(nl.harness_get_pc()));break
       before=bytes(m.ram);address=m.er(12);value=Pair.from_buffer_copy(before[address:address+20]);saved_value=bytes(value)
       # Rejected explicit tolerance returns through4DBC before reaching core.
       rejected=name=='tolerance'and case['tolerance']is not None and Decimal(case['tolerance'])<=0
       stop=nl.c4_stage(10000000,0x4dc4 if rejected else end);after=bytes(m.ram)
       if stop!=100 or nl.harness_get_pc()!=(0x4dc4 if rejected else end):
        boundary=dict(stage=name,stop=stop,pc=hex(nl.harness_get_pc()));break
       stage_states.append(dict(stage=name,before=before.hex(),after=after.hex(),value=bytes(value).hex()))
       for opt,lib in libs.items():
        ram=(C.c_uint8*65536).from_buffer_copy(before);s=Storage(ram,65536);status=C.c_uint(255)
        host=lib.fx_c4_derivative_point(C.byref(s),C.byref(value)) if name=='point' else lib.fx_c4_derivative_tolerance(C.byref(s),C.byref(value)if case['tolerance']is not None else None,C.byref(status))
        differences=[hex(a)for a in range(0x8500,0x8680)if ram[a]!=after[a]]
        okay=host==0 and not differences and bytes(value)==saved_value and(name=='point'or status.value==(8 if rejected else 0))
        checks[opt]+=3;stage_rows.append(dict(stage=name,optimization=opt,host=host,status=status.value if name=='tolerance'else None,expected_status=(8 if rejected else 0)if name=='tolerance'else None,differences=differences,pass_=okay))
       if rejected:boundary=dict(stage='rejected-tolerance',stop=stop,pc=hex(nl.harness_get_pc()),native_status=m.reg(0));break
      host_rows=[];observed=[];core_state=None
      if boundary is None:
       before=bytes(m.ram);address=m.er(12);nl.c4_reset();stop=nl.c4_stage(10000000,0x4dbc);after=bytes(m.ram)
       if stop!=100 or nl.harness_get_pc()!=0x4dbc:boundary=dict(stage='core',stop=stop,pc=hex(nl.harness_get_pc()))
       else:
        expected=after[address:address+20];native_status=m.reg(0)
        events=(Event*8192).in_dll(nl,'c4_events');assert count('event_count').value<=8192
        observed=[dict(kind='poll'if e.pc==0x5564 else'callback',workspace=bytes(e.workspace).hex(),x=bytes(e.x).hex())for e in events[:count('event_count').value]]
        results=(C.c_uint8*20*8192).in_dll(nl,'c4_results');statuses=(C.c_uint8*8192).in_dll(nl,'c4_statuses');delimiters=(C.c_uint8*8192).in_dll(nl,'c4_delimiters');flags=(C.c_uint8*8192).in_dll(nl,'c4_flags');callback_returns=[dict(index=i,result=bytes(results[i]).hex(),status=statuses[i],delimiter=delimiters[i],PSW=flags[i])for i,e in enumerate(events[:count('event_count').value])if e.pc!=0x5564]
        core_state=dict(before=before.hex(),after=after.hex(),address=address,events=observed,callback_returns=callback_returns)
        for opt,lib in libs.items():
         ram=(C.c_uint8*65536).from_buffer_copy(before);s=Storage(ram,65536);out=Pair.from_buffer_copy(before[address:address+20]);host_events=[];polls=[]
         @Publish
         def publish(x,_):pass
         callback_count=[0]
         @Function
         def function(y,x,_):
          host_events.append(dict(kind='callback',workspace=bytes(ram[0x8500:0x8680]).hex(),x=(bytes(ram[0x8276:0x8280])+bytes(ram[0x8458:0x8462])).hex()))
          callback_count[0]+=1
          if callback_count[0]==case.get('mode_call',0):ram[0x80f9]=case['mode_value']
          size=20 if ram[0x80f9]==0xc4 else 10
          if case['body'].startswith('X'):C.memmove(y,x,size)
          elif case['body'].startswith('A'):C.memmove(y,bytes(ram[0x823a:0x8244])+bytes(ram[0x841c:0x8426]),size)
          elif case['body']=='i':C.memmove(y,bytes(10)+number(1),20)
          else:C.memmove(y,number('raw:f3000000000000000000')+bytes(10),20);return 2
          if case['body'].endswith('+0'):
           zero=Pair();assert lib.fx_complex_binary(y,y,C.byref(zero),0)==0
          if size==10:C.memset(C.byref(y.contents.imaginary),0,10)
          # 51CA variable loads and the i literal preserve the live pair. The
          # native171EA returns FE with EQ even for an F-valued variable.
          # Arithmetic expressions own their separate finishing policy.
          return 1
         @Cancel
         def cancel(_):
          polls.append(1);host_events.append(dict(kind='poll',workspace=bytes(ram[0x8500:0x8680]).hex(),x=(bytes(ram[0x8276:0x8280])+bytes(ram[0x8458:0x8462])).hex()))
          return bool(case['abort']and len(polls)==case['abort'])
         control=Control(cancel,None);status=C.c_uint(255)
         host=lib.fx_c4_derivative_run(C.byref(out),C.byref(s),function,None,publish,C.byref(control),C.byref(status))
         differences=[[hex(a),after[a],ram[a]]for a in range(0x8500,0x8680)if ram[a]!=after[a]]
         xdiff=[hex(a)for a in list(range(0x8276,0x8280))+list(range(0x8458,0x8462))if ram[a]!=after[a]]
         event_diff=next((i for i,(a,b)in enumerate(zip(observed,host_events))if a!=b),None)
         okay=host==0 and status.value==native_status and bytes(out)==expected and not differences and not xdiff and len(observed)==len(host_events)and event_diff is None
         checks[opt]+=7+3*len(observed)
         host_rows.append(dict(optimization=opt,host=host,status=status.value,result=bytes(out).hex(),expected=expected.hex(),native_status=native_status,differences=differences,X_differences=xdiff,event_counts=[len(observed),len(host_events)],first_event_difference=event_diff,first_native_event=observed[event_diff]if event_diff is not None else None,first_host_event=host_events[event_diff]if event_diff is not None else None,pass_=okay))
      # Complete the real parser call, solely to retain cursor/output/restoration evidence.
      outer_stop=nl.c4_stage(10000000,0x2fffe) if boundary is None or boundary['stage']=='rejected-tolerance' else None
      final=bytes(m.ram);counts=(C.c_uint64*0x18000).in_dll(nl,'execution_counts');instruction_count=sum(counts);hits={hex(pc):counts[pc//2]for pc in [0x4a62,0x4b22,0x4b5a,0x4b66,0x4b7c,0x4c2a,0x4c5a,0x4c8c,0x4dae,0x4db4,0x4dbc,0x169ea,0x169ec]}
      row=dict(index=index,input=case,tokens=tokens.hex(),stages=stage_rows,host_rows=host_rows,boundary=boundary,outer_stop=outer_stop,outer_pc=hex(nl.harness_get_pc()),outer_status=m.reg(0),outer_cursor=m.word(0x8190)-0x8a00,outer_result20=final[0x8900:0x8914].hex(),outer_X_restored=initial[0x8276:0x8280]==final[0x8276:0x8280]and initial[0x8458:0x8462]==final[0x8458:0x8462],floor=count('floor').value,instructions=instruction_count,selected_instruction_hits=hits)
      stream.write(json.dumps(dict(row=row,initial=initial.hex(),final=final.hex(),stages=stage_states,core=core_state))+'\n');rows.append(row)
      if index%12==0 or any(not r['pass_']for r in stage_rows+host_rows):print(json.dumps(dict(parser_index=index,boundary=boundary,passing=all(r['pass_']for r in stage_rows+host_rows),native_status=row['outer_status'])),flush=True)
    parser_rows=rows;prepared_rows=[];rows=[]
    with gzip.open(OUT/'prepared-observations.jsonl.gz','wt')as stream:
        for input_case in fixture['prepared']:
            stage=input_case['stage'];recipe=input_case['record'];mate=input_case['mate']
            raw=(rom[recipe['rom_address']:recipe['rom_address']+10]if 'rom_address'in recipe else bytes.fromhex(recipe['raw']))+bytes.fromhex(mate)
            m.reset();nl.c4_reset();m.ram[0x80f9]=0xc4
            for a in range(0x8500,0x8680):m.ram[a]=(a*31+91)&255
            m.ram[0x8900:0x8914]=raw;m.er(8,0x85b4);m.er(12,0x8900);m.reg(0,0xff);nl.harness_set_sp(0x8dee);nl.harness_set_lr(0x2fffe);nl.harness_set_pc(0x4b1e if stage=='point' else 0x4b40)
            before=bytes(m.ram)
            boundary=None
            if stage=='point':
             stop=nl.c4_stage(10000000,0x4b2e);expected_status=None
             if stop!=100 or nl.harness_get_pc()!=0x4b2e:boundary=dict(phase='point',stop=stop,pc=hex(nl.harness_get_pc()))
            else:
             stop=nl.c4_stage(10000000,0x4b4c);expected_status=None
             if stop!=100 or nl.harness_get_pc()!=0x4b4c:boundary=dict(phase='tolerance-classification',stop=stop,pc=hex(nl.harness_get_pc()))
             else:
              positive=m.reg(0)==4;target=0x4b68 if positive else 0x4dc4
              stop=nl.c4_stage(10000000,target);expected_status=0 if positive else 8
              if stop!=100 or nl.harness_get_pc()!=target:boundary=dict(phase='tolerance-copy',stop=stop,pc=hex(nl.harness_get_pc()))
            if boundary:
             counts=(C.c_uint64*0x18000).in_dll(nl,'execution_counts');row=dict(stage=stage,input=recipe,mate=mate,record20=raw.hex(),stop_pc=hex(nl.harness_get_pc()),instructions=sum(counts),host=[],boundary=boundary)
             rows.append(row);stream.write(json.dumps(dict(row=row,before=before.hex(),after=bytes(m.ram).hex()))+'\n');continue
            after=bytes(m.ram);value=Pair.from_buffer_copy(raw);hs=[]
            for opt,lib in libs.items():
             ram=(C.c_uint8*65536).from_buffer_copy(before);s=Storage(ram,65536);status=C.c_uint(0xaabbccdd);saved=bytes(value)
             host=lib.fx_c4_derivative_point(C.byref(s),C.byref(value))if stage=='point'else lib.fx_c4_derivative_tolerance(C.byref(s),C.byref(value),C.byref(status))
             diff=[hex(a)for a in range(0x8500,0x8680)if ram[a]!=after[a]];okay=host==0 and not diff and bytes(value)==saved and (status.value==0xaabbccdd if expected_status is None else status.value==expected_status)
             hs.append(dict(optimization=opt,host=host,native_status=status.value,expected_status=expected_status,differences=diff,pass_=okay))
            counts=(C.c_uint64*0x18000).in_dll(nl,'execution_counts');row=dict(stage=stage,input=recipe,mate=mate,record20=raw.hex(),stop_pc=hex(nl.harness_get_pc()),instructions=sum(counts),host=hs,boundary=None)
            rows.append(row);stream.write(json.dumps(dict(row=row,before=before.hex(),after=after.hex()))+'\n')
    prepared_rows=rows
    input_changes={path:{'before':h,'after':digest(path)}for path,h in pre_pins.items()if digest(path)!=h}
    artifact_changes={path:{'before':h,'after':digest(path)}for path,h in artifacts_before.items()if digest(path)!=h}
    failures=[dict(kind='parser',index=row['index'],field=check)for row in parser_rows for check in row['stages']+row['host_rows']if not check['pass_']]
    failures.extend(dict(kind='prepared',index=index,field=check)for index,row in enumerate(prepared_rows)for check in row['host']if not check['pass_'])
    nonreturns=[row for row in parser_rows if row['outer_stop']!=100 or row['outer_pc']!='0x2fffe']
    # A deliberate rejection is an actual native4DC4 status8 return, not a budget stop.
    unexplained_boundaries=[row for row in parser_rows if row['boundary']and row['boundary']['stage']!='rejected-tolerance']
    prepared_boundaries=[row for row in prepared_rows if row['boundary']]
    failures.extend(dict(kind='native-boundary',row=row)for row in nonreturns+unexplained_boundaries+prepared_boundaries)
    prepared_compared=sum(bool(row['host'])for row in prepared_rows)
    native_calls=len(parser_rows)+len(prepared_rows)
    native_instructions=sum(row['instructions']for row in parser_rows+prepared_rows)
    variants=[dict(optimization=opt,checks=checks[opt]+4*prepared_compared+guards[opt]['checks'],parser_checks=checks[opt],prepared_checks=4*prepared_compared,host_only_checks=guards[opt]['checks'],host_abi=guards[opt],compile_command=commands[opt],library_sha256=artifacts_before[str(OUT/f'bounded-{opt}.so')])for opt in ['O2','O3']]
    report=dict(suite='numeric_c4_derivative',cases=native_calls,native_calls=native_calls,native_instructions=native_instructions,parser_calls=len(parser_rows),parser_preparation_boundaries=sum(len(row['stages'])//2 for row in parser_rows),prepared_cores=sum(bool(row['host_rows'])for row in parser_rows),direct_preparation_calls=len(prepared_rows),host_controls_per_build={opt:guards[opt]['negative_controls']for opt in guards},compiled_abi_checks_per_build={opt:guards[opt]['abi_checks']for opt in guards},checks=sum(row['checks']for row in variants),failures=failures,native_nonreturns=len(nonreturns)+len(prepared_boundaries),variants=variants,fixture_sha256=pre_pins[str(fixture_path)],input_only_inventory_sha256=inventory_hash(fixture),prepared_comparisons=prepared_compared,before_execution_inputs_sha256=pre_pins,source_changes=input_changes,compiled_artifacts_before_sha256=artifacts_before,artifact_changes=artifact_changes,oracle_compile_command=oracle_command,parser_rows=parser_rows,prepared_rows=prepared_rows,scope='Initial C4 prepared derivative stages/core; live paired copies and scalar 10-byte arithmetic; fixed RAM8500..867F, physical X, ordered events, live pair/status',limits=['Parser syntax/cursor, final error publication, callback finishing/rich banks, timer/device effects and saved X wrapper are caller-owned','No claim of full RAM/CPU frame/ordinary complex calculus equivalence','Native B exhaustion is retained statically but not reached by the default corpus','Malformed raw decimal domains outside existing primitive decoders remain host gaps'],full_firmware_complete=False)
    (OUT/'diagnostics.json').write_text(json.dumps(report,indent=2)+'\n')
    if args.private_report:
        target=args.private_report.resolve();target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key]for key in ['native_calls','native_instructions','parser_preparation_boundaries','prepared_cores','direct_preparation_calls','host_controls_per_build','compiled_abi_checks_per_build','checks','native_nonreturns','source_changes','artifact_changes']}),flush=True)
    print('failures',len(failures),flush=True)
    if failures or input_changes or artifact_changes:return 1
    if not args.no_report:
        publication=list(dict.fromkeys(Path(path).resolve().relative_to(ROOT)for path in pre_pins if Path(path).suffix in ['.c','.h','.py','.json','.bin']))
        write_report('analysis/c-verification/numeric_c4_derivative.json',report,publication,'tools/test_numeric_c4_derivative_c.py')
    return 0
if __name__=='__main__':raise SystemExit(main())
