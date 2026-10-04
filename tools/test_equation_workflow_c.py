#!/usr/bin/env python3
"""Input-only EQN coefficient/solve/replay workflow vs independent original ROM.

Production is handwritten high-level C. Only the test oracle executes firmware.
Prepared call boundaries retain independent complete C/native RAM per sequence;
operand scratch, inactive linalg scratch and witnessed frames remain explicit.
SPDX-License-Identifier: GPL-3.0-only
"""
from pathlib import Path
import sys,ctypes as C,json,gzip,hashlib,re,subprocess,uuid,argparse,base64,zlib
ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'tools/nxu8/machine.py').is_file(): ROOT=Path.cwd().resolve()
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from test_platform_c import Platform
from c_build_inputs import implementation_inputs
from c_verification import write_report
FIXTURE='analysis/native-fixtures/equation-workflow/inputs.json'
FIXTURE_SHA='a0ca5e54c9cf2fae8898113c15a67542e059d2395e6d96507a924b9c7276fd8e'
SUPPORT=['tools/equation_support/workflow_adapter.c','tools/equation_support/workflow_native.c']
TEST='tools/test_equation_workflow_c.py'
class Control(C.Structure): _fields_=[('cancelled',C.c_void_p),('userdata',C.c_void_p)]
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest_bytes(data): return hashlib.sha256(data).hexdigest()
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--optimization',choices=['O2','O3'])
parser.add_argument('--candidate-root',type=Path)
parser.add_argument('--fixture',type=Path)
parser.add_argument('--private-report',type=Path)
parser.add_argument('--no-report',action='store_true')
args=parser.parse_args()
if args.candidate_root and not args.private_report: parser.error('--candidate-root requires --private-report')
if args.fixture and not (args.private_report or args.no_report): parser.error('Custom fixture requires a private report or --no-report')
if args.optimization and not (args.private_report or args.no_report): parser.error('Single optimization requires a private report or --no-report')
if args.private_report and args.private_report.resolve().is_relative_to((ROOT/'analysis/c-verification').resolve()): parser.error('Private reports cannot replace canonical reports')
CANDIDATE=args.candidate_root.resolve() if args.candidate_root else ROOT
fixture_path=args.fixture.resolve() if args.fixture else CANDIDATE/FIXTURE
fixture=json.loads(fixture_path.read_text())
if set(fixture)!={'basis','initial_ram','scenarios'} or not isinstance(fixture['basis'],str): parser.error('Malformed input-only fixture metadata')
if set(fixture['initial_ram'])!={'1','2'}: parser.error('Two complete original prepared seeds required')
for key,value in fixture['initial_ram'].items():
 try: seed=bytes.fromhex(value)
 except (ValueError,TypeError): parser.error('Invalid RAM seed encoding')
 if len(seed)!=65536: parser.error('Invalid complete RAM seed length')
 if seed[0x80f9]!=0x45 or seed[0x80fa]!=int(key) or seed[0x80fc]!=21: parser.error('Seed is not prepared linear EQN screen21')
expected=[('linear2-positive',1,1),('linear2-negative',1,1),('linear2-fraction',1,1),('linear3-positive',2,1),('linear3-math-off',2,0)]
if not isinstance(fixture['scenarios'],list) or len(fixture['scenarios'])!=5: parser.error('All five workflow scenarios required')
for scenario,(label,selector,math) in zip(fixture['scenarios'],expected):
 if set(scenario)!={'label','selector','math','coefficients'} or (scenario['label'],scenario['selector'],scenario['math'])!=(label,selector,math): parser.error('Malformed or reordered workflow scenario')
 if len(scenario['coefficients'])!=(6 if selector==1 else 12): parser.error('Incomplete coefficient recipe')
 for text in scenario['coefficients']:
  try: tokens=bytes.fromhex(text)
  except (ValueError,TypeError): parser.error('Invalid physical token encoding')
  if not 1<=len(tokens)<=99 or 0 in tokens: parser.error('Invalid physical coefficient tokens')
if not args.fixture and digest(fixture_path)!=FIXTURE_SHA: parser.error('Canonical input-only fixture changed')
cmake=CANDIDATE/'csrc/CMakeLists.txt'
sources=['csrc/'+p for p in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',cmake.read_text().split('target_include_directories')[0])]
if not {'csrc/ui/fx_equation_controller.c','csrc/ui/fx_equation_result.c'}<=set(sources): parser.error('EQN modules must be registered in the actual CMake library')
closure=implementation_inputs(CANDIDATE,sources)
paths=[*[CANDIDATE/p for p in closure],cmake,*[CANDIDATE/p for p in SUPPORT],fixture_path,Path(__file__).resolve(),ROOT/'firmware/fx-991es-plus-c-ver4.bin',ROOT/'tools/nxu8/harness.c',ROOT/'tools/nxu8/vendor/SimU8/core.c',*sorted((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h'))]
paths += [Path(v.__file__).resolve() for v in sys.modules.values() if getattr(v,'__file__',None) and Path(v.__file__).resolve().is_relative_to(ROOT/'tools')]
pins={str(p):digest(p) for p in paths}
def stable():
 changes=[q for q,h in pins.items() if digest(q)!=h]
 if changes: raise RuntimeError('Test inputs changed during run: '+', '.join(changes))
if args.optimization is None:
 run=CANDIDATE/'analysis/build/equation-workflow'/uuid.uuid4().hex;run.mkdir(parents=True)
 reports=[]
 for optimization in ('O2','O3'):
  path=run/('proof-'+optimization+'.json')
  command=[sys.executable,str(Path(__file__).resolve()),'--optimization',optimization,'--private-report',str(path)]
  if args.candidate_root: command+=['--candidate-root',str(CANDIDATE)]
  if args.fixture: command+=['--fixture',str(fixture_path)]
  subprocess.run(command,cwd=ROOT,check=True);reports.append(json.loads(path.read_text()))
 stable()
 if reports[0]['observations']!=reports[1]['observations']: raise AssertionError('O2/O3 workflow observations differ')
 report=dict(status='pass',full_firmware_complete=False,cases=5,native_calls_per_optimization=reports[0]['native_calls'],checks_per_optimization=reports[0]['checks'],optimization_reports=reports,scope=reports[0]['scope'])
 if args.private_report:
  args.private_report.parent.mkdir(parents=True,exist_ok=True);args.private_report.write_text(json.dumps(report,indent=2)+'\n')
 elif not args.no_report: write_report('analysis/c-verification/equation_workflow.json',report,[*sources,*SUPPORT,FIXTURE,'csrc/CMakeLists.txt'],TEST)
 print(json.dumps({k:report[k] for k in ('status','cases','native_calls_per_optimization','checks_per_optimization')}));sys.exit(0)
run=CANDIDATE/'analysis/build/equation-workflow'/uuid.uuid4().hex/args.optimization;run.mkdir(parents=True)
libfile=run/'candidate.so';nativefile=run/'native.so'
subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined','-I',str(CANDIDATE/'csrc'),*[str(CANDIDATE/p) for p in sources],str(CANDIDATE/SUPPORT[0]),'-o',str(libfile)],check=True)
subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(ROOT/'tools'),str(CANDIDATE/SUPPORT[1]),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(nativefile)],check=True)
artifacts={str(p):digest(p) for p in [libfile,nativefile]}
rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();m=Machine(rom,run/'base-oracle');native=C.CDLL(str(nativefile))
for name in ('harness_init','harness_set_pc','harness_get_pc','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_ram','harness_run','harness_trace_open'):
 getattr(native,name).argtypes=getattr(m.lib,name).argtypes;getattr(native,name).restype=getattr(m.lib,name).restype
m.lib=native;m.ram=native.harness_ram().contents;m.reset();native.lifecycle_run.argtypes=[C.c_uint64,C.c_uint32,C.c_uint]
lib=C.CDLL(str(libfile));lib.eq_ui_size.restype=C.c_size_t;lib.eq_controller_size.restype=C.c_size_t;lib.eq_controller_return.argtypes=[C.c_void_p];lib.eq_ui_field.argtypes=[C.c_void_p,C.c_uint]
pp=C.POINTER(Platform)
lib.fx_ui_controller_begin.argtypes=[pp,C.c_void_p,C.c_uint8,C.c_void_p];lib.fx_ui_controller_tick.argtypes=[pp,C.c_void_p]
lib.fx_equation_controller_begin.argtypes=[pp,C.c_void_p,C.c_void_p];lib.fx_equation_controller_tick.argtypes=[pp,C.c_void_p]
lib.eq_abi.argtypes=[C.c_uint];lib.eq_abi.restype=C.c_size_t
abi=[C.sizeof(Platform),*[getattr(Platform,n).offset for n in ('rom','rom_size','ram','callback_pending','status')],C.sizeof(Control),Control.cancelled.offset,Control.userdata.offset]
assert abi==[lib.eq_abi(n) for n in range(len(abi))]
rd=(C.c_uint8*len(rom)).from_buffer_copy(rom);ram=(C.c_uint8*65536)();p=Platform(rd,len(rom),ram,0,0)
frames=(C.c_uint8*65536).in_dll(native,'lifecycle_frames');observations=[];failures=[];checks=len(abi);polls=C.c_uint.in_dll(native,'lifecycle_polls')

def packed(b):return base64.b64encode(zlib.compress(b)).decode()
with gzip.open(run/'observations.jsonl.gz','wt') as archive:
 for scenario in fixture['scenarios']:
  initial=bytes.fromhex(fixture['initial_ram'][str(scenario['selector'])]);assert len(initial)==65536
  m.reset();C.memmove(ram,initial,65536);C.memmove(m.ram,initial,65536);p.status=p.callback_pending=0
  ram[0x8106]=m.ram[0x8106]=scenario['math'];seen_frames=bytearray(65536)
  def step(kind,token,label):
   global checks
   ram[0x80f5]=m.ram[0x80f5]=token;ram[0x80f7]=m.ram[0x80f7]=1
   native.lifecycle_reset()
   if kind=='input':
    state=C.create_string_buffer(lib.eq_ui_size());status=lib.fx_ui_controller_begin(C.byref(p),state,0,None);tick=lib.fx_ui_controller_tick;field=lib.eq_ui_field
   else:
    state=C.create_string_buffer(lib.eq_controller_size());status=lib.fx_equation_controller_begin(C.byref(p),state,None);tick=lib.fx_equation_controller_tick;field=lambda state,index:lib.eq_controller_return(state)
   for _ in range(12):
    if status!=4:break
    status=tick(C.byref(p),state)
   returned=field(state,0)
   m.reg(0,0);native.harness_set_sp(0x8dee);native.harness_set_lr(0x2fffe);native.harness_set_pc(0xd9ee if kind=='input' else 0xe862)
   native_status=native.lifecycle_run(50000000,0x2fffe,0)
   for i in range(65536):seen_frames[i]|=frames[i]
   actual,expected=bytes(ram),bytes(m.ram)
   residuals=[];unexpected=[]
   for i in range(65536):
    if actual[i]==expected[i]:continue
    v=[i,actual[i],expected[i]]
    if seen_frames[i] or 0x8000<=i<0x80dc or 0x8640<=i<0x87d0:residuals.append(v)
    else:unexpected.append(v)
   callback=lib.fx_take_callback(C.byref(p));native_callback=native.harness_callback()
   row={'scenario':scenario['label'],'stage':label,'kind':kind,'token':token,'host_status':status,'returned':returned,'native_status':native_status,'native_return':m.reg(0),'native_polls':polls.value,'callback':callback,'native_callback':native_callback,'unexpected':unexpected,'residuals':residuals,'c_ram_sha256':hashlib.sha256(actual).hexdigest(),'native_ram_sha256':hashlib.sha256(expected).hexdigest()}
   observations.append(row);checks+=4
   archive.write(json.dumps(dict(**row,c_ram=packed(actual),native_ram=packed(expected),frame_writes=packed(bytes(seen_frames))))+'\n')
   if status!=1 or native_status!=100 or returned!=m.reg(0) or callback!=native_callback or unexpected:failures.append(row)
   print(scenario['label'],label,status,returned,len(unexpected),flush=True)
  step('screen',0,'initial-grid')
  for i,expression in enumerate(scenario['coefficients']):
   for j,token in enumerate(bytes.fromhex(expression)):step('input',token,f'field-{i}-token-{j}')
   step('input',0xed,f'field-{i}-commit');step('screen',0xed,f'field-{i}-grid')
  step('screen',0xed,'solve')
  for root in range(scenario['selector']+1):step('input',0xed,f'root-{root+1}')
  step('input',0xed,'return-to-coefficients');step('screen',0,'returned-grid')
stable()
if any(digest(q)!=h for q,h in artifacts.items()): raise RuntimeError('Compiled library changed during execution')
if not args.fixture: assert len(observations)==161 and checks==653
scope='Prepared actual45/screen21 coefficient entry, successful linear2/3 solve and all root replay/return transitions, with independent retained full C/native RAM across each sequence. Native PC/SP/LR reset at routine boundaries; not uninterrupted boot-main proof. Numeric8000..80DB, inactive linalg8640..87CF and cumulative individually witnessed original frame-written bytes remain separately recorded residuals. Singular/error, polynomial/INEQ, cancellation and nested menu bodies remain explicit limits.'
report=dict(optimization=args.optimization,sequences=len(fixture['scenarios']),native_calls=len(observations),checks=checks,failures=failures,abi=abi,source_pins=pins,end_pins={q:digest(q) for q in pins},source_changes=[],compiled_artifacts=artifacts,observations=observations,scope=scope,archive=str(run/'observations.jsonl.gz'),archive_sha256=digest(run/'observations.jsonl.gz'))
(run/'proof.json').write_text(json.dumps(report,indent=2)+'\n')
if args.private_report:
 args.private_report.parent.mkdir(parents=True,exist_ok=True);args.private_report.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(optimization=args.optimization,sequences=report['sequences'],native_calls=len(observations),checks=checks,failures=len(failures),source_changes=[])))
if failures: sys.exit(1)
