#!/usr/bin/env python3
"""Native proof of C4 integral live sources, output aliases and paired fields."""
import argparse,ctypes as C,hashlib,json,re,random,subprocess,sys
from pathlib import Path
from c_verification import ROOT,write_report
from c_build_inputs import implementation_inputs
HERE=ROOT/'analysis/build/eval-c4-integral'
SRC=ROOT/'csrc'
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from test_eval_variables_c import Number,Result,SOURCES
from test_eval_environment_c import Effects,Storage
from test_numeric_calculus_c import Cancel,Control
BeforeSample=C.CFUNCTYPE(None,C.POINTER(Storage),C.c_uint16,C.c_uint16,C.c_void_p)
class Transport(C.Structure):_fields_=[('input_address',C.c_uint16),('cursor_address',C.c_uint16),('output_address',C.c_uint16),('before_sample',BeforeSample),('userdata',C.c_void_p)]
class Write(C.Structure):_fields_=[('pc',C.c_uint32),('anchor',C.c_uint32),('address',C.c_uint16),('size',C.c_uint8),('value',C.c_uint64)]
class Event(C.Structure):_fields_=[('pc',C.c_uint32),('caller',C.c_uint32),('cursor',C.c_uint16),('sink',C.c_uint16),('workspace',C.c_uint8*0xc6),('x',C.c_uint8*20)]
ap=argparse.ArgumentParser(description='Complete140 original171F4 C4 integral supplemental controls.')
ap.add_argument('--optimization',choices=['O2','O3'],default='O2')
ap.add_argument('--no-report',action='store_true')
ap.add_argument('--source-root',type=Path,default=ROOT)
ap.add_argument('--fixture',type=Path,default=ROOT/'analysis/native-fixtures/c4-integral/supplement/inputs.json')
ap.add_argument('--build-dir',type=Path,default=HERE)
args=ap.parse_args()
if args.source_root.resolve()!=ROOT.resolve() and not args.no_report:ap.error('Private source-root requires --no-report')
CANONICAL_FIXTURE=ROOT/'analysis/native-fixtures/c4-integral/supplement/inputs.json'
FIXTURE_SHA256='42bd4feade16024befdf32d76d72cb7f809c9eefcbe8ccf2b60baa35e8491c82'
if args.fixture.resolve()!=CANONICAL_FIXTURE.resolve() and not args.no_report:ap.error('Custom fixture requires --no-report')
assert hashlib.sha256(args.fixture.read_bytes()).hexdigest()==FIXTURE_SHA256
fixture_hash_before=hashlib.sha256(args.fixture.read_bytes()).hexdigest()
python_helpers={Path(module.__file__).resolve() for module in list(sys.modules.values())
 if getattr(module,'__file__',None) and Path(module.__file__).suffix=='.py'
 and Path(module.__file__).resolve().is_relative_to(ROOT/'tools')}
python_helpers.add(Path(__file__).resolve())
helper_hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(python_helpers)}
HERE=args.build_dir;HERE.mkdir(parents=True,exist_ok=True);SRC=args.source_root/'csrc'
sources=['csrc/'+n for n in dict.fromkeys([*SOURCES,'numeric/fx_integral_storage.c','numeric/fx_c4_integral_storage.c'])]
source_inputs=implementation_inputs(args.source_root,sources)
pins={name:hashlib.sha256((args.source_root/name).read_bytes()).hexdigest()for name in source_inputs}
ABI_PROBE=r'''
#include <stddef.h>
#include "parse/fx_eval_transport.h"
#include "parse/fx_eval_storage.h"
#include "complex/fx_complex.h"
size_t fx_eval_physical_test_abi(unsigned item) {
 switch(item) {
 case0:return sizeof(fx_eval_transport);
 case1:return offsetof(fx_eval_transport,input_address);
 case2:return offsetof(fx_eval_transport,cursor_address);
 case3:return offsetof(fx_eval_transport,output_address);
 case4:return offsetof(fx_eval_transport,before_sample);
 case5:return offsetof(fx_eval_transport,userdata);
 case6:return sizeof(fx_eval_storage);
 case7:return offsetof(fx_eval_storage,ram_size);
 case8:return offsetof(fx_eval_storage,rom);
 case9:return sizeof(fx_eval_result);
 case10:return offsetof(fx_eval_result,consumed);
 case11:return offsetof(fx_eval_result,unsupported_token);
 case12:return sizeof(fx_number);
 case13:return sizeof(fx_complex);
 case14:return offsetof(fx_complex,real);
 case15:return offsetof(fx_complex,imaginary);
 default:return 0;
 }
}
'''
ABI_PROBE=ABI_PROBE.replace('case','case ')
so=HERE/f'parser-{args.optimization}.so';subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-pedantic','-shared','-fPIC','-Wl,--no-undefined','-I',str(SRC),*[str(args.source_root/p)for p in sources],'-x','c','-','-o',str(so)],input=ABI_PROBE,text=True,check=True)
compiled_hash_before=hashlib.sha256(so.read_bytes()).hexdigest()
lib=C.CDLL(str(so));lib.fx_eval_physical_test_abi.argtypes=[C.c_uint];lib.fx_eval_physical_test_abi.restype=C.c_size_t
abi_expected=[C.sizeof(Transport),Transport.input_address.offset,Transport.cursor_address.offset,
 Transport.output_address.offset,Transport.before_sample.offset,Transport.userdata.offset,
 C.sizeof(Storage),Storage.ram_size.offset,Storage.rom.offset,C.sizeof(Result),
 Result.consumed.offset,Result.unsupported_token.offset,C.sizeof(Number),20,0,10]
abi_actual=[lib.fx_eval_physical_test_abi(index)for index in range(len(abi_expected))]
assert abi_actual==abi_expected,(abi_actual,abi_expected)
lib.fx_evaluate_prepared_physical.argtypes=[C.c_size_t]+[C.c_void_p]*9;lib.fx_decimal_parse.argtypes=[C.POINTER(Number),C.c_char_p]
oracle_inputs=[ROOT/'firmware/fx-991es-plus-c-ver4.bin',ROOT/'tools/nxu8/integral_storage_events.c',ROOT/'tools/nxu8/harness.c',ROOT/'tools/nxu8/vendor/SimU8/core.c',*(ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
oracle_hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest()for path in oracle_inputs}
rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();native=Machine(rom,HERE/f'machine-{args.optimization}')
obs=HERE/f'observer-{args.optimization}.so';subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(ROOT/'tools/nxu8/integral_storage_events.c'),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(obs)],check=True)
nl=C.CDLL(str(obs));old=native.lib
for n in ['harness_init','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_set_pc','harness_get_pc','harness_ram']:
 getattr(nl,n).argtypes=getattr(old,n).argtypes;getattr(nl,n).restype=getattr(old,n).restype
nl.integral_observer_run.argtypes=[C.c_uint64,C.c_uint32];native.lib=nl;native.ram=nl.harness_ram().contents
writes=(Write*100000).in_dll(nl,'integral_writes');events=(Event*8192).in_dll(nl,'integral_events')
def count(name):return C.c_uint.in_dll(nl,'integral_'+name)
def literal(s):
 n=Number();assert lib.fx_decimal_parse(C.byref(n),str(s).encode())==0;return bytes(n.bytes)
def store(a,raw):C.memmove(C.byref(native.ram,a),raw,len(raw))
formulas={'identity':b'X','square':b'X\x75','cube':b'X\x76','constant':b'A','radical':b'\x98X)','reciprocal':b'1\x4fX','error':b'1\x4f0','reciprocal_A':b'1\x4fA'}
fixture=json.loads(args.fixture.read_text())
assert set(fixture)=={'schema','provenance','expected_cases','rows'}
assert fixture['schema']==1 and len(fixture['rows'])==fixture['expected_cases']==140
assert all(set(row)=={'setup','tokens'} and isinstance(row['setup'],dict)
 and isinstance(row['tokens'],str) and bytes.fromhex(row['tokens'])[-1]==0 for row in fixture['rows'])
INPUT_SETUP_FIELDS={'abort','cursor_address','formula','group','imag','mode','output','rich','source'}
assert all(set(row['setup'])<=INPUT_SETUP_FIELDS and row['setup'].get('mode')==0xc4
 and set(row['setup'].get('imag',{}))<={'A','B','C','X'}for row in fixture['rows'])
cases=[dict(row['setup'],fixture_tokens=row['tokens'])for row in fixture['rows']]
rb=(C.c_uint8*len(rom)).from_buffer_copy(rom);ram=(C.c_uint8*65536)();storage=Storage(ram,65536,rb,len(rom))
rows=[]
for index,c in enumerate(cases):
 native.reset();nl.integral_observer_reset();count('abort').value=c.get('abort',0);mutation=c.get('mutation');count('mutation_call').value=mutation['call']if mutation else 0;count('mutation_address').value=mutation['address']if mutation else 0
 if mutation:C.memmove((C.c_uint8*10).in_dll(nl,'integral_mutation_value'),literal(mutation['value']),10)
 rich=c.get('rich',False)or c['group']=='preparation'
 if rich:
  for identity in range(16):
   native.ram[0x80e0+2*identity]=native.ram[0x80e1+2*identity]=1
   for cell in range(9):store(0x829e+90*identity+10*cell,literal(identity+cell+1))
 else:store(0x850a,bytes((j*17+3)&255 for j in range(0xc6)))
 store(0x8408,bytes(100))
 for a,v in [(0x80f9,c.get('mode',0xc1)),(0x80fc,c.get('screen',1)),(0x80f5,0xf0),(0x8105,4),(0x8106,c.get('math',1)),(0x8121,1)]:native.ram[a]=v
 body=formulas[c.get('formula','identity')];lower=b'B';upper=b'C';tol=None;b=bytes.fromhex(c['lower_raw'])if'lower_raw'in c else literal(c.get('lower',0));u=bytes.fromhex(c['upper_raw'])if'upper_raw'in c else literal(c.get('upper',1));d=literal('0.0001')
 pattern=c.get('pattern')
 if pattern=='explicit-positive':tol=b'D'
 if pattern=='negative-tolerance':tol=b'D';d=literal('-1')
 if pattern=='zero-tolerance':tol=b'D';d=literal('0')
 if pattern=='lower-error':lower=b'1\x4f0'
 if pattern=='upper-error':upper=b'1\x4f0'
 if pattern=='tolerance-error':tol=b'1\x4f0'
 if pattern=='missing-upper':upper=b''
 if pattern=='equal-bounds':u=b
 if pattern=='lower-F':b=bytes.fromhex('f3000000000000000000')
 if pattern=='upper-F':u=bytes.fromhex('f3000000000000000000')
 if pattern=='tolerance-F':tol=b'D';d=bytes.fromhex('f3000000000000000000')
 if'raw'in c:b=bytes.fromhex(c['raw'])
 tokens=b'\x6a'+body+b','+lower+b','+upper+(b','+tol if tol is not None else b'')+b')\0'
 tokens=bytes.fromhex(c['fixture_tokens'])
 output=c.get('output',0x8900);source=c.get('source',0x8a00);cursor_address=c.get('cursor_address',0x8190)
 coefficient=bytes.fromhex(c['coefficient'])if isinstance(c.get('coefficient'),str)else c.get('coefficient',literal('2'))
 for a,raw in [(0x823a,coefficient),(0x8244,b),(0x824e,u),(0x8258,d),(0x8276,literal('37')),(source,tokens),(output,bytes([0xee])*20),(cursor_address,source.to_bytes(2,'little'))]:store(a,raw)
 for name,value in c.get('imag',{}).items():store(dict(A=0x841c,B=0x8426,C=0x8430,X=0x8458)[name],literal(value))
 before=bytes(native.ram);C.memmove(ram,before,65536)
 native.er(0,cursor_address);native.er(2,output);nl.harness_set_sp(0x8dee);nl.harness_set_lr(0x2fffe);nl.harness_set_pc(0x171f4)
 execution=nl.integral_observer_run(200000000,0x2fffe);after=bytes(native.ram);floor=count('floor').value
 c_polls=[]
 @Cancel
 def cancel(_):c_polls.append(bytes(ram[0x850a:0x85d0]).hex());return int(c.get('abort',0)==len(c_polls))
 c_callbacks=[0]
 @BeforeSample
 def before_sample(storage,cursor,sink,_):
  c_callbacks[0]+=1
  if mutation and mutation['call']==c_callbacks[0]:C.memmove(C.byref(ram,mutation['address']),literal(mutation['value']),10)
 control=Control(cancel,None);transport=Transport(source,cursor_address,output,before_sample,None);result=Result();effects=Effects()
 status=lib.fx_evaluate_prepared_physical(len(tokens),None,None,None,C.byref(control),None,C.byref(storage),C.byref(transport),C.byref(effects),C.byref(result));actual=bytes(ram)
 differences=[[f'{a:04x}',after[a],actual[a]]for a in range(0x80dc,65536)if not floor<=a<0x8dee and after[a]!=actual[a]]
 n_polls=[bytes(e.workspace).hex()for e in events[:min(count('event_count').value,8192)]if e.pc==0x5564]
 host_unchanged=actual==before
 row=dict(host_unchanged=host_unchanged,index=index,input=c,tokens=tokens.hex(),stop=execution,floor=f'{floor:04x}',native=dict(status=native.reg(0),cursor=(native.word(cursor_address)-source)&65535,pair=after[output:output+20].hex(),polls=count('polls').value,callbacks=count('callbacks').value),actual=dict(status=status,cursor=result.consumed,pair=actual[output:output+20].hex(),named_pair=bytes(result.value).hex(),polls=len(c_polls),unsupported=result.unsupported_token,callbacks=c_callbacks[0]),ram_differences=differences,poll_snapshots_match=n_polls==c_polls,native_polls=n_polls,actual_polls=c_polls)
 rows.append(row)
 print(index,c['group'],c.get('formula',pattern),'native',row['native']['status'],row['native']['cursor'],'C',status,result.consumed,'ram',len(differences),flush=True)
changes=[p for p,h in pins.items()if hashlib.sha256((args.source_root/p).read_bytes()).hexdigest()!=h]
changes += [path for path,digest in {**helper_hashes,**oracle_hashes}.items()if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest]
if hashlib.sha256(args.fixture.read_bytes()).hexdigest()!=fixture_hash_before:changes.append(str(args.fixture))
if hashlib.sha256(so.read_bytes()).hexdigest()!=compiled_hash_before:changes.append(str(so))
def different(row):
 return (row['native']['status']!=row['actual']['status'] or
  row['native']['cursor']!=row['actual']['cursor'] or
  row['native']['pair']!=row['actual']['pair'] or
  bool(row['ram_differences']) or not row['poll_snapshots_match'] or
  row['native']['callbacks']!=row['actual']['callbacks'])
LIMIT_IDS=frozenset()
limits=[]
matching=[row for row in rows if row not in limits and not different(row)]
failures=[row for row in rows if row not in limits and different(row)]
checks=len(rows)*6+len(abi_expected)+3+len(limits)*4+2
report=dict(explicit_limit_case_ids=sorted(LIMIT_IDS),explicit_limit_host_policy='All140 returned controls must match; no omissions or inferred limit admission. Prepared core convergence04696 is tested separately.',fixture_sha256=FIXTURE_SHA256,compiled_artifact_sha256=compiled_hash_before,abi_sizes_offsets=abi_actual,python_helper_hashes=helper_hashes,oracle_input_hashes=oracle_hashes,status='pass'if not failures and not changes else 'fail',
 optimization=args.optimization,cases=len(rows),checks=checks,
 matching_native_calls=len(matching),explicit_native_returning_limits=len(limits),
 comparison='Original171F4 status, consumed cursor, physical output pair, fullpersistentRAM80DC..FFFF outside observed activeCPUframe, and exact5550 cancellation workspace snapshots; numeric8000..80DB CPUscratch excluded. All140 fresh C4 source/output aliases and paired bound/body/saved-X component controls replayed unfiltered.',
 original_calls=len(rows),original_callbacks=sum(row['native']['callbacks']for row in rows),
 original_polls=sum(row['native']['polls']for row in rows),mismatches=failures,
 explicit_limits=limits,source_changes=changes)
(HERE/f'proof-{args.optimization}.json').write_text(json.dumps(dict(report=report,pins=pins,rows=rows),indent=2)+'\n')
if any(row['stop']!=100 for row in rows):raise AssertionError('Original CPU did not return')
if failures or changes:raise AssertionError((len(failures),changes))
if not args.no_report:
 dependencies=implementation_inputs(ROOT,sources)+[str(path.relative_to(ROOT))for path in python_helpers if path.is_relative_to(ROOT)]+[
  'tools/test_eval_c4_integral_c.py','tools/test_eval_variables_c.py',
  'tools/test_eval_environment_c.py','tools/test_numeric_calculus_c.py',
  'tools/nxu8/integral_storage_events.c','tools/nxu8/harness.c',
  'tools/nxu8/machine.py','tools/nxu8/vendor/SimU8/core.c',
  'firmware/fx-991es-plus-c-ver4.bin',str(args.fixture.relative_to(ROOT)),
  'tools/c_verification.py','tools/c_build_inputs.py']+[str(path.relative_to(ROOT))for path in (ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
 report=write_report('analysis/c-verification/eval_c4_integral.json',report,
  sorted(set(dependencies)),'tools/test_eval_c4_integral_c.py')
print(json.dumps({k:v for k,v in report.items()if k not in ('mismatches','explicit_limits','input_hashes','verification')}))
