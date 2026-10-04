#!/usr/bin/env python3
"""Live original-ROM proof of the physical staged Richardson workspace.
GPL-3.0-or-later. The ROM and CPU are test oracles only.
"""
import ctypes as C
from decimal import Decimal
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'analysis/build/numeric/derivative-storage'
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from c_verification import write_report

def decimal(text):
    if isinstance(text,str)and text.startswith('raw:'):
        raw=bytes.fromhex(text[4:]);assert len(raw)==10
        return raw
    d=Decimal(str(text))
    if not d:return bytes(10)
    t=d.as_tuple();digits=''.join(map(str,t.digits));e=len(digits)-1+t.exponent
    digits=digits.ljust(15,'0')
    return bytes([int(digits[0]),*[int(digits[i:i+2],16)for i in range(1,15,2)],
        int(f'{e if e>=0 else e+100:02}',16),(6 if t.sign else 1)-(e<0)])

class Store(C.Structure):
    _fields_=[('pc',C.c_uint32),('link',C.c_uint32),('address',C.c_uint16),('sp',C.c_uint16),
              ('size',C.c_uint8),('value',C.c_uint64)]
class Checkpoint(C.Structure):
    _fields_=[('pc',C.c_uint32),('link',C.c_uint16),('output',C.c_uint16),
              ('kind',C.c_uint8),('x',C.c_uint8*10),('workspace',C.c_uint8*0x180)]


def setup_oracle():
    global m,lib,stores,points
    sources=[ROOT/'tools/nxu8/derivative_storage_events.c',ROOT/'tools/nxu8/vendor/SimU8/core.c']
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        *map(str,sources),'-o',str(HERE/'observer.so')],check=True)
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    m=Machine(rom,HERE/'oracle');lib=C.CDLL(str(HERE/'observer.so'))
    for name in ('harness_init','harness_set_reg','harness_get_reg','harness_set_sp',
                 'harness_get_sp','harness_set_lr','harness_set_pc','harness_ram',
                 'harness_get_pc'):
        getattr(lib,name).argtypes=getattr(m.lib,name).argtypes
        getattr(lib,name).restype=getattr(m.lib,name).restype
    m.lib=lib;m.ram=lib.harness_ram().contents
    lib.derivative_storage_observe.argtypes=[C.c_uint,C.c_uint64]
    stores=(Store*30000).in_dll(lib,'derivative_stores')
    points=(Checkpoint*512).in_dll(lib,'derivative_checkpoints')


def native(body,point='1',tolerance=None,abort=0,poison=0,coefficient='2',
           point_record=None,coefficient_record=None,scale='1e-99',mutation=None):
    m.reset()
    for addr,value in ((0x80f9,0xc1),(0x80fc,1),(0x80f5,0xf0),(0x8106,1),
                       (0x8105,4),(0x8121,1)):m.ram[addr]=value
    for addr in range(0x8500,0x8680):m.ram[addr]=(addr*73+poison*31)&255 if poison else 0
    for addr,record in ((0x8276,decimal(37)),
                        (0x823a,bytes.fromhex(coefficient_record)if coefficient_record else decimal(coefficient)),
                        (0x8244,bytes.fromhex(point_record)if point_record else decimal(point)),
                        (0x824e,decimal(tolerance or 0)),(0x8258,decimal(scale))):
        m.ram[addr:addr+10]=record
    raw=b'\x6b'+body+b',B'+(b',C'if tolerance is not None else b'')+b')\0'
    m.ram[0x8a00:0x8a00+len(raw)]=raw;m.word(0x8190,0x8a00);m.word(0x812c,0x8a00)
    m.ram[0x8900:0x8914]=b'\xad'*20
    initial=bytes(m.ram);m.er(0,0x8190);m.er(2,0x8900)
    for field,value in (('kind',mutation['kind']if mutation else 0),
                        ('call',mutation['call']if mutation else 0),
                        ('address',mutation['address']if mutation else 0)):
        C.c_uint.in_dll(lib,'derivative_mutation_'+field).value=value
    if mutation:
        C.memmove((C.c_uint8*10).in_dll(lib,'derivative_mutation_value'),decimal(mutation['value']),10)
    lib.harness_set_sp(0x8dee);lib.harness_set_lr(0x2fffe);lib.harness_set_pc(0x171f4)
    status=lib.derivative_storage_observe(abort,30000000)
    store_count=C.c_uint.in_dll(lib,'derivative_store_count').value
    checkpoint_count=C.c_uint.in_dll(lib,'derivative_checkpoint_count').value
    assert store_count<=30000 and checkpoint_count<=512
    events=[{'pc':f'{s.pc:05x}','link':f'{s.link:05x}','address':f'{s.address:04x}','size':s.size,
        'value':s.value.to_bytes(8,'little')[:s.size].hex()}for s in stores[:store_count]]
    checkpoints=[{'kind':p.kind,'pc':f'{p.pc:05x}','link':f'{p.link:04x}',
        'output':f'{p.output:04x}','x':bytes(p.x).hex(),
        'workspace':bytes(p.workspace).hex()}for p in points[:checkpoint_count]]
    after=bytes(m.ram)
    return {'input':{'body':body.hex(),'point':point,'tolerance':tolerance,'abort':abort,
        'poison':poison,'coefficient':coefficient,'point_record':point_record,
        'coefficient_record':coefficient_record,'scale':scale,'mutation':mutation,'tokens':raw.hex()},'stop':status,'status':m.reg(0),
        'cursor':m.word(0x8190)-0x8a00,'record20':after[0x8900:0x8914].hex(),
        'initial_workspace':initial[0x8500:0x8680].hex(),
        'final_workspace':after[0x8500:0x8680].hex(),'polls':C.c_uint.in_dll(lib,'derivative_polls').value,
        'events':events,'checkpoints':checkpoints,'after':after.hex(),'before':initial.hex()}


class Number(C.Structure):
    _fields_=[('bytes',C.c_uint8*10)]
Pointer=C.POINTER(Number)
Function=C.CFUNCTYPE(C.c_int,Pointer,Pointer,C.c_void_p)
Cancel=C.CFUNCTYPE(C.c_int,C.c_void_p)
class Control(C.Structure):
    _fields_=[('cancelled',Cancel),('userdata',C.c_void_p)]
class Storage(C.Structure):
    _fields_=[('ram',C.POINTER(C.c_uint8)),('ram_size',C.c_size_t)]

def prepare_library(path):
    lib=C.CDLL(str(path))
    lib.fx_derivative_storage_point.argtypes=[C.POINTER(Storage),Pointer]
    lib.fx_derivative_storage_tolerance.argtypes=[C.POINTER(Storage),Pointer,C.POINTER(C.c_uint)]
    lib.fx_number_derivative_storage.argtypes=[Pointer,C.POINTER(Storage),Function,C.c_void_p,C.POINTER(Control)]
    lib.fx_number_integer_power.argtypes=[Pointer,Pointer,C.c_int]
    lib.fx_number_sqrt.argtypes=[Pointer,Pointer,C.c_int]
    lib.fx_number_binary.argtypes=[Pointer,Pointer,Pointer,C.c_int]
    lib.fx_number_negate.argtypes=[Pointer,Pointer]
    lib.fx_decimal_integer_cleanup.argtypes=[Pointer]
    return lib

def compare(lib,row,recipe):
    case=recipe;ram=(C.c_uint8*65536).from_buffer_copy(bytes.fromhex(row['before']))
    raw=bytes.fromhex(row['initial_workspace']);C.memmove(C.byref(ram,0x8500),raw,len(raw))
    C.memmove(C.byref(ram,0x8276),decimal(37),10)
    prepared_point=case.get('prepared_point')
    if prepared_point:
        assert row['checkpoints'][0]['x']==prepared_point, 'native prepared argument boundary changed'
    # The staged API receives the already parsed argument. A rich variable
    # reaches that boundary as the original parser's cleaned F9, not its
    # stored61 reference. Keep the upstream stored reference in the fixture.
    storage=Storage(ram,65536);point=Number.from_buffer_copy(
        bytes.fromhex(prepared_point or case['point_record'])if case.get('point_record')else decimal(case['point']))
    tolerance=Number.from_buffer_copy(decimal(case['tolerance']))if case['tolerance']is not None else None
    out=Number.from_buffer_copy(b'\xad'*10);ns=C.c_uint()
    status=lib.fx_derivative_storage_point(C.byref(storage),C.byref(point))
    if status==0:status=lib.fx_derivative_storage_tolerance(C.byref(storage),
        C.byref(tolerance)if tolerance else None,C.byref(ns))
    checkpoints=[];polls=[];callback_count=0;body=bytes.fromhex(case['body'])
    def checkpoint(kind,x):
        checkpoints.append({'kind':kind,'x':x.hex(),'workspace':bytes(ram[0x8500:0x8680]).hex()})
        mutation=case.get('mutation')
        call=callback_count if kind==1 else len(polls)
        if mutation and mutation['kind']==kind and mutation['call']==call:
            C.memmove(C.byref(ram,mutation['address']),decimal(mutation['value']),10)
    @Function
    def function(result,x,userdata):
        nonlocal callback_count
        del userdata
        callback_count+=1
        checkpoint(1,bytes(x.contents))
        if body==b'X':
            C.memmove(result,x,10);status=0
            if bytes(result.contents)[0]>=0xf0:
                C.memmove(result,bytes.fromhex('f3000000000000000000'),10)
                return 1
        elif body in (b'X\x75',b'X\x76'):
            status=lib.fx_number_integer_power(result,x,2 if body[-1]==0x75 else 3)
        elif body==b'A':
            raw=bytes.fromhex(case['coefficient_record'])if case.get('coefficient_record')else decimal(case['coefficient'])
            if raw[0]>=0xf0:
                C.memmove(result,bytes.fromhex('f3000000000000000000'),10)
                return 1  # successful F-valued variable, cleanup preserves EQ
            C.memmove(result,raw,10);status=0
        elif body==b'1\x4f0':
            C.memmove(result,bytes.fromhex('f3000000000000000000'),10)
            return 2  # FX_CALCULUS_EVALUATION_ERROR
        elif body==b'\x98X)':status=lib.fx_number_sqrt(result,x,0)
        elif body==b'1\x4fX':
            one=Number.from_buffer_copy(decimal(1))
            status=lib.fx_number_binary(result,C.byref(one),x,3)
        elif body==b'\x63X-A)':
            coefficient=Number.from_buffer_copy(decimal(case['coefficient']))
            status=lib.fx_number_binary(result,x,C.byref(coefficient),1)
            if status==0:status=lib.fx_decimal_integer_cleanup(result)
            if status==0 and bytes(result.contents)[9]>=5:
                status=lib.fx_number_negate(result,result)
        elif body==b'X\x76\x4eD':
            status=lib.fx_number_integer_power(result,x,3)
            if status==0:status=lib.fx_decimal_integer_cleanup(result)
            scale=Number.from_buffer_copy(decimal(case['scale']))
            if status==0:status=lib.fx_number_binary(result,result,C.byref(scale),2)
        elif body==b'X\x76+D':
            status=lib.fx_number_integer_power(result,x,3)
            if status==0:status=lib.fx_decimal_integer_cleanup(result)
            offset=Number.from_buffer_copy(decimal(case['scale']))
            if status==0:status=lib.fx_number_binary(result,result,C.byref(offset),0)
        else:raise AssertionError(body)
        if status==0:status=lib.fx_decimal_integer_cleanup(result)
        # Successful F-valued variables are separate from parser errors.
        if bytes(result.contents)[0]>=0xf0:return 2
        return status
    @Cancel
    def cancelled(userdata):
        del userdata
        x=bytes(ram[0x8276:0x8280]);polls.append(x);checkpoint(2,x)
        cancel=bool(case['abort'])and len(polls)==case['abort']
        if cancel:
            #5550's external cancellation fixture publishes the AC key word.
            # This is a device-control effect, not Richardson algorithm state.
            ram[0x80f2]=4;ram[0x80f3]=16
        return int(cancel)
    control=Control(cancelled,None)
    if status==0 and ns.value==0:
        status=lib.fx_number_derivative_storage(C.byref(out),C.byref(storage),function,None,C.byref(control))
    elif status==0:out=Number.from_buffer_copy(bytes([0xf0|ns.value])+bytes(9))
    expected=[{k:x[k]for k in ('kind','x','workspace')}for x in row['checkpoints']]
    actual={'host_status':status,'record':bytes(out).hex(),
            'workspace':bytes(ram[0x8500:0x8680]).hex(),'polls':len(polls),'checkpoints':checkpoints}
    want={'host_status':0,'record':row['record20'][:20],
          'workspace':row['final_workspace'],'polls':row['polls'],'checkpoints':expected}
    actual['physical_bank16']=bytes(ram[0x829e:0x883e]).hex()
    want['physical_bank16']=bytes.fromhex(row['after'])[0x829e:0x883e].hex()
    actual['physical_dimensions16']=bytes(ram[0x80e0:0x8100]).hex()
    want['physical_dimensions16']=bytes.fromhex(row['after'])[0x80e0:0x8100].hex()
    actual['immutable_point']=bytes(point).hex()
    want['immutable_point']=(prepared_point or case['point_record'])if case.get('point_record')else decimal(case['point']).hex()
    actual['immutable_tolerance']=bytes(tolerance).hex()if tolerance else None
    want['immutable_tolerance']=decimal(case['tolerance']).hex()if case['tolerance']is not None else None
    differences={key:{'actual':actual[key],'native':value}for key,value in want.items()if actual[key]!=value}
    return actual,want,differences

SOURCES = [
    'csrc/numeric/fx_derivative_storage.c',
    'csrc/numeric/fx_numeric.c',
    'csrc/numeric/fx_raw_fraction_convert.c',
    'csrc/numeric/fx_raw_decimal_parts.c',
    'csrc/numeric/fx_raw_decimal_divide.c',
    'csrc/numeric/fx_raw_decimal_multiply_add.c',
    'csrc/numeric/fx_surd_components.c',
]
HEADERS = [path[:-2]+'.h' for path in SOURCES]
EXTRA = ['csrc/numeric/fx_derivative.h','csrc/numeric/fx_calculus.h',
         'csrc/numeric/fx_numeric_components.h',
         'tools/nxu8/derivative_storage_events.c','tools/c_verification.py',
         'csrc/numeric/derivative_storage/manifest.json',
         'analysis/native-fixtures/derivative-storage/inputs.json']

def host_guards(library):
    ram=(C.c_uint8*65536)()
    ram[0x80f9]=0xc1
    storage=Storage(ram,65536)
    short=Storage(ram,65535)
    point=Number.from_buffer_copy(decimal(1))
    out=Number.from_buffer_copy(b'\xad'*10)
    error=C.c_uint(0xdead)
    @Function
    def host_failure(value,x,userdata):
        del value,x,userdata
        return -3
    cases=[
        library.fx_derivative_storage_point(None,C.byref(point))==-1,
        library.fx_derivative_storage_point(C.byref(short),C.byref(point))==-1,
        library.fx_derivative_storage_point(C.byref(storage),None)==-1,
        library.fx_derivative_storage_tolerance(None,None,C.byref(error))==-1,
        library.fx_derivative_storage_tolerance(C.byref(storage),None,None)==-1,
        library.fx_number_derivative_storage(None,C.byref(storage),host_failure,None,None)==-1,
        library.fx_number_derivative_storage(C.byref(out),C.byref(short),host_failure,None,None)==-1,
    ]
    assert library.fx_derivative_storage_point(C.byref(storage),C.byref(point))==0
    assert library.fx_derivative_storage_tolerance(C.byref(storage),None,C.byref(error))==0
    cases += [library.fx_number_derivative_storage(C.byref(out),C.byref(storage),host_failure,None,None)==-3,
              bytes(out)==b'\xad'*10]
    ram[0x80f9]=0xc4
    unsupported_before=bytes(ram)
    cases += [library.fx_derivative_storage_point(C.byref(storage),C.byref(point))==-3,
              library.fx_derivative_storage_tolerance(C.byref(storage),None,C.byref(error))==-3,
              library.fx_number_derivative_storage(C.byref(out),C.byref(storage),host_failure,None,None)==-3,
              bytes(ram)==unsupported_before]
    assert all(cases),cases
    return len(cases)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-report',action='store_true')
    args=parser.parse_args()
    HERE.mkdir(parents=True,exist_ok=True)
    paths=SOURCES+HEADERS+EXTRA+['tools/test_numeric_derivative_storage_c.py',
        'csrc/numeric/derivative_storage/EXECUTION.md',
        'analysis/native-fixtures/derivative-storage/README.md',
        'tools/nxu8/machine.py','tools/nxu8/harness.c',
        'tools/nxu8/vendor/SimU8/core.c','firmware/fx-991es-plus-c-ver4.bin']
    paths += [str(p.relative_to(ROOT))for p in (ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
    pins={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()for p in paths}
    recipes=json.loads((ROOT/EXTRA[-1]).read_text())['cases']
    setup_oracle()
    native_rows=[]
    for recipe in recipes:
        inputs={key:value for key,value in recipe.items()if key not in ('tokens','prepared_point')}
        inputs['body']=bytes.fromhex(inputs['body'])
        row=native(**inputs)
        assert row['stop']==100,(recipe,row['stop'])
        assert row['input']['tokens']==recipe['tokens']
        native_rows.append(row)
    import gzip
    with gzip.open(HERE/'native-observations.json.gz','wt')as output:
        json.dump(native_rows,output)
    failures=[];checks=0;variants=[];observations=[]
    for optimization in ('-O2','-O3'):
        path=HERE/('derivative-storage'+optimization+'.so')
        command=['gcc','-std=c99',optimization,'-Wall','-Wextra','-Werror','-pedantic',
                 '-shared','-fPIC','-Wl,--no-undefined',*[str(ROOT/p)for p in SOURCES],'-o',str(path)]
        subprocess.run(command,check=True)
        library=prepare_library(path)
        guard_checks=host_guards(library);checks+=guard_checks
        before_count=len(failures)
        for index,(row,recipe)in enumerate(zip(native_rows,recipes)):
            actual,want,differences=compare(library,row,recipe)
            checks+=len(want)
            observation={'index':index,'optimization':optimization,'input':recipe,
                         'actual':actual,'native':want,'differences':differences}
            observations.append(observation)
            if differences:
                failures.append(observation)
                print(json.dumps({'index':index,'optimization':optimization,
                    'tokens':recipe['tokens'],'fields':list(differences)}),flush=True)
        variants.append({'optimization':optimization,'cases':len(recipes),
                         'guard_checks':guard_checks,'failures':len(failures)-before_count,
                         'library_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                         'compile_command':command})
    changes={p:{'before':h,'after':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()}
             for p,h in pins.items()if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h}
    with gzip.open(HERE/'differential-observations.json.gz','wt')as output:
        json.dump(observations,output)
    outcomes={str(status):sum(row['status']==status for row in native_rows)
              for status in sorted({row['status']for row in native_rows})}
    report={'suite':'numeric_derivative_storage','native_cases':len(native_rows),
            'c_cases':len(recipes)*len(variants),'checks':checks,'failures':failures,
            'native_outcomes':outcomes,'native_nonreturns':0,
            'callback_checkpoints':sum(sum(p['kind']==1 for p in row['checkpoints'])for row in native_rows),
            'poll_checkpoints':sum(row['polls']for row in native_rows),
            'maximum_polls':max(row['polls']for row in native_rows),
            'physical_workspace':'8500..867F, all16 bank dimensions and829E..883D payload',
            'scope':'staged scalar point/tolerance preparation plus live RAM-backed real Richardson driver',
            'limits':['C4 complex20-byte driver is outside this10-byte adapter',
                      'malformed decimal coordinates outside bounded raw comparator decoder return hostUNIMPLEMENTED',
                      'upstream rich argument preparation and forced-decimal SURD variable loads remain parser-owned',
                      'parser owns X restoration,522A variable publication and timer/device effects'],
            'variants':variants,'before_build_inputs_sha256':pins,'source_changes':changes}
    (HERE/'diagnostics.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key]for key in ('native_cases','c_cases','checks','native_outcomes',
                  'callback_checkpoints','poll_checkpoints','maximum_polls','source_changes')},indent=2))
    print('failures',len(failures),flush=True)
    if failures or changes:return 1
    if not args.no_report:
        write_report('analysis/c-verification/numeric_derivative_storage.json',report,
                     SOURCES+HEADERS+EXTRA,'tools/test_numeric_derivative_storage_c.py')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
