#!/usr/bin/env python3
"""Opaque persistent device session vs fresh uninterrupted original boot/key sequences.

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

FIXTURE = 'analysis/native-fixtures/device-session/inputs.json'
FIXTURE_SHA256 = '88054339be481ae4aefe7b41974e78e8b028448cf0bdd4dee430d6625943b180'
SUPPORT = ['tools/device_session_support/adapter.c', 'tools/device_session_support/native.c']
TEST = 'tools/test_device_session_c.py'
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--optimization', choices=['O2', 'O3'])
ap.add_argument('--fixture', type=Path)
ap.add_argument('--candidate-root', type=Path)
ap.add_argument('--private-report', type=Path)
ap.add_argument('--no-report', action='store_true')
a = ap.parse_args()
if sys.flags.optimize:
    ap.error('Optimized Python would disable differential assertions')
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

authored = json.loads(fixture_path.read_text())
if set(authored) != {'basis','instruction_budget','legacy_fixture','legacy_fixture_sha256','extensions'} or authored['instruction_budget'] != 50000000:
    ap.error('Malformed input-only device fixture')
legacy_path = ROOT / authored['legacy_fixture']
if authored['legacy_fixture'] != 'analysis/native-fixtures/runtime/inputs.json' or authored['legacy_fixture_sha256'] != 'bdb912ff45f75c00e582fabc95b038c30c3841fd9ee26caff3282e6e2427f432' or digest(legacy_path) != authored['legacy_fixture_sha256']:
    ap.error('The exact original16 raw-input fixture is required')
fixture = json.loads(legacy_path.read_text())
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

for i,row in enumerate(authored['extensions'],17):
    if set(row) != {'id','group','initial_image','operations'} or row['id'] != i or row['initial_image'] not in ('cold','legacy:1') or not isinstance(row['group'],str) or not row['operations']:
        ap.error('Malformed extension input recipe')
    for op in row['operations']:
        if op.get('kind') == 'key':
            if set(op) != {'kind','token'} or type(op['token']) is not int or not 1 <= op['token'] <= 255:
                ap.error('Invalid physical key input')
        elif op.get('kind') == 'host-pair':
            if set(op) != {'kind','columns','rows'} or op['rows'] != 0x80 or op['columns'] not in (0x80,0x40,0x20,0x10):
                ap.error('Invalid authored host packet')
        else:ap.error('Expected only raw key or host-pair operations')
    if row['initial_image']=='cold':
        seed=bytearray(65536);seed[0xf040]=255
        image=base64.b64encode(zlib.compress(seed)).decode();image_sha=digest_bytes(seed)
    else:
        image=fixture['rows'][0]['initial_ram_zlib_base64'];image_sha=fixture['rows'][0]['initial_ram_sha256']
    fixture['rows'].append(dict(row,initial_ram_zlib_base64=image,initial_ram_sha256=image_sha,physical_tokens=[op['token'] for op in row['operations'] if op['kind']=='key']))

sources = ['csrc/' + n for n in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',
    (CANDIDATE / 'csrc/CMakeLists.txt').read_text().split('target_include_directories')[0])]
# The runtime is a separate proposed source until its one-line CMake integration.
sources = list(dict.fromkeys(p for p in sources if p != 'csrc/platform/fx_runtime.c'))
if 'csrc/app/fx_device_session.c' not in sources:sources.append('csrc/app/fx_device_session.c')
source_paths = [CANDIDATE / n for n in implementation_inputs(CANDIDATE, sources + ['csrc/platform/fx_runtime.c'])]
source_paths += [CANDIDATE / 'csrc/CMakeLists.txt', ROOT / 'tools/c_build_inputs.py',
    ROOT / 'tools/c_verification.py', ROOT / 'tools/nxu8/machine.py',
    ROOT / 'tools/nxu8/harness.c', ROOT / 'tools/nxu8/vendor/SimU8/core.c',
    ROOT / 'firmware/fx-991es-plus-c-ver4.bin',
    *sorted((ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h')),
    CANDIDATE / 'csrc/platform/fx_runtime.c', CANDIDATE / 'csrc/platform/fx_runtime.h',
    *[CANDIDATE / p for p in SUPPORT], Path(__file__).resolve(), fixture_path, legacy_path, ROOT / 'analysis/disassembly/complete.asm']
pins = {str(p): digest(p) for p in source_paths}

def assert_stable():
    changed = [q for q, h in pins.items() if digest(q) != h]
    if changed:
        raise RuntimeError('Test inputs changed during execution: ' + ', '.join(changed))

if a.optimization is None:
    reports = []
    report_dir = CANDIDATE / 'analysis/build/device-session' / uuid.uuid4().hex
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
    if any(reports[0][key]!=reports[1][key] for key in ('rows','pending_bodies','completed_former_body_controls','api_guards','legacy_counts')):
        raise AssertionError('Native/runtime observations differ between O2 and O3')
    report = dict(status='pass', full_firmware_complete=False,
        cases=len(fixture['rows']), legacy_cases=16, observations_per_optimization=reports[0]['observations'], checks_per_optimization=reports[0]['checks'],
        original_body_controls=5,
        pending_body_controls_per_optimization=len(reports[0]['pending_bodies']),
        native_completed_former_body_controls_per_optimization=len(reports[0]['completed_former_body_controls']),
        optimization_reports=reports,api_guards_per_optimization=len(reports[0]['api_guards']),legacy_counts=reports[0]['legacy_counts'],
        numerical_residual_observations_per_optimization=len(reports[0]['numeric_scratch_residuals']),
        limits=reports[0]['limits'])
    if a.private_report:
        a.private_report.parent.mkdir(parents=True, exist_ok=True)
        a.private_report.write_text(json.dumps(report, indent=2) + '\n')
    elif not a.no_report:
        report_sources = sources + ['csrc/platform/fx_runtime.c', 'csrc/platform/fx_runtime.h',
            *SUPPORT, 'csrc/CMakeLists.txt', FIXTURE, authored['legacy_fixture'], 'analysis/disassembly/complete.asm']
        write_report('analysis/c-verification/device_session.json', report, report_sources, TEST)
    print(json.dumps(dict(status='pass', sequences=len(fixture['rows']), observations_per_optimization=reports[0]['observations'],
        checks_per_optimization=reports[0]['checks'], numerical_residual_observations_per_optimization=len(reports[0]['numeric_scratch_residuals']))))
    sys.exit(0)

BUILD = (a.private_report.parent if a.private_report else CANDIDATE / 'analysis/build/device-session' / uuid.uuid4().hex) / a.optimization
BUILD.mkdir(parents=True, exist_ok=True)
subprocess.run(['gcc', '-std=c99', '-' + a.optimization, '-Wall', '-Wextra', '-Werror',
    '-shared', '-fPIC', '-Wl,--no-undefined', '-I', str(CANDIDATE / 'csrc'),
    *[str(CANDIDATE / p) for p in sources], str(CANDIDATE / 'csrc/platform/fx_runtime.c'),
    str(CANDIDATE / SUPPORT[0]), '-o', str(BUILD / 'device-session.so')], check=True)
nd = BUILD / 'native'
nd.mkdir(exist_ok=True)
subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
    '-I', str(ROOT / 'tools'), str(CANDIDATE / SUPPORT[1]),
    str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'), '-o', str(nd / 'nxu8-harness.so')], check=True)
compiled_artifacts = {str(p): digest(p) for p in [BUILD / 'device-session.so', nd / 'nxu8-harness.so']}
lib=C.CDLL(str(BUILD/'device-session.so'))
lib.device_create_seed.argtypes=[C.POINTER(C.c_uint8)];lib.device_create_seed.restype=C.c_void_p
lib.device_create_config.argtypes=[C.POINTER(C.c_uint8),C.c_size_t,C.c_uint8];lib.device_create_config.restype=C.c_void_p
lib.device_field.argtypes=[C.c_void_p,C.c_uint];lib.device_field.restype=C.c_uint
for name in ('fx_device_session_destroy','fx_device_session_reset','fx_device_session_release','fx_device_session_take_callback'):
    getattr(lib,name).argtypes=[C.c_void_p]
lib.fx_device_session_destroy.restype=None
lib.fx_device_session_step.argtypes=[C.c_void_p,C.c_void_p,C.c_uint8]
lib.fx_device_session_ack_timer.argtypes=[C.c_void_p,C.c_void_p]
lib.fx_device_session_submit_pair.argtypes=[C.c_void_p,C.c_uint8,C.c_uint8]
lib.fx_device_session_read_ram.argtypes=[C.c_void_p,C.c_uint16,C.c_void_p,C.c_size_t]
lib.device_framebuffer.argtypes=[C.c_void_p,C.c_void_p]
lib.device_alias_guard.argtypes=[C.c_void_p,C.c_uint]
s=None
class SessionRam:
    def __bytes__(self):
        result=(C.c_uint8*65536)()
        assert lib.fx_device_session_read_ram(s,0,result,65536)==0
        return bytes(result)
    def __getitem__(self,index):return bytes(self)[index]
ram=SessionRam()
actual_abi={'transport':'opaque public device session; C snapshot adapter; no writable data/CPU/frame seam'}
rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rd=(C.c_uint8*len(rom)).from_buffer_copy(rom)
n=Machine(rom,nd)
nl=n.lib;nl.runtime_run_to.argtypes=[C.c_uint32,C.c_uint64];nl.runtime_run_to.restype=C.c_int
frames=(C.c_uint8*65536).in_dll(nl,'runtime_frame_writes')
pairs={rom[0x7fe+8*col+row]:(1<<col,1<<row) for col in range(8) for row in range(8)}
def field(i):return lib.device_field(s,i)
def packed(b):return base64.b64encode(zlib.compress(b)).decode()
NUMERIC_RESIDUAL_CHECKPOINTS = set([(1, 'arithmetic:0xf0:3'), (1, 'arithmetic:0xf0:4'), (1, 'next-key-wait'), (2, 'arithmetic:0xf0:3'), (2, 'arithmetic:0xf0:4'), (2, 'next-key-wait'), (3, 'arithmetic:0xf0:3'), (3, 'arithmetic:0xf0:4'), (3, 'next-key-wait'), (4, 'arithmetic:0xf0:3'), (4, 'arithmetic:0xf0:4'), (4, 'next-key-wait'), (5, 'arithmetic:0xf0:3'), (5, 'arithmetic:0xf0:4'), (5, 'next-key-wait'), (6, 'arithmetic:0xf0:3'), (6, 'arithmetic:0xf0:4'), (6, 'next-key-wait'), (7, 'arithmetic:0xf0:3'), (7, 'arithmetic:0xf0:4'), (7, 'next-key-wait'), (8, 'arithmetic:0xf0:3'), (8, 'arithmetic:0xf0:4'), (8, 'next-key-wait'), (9, 'arithmetic:0xf0:3'), (9, 'arithmetic:0xf0:4'), (9, 'next-key-wait'), (12, 'back:bank-return'), (12, 'back:MODE-return'), (12, 'back:wholeINPUT-entry'), (12, 'back:wholeINPUT-preparation')])
NUMERIC_RESIDUAL_CHECKPOINTS.update((12,label) for label in ('back:wholeINPUT-completed','back:wholeINPUT-cycle-return','back:next-real-key-wait'))
api_guards=[]
def api_guard(name,condition):
 if not condition:raise AssertionError(('public API guard',name))
 api_guards.append(name)
seed_guard=(C.c_uint8*65536).from_buffer_copy(zlib.decompress(base64.b64decode(fixture['rows'][0]['initial_ram_zlib_base64'])))
s=lib.device_create_seed(seed_guard);assert s
initial=bytes(ram)
seed_guard[0x8140]^=255
api_guard('constructor-copies-authored-input-once',bytes(ram)==initial)
api_guard('invalid-short-initial-image',not lib.device_create_config(seed_guard,65535,0))
api_guard('invalid-null-nonzero-image',not lib.device_create_config(None,1,0))
api_guard('reset-null-invalid',lib.fx_device_session_reset(None)==-1)
api_guard('step-null-invalid',lib.fx_device_session_step(None,None,0)==-1)
api_guard('submit-null-invalid',lib.fx_device_session_submit_pair(None,1,1)==-1)
api_guard('release-null-invalid',lib.fx_device_session_release(None)==-1)
api_guard('ack-without-pending-no-change',lib.fx_device_session_ack_timer(s,None)==-1 and bytes(ram)==initial and field(25)==0xffffffff)
output=(C.c_uint8*2)(0x55,0xaa)
api_guard('nonwrapping-read-rejection',lib.fx_device_session_read_ram(s,65535,output,2)==-1 and bytes(output)==b'\x55\xaa')
api_guard('zero-read-null-storage',lib.fx_device_session_read_ram(s,0,None,0)==0)
api_guard('nonzero-read-null-rejection',lib.fx_device_session_read_ram(s,0,None,1)==-1)
api_guard('snapshot-output-session-alias',lib.device_alias_guard(s,0)==-1 and bytes(ram)==initial)
api_guard('ram-output-session-alias',lib.device_alias_guard(s,1)==-1 and bytes(ram)==initial)
api_guard('zero-size-session-alias-no-change',lib.device_alias_guard(s,2)==0 and bytes(ram)==initial)
assert lib.fx_device_session_submit_pair(s,0x12,0x34)==0
changed=[i for i,(a,b) in enumerate(zip(initial,bytes(ram))) if a!=b]
api_guard('raw-submit-only-pair-bytes',set(changed)<=set((0x8e01,0x8e02)) and ram[0x8e01:0x8e03]==b'\x12\x34')
api_guard('release-only-pair-bytes',lib.fx_device_session_release(s)==0 and ram[0x8e01:0x8e03]==b'\x00\x00')
first=s;s=lib.device_create_seed(None);assert s
cold=bytearray(65536);cold[0xf040]=255
api_guard('default-cold-input-image',bytes(ram)==bytes(cold) and field(0)==0 and field(27)==0)
assert lib.fx_device_session_submit_pair(s,3,4)==0
s2=s;s=first
api_guard('sessions-own-independent-ram',ram[0x8e01:0x8e03]==b'\x00\x00')
lib.fx_device_session_destroy(s2);lib.fx_device_session_destroy(s);s=None
rows=[];failures=[];residuals=[];pending_bodies=[];completed_bodies=[];checks=len(api_guards);sequence_id=0; token_index=0
def compare(label,stop,status,numeric=False):
 global checks
 if nl.harness_get_pc()==stop:assert nl.harness_run(1,0x2fffe,False)==103
 result=nl.runtime_run_to(stop,fixture['instruction_budget'])
 after=bytes(n.ram);actual=bytes(ram)
 diffs=[(i,after[i],actual[i]) for i in range(65536) if after[i]!=actual[i] and not frames[i]]
 allowed=[v for v in diffs if numeric and ((sequence_id,label) in NUMERIC_RESIDUAL_CHECKPOINTS or sequence_id>16) and 0x8000<=v[0]<0x80dc]
 unexpected=[v for v in diffs if v not in allowed]
 callback=lib.fx_device_session_take_callback(s);native_callback=nl.harness_callback()
 semantic=[]
 framebuffer=(C.c_uint8*384)();assert lib.device_framebuffer(s,framebuffer)==0
 original_frame=b''.join(bytes(n.ram[0xf800+16*y:0xf800+16*y+12]) for y in range(32))
 if bytes(framebuffer)!=original_frame:semantic.append(['visible-LCD',digest_bytes(framebuffer),digest_bytes(original_frame)])
 if field(25)!=status:semantic.append(['public-status',field(25),status])
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
 before=field(0);has_pair=bool(ram[0x8e01] or ram[0x8e02]);status=lib.fx_device_session_step(s,None,0);event=field(1)
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
 elif event==12:stop=0xd7ae
 elif event==11:
  if field(9)==1:stop={7:0xecaa,8:0xeca6,4:0xcd66,5:0xf02c,10:0xe1be}.get(field(10))
  elif field(9)==2:stop=0xda58 # UI readiness gate atDA58 needs later exact leaf boundary.
 if stop is not None:compare(label,stop,status,numeric)
 return status
def release():
 lib.fx_device_session_release(s);n.ram[0x8e01]=n.ram[0x8e02]=0
def raw(token):
 global token_index
 tokens=fixture['rows'][sequence_id-1]['physical_tokens']
 assert token_index < len(tokens) and token == tokens[token_index]
 token=tokens[token_index];token_index+=1
 key=pairs[token];lib.fx_device_session_submit_pair(s,*key);n.ram[0x8e01],n.ram[0x8e02]=key
def retain_body(label):
 global checks
 before=bytes(ram);status=lib.fx_device_session_step(s,None,0)
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
 global sequence_id,token_index,s
 if sequence_id:
  assert token_index == len(fixture['rows'][sequence_id-1]['physical_tokens'])
 token_index=0
 sequence_id+=1
 row = fixture['rows'][sequence_id - 1]
 if row['group'] == 'arithmetic':
  assert row['port'] == port and row['mode'] == mode
 seed = bytearray(zlib.decompress(base64.b64decode(row['initial_ram_zlib_base64'])))
 n.reset();nl.runtime_observer_reset();C.memmove(n.ram,bytes(seed),65536)
 if s:lib.fx_device_session_destroy(s)
 seed_input=(C.c_uint8*65536).from_buffer_copy(seed)
 s=lib.device_create_seed(None if row.get('initial_image')=='cold' else seed_input)
 assert s
 status=lib.fx_device_session_reset(s);assert status==1 and field(1)==1
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
 before=bytes(ram);assert lib.fx_device_session_step(s,None,0)==3 and bytes(ram)==before;checks+=1
 status=lib.fx_device_session_ack_timer(s,None);assert status==0;compare('back:invalid-key-ack',0x1d8a4,status)
 raw(0xe6);assert step('back:AC-timer')==3;release()
 before=bytes(ram);assert lib.fx_device_session_step(s,None,0)==3 and bytes(ram)==before;checks+=1
 status=lib.fx_device_session_ack_timer(s,None);assert status==1;compare('back:AC-ack',0xc9e8,status)
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
 before=bytes(ram);assert lib.fx_device_session_step(s,None,0)==3 and bytes(ram)==before;checks+=1
 status=lib.fx_device_session_ack_timer(s,None);assert status==0;compare('timer-ack',0x1d8a4,status)
 raw(0x35);assert step('SETUP-Gra')==1;release();assert step('SETUP-return')==1
 assert step('SETUP-followup-input-entry')==1
 for k in range(8):
  step('SETUP-followup-input:'+str(k))
  if field(1)==5:break
 release();assert step('SETUP-next-key-wait')==0
 export_pair=fixture['rows'][sequence_id-1]['export_pair']
 lib.fx_device_session_submit_pair(s,*export_pair);n.ram[0x8e01],n.ram[0x8e02]=export_pair
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
 # The original physical recipe ends at its real retained STAT prefix.
 # No fabricated host reply advances the native or C body.
 # Dedicated MATRIX/VECTOR screen bodies and the four remaining typed body controls
 # remain explicit runtime requests in this fixture. The completed rich AC
 # control above uses its actual whole UI; it never substitutes direct F12A.
 # No success is synthesized for the four remaining typed body controls.
 assert sequence_id==16 and len(rows)==346 and checks==1056+len(api_guards)
 assert len(pending_bodies)==3 and len(completed_bodies)==2
 legacy_counts=dict(cases=16,observations=len(rows),checks=checks,pending=len(pending_bodies),completed=len(completed_bodies))
 for recipe in authored['extensions']:
  seed=boot(0);sequences.append(dict(id=sequence_id,group=recipe['group'],initial_ram_sha256=digest_bytes(seed)))
  for op_index,op in enumerate(recipe['operations']):
   label=recipe['group']+':'+str(op_index)
   if op['kind']=='key':raw(op['token'])
   else:
    lib.fx_device_session_submit_pair(s,op['columns'],op['rows'])
    n.ram[0x8e01]=op['columns'];n.ram[0x8e02]=op['rows']
   for k in range(40):
    status=step(label+':'+str(k),True)
    if field(1)==5 or status in (0,2,3,4,5):break
   else:raise AssertionError(('unbounded persistent action',label,field(0),field(1)))
   release()
   assert status!=4,('new ordinary recipe reached typed gap',label,field(9),field(10))
   for k in range(40):
    status=step(label+':released:'+str(k),True)
    if status in (0,3,4):break
   else:raise AssertionError(('unbounded persistent release',label))
   assert status==0,('ordinary recipe failed to retain actual next-key-wait',label,status)
 assert token_index==len(fixture['rows'][sequence_id-1]['physical_tokens'])
assert sequence_id==len(fixture['rows'])
lib.fx_device_session_destroy(s);s=None
assert_stable()
changed=[]
if any(digest(q) != h for q, h in compiled_artifacts.items()):
 raise RuntimeError('Compiled artifact changed during execution')
report=dict(optimization=a.optimization,sequences=sequences,observations=len(rows),checks=checks,failures=failures,transport_abi=actual_abi,api_guards=api_guards,legacy_counts=legacy_counts,numeric_scratch_residuals=residuals,pending_bodies=pending_bodies,completed_former_body_controls=completed_bodies,input_pins=pins,end_pins={str(q):digest(q) for q in source_paths},source_changes=changed,rows=rows,limits=['The exact original16 physical recipes are retained. Three real MATRIX/VECTOR/STAT typed requests remain explicit incomplete boundaries; two former readiness bodies really complete. The old host-only fabricated STAT body reply is deliberately excluded from the new opaque API.',
'Fresh extensions execute original reset6F82 once, then uninterrupted real key continuations; no native output or CPU/frame state is supplied to C.',
'Only witnessed original stack writes are excluded; declared numerical8000..80DB workspace differences remain explicit residuals. Persistent result, variables, Ans/PreAns, replay, MMIO and LCD remain compared.',
'Each public device step calls one named controller phase. A timer acknowledgment is an explicit input, not elapsed wall clock. No unsupported body is accepted as success.'])
report['artifacts']={str(q):digest(q) for q in [BUILD/'device-session.so',nd/'nxu8-harness.so',BUILD/'observations.jsonl.gz']}
assert a.private_report is not None or a.no_report
if a.private_report:
 a.private_report.parent.mkdir(parents=True, exist_ok=True)
 a.private_report.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(optimization=a.optimization,sequences=len(sequences),observations=len(rows),checks=checks,failures=len(failures),source_changes=changed)))
if failures or changed:sys.exit(1)
