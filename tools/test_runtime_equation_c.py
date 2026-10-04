#!/usr/bin/env python3
"""Fresh uninterrupted boot/main/EQN composition. GPL-3.0-only."""
from pathlib import Path
import ctypes as C,sys,json,gzip,base64,zlib,hashlib,re,subprocess,uuid,argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from c_build_inputs import implementation_inputs
ap=argparse.ArgumentParser();ap.add_argument('--verbose',action='store_true');ap.add_argument('--prefix-controls',action='store_true');ap.add_argument('--optimization',choices=['O2','O3'],default='O2');args=ap.parse_args()
fixture_path=ROOT/('analysis/native-fixtures/runtime-equation/prefix-inputs.json' if args.prefix_controls else 'analysis/native-fixtures/runtime-equation/inputs.json')
cmake_path=ROOT/'csrc/CMakeLists.txt'
fixture_bytes=fixture_path.read_bytes();cmake_bytes=cmake_path.read_bytes()
parsed_pins={str(fixture_path):hashlib.sha256(fixture_bytes).hexdigest(),str(cmake_path):hashlib.sha256(cmake_bytes).hexdigest()}
fixture=json.loads(fixture_bytes)
run=ROOT/'analysis/build/runtime-equation'/uuid.uuid4().hex/args.optimization;run.mkdir(parents=True)
sources=['csrc/'+n for n in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',cmake_bytes.decode().split('target_include_directories')[0])]
implementation_closure=implementation_inputs(ROOT,sources)
paths=[*[ROOT/n for n in implementation_closure],ROOT/'csrc/CMakeLists.txt',ROOT/'tools/runtime_equation_support/adapter.c',ROOT/'tools/runtime_equation_support/native.c',fixture_path,Path(__file__).resolve(),ROOT/'tools/nxu8/harness.c',ROOT/'tools/nxu8/vendor/SimU8/core.c',*sorted((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')),ROOT/'firmware/fx-991es-plus-c-ver4.bin']
paths += [Path(v.__file__).resolve() for v in sys.modules.values() if getattr(v,'__file__',None) and Path(v.__file__).resolve().is_relative_to(ROOT/'tools')]
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def raw_packed(data):return base64.b64encode(zlib.compress(data)).decode()
archive_seed=zlib.decompress(base64.b64decode(fixture['initial_ram_zlib_base64']))
archive_seed_int=int.from_bytes(archive_seed,'little')
def packed(data):
 assert len(data)==65536
 delta=(int.from_bytes(data,'little')^archive_seed_int).to_bytes(65536,'little')
 return raw_packed(delta)
pins={str(p):digest(p) for p in paths}
assert all(pins[p]==h for p,h in parsed_pins.items()),'parsed fixture/CMake changed before pin capture'
assert implementation_inputs(ROOT,sources)==implementation_closure,'implementation closure changed before compile'
assert all(digest(p)==h for p,h in pins.items()),'input changed before compile'
libpath=run/'candidate.so';nativepath=run/'native'
subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined','-Wl,--wrap=fx_timer_start','-I',str(ROOT/'csrc'),*[str(ROOT/n) for n in sources],str(ROOT/'tools/runtime_equation_support/adapter.c'),'-o',str(libpath)],check=True)
nativepath.mkdir();subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(ROOT/'tools'),str(ROOT/'tools/runtime_equation_support/native.c'),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(nativepath/'nxu8-harness.so')],check=True)
artifacts={str(p):digest(p) for p in [libpath,nativepath/'nxu8-harness.so']}
class Platform(C.Structure):_fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),('ram',C.POINTER(C.c_uint8)),('callback_pending',C.c_uint8),('status',C.c_int)]
class Pair(C.Structure):_fields_=[('columns',C.c_uint8),('rows',C.c_uint8)]
lib=C.CDLL(str(libpath));lib.runtime_size.restype=lib.runtime_equation_size.restype=C.c_size_t
lib.runtime_transport_abi.argtypes=[C.c_uint];lib.runtime_transport_abi.restype=C.c_size_t
abi=[C.sizeof(Platform),Platform.rom.offset,Platform.rom_size.offset,Platform.ram.offset,Platform.callback_pending.offset,Platform.status.offset,C.sizeof(Pair),Pair.columns.offset,Pair.rows.offset]
assert abi==[lib.runtime_transport_abi(i) for i in range(len(abi))]
pp=C.POINTER(Platform)
for name in ('fx_runtime_reset','fx_equation_controller_begin'):getattr(lib,name).argtypes=[pp,C.c_void_p,C.c_void_p]
lib.fx_runtime_step.argtypes=[pp,C.c_void_p,C.c_void_p,C.c_uint8];lib.fx_runtime_submit_pair.argtypes=[pp,Pair];lib.fx_runtime_accept_body.argtypes=[pp,C.c_void_p,C.c_uint8,C.c_uint8]
lib.equation_begin_controlled.argtypes=[pp,C.c_void_p]
lib.equation_control_reset.argtypes=[C.c_uint]
lib.fx_equation_controller_tick.argtypes=[pp,C.c_void_p];lib.fx_equation_controller_finish.argtypes=[C.c_void_p,C.POINTER(C.c_uint8)]
lib.runtime_field.argtypes=lib.runtime_equation_field.argtypes=[C.c_void_p,C.c_uint];lib.fx_take_callback.argtypes=[pp]
rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rd=(C.c_uint8*len(rom)).from_buffer_copy(rom);ram=(C.c_uint8*65536)();p=Platform(rd,len(rom),ram,0,0);state=C.create_string_buffer(lib.runtime_size())
n=Machine(rom,nativepath);nl=n.lib;nl.runtime_run_to.argtypes=[C.c_uint32,C.c_uint64];nl.runtime_run_to.restype=C.c_int
frames=(C.c_uint8*65536).in_dll(nl,'runtime_frame_writes');native_polls=C.c_uint.in_dll(nl,'equation_native_polls');c_polls=C.c_uint.in_dll(lib,'equation_c_polls');native_cancel=C.c_uint.in_dll(nl,'equation_native_cancel_at')
c_poll_ram=((C.c_uint8*65536)*256).in_dll(lib,'equation_c_poll_ram');n_poll_ram=((C.c_uint8*65536)*256).in_dll(nl,'equation_poll_ram')
pairs={rom[0x7fe+8*column+row]:(1<<column,1<<row) for column in range(8) for row in range(8)}
rows=[];failures=[];poll_rows=[];checks=len(abi);sequence=0;token_index=0

def field(index):return lib.runtime_field(state,index)
def compare(label,stop,status):
 global checks
 if nl.harness_get_pc()==stop:assert nl.harness_run(1,0x2fffe,False)==103
 result=nl.runtime_run_to(stop,fixture['instruction_budget']);actual,expected=bytes(ram),bytes(n.ram)
 residuals=[];unexpected=[]
 for i in range(65536):
  if actual[i]==expected[i]:continue
  v=[i,actual[i],expected[i]]
  if frames[i] or 0x8000<=i<0x80dc or 0x8640<=i<0x87d0:residuals.append(v)
  else:unexpected.append(v)
 callback=lib.fx_take_callback(C.byref(p));native_callback=nl.harness_callback();semantic=[]
 if stop==0xd87e and field(12)!=n.reg(0):semantic.append(['context-return',field(12),n.reg(0)])
 if stop==0xd98e and field(19)!=n.reg(0):semantic.append(['mode-return',field(19),n.reg(0)])
 if stop==0xd7b4 and field(3)!=n.reg(5):semantic.append(['main-wait',field(3),n.reg(5)])
 row=dict(sequence=sequence,label=label,status=status,event=field(1),phase=field(0),wait=field(3),pending=field(2),body_kind=field(9),body_operation=field(10),context_return=field(12),handler_action=field(13),native_status=result,native_pc=nl.harness_get_pc(),native_return=n.reg(0),native_polls=native_polls.value,callback=callback,native_callback=native_callback,unexpected=unexpected,residuals=residuals,semantic=semantic,c_ram_sha256=hashlib.sha256(actual).hexdigest(),native_ram_sha256=hashlib.sha256(expected).hexdigest())
 rows.append(row);checks+=3;archive.write(json.dumps(dict(**row,c_ram=packed(actual),native_ram=packed(expected),frame_writes=raw_packed(bytes(frames))))+'\n')
 if args.verbose:print(sequence,label,status,field(0),field(1),field(3),hex(stop),len(unexpected),flush=True)
 if result!=100 or unexpected or semantic or callback!=native_callback:
  failures.append(row);raise AssertionError(row)

def step(label):
 before=field(0);status=lib.fx_runtime_step(C.byref(p),state,None,0);event=field(1);stop=None
 if event==2:stop={1:0xd9ee,2:0xc978,3:0xca7c}[field(2)]
 elif event==3 and before==3:stop=0xda58
 elif event==4:
  stop={4:0xd87e,7:0xd98e if field(2)==2 else 0xd99e,10:0xc9e8 if field(16)==1 else 0xc9f4}.get(before)
  if before==11:stop=0xd98e
 elif event==5:stop=0xd7b4
 elif event in (6,7,10):stop=0x1d8a4
 elif event==8:stop=0xd0cc
 elif event==9:stop=0x53ce
 elif event==11:
  if field(9)==1:stop={9:0xe862}.get(field(10))
  elif field(9)==2:stop=0xda58
 if stop is not None:compare(label,stop,status)
 return status

def release():
 lib.fx_runtime_submit_pair(C.byref(p),Pair(0,0));n.ram[0x8e01]=n.ram[0x8e02]=0

def equation_body(label):
 global checks
 assert field(9)==1 and field(10)==9
 body=C.create_string_buffer(lib.runtime_equation_size());lib.equation_timer_reset();before=native_polls.value
 prefix=args.prefix_controls and token_index==len(scenario['physical_tokens'])
 if prefix:
  lib.equation_control_reset(scenario['cancel_at']);native_cancel.value=before+scenario['cancel_at'] if scenario['cancel_at'] else 0
 status=lib.equation_begin_controlled(C.byref(p),body) if prefix else lib.fx_equation_controller_begin(C.byref(p),body,None)
 for _ in range(20):
  if status!=4:break
  status=lib.fx_equation_controller_tick(C.byref(p),body)
 if not prefix and status!=1:raise AssertionError(('explicit-equation-body-gap',label,status,lib.runtime_equation_field(body,1)))
 returned=C.c_uint8(255)
 if prefix:
  assert status==-2,('expected-unsupported-prefix',label,status)
  assert lib.fx_equation_controller_finish(body,C.byref(returned))!=1 and returned.value==255
  compare(label+':retained-actual-E884-prefix',0xe884,status)
  assert n.reg(0)==scenario['expected_firmware_status'],(label,n.reg(0))
 else:
  assert lib.fx_equation_controller_finish(body,C.byref(returned))==1
  compare(label+':actual-E862-return',0xd934,status);assert returned.value==n.reg(0)
 actual_count=c_polls.value;assert actual_count<=256 and before+actual_count<=256
 expected_count=native_polls.value-before;assert actual_count==expected_count,(label,actual_count,expected_count)
 for index in range(actual_count):
  a,b=bytes(c_poll_ram[index]),bytes(n_poll_ram[before+index]);differences=[[i,a[i],b[i]] for i in range(65536) if a[i]!=b[i] and not frames[i]]
  row=dict(sequence=sequence,label=label,index=index,persistent_differences=[v for v in differences if not(0x8000<=v[0]<0x80dc or 0x8640<=v[0]<0x87d0)])
  poll_rows.append(row);archive.write(json.dumps(dict(**row,type='actual5550-poll-comparison',c_ram=packed(a),native_ram=packed(b)))+'\n')
 checks+=2
 if prefix:
  assert field(0)==12 and field(9)==1 and field(10)==9
  checks+=3;return 5
 accepted=lib.fx_runtime_accept_body(C.byref(p),state,0,returned.value);assert accepted==1
 compare(label+':actual-main-cycle',0xd7b4,accepted)
 return accepted

def press(token,label):
 global token_index
 assert token==scenario['physical_tokens'][token_index];token_index+=1
 pair=pairs[token];lib.fx_runtime_submit_pair(C.byref(p),Pair(*pair));n.ram[0x8e01],n.ram[0x8e02]=pair
 for index in range(50):
  status=step(label+':'+str(index))
  if status==4:
   if equation_body(label+':body-'+str(index))==5:return
   continue
  if status==0:release();return
  if field(1)==5 and field(3):release()
  if status in (2,3,5) or status<0:raise AssertionError(('retained-nonterminal',label,status,field(1),field(0)))
 raise AssertionError(('unbounded-press',label,field(0),field(1)))

with gzip.open(run/'observations.jsonl.gz','wt') as archive:
 archive.write(json.dumps(dict(type='archive-encoding',ram_encoding='zlib-base64-xor-initial-seed',ram_size=65536,initial_ram=raw_packed(archive_seed),initial_ram_sha256=fixture['initial_ram_sha256'],frame_encoding='zlib-base64'))+'\n')
 for scenario in fixture['scenarios']:
  sequence+=1;token_index=0
  seed=zlib.decompress(base64.b64decode(fixture['initial_ram_zlib_base64']));assert len(seed)==65536 and hashlib.sha256(seed).hexdigest()==fixture['initial_ram_sha256']
  n.reset();nl.runtime_observer_reset();C.memmove(n.ram,seed,65536);C.memmove(ram,seed,65536);p.callback_pending=p.status=0
  status=lib.fx_runtime_reset(C.byref(p),state,None);assert status==1;nl.harness_set_pc(0x6f82);compare('original-reset-to-ready',0xd7ae,status)
  for index in range(10):
   if step('boot-input:'+str(index))==0:break
  release()
  for index,token in enumerate(scenario['physical_tokens']):press(token,scenario['label']+':physical-'+str(index)+'-'+hex(token))
  assert token_index==len(scenario['physical_tokens'])
  assert ram[0x80f9]==0x45 and ram[0x80fa]==scenario['selector'] and ram[0x80fc]==21
  if args.verbose:print('SEQUENCE-END',scenario['label'],hex(ram[0x80f9]),ram[0x80fa],ram[0x80fc],ram[0x8113],flush=True)
# Invalid admission controls independently enforce the narrow public API:
# every RAM byte, action and caller result must remain unchanged.
lib.runtime_equation_result_size.restype=C.c_size_t
lib.fx_equation_solve_linear_controlled.argtypes=[pp,C.POINTER(C.c_uint8),C.c_void_p,C.c_void_p]
base=bytearray(ram);base[0x80f9]=0x45;base[0x80fa]=1;base[0x80fc]=21;base[0x80fd]=0;base[0x80f5]=0xf0;base[0x80f7]=1
invalid_admission=[]
for label,address,value in [('mode',0x80f9,0x44),('selector-zero',0x80fa,0),('selector-polynomial',0x80fa,3),('screen',0x80fc,20),('state',0x80fd,1),('key',0x80f5,0x30),('busy',0x80f7,0)]:
 data=bytearray(base);data[address]=value;C.memmove(ram,bytes(data),65536)
 output=C.create_string_buffer(b'\xa5'*lib.runtime_equation_result_size(),lib.runtime_equation_result_size());before_output=bytes(output);action=C.c_uint8(77)
 result=lib.fx_equation_solve_linear_controlled(C.byref(p),C.byref(action),output,None)
 assert result==-1 and bytes(ram)==bytes(data) and bytes(output)==before_output and action.value==77
 invalid_admission.append(label);checks+=4
for label in ('null-platform','null-ram','null-action','null-result'):
 C.memmove(ram,bytes(base),65536);output=C.create_string_buffer(b'\xa5'*lib.runtime_equation_result_size(),lib.runtime_equation_result_size());before_output=bytes(output);action=C.c_uint8(77)
 target=C.byref(p);action_ptr=C.byref(action);output_ptr=output;saved_ram=p.ram
 if label=='null-platform':target=None
 elif label=='null-ram':p.ram=None
 elif label=='null-action':action_ptr=None
 else:output_ptr=None
 result=lib.fx_equation_solve_linear_controlled(target,action_ptr,output_ptr,None);p.ram=saved_ram
 assert result==-2 and bytes(ram)==bytes(base) and bytes(output)==before_output and action.value==77
 invalid_admission.append(label);checks+=4
assert implementation_inputs(ROOT,sources)==implementation_closure,'implementation closure changed during proof'
changes=[q for q,h in pins.items() if digest(q)!=h];assert not changes,changes
assert all(digest(q)==h for q,h in artifacts.items())
gap_count=sum(bool(r['persistent_differences']) for r in poll_rows);assert gap_count==0,poll_rows
report=dict(status='pass-with-numeric-residuals',prefix_controls=args.prefix_controls,invalid_admission_controls=invalid_admission,full_firmware_complete=False,poll_publication_complete=True,optimization=args.optimization,sequences=sequence,observations=len(rows),checks=checks,failures=failures,rows=rows,poll_rows=poll_rows,poll_count=len(poll_rows),poll_snapshot_persistent_gap_count=sum(bool(r['persistent_differences']) for r in poll_rows),source_pins=pins,source_changes=changes,artifacts=artifacts,scope='Actual uninterrupted original6F82 and named C runtime through external successful linear EQN body API. Numeric/inactive-linalg/workspace residuals and actual witnessed original frames are retained. All actual prepared timer polls compare the full persistent RAM, including intermediate dimensions/work banks and timer MMIO; numeric residuals remain explicit. Successful routes finish root replay and return; the separate prefix-controls corpus retains native error/cancellation work and explicit unsupported UI handoff before original E884.')
(run/'proof.json').write_text(json.dumps(report,indent=2)+'\n');print('REPORT',run/'proof.json','polls',len(poll_rows),'snapshot-gaps',report['poll_snapshot_persistent_gap_count'])
