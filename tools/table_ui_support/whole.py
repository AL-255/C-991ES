#!/usr/bin/env python3
import os
import sys,ctypes as C,subprocess,json,hashlib,importlib.util,itertools,gzip,base64,zlib
from evidence import pins,stable,sha
from pathlib import Path
ROOT=Path(os.environ['FX_TABLE_REPOSITORY_ROOT']);HERE=Path(os.environ['FX_TABLE_BUILD_ROOT'])
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from test_platform_c import Platform
from test_input_controller_c import Context,Controller as Input,Control
from test_table_controller_c import Controller as Table
class UI(C.Structure):
 _fields_=[('context',Context),('input',Input),('cancellation',Control),('request',C.c_int),*[(n,C.c_uint8)for n in ('phase','active','refresh_only','structured_input','command_token','command_index','handler_action','saved_result_state')],('table',Table)]
spec=importlib.util.spec_from_file_location('seeds',ROOT/'analysis/native-fixtures/table-controller-lifecycle/controller-final/collect.py');seeds=importlib.util.module_from_spec(spec);spec.loader.exec_module(seeds)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
opt=sys.argv[1]if len(sys.argv)>1 else 'O2'
lib=C.CDLL(str(HERE/('table-ui-'+opt+'.so')));pp=C.POINTER(Platform);ss=C.POINTER(UI)
lib.fx_ui_controller_begin.argtypes=[pp,ss,C.c_uint8,C.POINTER(Control)];lib.fx_ui_controller_tick.argtypes=[pp,ss];lib.fx_ui_controller_finish.argtypes=[ss,C.POINTER(C.c_uint8)]
rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rb=(C.c_uint8*len(rom)).from_buffer_copy(rom)
# Passive observation: only5550 external status is supplied. No body/output injection.
source=HERE/'oracle.c';source.write_text((ROOT/'tools/nxu8/table_composition_events.c').read_text().replace('#include "harness.c"','#include "'+str(ROOT/'tools/nxu8/harness.c')+'"'))
subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(source),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(HERE/'oracle.so')],check=True)
n=Machine(rom,HERE/'native');events=C.CDLL(str(HERE/'oracle.so'))
for name in ('harness_init','harness_set_pc','harness_get_pc','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_ram','harness_run','harness_callback'):
 getattr(events,name).argtypes=getattr(n.lib,name).argtypes;getattr(events,name).restype=getattr(n.lib,name).restype
n.lib=events;n.ram=events.harness_ram().contents;n.reset();events.observer_reset.argtypes=[C.c_uint];events.observer_run.argtypes=[C.c_uint64,C.c_uint32]
floor=C.c_uint.in_dll(events,'minimum_sp');polls=C.c_uint.in_dll(events,'polls');ram=(C.c_uint8*65536)();p=Platform(rb,len(rom),ram,0,0)
assert lib.ui_size()==C.sizeof(UI) and lib.ui_table_offset()==UI.table.offset
source_pins=pins([Path(__file__),source,HERE/'oracle.so',HERE/('table-ui-'+opt+'.so')])
archive=gzip.open(HERE/('observations-'+opt+'.jsonl.gz'),'wt')
recipes=[]
rows=[];failures=[];checks=0
specs=[]
for math,func,phase,expr in itertools.product((0,1),(0,1),(0,1),(b'',b'X',b'X+1',b'1+')):
 specs.append(dict(group='function',expression=expr,math=math,functions=func,phase=phase))
for math,item,expr in itertools.product((0,1),(1,2,3),(b'0',b'2',b'-2',b'1O0',b'1+')):
 specs.append(dict(group='parameter',expression=expr,math=math,screen=6,item=item))
for math,func,phase,cancel in itertools.product((0,1),(0,1),(0,128),(0,1,2)):
 specs.append(dict(group='generation',expression=b'1',math=math,screen=6,item=4,functions=func,phase=phase,cancel=cancel))
for screen,item,refresh,flags,token in itertools.product((1,6),(1,),(0,1),(1,3),(ord('1'),ord('+'),0x3d,0x3a,0x80,0x98,0xa4,0x8b,0x5b,0xd0,0xe4,0xe6,0xe2,0xe3,0xfe)):
 specs.append(dict(group='ui-policy',expression=b'2',screen=screen,item=item,refresh=refresh,flags=flags,token=token))
for i,case in enumerate(specs):
 args={k:v for k,v in case.items()if k not in ('group','cancel','refresh')};seeds.seed(n,**args);C.memmove(ram,n.ram,65536);p.callback_pending=0
 recipes.append(dict(case_id=i,setup={k:(v.hex()if isinstance(v,bytes)else v)for k,v in case.items()},initial_ram_zlib_base64=base64.b64encode(zlib.compress(bytes(ram))).decode()))
 state=UI();calls=[];CB=C.CFUNCTYPE(C.c_int,C.c_void_p)
 def cancel(_):calls.append(1);return int(case.get('cancel',0)!=0 and len(calls)==case['cancel'])
 callback=CB(cancel);control=Control(C.cast(callback,C.c_void_p),None)
 status=lib.fx_ui_controller_begin(C.byref(p),C.byref(state),case.get('refresh',0),C.byref(control));assert status==4
 n.er(0,case.get('refresh',0));n.lib.harness_set_sp(0x8dee);n.lib.harness_set_lr(0x2fffe);events.observer_reset(case.get('cancel',0));n.lib.harness_set_pc(0xd9ee)
 native=events.observer_run(10_000_000,0xda58);assert native==100
 def compare(label,numeric=False):
  global checks
  checks+=1;archive.write(json.dumps(dict(case_id=i,stage=label,minimum_sp=floor.value,c_ram_zlib_base64=base64.b64encode(zlib.compress(bytes(ram))).decode(),native_ram_zlib_base64=base64.b64encode(zlib.compress(bytes(n.ram))).decode()))+'\n');diff=[(hex(a),ram[a],n.ram[a])for a in range(65536)if ram[a]!=n.ram[a]and not floor.value<=a<0x8dee and not(0x8000<=a<0x80dc)]
  if diff:failures.append(dict(case_id=i,stage=label,case={k:(v.hex()if isinstance(v,bytes)else v)for k,v in case.items()},diff=diff[:50],total=len(diff)));print(json.dumps(failures[-1]),flush=True)if len(failures)<=8 else None
 compare('entry')
 for step in range(8):
  status=lib.fx_ui_controller_tick(C.byref(p),C.byref(state))
  if status!=4:break
 native=events.observer_run(20_000_000,0x2fffe)
 expected=0 if native==105 else 1 if native==100 else -99
 checks+=1
 if status!=expected:failures.append(dict(case_id=i,stage='status',status=status,expected=expected,request=state.request,phase=state.phase,pc=hex(n.lib.harness_get_pc()),case={k:(v.hex()if isinstance(v,bytes)else v)for k,v in case.items()}));print(json.dumps(failures[-1]),flush=True)if len(failures)<=8 else None
 compare('wait'if native==105 else 'return',case['group']in ('parameter','generation'))
 if native==105 and status==0:
  for key in ((4,16),):
   ram[0x8e01]=n.ram[0x8e01]=key[0];ram[0x8e02]=n.ram[0x8e02]=key[1]
   status=lib.fx_ui_controller_tick(C.byref(p),C.byref(state));n.lib.harness_run(1,0x2fffe,False);native=events.observer_run(20_000_000,0x2fffe)
   checks+=1
   if status!=1 or native!=100:failures.append(dict(case_id=i,stage='resume-status',status=status,native=native))
   compare('resume',True)
 if native==100 and status==1:
  checks+=1
  if state.context.return_value!=n.reg(0):failures.append(dict(case_id=i,stage='context-return',actual=state.context.return_value,expected=n.reg(0)))
 rows.append(dict(case_id=i,group=case['group'],native=native,status=status,polls=polls.value,host_polls=len(calls),minimum_sp=floor.value,final_native_sha=hashlib.sha256(bytes(n.ram)).hexdigest(),final_c_sha=hashlib.sha256(bytes(ram)).hexdigest()))
archive.close();(HERE/'whole-ui-inputs.json').write_text(json.dumps(recipes,indent=2)+'\n')
source_changes=stable(source_pins)
report=dict(input_pins=source_pins,source_changes=source_changes,transport_abi=dict(size=C.sizeof(UI),table_offset=UI.table.offset),archive_sha256=sha(HERE/('observations-'+opt+'.jsonl.gz')),limits=['Only original CPU stack below measured minimumSP and numerical scratch8000..80DB are excluded. All remainingphysicalRAM,pool,history and framebuffer compared. Prepared CPU9D00 seed context is unused by wholeD9EE and remains compared.','Saved-Math restoration, parameter-calculus cancellation and native grid row253+ nonreturn are outside this bounded caller proof; earlier original artifacts remain retained.'],scope='Actual uninterrupted whole D9EE TABLE; real C subordinates, no native body injection',optimization=opt,cases=len(rows),checks=checks,failures=failures,rows=rows,sources={str(p):sha(p)for p in (Path(__file__),source,HERE/('table-ui-'+opt+'.so'),HERE/'oracle.so',ROOT/'firmware/fx-991es-plus-c-ver4.bin')})
(HERE/('proof-'+opt+'.json')).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(dict(cases=len(rows),checks=checks,failures=len(failures))),flush=True)
