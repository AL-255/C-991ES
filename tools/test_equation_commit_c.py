#!/usr/bin/env python3
"""Fresh complete E680/E782 coefficient-copy proof over504 input-only recipes.

Default canonical proof runs bothO2/O3. Custom fixtures, source roots, builds or
single optimization runs require --no-report and cannot replace canonical proof.
"""
import argparse,base64,ctypes as C,gzip,hashlib,json,re,subprocess,zlib
from pathlib import Path
from c_build_inputs import implementation_inputs
from c_verification import write_report

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE=ROOT/'analysis/native-fixtures/equation-commit/inputs.json'
DEFAULT_BUILD=ROOT/'analysis/build/equation-commit'
ADAPTER='tools/equation_support/commit_adapter.c'
NATIVE='tools/equation_support/commit_native.c'
TEST='tools/test_equation_commit_c.py'
class Platform(C.Structure):
    _fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),
              ('ram',C.POINTER(C.c_uint8)),('callback_pending',C.c_uint8),('status',C.c_int)]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def packed(raw):return base64.b64encode(zlib.compress(raw)).decode()
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-root',type=Path,default=ROOT)
    ap.add_argument('--fixture',type=Path,default=DEFAULT_FIXTURE)
    ap.add_argument('--build-dir',type=Path,default=DEFAULT_BUILD)
    ap.add_argument('--optimization',choices=('both','O2','O3'),default='both')
    ap.add_argument('--no-report',action='store_true')
    args=ap.parse_args()
    canonical=(args.source_root.resolve()==ROOT.resolve() and
               args.fixture.resolve()==DEFAULT_FIXTURE.resolve() and
               args.build_dir.resolve()==DEFAULT_BUILD.resolve() and args.optimization=='both')
    if not args.no_report and not canonical:
        ap.error('Custom/candidate/single-optimization runs require --no-report; canonical proof uses all defaults')
    fixture=json.loads(args.fixture.read_text())
    if set(fixture)!={'schema','basis','initial_ram_hex','cases'} or fixture['schema']!=1:
        raise ValueError('Unexpected fixture fields/schema; expected input-only recipe')
    seed=bytes.fromhex(fixture['initial_ram_hex'])
    if len(seed)!=65536:raise ValueError('Prepared RAM must contain65536 input bytes')
    recipes=[]
    for k in (1,2):
        for p in range(1,2+(k==2)):
            for r in range(1,k+2):
                for c in range(1,4):
                    for o in range(-10,11):
                        recipes.append(dict(id=len(recipes),selector=k,page=p,row=r,column=c,source_offset=o))
    if fixture['cases']!=recipes:raise ValueError('The exact complete504-case input recipe is required')
    source_root=args.source_root.resolve();cmake=source_root/'csrc/CMakeLists.txt'
    library=cmake.read_text().split('target_include_directories')[0]
    names=['csrc/'+n for n in re.findall(r'^\s+([a-zA-Z0-9_/]+\.c)\)?$',library,re.M)]
    if not {'csrc/ui/fx_equation_controller.c','csrc/ui/fx_equation_result.c'}<=set(names):
        raise ValueError('Production CMake closure must register the equation helpers')
    source_inputs=['csrc/CMakeLists.txt',*implementation_inputs(source_root,names)]
    common=[ADAPTER,NATIVE,TEST,'tools/c_build_inputs.py','tools/c_verification.py',
            'tools/nxu8/harness.c','tools/nxu8/machine.py','tools/nxu8/vendor/SimU8/core.c',
            'firmware/fx-991es-plus-c-ver4.bin']
    common += [str(p.relative_to(ROOT))for p in (ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
    paths=[*(source_root/p for p in source_inputs),*(ROOT/p for p in common),args.fixture]
    pins={str(p.resolve()):sha(p)for p in paths}
    def unchanged():
        changed=[p for p,h in pins.items()if sha(p)!=h]
        if changed:raise RuntimeError('Pinned input changed during execution: '+str(changed))
    args.build_dir.mkdir(parents=True,exist_ok=True)
    nativefile=args.build_dir/'commit-native.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        '-I'+str(ROOT/'tools/nxu8'),str(ROOT/NATIVE),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),
        '-o',str(nativefile)],check=True)
    native=C.CDLL(str(nativefile.resolve()))
    native.equation_commit_native_init.argtypes=[C.c_void_p,C.c_size_t]
    native.equation_commit_native_ram.restype=C.POINTER(C.c_uint8*65536)
    native.equation_commit_native_call.argtypes=[C.c_uint16]
    native.equation_commit_native_return.restype=C.c_uint
    frames=(C.c_uint8*65536).in_dll(native,'equation_commit_frames')
    floor=C.c_uint.in_dll(native,'equation_commit_floor')
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rombuf=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    summaries=[];artifacts={str(nativefile.resolve()):sha(nativefile)}
    optimizations=('O2','O3')if args.optimization=='both'else(args.optimization,)
    for optimization in optimizations:
        candidate=args.build_dir/('commit-'+optimization+'.so')
        subprocess.run(['gcc','-std=c99','-'+optimization,'-Wall','-Wextra','-Werror',
            '-shared','-fPIC','-Wl,--no-undefined','-I'+str(source_root/'csrc'),
            *[str(source_root/n)for n in names],str(ROOT/ADAPTER),'-o',str(candidate)],check=True)
        artifacts[str(candidate.resolve())]=sha(candidate);lib=C.CDLL(str(candidate.resolve()))
        lib.equation_commit_apply.argtypes=[C.POINTER(Platform),C.c_uint16]
        lib.equation_commit_abi.argtypes=[C.c_uint];lib.equation_commit_abi.restype=C.c_size_t
        abi=[C.sizeof(Platform),*[getattr(Platform,n).offset for n in('rom','rom_size','ram','callback_pending','status')],C.sizeof(C.c_uint16)]
        if abi!=[lib.equation_commit_abi(n)for n in range(len(abi))]:
            raise ValueError('Compiled platform/address ABI mismatch')
        failures=[];observations=[]
        archive=args.build_dir/('observations-'+optimization+'.jsonl.gz')
        with gzip.open(archive,'wt')as stream:
            for recipe in recipes:
                raw=bytearray(seed);k,p,r,c,o=(recipe[n]for n in('selector','page','row','column','source_offset'))
                pointer=0xfde+18*p+6*r+2*c
                destination=int.from_bytes(rom[pointer:pointer+2],'little');source=destination+o
                for a in range(0x8280,0x8360):raw[a]=(a-0x827f)%256
                for a,v in((0x80fa,k),(0x80fc,21),(0x80fd,0),(0x811c,p),(0x811d,r),(0x811e,c),(0x8100,0xac),(0x8101,2),(0x8130,1)):raw[a]=v
                ram=(C.c_uint8*65536).from_buffer_copy(raw);platform=Platform(rombuf,len(rom),ram,0,0)
                native.equation_commit_native_init(rombuf,len(rom));native_ram=native.equation_commit_native_ram().contents
                C.memmove(native_ram,bytes(raw),65536)
                host_status=lib.equation_commit_apply(C.byref(platform),source)
                native_status=native.equation_commit_native_call(source);native_return=native.equation_commit_native_return()
                actual,expected=bytes(ram),bytes(native_ram);mask=bytes(frames)
                differences=[[a,actual[a],expected[a]]for a in range(65536)if actual[a]!=expected[a]and not mask[a]]
                observation=dict(recipe=recipe,source_address=source,destination_address=destination,
                    c_status=host_status,native_status=native_status,native_return=native_return,
                    minimum_sp=floor.value,frame_writes=[a for a,b in enumerate(mask)if b],differences=differences,
                    c_ram_sha256=hashlib.sha256(actual).hexdigest(),native_ram_sha256=hashlib.sha256(expected).hexdigest())
                observations.append(observation)
                stream.write(json.dumps(dict(**observation,c_ram=packed(actual),native_ram=packed(expected),frame_mask=packed(mask)))+'\n')
                if host_status!=0 or native_status!=100 or native_return!=3 or differences:failures.append(observation)
        unchanged()
        if any(sha(p)!=h for p,h in artifacts.items()):raise RuntimeError('Compiled artifact changed during execution')
        summaries.append(dict(optimization=optimization,native_calls=len(observations),checks=len(abi)+4*len(observations),
            abi=abi,failures=failures,observations=observations,archive_sha256=sha(archive),archive=str(archive),
            candidate_sha256=sha(candidate)))
        print(optimization,len(observations),'complete native calls, failures',len(failures),flush=True)
    unchanged()
    if any(sha(p)!=h for p,h in artifacts.items()):raise RuntimeError('Compiled artifact changed during execution')
    report=dict(cases=sum(s['native_calls'] for s in summaries),
        checks_total=sum(s['checks'] for s in summaries),
        cases_per_optimization=504,optimizations=summaries,
        failures=[dict(optimization=s['optimization'],case=x)for s in summaries for x in s['failures']],
        exact_input_pins=pins,compiled_artifacts=artifacts,source_changes=[],
        scope='Prepared successful linear2/3 screen21 coefficient commit. Actual fullE680 includesE782 andEB6A. Portable51AA state clear plus production scalar commit. Entire65536 RAM compares except individually witnessed original CPU-frame writes; no numeric masks or synthesized output/state. Host helper status0 corresponds original caller return3. All24 grid coordinates each have21 physical overlapping/odd-source offsets. No original execution in production C; no whole-runtime/singular/polynomial claim.')
    diagnostic=args.build_dir/'proof.json';diagnostic.write_text(json.dumps(report,indent=2)+'\n')
    if report['failures']:raise AssertionError('Original coefficient commit mismatches; see '+str(diagnostic))
    if not args.no_report:
        deps=list(dict.fromkeys(source_inputs+common+[str(DEFAULT_FIXTURE.relative_to(ROOT))]))
        write_report('analysis/c-verification/equation_commit.json',report,deps,TEST)
if __name__=='__main__':main()
