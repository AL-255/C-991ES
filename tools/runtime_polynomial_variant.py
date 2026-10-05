#!/usr/bin/env python3
"""Private single-build uninterrupted polynomial runtime/native proof.

Only authored initial RAM, physical packets and timer readiness are inputs.
Arithmetic scratch 8000..80DB and individually witnessed original CPU-frame
writes remain explicit residuals. Inactive pools, display and MMIO are strict.
"""
from pathlib import Path
import ctypes as C,sys,json,gzip,base64,zlib,hashlib,re,subprocess,uuid,argparse,os
SCRIPT_ROOT=Path(__file__).resolve().parents[1]
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'firmware/fx-991es-plus-c-ver4.bin').exists());sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from c_build_inputs import implementation_inputs
ap=argparse.ArgumentParser();ap.add_argument('--build-dir',type=Path,required=True);ap.add_argument('--candidate-root',type=Path);ap.add_argument('--verbose',action='store_true');ap.add_argument('--corpus',choices=['polynomial','error','witness','all'],default='all');ap.add_argument('--optimization',choices=['O2','O3'],default='O2');args=ap.parse_args()
if sys.flags.optimize:ap.error('Optimized Python disables proof assertions')
SOURCE=(args.candidate_root or SCRIPT_ROOT).resolve()
fixture_path=SCRIPT_ROOT/'analysis/native-fixtures/runtime-polynomial/inputs.json'
cmake_path=SOURCE/'csrc/CMakeLists.txt'
fixture_bytes=fixture_path.read_bytes();cmake_bytes=cmake_path.read_bytes()
parsed_pins={str(fixture_path):hashlib.sha256(fixture_bytes).hexdigest(),str(cmake_path):hashlib.sha256(cmake_bytes).hexdigest()}
fixture=json.loads(fixture_bytes)
assert set(fixture)=={'instruction_budget','scenarios','basis','schema','entry','default_recipes','legacy_pending_sha256','browser_inputs_sha256'}
assert fixture['schema']==1 and fixture['entry']=='uninterrupted-boot-6F82-once'
assert fixture['default_recipes']==28 and len(fixture['scenarios'])==28
assert fixture['instruction_budget']==24000000
assert len({v['label'] for v in fixture['scenarios']})==28
for v in fixture['scenarios']:
 assert {'label','selector','coefficients','physical_tokens','corpus','initial_ram_zlib_base64','initial_ram_sha256'}<=set(v)<={'label','selector','coefficients','physical_tokens','corpus','initial_ram_zlib_base64','initial_ram_sha256','legacy_variant','cancel_at','host_pairs'}
 assert v['selector'] in (3,4) and v['corpus'] in ('polynomial','error','witness')
 assert v['physical_tokens'][:3]==[228,53,48+v['selector']]
 assert all(type(t)is int and 0<t<258 for t in v['physical_tokens'])
 assert v.get('cancel_at',0) in (0,1,2)
 assert all(isinstance(text,str) and bytes.fromhex(text) for text in v['coefficients'])
 assert all(k in ('256','257') and len(p)==2 and p[1]==128 and p[0] in (16,32,64,128) for k,p in v.get('host_pairs',{}).items())
 seed=zlib.decompress(base64.b64decode(v['initial_ram_zlib_base64'],validate=True))
 assert len(seed)==65536 and hashlib.sha256(seed).hexdigest()==v['initial_ram_sha256']
legacy_path=fixture_path.parent/'legacy-pending-inputs.json';browser_path=fixture_path.parent/'browser-polynomial-inputs.json'
assert hashlib.sha256(legacy_path.read_bytes()).hexdigest()==fixture['legacy_pending_sha256']
assert hashlib.sha256(browser_path.read_bytes()).hexdigest()==fixture['browser_inputs_sha256']
assert fixture['legacy_pending_sha256']=='c837695bd633477c4ce34695c5963c5f2e28ccbc8ed40c49d97240ec448ea95c'
assert fixture['browser_inputs_sha256']=='49b5167589f68ed275a9db55ba570d838c32fa2733b2097c30c2fa944d137577'
assert browser_path.read_bytes()==(ROOT/'tools/device_browser_support/polynomial_inputs.json').read_bytes()
old=json.loads(legacy_path.read_bytes())['rows'][0]
assert fixture['scenarios'][0]['legacy_variant']==old['variant']==0
assert fixture['scenarios'][0]['physical_tokens']==[k['token_label'] for k in old['keys']]
browser=json.loads(browser_path.read_bytes())
variant_zero=bytearray(65536);variant_zero[0xf040]=255
for v in fixture['scenarios']:
 if 'legacy_variant' in v:
  assert v['legacy_variant']==0 and zlib.decompress(base64.b64decode(v['initial_ram_zlib_base64']))==variant_zero
for original in browser['rows']:
 preserved=next(v for v in fixture['scenarios'] if v['label']=='browser-'+original['id']+'-coefficients')
 successor=next(v for v in fixture['scenarios'] if v['label']=='browser-'+original['id']+'-solve-replay')
 assert preserved['physical_tokens']==[k['token_label'] for k in original['keys']]
 assert successor['physical_tokens']==preserved['physical_tokens']+[240,240,240]
selected=[v for v in fixture['scenarios'] if args.corpus=='all' or v['corpus']==args.corpus]
run=(args.build_dir or ROOT/'analysis/build/runtime-polynomial-ownership').resolve()/uuid.uuid4().hex/args.optimization;run.mkdir(parents=True)
(run/'tmp').mkdir();os.environ['TMPDIR']=str(run/'tmp')
sources=['csrc/'+n for n in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',cmake_bytes.decode().split('target_include_directories')[0])]
implementation_closure=implementation_inputs(SOURCE,sources)
adapter=SCRIPT_ROOT/'tools/runtime_polynomial_support/adapter.c';observer=SCRIPT_ROOT/'tools/runtime_polynomial_support/native.c'
paths=[*[SOURCE/n for n in implementation_closure],SOURCE/'csrc/CMakeLists.txt',adapter,observer,fixture_path,legacy_path,browser_path,Path(__file__).resolve(),SCRIPT_ROOT/'tools/test_runtime_polynomial_c.py',ROOT/'tools/nxu8/harness.c',ROOT/'tools/nxu8/isa.txt',ROOT/'analysis/disassembly/complete.asm',ROOT/'tools/nxu8/vendor/SimU8/core.c',*sorted((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')),ROOT/'firmware/fx-991es-plus-c-ver4.bin',ROOT/'tools/device_browser_support/polynomial_inputs.json',ROOT/'csrc/app/fx_device_session.c']
paths += [Path(v.__file__).resolve() for v in sys.modules.values() if getattr(v,'__file__',None) and Path(v.__file__).resolve().is_relative_to(ROOT/'tools')]
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def raw_packed(data):return base64.b64encode(zlib.compress(data)).decode()
archive_seed=zlib.decompress(base64.b64decode(selected[0]['initial_ram_zlib_base64']))
archive_seed_int=int.from_bytes(archive_seed,'little')
def packed(data):
 assert len(data)==65536
 delta=(int.from_bytes(data,'little')^archive_seed_int).to_bytes(65536,'little')
 return raw_packed(delta)
pins={str(p):digest(p) for p in paths}
assert all(pins[p]==h for p,h in parsed_pins.items()),'parsed fixture/CMake changed before pin capture'
assert implementation_inputs(SOURCE,sources)==implementation_closure,'implementation closure changed before compile'
assert all(digest(p)==h for p,h in pins.items()),'input changed before compile'
libpath=run/'candidate.so';nativepath=run/'native'
commands=[['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined','-Wl,--wrap=fx_timer_start','-I',str(SOURCE/'csrc'),*[str(SOURCE/n) for n in sources],str(adapter),'-o',str(libpath)],['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(ROOT/'tools'),str(observer),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(nativepath/'nxu8-harness.so')]]
(run/'compiler-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
subprocess.run(commands[0],check=True);nativepath.mkdir();subprocess.run(commands[1],check=True)
dependency_inputs=set()
for command in commands:
 source_files=[x for x in command if x.endswith('.c')]
 includes=[x for i,x in enumerate(command) if i and command[i-1]=='-I']
 dep_command=['gcc','-std=c99','-MM',*[x for p in includes for x in ('-I',p)],*source_files]
 output=subprocess.run(dep_command,check=True,capture_output=True,text=True).stdout.replace('\\\n',' ')
 for line in output.splitlines():
  if ':' in line:dependency_inputs.update(str(Path(x).resolve()) for x in line.split(':',1)[1].split())
assert dependency_inputs<=set(pins),sorted(dependency_inputs-set(pins))
(run/'gcc-dependencies.json').write_text(json.dumps(sorted(dependency_inputs),indent=2)+'\n')
artifacts={str(p):digest(p) for p in [libpath,nativepath/'nxu8-harness.so']}
class Platform(C.Structure):_fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),('ram',C.POINTER(C.c_uint8)),('callback_pending',C.c_uint8),('status',C.c_int)]
class Pair(C.Structure):_fields_=[('columns',C.c_uint8),('rows',C.c_uint8)]
lib=C.CDLL(str(libpath));lib.runtime_size.restype=lib.runtime_equation_size.restype=C.c_size_t
lib.runtime_transport_abi.argtypes=[C.c_uint];lib.runtime_transport_abi.restype=C.c_size_t
abi=[C.sizeof(Platform),Platform.rom.offset,Platform.rom_size.offset,Platform.ram.offset,Platform.callback_pending.offset,Platform.status.offset,C.sizeof(Pair),Pair.columns.offset,Pair.rows.offset]
assert abi==[lib.runtime_transport_abi(i) for i in range(len(abi))]
pp=C.POINTER(Platform)
for name in ('fx_runtime_reset','fx_equation_controller_begin'):getattr(lib,name).argtypes=[pp,C.c_void_p,C.c_void_p]
lib.fx_runtime_step.argtypes=[pp,C.c_void_p,C.c_void_p,C.c_uint8];lib.fx_runtime_submit_pair.argtypes=[pp,Pair];lib.owned_runtime_reset.argtypes=[pp,C.c_void_p,C.c_uint]
lib.runtime_owned_constant.argtypes=[C.c_uint]
lib.runtime_polynomial_context_retained.argtypes=[C.c_void_p]
START_EQ,EQ,RETURN_EQ,START_TABLE,TABLE,RETURN_TABLE,BODY,EQ_GAP,TABLE_GAP,START_POLY,POLY,RETURN_POLY,POLY_GAP=[lib.runtime_owned_constant(i) for i in range(13)]
lib.equation_control_reset.argtypes=[C.c_uint]
lib.fx_runtime_accept_body.argtypes=[pp,C.c_void_p,C.c_uint8,C.c_uint8]
lib.fx_equation_controller_tick.argtypes=[pp,C.c_void_p];lib.fx_equation_controller_finish.argtypes=[C.c_void_p,C.POINTER(C.c_uint8)]
lib.runtime_field.argtypes=lib.runtime_equation_field.argtypes=[C.c_void_p,C.c_uint];lib.fx_take_callback.argtypes=[pp]
rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rd=(C.c_uint8*len(rom)).from_buffer_copy(rom);ram=(C.c_uint8*65536)();p=Platform(rd,len(rom),ram,0,0);state=C.create_string_buffer(lib.runtime_size())
n=Machine(rom,nativepath);nl=n.lib;nl.runtime_run_to.argtypes=[C.c_uint32,C.c_uint64];nl.runtime_run_to.restype=C.c_int
frames=(C.c_uint8*65536).in_dll(nl,'runtime_frame_writes');native_polls=C.c_uint.in_dll(nl,'equation_native_polls');c_polls=C.c_uint.in_dll(lib,'equation_c_polls');native_cancel=C.c_uint.in_dll(nl,'equation_native_cancel_at')
c_poll_ram=((C.c_uint8*65536)*256).in_dll(lib,'equation_c_poll_ram');n_poll_ram=((C.c_uint8*65536)*256).in_dll(nl,'equation_poll_ram')
pairs={rom[0x7fe+8*column+row]:(1<<column,1<<row) for column in range(8) for row in range(8)}
assert all(pairs[k['token_label']]==(k['columns'],k['rows']) for k in old['keys'])
assert all(pairs[k['token_label']]==(k['columns'],k['rows']) for original in browser['rows'] for k in original['keys'])
rows=[];failures=[];poll_rows=[];gap_controls=[];checks=len(abi);sequence=0;token_index=0

def field(index):return lib.runtime_field(state,index)
def compare(label,stop,status):
 global checks
 if nl.harness_get_pc()==stop:assert nl.harness_run(1,0x2fffe,False)==103
 result=nl.runtime_run_to(stop,fixture['instruction_budget']);actual,expected=bytes(ram),bytes(n.ram)
 residuals=[];unexpected=[]
 for i in range(65536):
  if actual[i]==expected[i]:continue
  v=[i,actual[i],expected[i]]
  if frames[i] or 0x8000<=i<0x80dc:residuals.append(v)
  else:unexpected.append(v)
 callback=lib.fx_take_callback(C.byref(p));native_callback=nl.harness_callback();semantic=[]
 if stop==0xd87e and field(12)!=n.reg(0):semantic.append(['context-return',field(12),n.reg(0)])
 if stop==0xd934 and field(36)!=n.reg(0):semantic.append(['polynomial-outer-return',field(36),n.reg(0)])
 if stop==0xd8fe and field(30)!=n.reg(0):semantic.append(['TABLE-admission-return',field(30),n.reg(0)])
 if stop==0xd98e and field(19)!=n.reg(0):semantic.append(['mode-return',field(19),n.reg(0)])
 if stop==0xd7b4 and field(3)!=n.reg(5):semantic.append(['main-wait',field(3),n.reg(5)])
 row=dict(sequence=sequence,label=label,status=status,event=field(1),phase=field(0),wait=field(3),pending=field(2),body_kind=field(9),body_operation=field(10),context_return=field(12),handler_action=field(13),native_status=result,native_pc=nl.harness_get_pc(),native_return=n.reg(0),native_polls=native_polls.value,callback=callback,native_callback=native_callback,unexpected=unexpected,residuals=residuals,semantic=semantic,c_ram_sha256=hashlib.sha256(actual).hexdigest(),native_ram_sha256=hashlib.sha256(expected).hexdigest())
 row['residual_count']=len(residuals);row['residual_sha256']=hashlib.sha256(json.dumps(residuals,separators=(',',':')).encode()).hexdigest();row.pop('residuals')
 rows.append(row);checks+=3;archive.write(json.dumps(dict(**row,c_ram=packed(actual),native_ram=packed(expected),frame_writes=raw_packed(bytes(frames))))+'\n')
 if args.verbose:print(sequence,label,status,field(0),field(1),field(3),hex(stop),len(unexpected),flush=True)
 if result!=100 or unexpected or semantic or callback!=native_callback:
  failures.append(row);raise AssertionError(row)

def step(label):
 global checks
 before=field(0);status=lib.fx_runtime_step(C.byref(p),state,None,0);event=field(1);stop=None
 assert lib.runtime_polynomial_context_retained(state)==1;checks+=1
 if event==2:stop={1:0xd9ee,2:0xc978,3:0xca7c,9:0xe862,10:0xe1be,5:0xf02c,6:0xe22a}[field(2)]
 elif event==3 and before in (3,START_POLY):stop=0xda58
 elif event==4:
  stop={4:0xd87e,7:0xd98e if field(2)==2 else 0xd99e,10:0xc9e8 if field(16)==1 else 0xc9f4}.get(before)
  if before==11:stop=0xd98e
  if before in (START_EQ,EQ,START_POLY,POLY):stop=0xd934
  if before in (START_TABLE,TABLE):stop={5:0xd8fe,6:0xd90a,10:0xd942}[field(28)]
 elif event==5:stop=0xd7b4
 elif event in (6,7):stop=0x1d8a4
 elif event==10:
  if before==POLY and field(34)==4:stop=0x1db86 if field(7)==7 else 0x1db9c
  else:stop=0x1d8a4
 elif event==8:stop=0xd0cc
 elif event==9:stop=0x53ce
 elif event==12:stop=0xd7ae
 elif event==11:
  if field(9)==POLY_GAP:raise AssertionError(('unexpected-owned-POLYNOMIAL-gap',label,field(10),field(11),field(34),field(35)))
  if field(9)==EQ_GAP:raise AssertionError(("unexpected-owned-EQN-gap",label,field(10),field(11)))
  elif field(9)==TABLE_GAP:raise AssertionError(('explicit-TABLE-gap',label,field(10),field(11)))
  elif field(9)==2:stop=0xda58
 if stop is not None:compare(label,stop,status)
 return status

def release():
 lib.fx_runtime_submit_pair(C.byref(p),Pair(0,0));n.ram[0x8e01]=n.ram[0x8e02]=0

def press(token,label):
 global token_index,checks
 assert token==scenario['physical_tokens'][token_index];token_index+=1
 pair=scenario["host_pairs"][str(token)] if token>255 else pairs[token];lib.fx_runtime_submit_pair(C.byref(p),Pair(*pair));n.ram[0x8e01],n.ram[0x8e02]=pair
 for index in range(50):
  status=step(label+':'+str(index))
  if status==4:raise AssertionError(('unexpected-owned-body-gap',label,field(9),field(10)))
  if status==2:
   assert field(0)==POLY and field(34)==4
   columns=pair[0];expected_mask=7 if columns in (128,64) else 1
   assert columns in (128,64,32) and pair[1]==128 and field(7)==expected_mask
   release();status=step(label+':actual-export-wait-restart');assert status==0
  if status==0 and field(0)==POLY and field(34)==4:
   snapshot=bytes(ram);before_state=bytes(state)
   assert lib.fx_runtime_accept_body(C.byref(p),state,0,0)==-1
   assert bytes(ram)==snapshot and bytes(state)==before_state
   checks+=3
   gap_controls.append(dict(sequence=sequence,label=label,type='owned-error-forged-reply-rejected',ram_sha256=hashlib.sha256(snapshot).hexdigest()))
  if status==5:
   release()
   for restart in range(20):
    if step(label+':actual-reset-restart-'+str(restart))==0:return
   raise AssertionError(('reset-restart-unbounded',label))
  if status==0:release();return
  if field(1)==5 and field(3):release()
  if status in (2,3,5) or status<0:raise AssertionError(('retained-nonterminal',label,status,field(1),field(0)))
 raise AssertionError(('unbounded-press',label,field(0),field(1)))

with gzip.open(run/'observations.jsonl.gz','wt') as archive:
 archive.write(json.dumps(dict(type='archive-encoding',ram_encoding='zlib-base64-xor-initial-seed',ram_size=65536,initial_ram=raw_packed(archive_seed),initial_ram_sha256=hashlib.sha256(archive_seed).hexdigest(),frame_encoding='zlib-base64'))+'\n')
 for scenario in selected:
  sequence+=1;token_index=0
  seed=zlib.decompress(base64.b64decode(scenario['initial_ram_zlib_base64']));assert len(seed)==65536 and hashlib.sha256(seed).hexdigest()==scenario['initial_ram_sha256']
  n.reset();nl.runtime_observer_reset();C.memmove(n.ram,seed,65536);C.memmove(ram,seed,65536);p.callback_pending=p.status=0
  status=lib.owned_runtime_reset(C.byref(p),state,scenario.get('cancel_at',0));assert status==1;native_cancel.value=scenario.get('cancel_at',0);nl.harness_set_pc(0x6f82);compare('original-reset-to-ready',0xd7ae,status)
  for index in range(10):
   if step('boot-input:'+str(index))==0:break
  release()
  for index,token in enumerate(scenario['physical_tokens']):press(token,scenario['label']+':physical-'+str(index)+'-'+hex(token))
  assert token_index==len(scenario['physical_tokens'])
  assert ram[0x80f9]==0x45 and ram[0x80fa]==scenario['selector'] and ram[0x80fc] in (1,21)
  actual_count=c_polls.value;assert actual_count==native_polls.value and actual_count<=256,(scenario['label'],actual_count,native_polls.value)
  for index in range(actual_count):
   a,b=bytes(c_poll_ram[index]),bytes(n_poll_ram[index]);differences=[[i,a[i],b[i]] for i in range(65536) if a[i]!=b[i] and not frames[i]]
   row=dict(sequence=sequence,label=scenario['label'],index=index,persistent_differences=[v for v in differences if not(0x8000<=v[0]<0x80dc)])
   poll_rows.append(row);archive.write(json.dumps(dict(**row,type='actual5550-poll-comparison',c_ram=packed(a),native_ram=packed(b)))+'\n')
  checks+=1
  if args.verbose:print('SEQUENCE-END',scenario['label'],hex(ram[0x80f9]),ram[0x80fc],flush=True)
assert implementation_inputs(SOURCE,sources)==implementation_closure,'implementation closure changed during proof'
changes=[q for q,h in pins.items() if digest(q)!=h];assert not changes,changes
assert all(digest(q)==h for q,h in artifacts.items())
gap_count=sum(bool(r['persistent_differences']) for r in poll_rows);assert gap_count==0,poll_rows
report=dict(schema=1,status='pass-with-numeric-residuals',corpus=args.corpus,gap_controls=gap_controls,successful_external_body_completion_calls=0,full_firmware_complete=False,poll_publication_complete=True,optimization=args.optimization,sequences=sequence,observations=len(rows),checks=checks,failures=failures,rows=rows,poll_rows=poll_rows,poll_count=len(poll_rows),poll_snapshot_persistent_gap_count=gap_count,source_pins=pins,source_changes=changes,artifacts=artifacts,compiled_sources=[str(SOURCE/n) for n in sources],compiler_commands=commands,gcc_dependencies=sorted(dependency_inputs),initial_native_pc=0x6f82,native_pc_sets_per_session=1,numeric_residual_range=[0x8000,0x80dc],completed_main_cycles=sum(r['native_pc']==0xd7b4 for r in rows),outer_returns=sum(r['native_pc']==0xd934 for r in rows),exports=sum(r['event']==10 for r in rows),resets=sum(r['event']==12 for r in rows),nonzero_callbacks=sum(bool(r['callback'] or r['native_callback']) for r in rows),scope=__doc__)
(run/'proof.json').write_text(json.dumps(report,separators=(',',':'))+'\n');print('REPORT',run/'proof.json','polls',len(poll_rows),'snapshot-gaps',gap_count)
