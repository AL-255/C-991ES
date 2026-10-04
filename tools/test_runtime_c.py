#!/usr/bin/env python3
"""Portable named runtime vs uninterrupted original boot/main/UI sequences.

Only the independent test oracle executes original instructions. All production
controller state remains named C objects; numerical scratch residuals and body
requests are retained as explicit incomplete scope. GPL-3.0-only.
"""
import argparse,base64,ctypes as C,gzip,hashlib,json,random,re,subprocess,sys,zlib,uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
# Candidate runs resolve this verifier's tooling against the real repository.
if not (ROOT / 'tools/nxu8/machine.py').exists():
    ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT / 'tools'))
from c_build_inputs import implementation_inputs
from c_verification import write_report
from nxu8.machine import Machine

FIXTURE = 'analysis/native-fixtures/runtime/inputs.json'
FIXTURE_SHA256 = 'bdb912ff45f75c00e582fabc95b038c30c3841fd9ee26caff3282e6e2427f432'
SUPPORT = ['tools/runtime_support/adapter.c', 'tools/runtime_support/native.c']
TEST = 'tools/test_runtime_c.py'
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--optimization', choices=['O2', 'O3'])
ap.add_argument('--fixture', type=Path)
ap.add_argument('--candidate-root', type=Path)
ap.add_argument('--private-report', type=Path)
ap.add_argument('--no-report', action='store_true')
a = ap.parse_args()
if a.candidate_root and not a.private_report:
    ap.error('--candidate-root requires --private-report')
if a.fixture and not (a.no_report or a.private_report):
    ap.error('Custom fixtures require --no-report or --private-report')
if a.optimization and not (a.no_report or a.private_report):
    ap.error('Single-optimization runs require --no-report or --private-report')
if a.private_report and a.private_report.resolve().is_relative_to((ROOT / 'analysis/c-verification').resolve()):
    ap.error('Private reports cannot replace canonical verification reports')
CANDIDATE = a.candidate_root.resolve() if a.candidate_root else ROOT
fixture_path = a.fixture.resolve() if a.fixture else CANDIDATE / FIXTURE

def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def digest_bytes(b):
    return hashlib.sha256(b).hexdigest()

fixture = json.loads(fixture_path.read_text())
if set(fixture) != {'basis', 'instruction_budget', 'rows'} or fixture['instruction_budget'] != 50000000:
    ap.error('Malformed fixture metadata')
expected_groups = ['arithmetic'] * 9 + ['matrix', 'vector', 'matrix-back-cancel',
    'setup-timer-export', 'setup-precision', 'TABLE-wholeINPUT-request', 'STAT-typed-admission-chain']
if len(fixture['rows']) != 16:
    ap.error('The complete 16-sequence fixture is required')
for i, row in enumerate(fixture['rows']):
    required = {'id', 'group', 'initial_ram_zlib_base64', 'initial_ram_sha256', 'physical_tokens'}
    allowed = required | ({'port', 'mode'} if i < 9 else {'export_pair'} if i == 12 else set())
    if not required <= set(row) <= allowed or row['id'] != i + 1 or row['group'] != expected_groups[i]:
        ap.error('Malformed or reordered input row')
    raw_seed = zlib.decompress(base64.b64decode(row['initial_ram_zlib_base64'], validate=True))
    if len(raw_seed) != 65536 or digest_bytes(raw_seed) != row['initial_ram_sha256']:
        ap.error('Invalid initial RAM input')
    if i < 9:
        if row.get('port') != (0, 3, 7)[i // 3] or row.get('mode') != (None, 0xc1, 0xc4)[i % 3]:
            ap.error('Invalid arithmetic recipe')
    elif set(row) != allowed:

        ap.error('Unexpected menu input fields')
    if not row['physical_tokens'] or any(type(token) is not int or not 0 <= token <= 255 for token in row['physical_tokens']):
        ap.error('Invalid raw physical token recipe')
    if i == 12 and row['export_pair'] != [0x20, 0x80]:
        ap.error('Invalid raw export packet')
if not a.fixture and digest(fixture_path) != FIXTURE_SHA256:
    ap.error('Canonical input-only fixture changed')

sources = ['csrc/' + n for n in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',
    (CANDIDATE / 'csrc/CMakeLists.txt').read_text().split('target_include_directories')[0])]
# The runtime is a separate proposed source until its one-line CMake integration.
sources = [p for p in sources if p != 'csrc/platform/fx_runtime.c']
source_paths = [CANDIDATE / n for n in implementation_inputs(CANDIDATE, sources + ['csrc/platform/fx_runtime.c'])]
source_paths += [CANDIDATE / 'csrc/CMakeLists.txt', ROOT / 'tools/c_build_inputs.py',
    ROOT / 'tools/c_verification.py', ROOT / 'tools/nxu8/machine.py',
    ROOT / 'tools/nxu8/harness.c', ROOT / 'tools/nxu8/vendor/SimU8/core.c',
    ROOT / 'firmware/fx-991es-plus-c-ver4.bin',
    *sorted((ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h')),
    CANDIDATE / 'csrc/platform/fx_runtime.c', CANDIDATE / 'csrc/platform/fx_runtime.h',
    *[CANDIDATE / p for p in SUPPORT], Path(__file__).resolve(), fixture_path]
pins = {str(p): digest(p) for p in source_paths}

def assert_stable():
    changed = [q for q, h in pins.items() if digest(q) != h]
    if changed:
        raise RuntimeError('Test inputs changed during execution: ' + ', '.join(changed))

if a.optimization is None:
    reports = []
    report_dir = CANDIDATE / 'analysis/build/runtime' / uuid.uuid4().hex
    report_dir.mkdir(parents=True, exist_ok=True)
    for optimization in ('O2', 'O3'):
        child_report = report_dir / ('proof-' + optimization + '.json')
        command = [sys.executable, str(Path(__file__).resolve()), '--optimization', optimization,
            '--private-report', str(child_report)]
        if a.candidate_root:
            command += ['--candidate-root', str(CANDIDATE)]
        if a.fixture:
            command += ['--fixture', str(fixture_path)]
        subprocess.run(command, check=True, cwd=ROOT)
        reports.append(json.loads(child_report.read_text()))
    assert_stable()
    if any(reports[0][key]!=reports[1][key] for key in ('rows','pending_bodies','completed_former_body_controls')):
        raise AssertionError('Native/runtime observations differ between O2 and O3')
    report = dict(status='pass', full_firmware_complete=False,
        cases=16, observations_per_optimization=reports[0]['observations'], checks_per_optimization=reports[0]['checks'],
        original_body_controls=6,
        pending_body_controls_per_optimization=len(reports[0]['pending_bodies']),
        native_completed_former_body_controls_per_optimization=len(reports[0]['completed_former_body_controls']),
        optimization_reports=reports,
        numerical_residual_observations_per_optimization=len(reports[0]['numeric_scratch_residuals']),
        limits=reports[0]['limits'])
    if a.private_report:
        a.private_report.parent.mkdir(parents=True, exist_ok=True)
        a.private_report.write_text(json.dumps(report, indent=2) + '\n')
    elif not a.no_report:
        report_sources = sources + ['csrc/platform/fx_runtime.c', 'csrc/platform/fx_runtime.h',
            *SUPPORT, 'csrc/CMakeLists.txt', FIXTURE]
        write_report('analysis/c-verification/runtime.json', report, report_sources, TEST)
    print(json.dumps(dict(status='pass', sequences=16, observations_per_optimization=reports[0]['observations'],
        checks_per_optimization=reports[0]['checks'], numerical_residual_observations_per_optimization=len(reports[0]['numeric_scratch_residuals']))))
    sys.exit(0)

BUILD = (a.private_report.parent if a.private_report else CANDIDATE / 'analysis/build/runtime' / uuid.uuid4().hex) / a.optimization
BUILD.mkdir(parents=True, exist_ok=True)
subprocess.run(['gcc', '-std=c99', '-' + a.optimization, '-Wall', '-Wextra', '-Werror',
    '-shared', '-fPIC', '-Wl,--no-undefined', '-I', str(CANDIDATE / 'csrc'),
    *[str(CANDIDATE / p) for p in sources], str(CANDIDATE / 'csrc/platform/fx_runtime.c'),
    str(CANDIDATE / SUPPORT[0]), '-o', str(BUILD / 'runtime.so')], check=True)
nd = BUILD / 'native'
nd.mkdir(exist_ok=True)
subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
    '-I', str(ROOT / 'tools'), str(CANDIDATE / SUPPORT[1]),
    str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'), '-o', str(nd / 'nxu8-harness.so')], check=True)
compiled_artifacts = {str(p): digest(p) for p in [BUILD / 'runtime.so', nd / 'nxu8-harness.so']}
class Platform(C.Structure):_fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),('ram',C.POINTER(C.c_uint8)),('callback_pending',C.c_uint8),('status',C.c_int)]
class Pair(C.Structure):_fields_=[('columns',C.c_uint8),('rows',C.c_uint8)]
lib=C.CDLL(str(BUILD/'runtime.so'));lib.runtime_size.restype=C.c_size_t
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
rows=[];failures=[];residuals=[];pending_bodies=[];completed_bodies=[];checks=0;sequence_id=0; token_index=0
def compare(label,stop,status,numeric=False):
 global checks
 if nl.harness_get_pc()==stop:assert nl.harness_run(1,0x2fffe,False)==103
 result=nl.runtime_run_to(stop,fixture['instruction_budget'])
 after=bytes(n.ram);actual=bytes(ram)
 diffs=[(i,after[i],actual[i]) for i in range(65536) if after[i]!=actual[i] and not frames[i]]
 allowed=[v for v in diffs if numeric and (sequence_id,label) in NUMERIC_RESIDUAL_CHECKPOINTS and 0x8000<=v[0]<0x80dc]
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
  if field(9)==1:stop={7:0xecaa,8:0xeca6,4:0xcd66,5:0xf02c,10:0xe1be}.get(field(10))
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
  if status==4:return status
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
with gzip.open(BUILD/'observations.jsonl.gz','wt') as archive:
 sequences=[]
 for port in (0,3,7):
  for mode in (None,0xc1,0xc4):
   seed=boot(port,mode);sequences.append(dict(id=sequence_id,group='arithmetic',port=port,mode=mode,initial_ram_zlib_base64=packed(seed),initial_ram_sha256=digest_bytes(seed)))
   for token in (0x31,0x2b,0x32,0xf0):
    assert action(token,'arithmetic:'+hex(token),token==0xf0)==1
    assert step('next-key-wait',token==0xf0)==0
   assert bytes(ram[0x8140:0x814a])==bytes.fromhex('03000000000000000001');checks+=1
 # MODE/SETUP nested menus use raw physical packets only. No prepared token,
 # selection, controller state, nativePC/register/frame replacement.
 for family,key,shape in [('matrix',0x36,0x35),('vector',0x38,0x32)]:
  seed=boot(0);sequences.append(dict(id=sequence_id,group=family,initial_ram_zlib_base64=packed(seed),initial_ram_sha256=digest_bytes(seed)))
  raw(0xe4);assert step(family+':MODE-entry')==1;assert step(family+':MODE-wait')==0;release()
  raw(key);assert step(family+':nested-bank-entry')==1;assert field(1)==8;assert step(family+':bank-wait')==0;release()
  raw(0x31);assert step(family+':slot-A')==0;release()
  raw(shape)
  assert step(family+':dimensions')==1;release()
  assert step(family+':bank-return')==1
  assert step(family+':mode-return')==1
  assert step(family+':screen-body-request')==4
  retain_body(family+':retain-screen-body')
 # MATRIX dimension submenu back-navigation, invalid key blink and actualAC
 # cancellation all retain the real MODE parent continuation.
 seed=boot(0);sequences.append(dict(id=sequence_id,group='matrix-back-cancel',initial_ram_zlib_base64=packed(seed),initial_ram_sha256=digest_bytes(seed)))
 raw(0xe4);assert step('back:MODE-entry')==1;assert step('back:MODE-wait')==0;release()
 raw(0x36);assert step('back:bank-entry')==1;assert step('back:bank-wait')==0;release()
 raw(0x31);assert step('back:slot-A')==0;release()
 raw(0xe3);assert step('back:dimension-to-family')==0;release()
 raw(0x30);assert step('back:invalid-key-timer')==3;release()
 before=bytes(ram);assert lib.fx_runtime_step(C.byref(p),s,None,0)==3 and bytes(ram)==before;checks+=1
 status=lib.fx_runtime_step(C.byref(p),s,None,1);assert status==0;compare('back:invalid-key-ack',0x1d8a4,status)
 raw(0xe6);assert step('back:AC-timer')==3;release()
 before=bytes(ram);assert lib.fx_runtime_step(C.byref(p),s,None,0)==3 and bytes(ram)==before;checks+=1
 status=lib.fx_runtime_step(C.byref(p),s,None,1);assert status==1;compare('back:AC-ack',0xc9e8,status)
 assert step('back:bank-return',True)==1;assert step('back:MODE-return',True)==1
 # The same original rich AC control is now admitted by the whole UI.
 # Retain its original native preparation, completion and main continuation.
 # No typed body reply substitutes for the original D9EE body.
 assert step('back:wholeINPUT-entry',True)==1;assert step('back:wholeINPUT-preparation',True)==1
 status=step('back:wholeINPUT-completed',True);assert status==1 and field(1)==4
 completed=dict(sequence=sequence_id,label='back:completed-wholeINPUT-body',former_kind=2,former_operation=1,context_return=field(12),handler_action=field(13),native_completion_pc=nl.harness_get_pc(),ram_sha256=digest_bytes(bytes(ram)))
 completed_bodies.append(completed);checks+=1
 archive.write(json.dumps(dict(**completed,type='native-completed-former-body-control'))+'\n')
 assert step('back:wholeINPUT-cycle-return',True)==1
 release();assert step('back:next-real-key-wait',True)==0
 # SETUP is reached by the real SHIFT+MODE physical pair sequence.
 seed=boot(0);sequences.append(dict(id=sequence_id,group='setup-timer-export',initial_ram_zlib_base64=packed(seed),initial_ram_sha256=digest_bytes(seed)))
 raw(0xe9);assert step('SHIFT')==0;release()
 raw(0xe4);assert step('SETUP-entry')==1;assert step('SETUP-wait')==0;release()
 raw(0x30);assert step('invalid-setup-key-timer')==3;release()
 before=bytes(ram);assert lib.fx_runtime_step(C.byref(p),s,None,0)==3 and bytes(ram)==before;checks+=1
 status=lib.fx_runtime_step(C.byref(p),s,None,1);assert status==0;compare('timer-ack',0x1d8a4,status)
 raw(0x35);assert step('SETUP-Gra')==1;release();assert step('SETUP-return')==1
 assert step('SETUP-followup-input-entry')==1
 for k in range(8):
  step('SETUP-followup-input:'+str(k))
  if field(1)==5:break
 release();assert step('SETUP-next-key-wait')==0
 export_pair=fixture['rows'][sequence_id-1]['export_pair']
 lib.fx_runtime_submit_pair(C.byref(p),Pair(*export_pair));n.ram[0x8e01],n.ram[0x8e02]=export_pair
 assert step('host-status-export')==2;assert field(7)==1;release()
 assert step('export-next-idle')==0
 # SETUPFIX precision owns a separate key controller from genericDFDE.
 seed=boot(0);sequences.append(dict(id=sequence_id,group='setup-precision',initial_ram_zlib_base64=packed(seed),initial_ram_sha256=digest_bytes(seed)))
 raw(0xe9);assert step('FIX:SHIFT')==0;release()
 raw(0xe4);assert step('FIX:SETUP-entry')==1;assert step('FIX:SETUP-wait')==0;release()
 raw(0x36);assert step('FIX:precision-wait')==0;release()
 raw(0x34);assert step('FIX:four-digits')==1;release();assert step('FIX:SETUP-return')==1
 assert ram[0x8102]==8 and ram[0x8103]==4;checks+=1
 # Preserve the original TABLE empty-function readiness sequence. Actual
 # wholeD9EE now completes; compare its caller return and main continuation.
 seed=boot(0);sequences.append(dict(id=sequence_id,group='TABLE-wholeINPUT-request',initial_ram_zlib_base64=packed(seed),initial_ram_sha256=digest_bytes(seed)))
 raw(0xe4);assert step('TABLE:MODE-entry')==1;assert step('TABLE:MODE-wait')==0;release()
 raw(0x37);assert step('TABLE:MODE-choice',True)==1;release();assert step('TABLE:MODE-return',True)==1
 assert step('TABLE:wholeINPUT-entry',True)==1;assert step('TABLE:wholeINPUT-preparation',True)==1
 status=step('TABLE:wholeINPUT-completed',True);assert status==1 and field(1)==4
 completed=dict(sequence=sequence_id,label='TABLE:completed-wholeINPUT-body',former_kind=2,former_operation=1,context_return=field(12),handler_action=field(13),native_completion_pc=nl.harness_get_pc(),ram_sha256=digest_bytes(bytes(ram)))
 completed_bodies.append(completed);checks+=1
 archive.write(json.dumps(dict(**completed,type='native-completed-former-body-control'))+'\n')
 assert step('TABLE:wholeINPUT-cycle-return',True)==1
 release();assert step('TABLE:next-real-key-wait',True)==0
 # STAT admission remains delegated. The explicit host reply0 must expose
 # its secondSCREEN18 request, rather than reporting INVALID after the real
 # main controller has already advanced that state. This reply control is
 # host-only; nativeF02C body execution is not represented as implemented.
 seed=boot(0);sequences.append(dict(id=sequence_id,group='STAT-typed-admission-chain',initial_ram_zlib_base64=packed(seed),initial_ram_sha256=digest_bytes(seed)))
 raw(0xe4);assert step('STAT:MODE-entry')==1;assert step('STAT:MODE-wait')==0;release()
 raw(0x33);assert step('STAT:submode-wait')==0;release()
 raw(0x31);assert step('STAT:submode-one')==1;release();assert step('STAT:MODE-return')==1
 assert step('STAT:admission-request')==4;assert field(9)==1 and field(10)==5
 retain_body('STAT:retain-admission')
 assert lib.fx_runtime_accept_body(C.byref(p),s,0,0)==4 and field(9)==1 and field(10)==6
 retain_body('STAT:retain-second-request-after-host-reply')
 # Dedicated MATRIX/VECTOR screen bodies and the four remaining typed body controls
 # remain explicit runtime requests in this fixture. The completed rich AC
 # control above uses its actual whole UI; it never substitutes direct F12A.
 # No success is synthesized for the four remaining typed body controls.
assert token_index == len(fixture['rows'][sequence_id-1]['physical_tokens'])
assert len(rows) == 346 and sequence_id == 16 and checks == 1057
assert len(pending_bodies)==4 and len(completed_bodies)==2
assert len(pending_bodies)+len(completed_bodies)==6
assert_stable()
changed=[]
if any(digest(q) != h for q, h in compiled_artifacts.items()):
 raise RuntimeError('Compiled artifact changed during execution')
report=dict(optimization=a.optimization,sequences=sequences,observations=len(rows),checks=checks,failures=failures,transport_abi=actual_abi,numeric_scratch_residuals=residuals,pending_bodies=pending_bodies,completed_former_body_controls=completed_bodies,input_pins=pins,end_pins={str(q):digest(q) for q in source_paths},source_changes=changed,rows=rows,limits=['Ordinary COMP/CMPLX and the original rich back/AC wholeD9EE control are composed. The same six original body-control recipes remain: four typed requests are retained; the former rich readiness and TABLE empty-function readiness controls now complete through actual wholeD9EE and main return. Full TABLE key/range/grid interaction is proved separately; retained/STAT-host-reply controls claim no native completion.','Parameter-menu wrapper remains a typed MAIN request; MODE nested MATRIX/VECTOR menus are actually composed.','Physical timer acknowledgment is a named host event, not elapsed wall time or simulated interrupt.','Only witnessed original CPU-frame writes are excluded; arithmetic and MATRIX-cancel default-title/TABLE-mode numeric8000..80DB differences are retained as explicit residuals.','Native machine PC is set only once at reset6F82 for each sequence; every later checkpoint retains actual stack/register continuations.','The scheduler does not model CPU architecture self-test; boot event lifecycle uses the frozen verified-success policy. Welcome/diagnostic and raw reset routes are composed but have not been proved through new uninterrupted6F82 sequences.'])
report['artifacts']={str(q):digest(q) for q in [BUILD/'runtime.so',nd/'nxu8-harness.so',BUILD/'observations.jsonl.gz']}
assert a.private_report is not None or a.no_report
if a.private_report:
 a.private_report.parent.mkdir(parents=True, exist_ok=True)
 a.private_report.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(optimization=a.optimization,sequences=len(sequences),observations=len(rows),checks=checks,failures=len(failures),source_changes=changed)))
if failures or changed:sys.exit(1)
