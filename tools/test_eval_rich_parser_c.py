#!/usr/bin/env python3
"""Compare prepared physical rich grammar against fresh original171F4 calls."""
import argparse,base64,ctypes as C,gzip,hashlib,json,re,subprocess,sys,zlib
from collections import Counter
from pathlib import Path
from c_verification import ROOT, write_report
from c_build_inputs import implementation_inputs
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--parser-source',type=Path,help='Preview source; requires --no-report')
ap.add_argument('--no-report',action='store_true')
ap.add_argument('--optimization',choices=('O2','O3'),default='O2')
ap.add_argument('--build-dir',type=Path,help='Private output directory; requires --no-report')
args=ap.parse_args()
if args.build_dir and not args.no_report:ap.error('--build-dir requires --no-report')
HERE=args.build_dir.resolve() if args.build_dir else ROOT/'analysis/build/eval-rich-parser'
HERE.mkdir(parents=True,exist_ok=True)
if args.parser_source and not args.no_report:ap.error('--parser-source requires --no-report')
preview=args.parser_source.resolve() if args.parser_source else None
if preview and not preview.is_file():ap.error('Preview source does not exist')
preview_digest=hashlib.sha256(preview.read_bytes()).hexdigest() if preview else None
SNAP=ROOT
sys.path.insert(0,str(ROOT/'tools'))
class Number(C.Structure):_fields_=[('bytes',C.c_uint8*10)]
class Result(C.Structure):_fields_=[('value',Number*2),('consumed',C.c_size_t),('unsupported_token',C.c_uint8)]
class Storage(C.Structure):_fields_=[('ram',C.POINTER(C.c_uint8)),('ram_size',C.c_size_t),('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t)]
class Effects(C.Structure):_fields_=[('equation_used',C.c_uint8),('restricted_state',C.c_uint8)]
from nxu8.machine import Machine
fixture_relative='analysis/native-fixtures/rich-expression-grammar/operators/fixtures.json.gz'
alias_relative='analysis/native-fixtures/eval-rich/parser/ordered-alias-inputs.json'
sources=['csrc/'+n for n in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',(SNAP/'csrc/CMakeLists.txt').read_text().split('target_include_directories')[0])]
dependencies=implementation_inputs(ROOT,sources)+['csrc/CMakeLists.txt','tools/test_eval_rich_parser_c.py','tools/nxu8/rich_parser_host_events.c','tools/c_build_inputs.py','tools/c_verification.py','tools/nxu8/machine.py','tools/nxu8/harness.c','tools/nxu8/vendor/SimU8/core.c','firmware/fx-991es-plus-c-ver4.bin',fixture_relative,alias_relative]
dependencies+=[str(p.relative_to(ROOT)) for p in sorted((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h'))]
pins={str(p):hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in dependencies}
if preview:
 includes=lambda p:set(re.findall(r'^\s*#\s*include\s*"([^"]+)"',p.read_text(),re.MULTILINE))
 if includes(preview)!=includes(ROOT/'csrc/parse/fx_eval.c'):ap.error('Preview must use pinned production include closure')
 for name in includes(preview):
  local=(preview.parent/name).resolve()
  approved=[(ROOT/'csrc/parse'/name).resolve(),(ROOT/'csrc'/name).resolve()]
  if local.is_file() and local not in approved:ap.error('Preview-local unpinned header: '+name)
abi_source=HERE/'abi.c'
abi_source.write_text("#include <stddef.h>\n#include \"parse/fx_eval.h\"\nsize_t rich_parser_test_abi(unsigned i){const size_t v[]={sizeof(fx_number),sizeof(fx_eval_result),offsetof(fx_eval_result,value),offsetof(fx_eval_result,consumed),offsetof(fx_eval_result,unsupported_token),sizeof(fx_eval_storage),offsetof(fx_eval_storage,ram),offsetof(fx_eval_storage,ram_size),offsetof(fx_eval_storage,rom),offsetof(fx_eval_storage,rom_size),sizeof(fx_eval_effects),offsetof(fx_eval_effects,equation_used),offsetof(fx_eval_effects,restricted_state)};return v[i];}\n")
compiled=[str(preview if preview and p=='csrc/parse/fx_eval.c' else SNAP/p) for p in sources]
subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined','-I',str(ROOT/'csrc'),'-I',str(ROOT/'csrc/parse'),*compiled,str(abi_source),'-o',str(HERE/'parser.so')],check=True)
lib=C.CDLL(str(HERE/'parser.so'))
lib.fx_evaluate_prepared_with_storage.argtypes=[C.POINTER(C.c_uint8),C.c_size_t,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,C.POINTER(Number),C.c_void_p,C.POINTER(Storage),C.POINTER(Effects),C.POINTER(Result)]
lib.rich_parser_test_abi.argtypes=[C.c_uint];lib.rich_parser_test_abi.restype=C.c_size_t
abi_expected=[C.sizeof(Number),C.sizeof(Result),Result.value.offset,Result.consumed.offset,Result.unsupported_token.offset,C.sizeof(Storage),Storage.ram.offset,Storage.ram_size.offset,Storage.rom.offset,Storage.rom_size.offset,C.sizeof(Effects),Effects.equation_used.offset,Effects.restricted_state.offset]
abi_actual=[lib.rich_parser_test_abi(i) for i in range(len(abi_expected))]
if abi_actual!=abi_expected:raise AssertionError(('ABI mismatch',abi_actual,abi_expected))
rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
oracle_dir=HERE/'native';oracle_dir.mkdir(exist_ok=True)
observer=ROOT/'tools/nxu8/rich_parser_host_events.c'
subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(observer),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(oracle_dir/'nxu8-harness.so')],check=True)
native=Machine(rom,oracle_dir)
nl=native.lib
nl.review_run.argtypes=[];nl.review_run.restype=C.c_int
frame_writes=(C.c_uint8*65536).in_dll(nl,'review_frame_writes')
compiled_artifact_pins={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [abi_source,HERE/'parser.so',oracle_dir/'nxu8-harness.so']}
fixture_path=ROOT/fixture_relative
archive_digest=pins[fixture_relative]
fixtures=json.load(gzip.open(fixture_path,'rt'))
alias_fixture=json.loads((ROOT/alias_relative).read_text())
if alias_fixture['schema_version']!=1 or alias_fixture['seed_count']!=545 or len(alias_fixture['seeds'])!=545:
 raise AssertionError('Unexpected ordered-alias input corpus')
if [c['case_id'] for c in alias_fixture['seeds']]!=list(range(545)):
 raise AssertionError('Ordered-alias IDs must be complete and unique')
rb=(C.c_uint8*len(rom)).from_buffer_copy(rom);ram=(C.c_uint8*65536)()
storage=Storage(ram,65536,rb,len(rom));secondary=Number.from_buffer_copy(bytes([0xee])*10)
rows=[];archive_disagreements=[]
for index,case in enumerate(fixtures['fixtures']):
 native.reset();seed=fixtures['profiles'][case['profile']]
 for a,v in [(0x80f9,case['mode']),(0x80fa,case['selected_state']),(0x80fc,1),(0x80f5,0xf0),(0x8105,4),(0x8106,case['math_output']),(0x8121,1),(0x8125,seed['incoming_mask'])]:native.ram[a]=v
 for a,raw in [(0x80e0,bytes.fromhex(seed['dimensions'])),(0x829e,bytes.fromhex(seed['payload'])),(0x8226,bytes.fromhex(fixtures['initial_variables100'])),(0x8900,bytes([0xee])*20),(0x8600,bytes.fromhex(case['tokens'])+b'\0'),(0x8190,b'\0\x86')]:
  C.memmove(C.byref(native.ram,a),raw,len(raw))
 before=bytes(native.ram);C.memmove(ram,before,65536)
 native.er(0,0x8190);native.er(2,0x8900);nl.harness_set_sp(0x8dee);nl.harness_set_lr(0x2fffe);nl.harness_set_pc(0x171f4)
 execution=nl.review_run();after=bytes(native.ram);floor=C.c_uint.in_dll(nl,'review_floor').value
 expected=dict(stop=execution,status=native.reg(0),cursor=native.word(0x8190)-0x8600,record20=after[0x8900:0x8914].hex(),dimensions=after[0x80e0:0x80f2].hex(),payload=after[0x829e:0x85c8].hex(),mask=after[0x8125],variables100=after[0x8226:0x828a].hex())
 for key,value in expected.items():
  if value!=case['result'][key]:archive_disagreements.append(dict(index=index,field=key,expected=case['result'][key],actual=value))
 raw=bytes.fromhex(case['tokens'])+b'\0';token_buffer=(C.c_uint8*len(raw)).from_buffer_copy(raw);result=Result();effects=Effects()
 status=lib.fx_evaluate_prepared_with_storage(token_buffer,len(raw),None,None,None,None,C.byref(secondary),None,C.byref(storage),C.byref(effects),C.byref(result))
 C.memmove(C.byref(ram,0x8900),bytes(result.value),20)
 cursor=0x8600+result.consumed;ram[0x8190]=cursor&255;ram[0x8191]=(cursor>>8)&255
 actual=bytes(ram)
 differences=[]
 # Only the numeric-register arena and individually witnessed frame writes
 # are host-local. All16 bank dimensions/payloads and globals remain visible.
 exclusions=[(0x8000,0x80dc)]
 for a in range(0x80dc,65536):
  if actual[a]!=after[a] and not frame_writes[a]:differences.append([f'{a:04x}',after[a],actual[a]])
 rows.append(dict(index=index,label=case['label'],tokens=case['tokens'],mode=case['mode'],native=expected,actual_status=status,actual_cursor=result.consumed,actual_record20=bytes(result.value).hex(),unsupported_token=result.unsupported_token,differences=differences,native_polls=C.c_uint.in_dll(nl,'review_polls').value,exclusions=exclusions,minimum_sp=floor,witnessed_frame_bytes=sum(frame_writes)))
 if index%100==0:print('completed',index,flush=True)
# The original1376 cases above remain unchanged. These input-only seeds
# additionally reach live component-pool aliases through the full grammar.
BASE_DOMAIN_IDS={508,509,518,519,520,521}
def alias_policy_checks(row,kind):
    """Compare one fresh native/C observation, retaining declared domains."""
    checks=[]
    expected=row['native'];actual=row['actual']
    if kind=='C4-round':
        checks.extend([('native_architecture',True,expected['stop'] in (3,101)),
                       ('host_explicit_boundary',-1,actual['status'])])
    elif kind=='BASE-selected2':
        checks.extend([('native_return',100,expected['stop']),
                       ('native_math',3,expected['status']),
                       ('native_cursor',1,expected['cursor']),
                       ('native_error_record','f3'+'00'*9+'ee'*10,expected['record20']),
                       ('host_explicit_domain_gap',-1,actual['status']),
                       ('host_domain_cursor',0,actual['cursor']),
                       ('host_domain_record','00'*10+'ee'*10,actual['record20']),
                       ('exact_domain_differences',[['8190',1,0],['8900',243,0]],row['differences'])])
    else:
        checks.extend([('native_return',100,expected['stop']),
                       ('status',expected['status'],actual['status']),
                       ('cursor',expected['cursor'],actual['cursor']),
                       ('record20',expected['record20'],actual['record20']),
                       ('persistent_ram',[],row['differences'])])
    return checks

def alias_tokens(selector,form):
    prefix=0x63 if selector==1 else 0xb3
    tokens=bytes([prefix,0x41,0x29])
    if form=='open':return tokens[:-1]
    if form=='grouped':return bytes([0x28])+tokens+bytes([0x29])
    if form=='double':return bytes([prefix])+tokens+bytes([0x29])
    if form!='closed':raise ValueError('Unknown ordered-alias expression form')
    return tokens

def lossless_ram(data):
    return base64.b64encode(zlib.compress(data)).decode('ascii')

alias_rows=[];alias_failures=[];alias_counts=Counter();alias_groups=Counter();alias_checks=0
alias_archive=HERE/'ordered-alias-observations.jsonl.gz'
with gzip.open(alias_archive,'wt') as retained:
 for variant in alias_fixture['variants']:
  for case in alias_fixture['seeds']:
   seed=zlib.decompress(base64.b64decode(case['initial_ram_zlib_base64']))
   if len(seed)!=65536 or hashlib.sha256(seed).hexdigest()!=case['initial_ram_sha256']:
    raise AssertionError(('Invalid ordered-alias seed',case['case_id']))
   before=bytearray(seed);mode=before[0x80f9] if variant['mode'] is None else variant['mode']
   before[0x80f9]=mode;before[0x80fc]=variant['screen']
   before[0x823a:0x8244]=bytes.fromhex('6a000000000000000000')
   if mode==0xc4:before[0x841c:0x8426]=b'\0'*10
   tokens=alias_tokens(case['selector'],variant['form']);raw=tokens+b'\0'
   before[0x8600:0x8600+len(raw)]=raw;before[0x8190:0x8192]=b'\0\x86';before[0x8900:0x8914]=b'\xee'*20
   #80F4/80F5 is the bank10 dimension word; do not overwrite its columns
   # with a generic prior-operation default when constructing the grammar.
   native.reset();C.memmove(native.ram,bytes(before),65536);C.memmove(ram,bytes(before),65536)
   native.er(0,0x8190);native.er(2,0x8900);nl.harness_set_sp(0x8dee);nl.harness_set_lr(0x2fffe);nl.harness_set_pc(0x171f4)
   execution=nl.review_run();after=bytes(native.ram)
   expected=dict(stop=execution,status=native.reg(0),cursor=native.word(0x8190)-0x8600,record20=after[0x8900:0x8914].hex(),pc=nl.harness_get_pc(),last_address=nl.harness_last_address())
   token_buffer=(C.c_uint8*len(raw)).from_buffer_copy(raw);result=Result();effects=Effects()
   status=lib.fx_evaluate_prepared_with_storage(token_buffer,len(raw),None,None,None,None,C.byref(secondary),None,C.byref(storage),C.byref(effects),C.byref(result))
   C.memmove(C.byref(ram,0x8900),bytes(result.value),20);cursor=0x8600+result.consumed;ram[0x8190]=cursor&255;ram[0x8191]=(cursor>>8)&255;actual=bytes(ram)
   differences=[[f'{address:04x}',after[address],actual[address]] for address in range(0x80dc,65536) if actual[address]!=after[address] and not frame_writes[address]]
   kind='handled'
   if variant.get('diagnostic')=='C4-round' and case['selector']==2:kind='C4-round'
   elif variant.get('diagnostic')=='BASE-selected2' and case['case_id'] in BASE_DOMAIN_IDS:kind='BASE-selected2'
   row=dict(variant=variant['name'],case_id=case['case_id'],group=case['group'],source=case['source'],selector=case['selector'],mode=mode,selected_base=before[0x80fa],screen=variant['screen'],tokens=tokens.hex(),classification=kind,native=expected,actual=dict(status=status,cursor=result.consumed,record20=bytes(result.value).hex(),unsupported_token=result.unsupported_token,effects=[effects.equation_used,effects.restricted_state]),differences=differences,native_polls=C.c_uint.in_dll(nl,'review_polls').value,minimum_sp=C.c_uint.in_dll(nl,'review_floor').value,witnessed_frame_bytes=sum(frame_writes),native_entries={f'{entry:06x}':int(native.counts[entry>>1]) for entry in (0x140c6,0x1414a,0x15c9e,0x173fa,0x178ba)})
   for label,wanted,found in alias_policy_checks(row,kind):
    alias_checks+=1
    if wanted!=found:alias_failures.append(dict(variant=variant['name'],case_id=case['case_id'],check=label,expected=wanted,actual=found))
   alias_counts[kind]+=1;alias_groups[variant['name']]+=1;alias_rows.append(row)
   retained.write(json.dumps(dict(**row,initial_ram_zlib_base64=lossless_ram(bytes(before)),native_ram_zlib_base64=lossless_ram(after),c_ram_zlib_base64=lossless_ram(actual),frame_writes_zlib_base64=lossless_ram(bytes(frame_writes)),initial_ram_sha256=hashlib.sha256(before).hexdigest(),native_ram_sha256=hashlib.sha256(after).hexdigest(),c_ram_sha256=hashlib.sha256(actual).hexdigest()))+'\n')
  print(json.dumps(dict(ordered_alias_variant=variant['name'],cases=alias_groups[variant['name']],failures=len(alias_failures))),flush=True)
if len(alias_rows)!=3815 or len(rows)!=1376 or alias_counts!={'handled':3532,'C4-round':277,'BASE-selected2':6}:
 raise AssertionError(('Incomplete unfiltered rich-parser coverage',len(rows),len(alias_rows),dict(alias_counts)))

artifact_changes=[p for p,h in compiled_artifact_pins.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
changed=[p for p,h in pins.items() if hashlib.sha256((SNAP/p).read_bytes()).hexdigest()!=h]
preview_changed=bool(preview and hashlib.sha256(preview.read_bytes()).hexdigest()!=preview_digest)
report=dict(cases=len(rows)+len(alias_rows),ordinary_cases=len(rows),alias_cases=len(alias_rows),alias_counts=dict(alias_counts),alias_failures=alias_failures,alias_groups=dict(alias_groups),alias_observations_sha256=hashlib.sha256(alias_archive.read_bytes()).hexdigest(),alias_rows=alias_rows,compiled_artifact_pins=compiled_artifact_pins,artifact_changes=artifact_changes,preview_source=str(preview) if preview else None,preview_sha256=preview_digest,preview_changed=preview_changed,abi_expected=abi_expected,abi_actual=abi_actual,input_hashes_end={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in dependencies},source_changes=changed,archive_disagreements=archive_disagreements,fixture_sha256=hashlib.sha256(fixture_path.read_bytes()).hexdigest(),snapshot_pins=pins,rows=rows)
report_name=('preview-' if preview else 'report-')+args.optimization+'.json'
(HERE/report_name).write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(cases=len(rows)+len(alias_rows),ordinary_cases=len(rows),ordered_alias_cases=len(alias_rows),alias_counts=dict(alias_counts),alias_failures=len(alias_failures),semantic_mismatches=sum(r['actual_status']!=r['native']['status'] or r['actual_cursor']!=r['native']['cursor'] or r['actual_record20']!=r['native']['record20'] for r in rows),ram_mismatches=sum(bool(r['differences']) for r in rows),archive_disagreements=len(archive_disagreements),source_changes=changed)))

semantic=sum(r['actual_status']!=r['native']['status'] or r['actual_cursor']!=r['native']['cursor'] or r['actual_record20']!=r['native']['record20'] for r in rows)
ram_failures=sum(bool(r['differences']) for r in rows)
nonreturns=sum(r['native']['stop']!=100 for r in rows)
if semantic or ram_failures or nonreturns or archive_disagreements or changed or preview_changed or alias_failures or artifact_changes:
    raise AssertionError('Prepared rich grammar has semantic/RAM/native-boundary/archive/source failures')
if hashlib.sha256(fixture_path.read_bytes()).hexdigest()!=archive_digest:
    raise AssertionError('Immutable original archive changed during the test')
canonical=dict(cases=len(rows)+len(alias_rows),ordinary_cases=len(rows),alias_cases=len(alias_rows),handled_native_calls=len(rows)+alias_counts['handled'],diagnostic_native_boundaries=alias_counts['C4-round'],diagnostic_base_domain_gaps=alias_counts['BASE-selected2'],alias_groups=dict(alias_groups),checks=6*len(rows)+len(abi_expected)+alias_checks,abi_actual=abi_actual,abi_probe_sha256=hashlib.sha256(abi_source.read_bytes()).hexdigest(),optimization=args.optimization,original_calls=len(rows)+len(alias_rows),failures=[],
    generated_artifacts_sha256={(str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [abi_source,HERE/'parser.so',oracle_dir/'nxu8-harness.so',alias_archive]},
    archive_disagreements=0,source_changes=[],observations='analysis/build/eval-rich-parser/'+report_name,
    semantic_contract='Original171F4 status, cursor, both output records, all observable RAM; only numeric register arena8000..80DB and individually witnessed native CPU-frame writes excluded.',
    limitation='The original 1,376 grammar cases are preserved. New ordered ABS/ROUND alias controls cover MATRIX mode 6 and COMP 0xC1, nested/grouped/implicit-close expressions, and 268 finite CMPLX ABS calls. The 277 CMPLX ROUND native architectural outcomes and 6 BASE-selected2 settings gaps are explicit diagnostic controls, not handled numerical results. Continuous-calculus physical workspace, TABLE/statistics expression grammar, caller-output/CPU-frame aliases and full key/menu workflows remain separate requirements.')
if not args.no_report:
 canonical=write_report('analysis/c-verification/eval_rich_parser.json',canonical,[p for p in dependencies if p!=fixture_relative],'tools/test_eval_rich_parser_c.py')
 canonical['tested_inputs_sha256'][fixture_relative]=archive_digest
 (ROOT/'analysis/c-verification/eval_rich_parser.json').write_text(json.dumps(canonical,indent=2)+'\n')
 print(json.dumps(dict(status=canonical['status'],pins=len(canonical['tested_inputs_sha256']))))
