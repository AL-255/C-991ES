#!/usr/bin/env python3
import os
import ctypes as C,json,gzip,sys,base64,zlib,hashlib,subprocess
from pathlib import Path
ROOT=Path(os.environ['FX_TABLE_REPOSITORY_ROOT']);HERE=Path(os.environ['FX_TABLE_BUILD_ROOT'])
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from evidence import pins,stable,sha
opt=sys.argv[1]if len(sys.argv)>1 else 'O2';variant=sys.argv[2]if len(sys.argv)>2 else 'single';BUILD=HERE/('runtime-'+variant+'-'+opt);BUILD.mkdir(exist_ok=True);nd=BUILD/'native';nd.mkdir(exist_ok=True)
subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-I'+str(ROOT/'tools'),str(HERE/'runtime-native.c'),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(nd/'nxu8-harness.so')],check=True)
def digest_bytes(b):return hashlib.sha256(b).hexdigest()
seed=json.loads((ROOT/'analysis/native-fixtures/runtime/inputs.json').read_text())['rows'][14]
tokens=[0xe4,0x37,0x32,0xf0,0x31,0xf0,0x33,0xf0,0x31,0xf0,0xe1,0xe2,0xe3,0xe0,0xfe]
setup_tokens=[0xe9,0xe4,0xe1,0x35,0x31]if variant=='single' else [0xe9,0xe4,0xe1,0x35,0x32]if variant=='two' else [0xe9,0xe4,0x32]if variant=='linear'else []
if variant in ('two','linear'):tokens=tokens[:4]+[0x33,0xf0]+tokens[4:]
all_tokens=setup_tokens+tokens
fixture=dict(instruction_budget=50000000,rows=[dict(seed,id=1,group='TABLE-full',physical_tokens=all_tokens)])
class Platform(C.Structure):_fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),('ram',C.POINTER(C.c_uint8)),('callback_pending',C.c_uint8),('status',C.c_int)]
class Pair(C.Structure):_fields_=[('columns',C.c_uint8),('rows',C.c_uint8)]
lib=C.CDLL(str(HERE/('table-ui-'+opt+'.so')));lib.runtime_size.restype=C.c_size_t
lib.runtime_transport_abi.argtypes=[C.c_uint];lib.runtime_transport_abi.restype=C.c_size_t
expected_abi=[C.sizeof(Platform),Platform.rom.offset,Platform.rom_size.offset,Platform.ram.offset,Platform.callback_pending.offset,Platform.status.offset,C.sizeof(Pair),Pair.columns.offset,Pair.rows.offset]
actual_abi=[lib.runtime_transport_abi(i) for i in range(len(expected_abi))];assert actual_abi==expected_abi
lib.runtime_field.argtypes=[C.c_void_p,C.c_uint];lib.runtime_field.restype=C.c_uint
lib.fx_runtime_reset.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_void_p]
lib.fx_runtime_step.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_void_p,C.c_uint8]
lib.fx_runtime_submit_pair.argtypes=[C.POINTER(Platform),Pair]
lib.fx_take_callback.argtypes=[C.POINTER(Platform)]
lib.fx_runtime_accept_body.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_uint8,C.c_uint8]
rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rd=(C.c_uint8*len(rom)).from_buffer_copy(rom);ram=(C.c_uint8*65536)();p=Platform(rd,len(rom),ram,0,0)
s=C.create_string_buffer(lib.runtime_size());n=Machine(rom,nd)
nl=n.lib;nl.runtime_run_to.argtypes=[C.c_uint32,C.c_uint64];nl.runtime_run_to.restype=C.c_int
frames=(C.c_uint8*65536).in_dll(nl,'runtime_frame_writes')
pairs={rom[0x7fe+8*col+row]:(1<<col,1<<row) for col in range(8) for row in range(8)}
def field(i):return lib.runtime_field(s,i)
def packed(b):return base64.b64encode(zlib.compress(b)).decode()
NUMERIC_RESIDUAL_CHECKPOINTS = set([(1, 'arithmetic:0xf0:3'), (1, 'arithmetic:0xf0:4'), (1, 'next-key-wait'), (2, 'arithmetic:0xf0:3'), (2, 'arithmetic:0xf0:4'), (2, 'next-key-wait'), (3, 'arithmetic:0xf0:3'), (3, 'arithmetic:0xf0:4'), (3, 'next-key-wait'), (4, 'arithmetic:0xf0:3'), (4, 'arithmetic:0xf0:4'), (4, 'next-key-wait'), (5, 'arithmetic:0xf0:3'), (5, 'arithmetic:0xf0:4'), (5, 'next-key-wait'), (6, 'arithmetic:0xf0:3'), (6, 'arithmetic:0xf0:4'), (6, 'next-key-wait'), (7, 'arithmetic:0xf0:3'), (7, 'arithmetic:0xf0:4'), (7, 'next-key-wait'), (8, 'arithmetic:0xf0:3'), (8, 'arithmetic:0xf0:4'), (8, 'next-key-wait'), (9, 'arithmetic:0xf0:3'), (9, 'arithmetic:0xf0:4'), (9, 'next-key-wait'), (12, 'back:bank-return'), (12, 'back:MODE-return'), (12, 'back:wholeINPUT-entry'), (12, 'back:wholeINPUT-preparation')])
NUMERIC_RESIDUAL_CHECKPOINTS.update((12,label) for label in ('back:wholeINPUT-completed','back:wholeINPUT-cycle-return','back:next-real-key-wait'))
source_pins=pins([Path(__file__),HERE/('table-ui-'+opt+'.so'),HERE/'runtime-native.c',nd/'nxu8-harness.so',ROOT/'analysis/native-fixtures/runtime/inputs.json'])
rows=[];failures=[];residuals=[];pending_bodies=[];completed_bodies=[];checks=0;sequence_id=0; token_index=0
def compare(label,stop,status,numeric=False):
 global checks
 if nl.harness_get_pc()==stop:assert nl.harness_run(1,0x2fffe,False)==103
 result=nl.runtime_run_to(stop,fixture['instruction_budget'])
 after=bytes(n.ram);actual=bytes(ram)
 diffs=[(i,after[i],actual[i]) for i in range(65536) if after[i]!=actual[i] and not frames[i]]
 allowed=[v for v in diffs if 0x8000<=v[0]<0x80dc]
 unexpected=[v for v in diffs if v not in allowed]
 callback=lib.fx_take_callback(C.byref(p));native_callback=nl.harness_callback()
 semantic=[]
 if stop==0xd87e and field(12)!=n.reg(0):semantic.append(['INPUT-context-return',field(12),n.reg(0)])
 if stop in (0xd98e,0xd99e) and field(19)!=n.reg(0):semantic.append(['MODE/SETUP-return',field(19),n.reg(0)])
 if stop in (0xc9e8,0xc9f4) and field(20)!=n.reg(0):semantic.append(['BANK-return',field(20),n.reg(0)])
 if stop==0xd7b4:
  if field(3)!=n.reg(5):semantic.append(['main-wait',field(3),n.reg(5)])
  if field(4)!=n.reg(4):semantic.append(['main-last-menu-result',field(4),n.reg(4)])
 if stop in (0xecaa,0xeca6) and field(11)!=n.reg(0):semantic.append(['rich-view-argument',field(11),n.reg(0)])
 record=dict(sequence=sequence_id,label=label,status=status,event=field(1),phase=field(0),native_stop=result,native_pc=nl.harness_get_pc(),minimum_sp=C.c_uint.in_dll(nl,'runtime_floor').value,frame_bytes=sum(frames),callback=callback,native_callback=native_callback,unexpected=unexpected,numeric_residuals=allowed,semantic=semantic,main_request=field(2),wait_required=field(3),last_menu_result=field(4),timer=field(6),export_mask=field(7),request_kind=field(9),request_operation=field(10),context_return=field(12),handler_action=field(13),mode_page=field(14),bank_page=field(15),ram_sha256=digest_bytes(actual),native_ram_sha256=digest_bytes(after))
 rows.append(record);checks+=3
 archive.write(json.dumps(dict(**record,c_ram_zlib_base64=packed(actual),native_ram_zlib_base64=packed(after),frame_writes_zlib_base64=packed(bytes(frames))))+'\n')
 if result!=100 or unexpected or semantic or callback!=native_callback:
  failures.append(record);raise AssertionError({k:record[k] for k in ['label','phase','event','native_stop','native_pc','unexpected','callback','native_callback']})
 if allowed:residuals.append(dict(sequence=sequence_id,label=label,bytes=allowed))
def digest_bytes(b):return hashlib.sha256(b).hexdigest()
def step(label,numeric=False):
 before=field(0);has_pair=bool(ram[0x8e01] or ram[0x8e02]);status=lib.fx_runtime_step(C.byref(p),s,None,0);event=field(1)
 stop=None
 if event==2:stop={1:0xd9ee,2:0xc978,3:0xca7c}[field(2)]
 elif event==3 and before==3:stop=0xda58
 elif event==4:
  stop={4:0xd87e,7:0xd98e if field(2)==2 else 0xd99e,10:0xc9e8 if field(16)==1 else 0xc9f4}.get(before)
  if before==7 and field(2)==3:stop=0xd99e
  if before==11:stop=0xd98e
 elif event==5:stop=0xd7b4
 elif event in (6,7,10):stop=0x1d8d0 if event==7 and not has_pair else 0x1d8a4
 elif event==8:stop=0xd0cc
 elif event==9:stop=0x53ce
 elif event==11:
  if field(9)==1:stop={7:0xecaa,8:0xeca6,4:0xcd66,5:0xf02c,6:0xe22a,10:0xe1be}.get(field(10))
  elif field(9)==2:stop=0xda58 # UI readiness gate atDA58 needs later exact leaf boundary.
 if stop is not None:compare(label,stop,status,numeric)
 return status
def release():
 lib.fx_runtime_submit_pair(C.byref(p),Pair(0,0));n.ram[0x8e01]=n.ram[0x8e02]=0
def raw(token):
 global token_index
 tokens=fixture['rows'][sequence_id-1]['physical_tokens']
 assert token_index < len(tokens) and token == tokens[token_index]
 token=tokens[token_index];token_index+=1
 key=pairs[token];lib.fx_runtime_submit_pair(C.byref(p),Pair(*key));n.ram[0x8e01],n.ram[0x8e02]=key
def retain_body(label):
 global checks
 before=bytes(ram);status=lib.fx_runtime_step(C.byref(p),s,None,0)
 assert status==4 and bytes(ram)==before
 row=dict(sequence=sequence_id,label=label,kind=field(9),operation=field(10),argument=field(11),context_return=field(12),handler_action=field(13),expression_address=field(21),result_address=field(22),prepared_source=field(23),current_source=field(24),native_prefix_pc=nl.harness_get_pc(),ram_sha256=digest_bytes(before),native_completion_claim=False)
 pending_bodies.append(row);checks+=1
 archive.write(json.dumps(dict(**row,type='host-only-retained-body',ram_zlib_base64=packed(before)))+'\n')
def action(token,label,numeric=False):
 raw(token)
 for k in range(20):
  status=step(label+':'+str(k),numeric)
  if field(1)==5:
   release();return status
  if status==4:
   status=body(label+':body')
   if status==4:return status
   if field(1)==5:
    release();return status
 raise AssertionError(('unbounded action',label,field(0),field(1)))
def boot(port,mode=None):
 global sequence_id,token_index
 if sequence_id:
  assert token_index == len(fixture['rows'][sequence_id-1]['physical_tokens'])
 token_index=0
 sequence_id+=1
 row = fixture['rows'][sequence_id - 1]
 if row['group'] == 'arithmetic':
  assert row['port'] == port and row['mode'] == mode
 seed = bytearray(zlib.decompress(base64.b64decode(row['initial_ram_zlib_base64'])))
 n.reset();nl.runtime_observer_reset();C.memmove(n.ram,bytes(seed),65536);C.memmove(ram,bytes(seed),65536);p.callback_pending=p.status=0
 status=lib.fx_runtime_reset(C.byref(p),s,None);assert status==1 and field(1)==1
 nl.harness_set_pc(0x6f82);compare('reset-to-boot-ready',0xd7ae,status)
 for k in range(8):
  step('boot-input:'+str(k))
  if field(1)==5:break
 release();assert step('first-key-wait')==0
 return bytes(seed)

lib.table_body_size.restype=C.c_size_t
b=C.create_string_buffer(lib.table_body_size())
lib.table_body_from_runtime.argtypes=[C.POINTER(Platform),C.c_void_p,C.c_void_p]
lib.fx_table_body_tick.argtypes=[C.POINTER(Platform),C.c_void_p]
lib.table_body_field.argtypes=[C.c_void_p,C.c_uint];lib.table_body_field.restype=C.c_uint
def body(label):
 for route in range(4):
  operation=field(10)
  if field(9)!=1 or operation not in (5,6,10):return 4
  status=lib.table_body_from_runtime(C.byref(p),b,s)
  for k in range(16):
   if status!=4:break
   status=lib.fx_table_body_tick(C.byref(p),b)
  if status!=1:raise AssertionError(('TABLE-body-gap',operation,status,lib.table_body_field(b,0),lib.table_body_field(b,2)))
  returned=lib.table_body_field(b,1)
  compare(label+':original-body-return',{5:0xd8fe,6:0xd90a,10:0xd942}[operation],status,True)
  status=lib.fx_runtime_accept_body(C.byref(p),s,0,returned)
  if status!=4:
   if field(1)==5:compare(label+':main-commit',0xd7b4,status,True)
   return status
  if field(9)==1 and field(10)==6:compare(label+':actual-grid-admission',0xe22a,status,True)
 return status
with gzip.open(BUILD/'observations.jsonl.gz','wt') as archive:
 boot(0)
 if setup_tokens:
  raw(0xe9);step('SETUP:SHIFT',True);release()
  raw(0xe4);step('SETUP:entry',True);step('SETUP:wait',True);release()
  for token in setup_tokens[2:]:
   raw(token);status=step('SETUP:choice-'+hex(token),True);release()
  step('SETUP:return',True)
  for k in range(12):
   step('SETUP:followup:'+str(k),True)
   if field(1)==5:break
  release();step('SETUP:first-wait',True)
 raw(0xe4);step('TABLE:MODE-entry');step('TABLE:MODE-wait');release()
 raw(0x37);step('TABLE:MODE-choice',True);release();step('TABLE:MODE-return',True)
 for k in range(10):
  status=step('TABLE:initial-input:'+str(k),True)
  if field(1)==5:break
 release();step('TABLE:first-wait',True)
 for token in tokens[2:]:
  action(token,'TABLE:key-'+hex(token),True)
  # Immediate range prompts/generation happen before the next wait.
  for k in range(30):
   status=step('TABLE:followup-'+hex(token)+':'+str(k),True)
   if status==4:
    status=body('TABLE:followup-body-'+hex(token))
    if status==4:raise AssertionError(('uncompleted',field(9),field(10)))
   if status==0 and field(1) in (6,7):break
  else:raise AssertionError(('no-wait',hex(token),field(0),field(1)))
assert token_index==len(all_tokens),(token_index,len(all_tokens))
assert ram[0x80de]==3 and ram[0x80fc]==18,(ram[0x80de],ram[0x80fc])
report=dict(input_pins=source_pins,source_changes=stable(source_pins),archive_sha256=sha(BUILD/'observations.jsonl.gz'),limits=['Native PC set onlyonce6F82 per sequence; only externalrawkeypackets and5550 readiness0 are supplied. All persistent RAM outside witnessedCPUframewrites compared; numerical8000..80DB differences retained explicitly in residuals.', 'Typed unfinished contexts are not completed. Row253+ nativeCPU nonreturn remains earlierpreparedkernel architecture boundary.'],variant=variant,scope='Uninterrupted reset6F82 raw MODE TABLE input/range/generation/navigation using actual C bodies',optimization=opt,observations=len(rows),checks=checks,failures=failures,residuals=residuals,rows=rows,fixture=fixture)
(BUILD/'proof.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(observations=len(rows),checks=checks,failures=len(failures))),flush=True)
