#!/usr/bin/env python3
"""Complete original171F4/F12A ordinary odd-result differential proof.

Both optimizations and all defaults are required for canonical publication.
Candidate/custom/single optimization runs require --no-report.
"""
import argparse,base64,ctypes as C,gzip,hashlib,json,re,subprocess,uuid,zlib
from pathlib import Path
from c_build_inputs import implementation_inputs
from c_verification import write_report
ROOT=Path(__file__).resolve().parents[1]
TEST='tools/test_odd_result_c.py'
ADAPTER='tools/odd_result_support/adapter.c'
NATIVE='tools/odd_result_support/native.c'
DEFAULT_FIXTURE=ROOT/'analysis/native-fixtures/ordinary-odd-result/inputs.json'
DEFAULT_BUILD=ROOT/'analysis/build/ordinary-odd-result'
FIXTURE_SHA='0b871020ed1099a2b12bf15f103868d11d12c78d53dc168ceeed20118fd6cf33'
class Platform(C.Structure):
    _fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),
              ('ram',C.POINTER(C.c_uint8)),('callback_pending',C.c_uint8),('status',C.c_int)]
class Context(C.Structure):
    _fields_=[('display_address',C.c_uint16),('result_address',C.c_uint16),
              *[(n,C.c_uint8)for n in('return_value','calculation_mode','saved_math_result','natural_input','natural_result','special_view')]]
class Number(C.Structure):_fields_=[('bytes',C.c_uint8*10)]
class Result(C.Structure):_fields_=[('value',Number*2),('consumed',C.c_size_t),('unsupported_token',C.c_uint8)]
class Storage(C.Structure):_fields_=[('ram',C.POINTER(C.c_uint8)),('ram_size',C.c_size_t),('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t)]
class Source(C.Structure):_fields_=[('input_address',C.c_uint16),('output_address',C.c_uint16),('before_sample',C.c_void_p),('userdata',C.c_void_p)]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def packed(raw):return base64.b64encode(zlib.compress(raw)).decode()
def guard_files(pins):
    changed=[p for p,h in pins.items()if not Path(p).is_file()or sha(p)!=h]
    if changed:raise RuntimeError('Pinned inputs/artifacts changed: '+str(changed))
def guard_abi(actual,expected):
    if actual!=expected:raise ValueError('Compiled opaque transport ABI mismatch')
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-root',type=Path,default=ROOT)
    ap.add_argument('--fixture',type=Path,default=DEFAULT_FIXTURE)
    ap.add_argument('--build-dir',type=Path,default=DEFAULT_BUILD)
    ap.add_argument('--optimization',choices=('both','O2','O3'),default='both')
    ap.add_argument('--no-report',action='store_true');args=ap.parse_args()
    canonical=(args.source_root.resolve()==ROOT.resolve()and args.fixture.resolve()==DEFAULT_FIXTURE.resolve()and args.build_dir.resolve()==DEFAULT_BUILD.resolve()and args.optimization=='both')
    if not args.no_report and not canonical:ap.error('Candidate/custom/single-optimization runs require --no-report; canonical proof uses all defaults')
    if sha(args.fixture)!=FIXTURE_SHA:raise ValueError('Exact historical96 input-only fixture changed')
    fixture=json.loads(args.fixture.read_text())
    if set(fixture)!={'schema','basis','initial_ram_hex','cases'}or fixture['schema']!=1:raise ValueError('Unexpected input-only fixture schema')
    seed=bytes.fromhex(fixture['initial_ram_hex']);assert len(seed)==65536
    recipes=[]
    for entry in('171F4','F12A'):
        for mode in(0xc1,0xc4):
            for math in(0,1):
                for out in(0x8140,0x8141,0x8142,0x8901):
                    for label,tokens in(('integer','3100'),('Pol','6c332c342900'),('Rec','6d322c33302900')):
                        recipes.append(dict(id=len(recipes),entry=entry,mode=mode,math=math,result_address=out,label=label,tokens=tokens))
    if fixture['cases']!=recipes:raise ValueError('Exact complete96-case historical recipe required')
    source_root=args.source_root.resolve();cmake=source_root/'csrc/CMakeLists.txt'
    names=['csrc/'+n for n in re.findall(r'^\s+([a-zA-Z0-9_/]+\.c)\)?$',cmake.read_text().split('target_include_directories')[0],re.M)]
    if not {'csrc/parse/fx_eval.c','csrc/ui/fx_input_controller.c','csrc/platform/fx_persistent.c'}<=set(names):raise ValueError('Production CMake closure missing ordinary INPUT/parser')
    source_inputs=['csrc/CMakeLists.txt',*implementation_inputs(source_root,names+['csrc/ui/fx_input_controller.h','csrc/parse/fx_eval_transport.h'])]
    common=[TEST,ADAPTER,NATIVE,'tools/c_build_inputs.py','tools/c_verification.py','tools/nxu8/harness.c','tools/nxu8/machine.py','tools/nxu8/vendor/SimU8/core.c','firmware/fx-991es-plus-c-ver4.bin']
    common += [str(p.relative_to(ROOT))for p in(ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
    paths=[*(source_root/p for p in source_inputs),*(ROOT/p for p in common),args.fixture]
    pins={str(p.resolve()):sha(p)for p in paths}
    run=args.build_dir/uuid.uuid4().hex;run.mkdir(parents=True,exist_ok=False)
    nativepath=run/'native.so';subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-I'+str(ROOT/'tools/nxu8'),str(ROOT/NATIVE),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(nativepath)],check=True)
    native=C.CDLL(str(nativepath.resolve()));native.harness_init.argtypes=[C.c_void_p,C.c_size_t];native.harness_ram.restype=C.POINTER(C.c_uint8*65536)
    native.odd_result_native_call.argtypes=[C.c_uint32,C.c_uint16];native.harness_get_reg.argtypes=[C.c_uint];native.harness_get_reg.restype=C.c_uint8
    native.harness_callback.restype=C.c_uint32;frames=(C.c_uint8*65536).in_dll(native,'odd_result_frames');floor=C.c_uint.in_dll(native,'odd_result_floor')
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rombuf=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    summaries=[];artifacts={str(nativepath.resolve()):sha(nativepath)}
    opts=('O2','O3')if args.optimization=='both'else(args.optimization,)
    for opt in opts:
        candidate=run/('candidate-'+opt+'.so');subprocess.run(['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined','-I'+str(source_root/'csrc'),*[str(source_root/p)for p in names],str(ROOT/ADAPTER),'-o',str(candidate)],check=True)
        artifacts[str(candidate.resolve())]=sha(candidate);lib=C.CDLL(str(candidate.resolve()));lib.odd_input_size.restype=C.c_size_t;lib.odd_input_field.argtypes=[C.c_void_p,C.c_uint];lib.odd_input_field.restype=C.c_uint
        lib.odd_input_abi.argtypes=[C.c_uint];lib.odd_input_abi.restype=C.c_size_t
        abi=[C.sizeof(Platform),*[getattr(Platform,n).offset for n in('rom','rom_size','ram','callback_pending','status')],C.sizeof(Context),*[getattr(Context,n).offset for n in('display_address','result_address','return_value','calculation_mode','saved_math_result','natural_input','natural_result','special_view')],C.sizeof(Storage),C.sizeof(Source),C.sizeof(Result)]
        guard_abi(abi,[lib.odd_input_abi(n)for n in range(len(abi))]);assert len(abi)==18
        pp=C.POINTER(Platform);lib.odd_result_begin.argtypes=[pp,C.c_void_p,C.c_uint16,C.c_uint8,C.c_uint8];lib.fx_input_controller_tick.argtypes=[pp,C.c_void_p]
        lib.odd_result_prepared.argtypes=[pp,C.c_uint16,C.c_size_t,C.POINTER(C.c_uint16)];lib.fx_take_callback.argtypes=[pp];lib.fx_take_callback.restype=C.c_uint8
        rows=[];failures=[];archive=run/('observations-'+opt+'.jsonl.gz')
        with gzip.open(archive,'wt')as stream:
            for recipe in recipes:
                raw=bytearray(seed);mode,math,out=(recipe[k]for k in('mode','math','result_address'))
                for a,v in((0x80f9,mode),(0x80fc,1),(0x80fd,0),(0x80fe,1),(0x80ff,0),(0x80f5,0xf0),(0x8100,0),(0x8101,0),(0x8130,0),(0x8106,math),(0x810c,0),(0x8105,4)):raw[a]=v
                raw[out:out+20]=b'\xa5'*20;tokens=bytes.fromhex(recipe['tokens']);raw[0x8154:0x8154+len(tokens)]=tokens
                context=bytearray(12);context[:4]=(0x8154).to_bytes(2,'little')+out.to_bytes(2,'little')
                for a,v in((4,1),(6,mode),(9,math)):context[a]=v
                raw[0x9d00:0x9d0c]=context;raw[0x9900:0x9902]=(0x8154).to_bytes(2,'little')
                ram=(C.c_uint8*65536).from_buffer_copy(raw);platform=Platform(rombuf,len(rom),ram,0,0)
                native.harness_init(rombuf,len(rom));nr=native.harness_ram().contents;C.memmove(nr,bytes(raw),65536)
                if recipe['entry']=='F12A':
                    state=C.create_string_buffer(lib.odd_input_size());begin=lib.odd_result_begin(C.byref(platform),state,out,mode,math)
                    status=lib.fx_input_controller_tick(C.byref(platform),state)if begin==4 else begin
                    returned=lib.odd_input_field(state,1);context_return=lib.odd_input_field(state,0);entry=0x1f12a
                else:
                    cursor=C.c_uint16();status=lib.odd_result_prepared(C.byref(platform),out,len(tokens),C.byref(cursor));returned=status;context_return=None;entry=0x171f4
                native_status=native.odd_result_native_call(entry,out);actual=bytes(ram);expected=bytes(nr);comparison=bytearray(actual)
                if recipe['entry']=='F12A':comparison[0x9d04]=context_return
                else:comparison[0x9900:0x9902]=cursor.value.to_bytes(2,'little')
                mask=bytes(frames);differences=[[a,comparison[a],expected[a]]for a in range(65536)if comparison[a]!=expected[a]and not mask[a]and not(0x8000<=a<0x80dc)]
                callback=lib.fx_take_callback(C.byref(platform));native_callback=native.harness_callback();native_return=native.harness_get_reg(0)
                row=dict(recipe=recipe,host_status=status,host_return=returned,context_return=context_return,native_status=native_status,native_return=native_return,callback=callback,native_callback=native_callback,platform_status=platform.status,minimum_sp=floor.value,frame_writes=[a for a,b in enumerate(mask)if b],differences=differences,c_result=actual[out:out+20].hex(),native_result=expected[out:out+20].hex(),c_ram_sha256=hashlib.sha256(actual).hexdigest(),native_ram_sha256=hashlib.sha256(expected).hexdigest())
                rows.append(row);stream.write(json.dumps(dict(**row,c_ram=packed(actual),native_ram=packed(expected),frame_mask=packed(mask)))+'\n')
                if differences or native_status!=100 or returned!=native_return or callback!=native_callback or platform.status!=0 or(recipe['entry']=='F12A'and status!=1):failures.append(row)
        guard_files(pins);guard_files(artifacts)
        summaries.append(dict(optimization=opt,native_calls=len(rows),checks=18+6*len(rows),abi=abi,failures=failures,observations=rows,archive=str(archive),archive_sha256=sha(archive),candidate_sha256=sha(candidate)))
        print(opt,len(rows),'original calls, failures',len(failures),flush=True)
    # Exercise the actual rejecting guard functions on private copies only.
    guards=[];bad=abi.copy();bad[-1]+=1
    try:guard_abi(bad,abi)
    except ValueError:guards.append('altered-ABI')
    else:raise AssertionError('Altered ABI accepted')
    for label,source in(('source',source_root/'csrc/parse/fx_eval.c'),('artifact',candidate),('fixture',args.fixture)):
        copy=run/('guard-'+label);copy.write_bytes(Path(source).read_bytes());expected={str(copy):sha(copy)};copy.write_bytes(copy.read_bytes()+b'\0')
        try:guard_files(expected)
        except RuntimeError:guards.append('altered-'+label+'-copy')
        else:raise AssertionError('Altered '+label+' accepted')
    guard_files(pins);guard_files(artifacts)
    report=dict(cases=96*len(summaries),checks_total=sum(s['checks']for s in summaries)+len(guards),cases_per_optimization=96,optimizations=summaries,guard_checks=guards,failures=[dict(optimization=s['optimization'],case=f)for s in summaries for f in s['failures']],exact_input_pins=pins,compiled_artifacts=artifacts,source_changes=[],scope='Prepared successful scalar1/Pol(3,4)/Rec(2,30) full original171F4/F12A. Exact96 historical input-only recipes spanC1/C4,Math0/1 and8140/8141/8142/8901 outputs. Entire65536 RAM compares outside numeric8000..80DB and per-call witnessed minSP..8DED CPU writes. Named source/context are reconstructed only into comparison image. Results/Ans/variables/replay/MMIO remain compared; no native outputs enter C. No failed/canceled/odd restore or malformed record completeness claim.')
    diagnostic=run/'proof.json';diagnostic.write_text(json.dumps(report,indent=2)+'\n')
    if report['failures']:raise AssertionError('Original odd-result mismatches; see '+str(diagnostic))
    if not args.no_report:write_report('analysis/c-verification/odd_result.json',report,list(dict.fromkeys(source_inputs+common+[str(DEFAULT_FIXTURE.relative_to(ROOT))])),TEST)
    print('REPORT',diagnostic,flush=True)
if __name__=='__main__':main()
