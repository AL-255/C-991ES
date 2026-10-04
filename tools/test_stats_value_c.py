#!/usr/bin/env python3
"""Original13448 differential of the prepared physical Y-mean adapter.

Input fixtures contain no expected outputs. Every expected status/record and
physical RAM observation is obtained from the unmodified firmware on this run.
Only the numeric-register arena and measured original call frame are local
workspace. Statistics cache/table/high physical bank aliases remain compared.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repository-root',type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument('--source-root',type=Path)
    ap.add_argument('--fixtures',type=Path)
    ap.add_argument('--build',type=Path)
    ap.add_argument('--report',type=Path)
    args=ap.parse_args()
    root=args.repository_root.resolve()
    source=(args.source_root or root).resolve()
    fixture=args.fixtures or root/'analysis/native-fixtures/stats-mean-y/inputs.json'
    build=args.build or root/'analysis/build/stats-value'
    report_path=args.report or root/'analysis/c-verification/stats_value.json'
    build.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(root/'tools'))
    from nxu8.machine import Machine
    from c_build_inputs import implementation_inputs
    from c_verification import write_report
    class Number(C.Structure):
        _fields_=[('bytes',C.c_uint8*10)]
    sources=['csrc/numeric/fx_numeric.c','csrc/numeric/fx_transcend.c',
             'csrc/stats/fx_stats.c','csrc/stats/fx_stats_value.c']
    oracle=[root/'tools/nxu8/machine.py',root/'tools/nxu8/harness.c',
            root/'tools/nxu8/vendor/SimU8/core.c',root/'firmware/fx-991es-plus-c-ver4.bin',
            root/'analysis/disassembly/complete.asm',root/'tools/c_build_inputs.py']
    oracle+=sorted((root/'tools/nxu8/vendor/SimU8').glob('*.h'))
    dependencies=[source/p for p in implementation_inputs(source,sources)]
    dependencies+=oracle+[fixture,Path(__file__).resolve(),
        source/'csrc/stats/value/EXECUTION.md',source/'csrc/stats/value/manifest.json']
    def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    pins={str(p):digest(p) for p in dependencies}
    libraries={}
    for optimization in ('O2','O3'):
        library=build/f'stats-value-{optimization}.so'
        subprocess.run(['gcc','-std=c99','-'+optimization,'-Wall','-Wextra','-Werror','-pedantic',
                        '-shared','-fPIC','-Wl,--no-undefined',
                        *[str(source/p) for p in sources],'-o',str(library)],check=True)
        lib=C.CDLL(str(library))
        lib.fx_stats_mean_y_prepared.argtypes=[C.POINTER(Number),C.POINTER(C.c_uint8),C.c_size_t]
        libraries[optimization]=lib
    rom=(root/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    native=Machine(rom,build/'machine')
    observer=build/'observer.c'
    observer.write_text('#include "'+str(root/'tools/nxu8/harness.c')+'"\n'
        'unsigned mean_frame_floor;int mean_run(void){mean_frame_floor=0x8dee;'
        'for(unsigned i=0;i<5000000;++i){unsigned sp=harness_get_sp();'
        'if(sp<mean_frame_floor)mean_frame_floor=sp;'
        'int status=harness_run(1,0x2fffe,false);if(status!=103)return status;}return 103;}\n')
    observer_library=build/'observer.so'
    subprocess.run(['gcc','-std=c99','-O3','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    str(observer),str(root/'tools/nxu8/vendor/SimU8/core.c'),
                    '-o',str(observer_library)],check=True)
    ol=C.CDLL(str(observer_library))
    for name in ['harness_init','harness_set_reg','harness_get_reg','harness_set_sp',
                 'harness_set_lr','harness_set_pc','harness_ram']:
        getattr(ol,name).argtypes=getattr(native.lib,name).argtypes
        getattr(ol,name).restype=getattr(native.lib,name).restype
    native.lib=ol
    native.ram=ol.harness_ram().contents
    ram=(C.c_uint8*65536)()
    cases=json.loads(fixture.read_text())['cases']
    checks=0;failures=[];observations=[]
    for index,case in enumerate(cases):
        native.reset()
        for address,value in [(0x80f9,case['mode']),(0x80fa,case['selected']),
                              (0x80de,case['count']),(0x8109,case['frequency']),
                              (0x810e,case['third']),(0x8138,case['suppress']),(0x812a,0xa5)]:
            native.ram[address]=value
        table_records=bytes.fromhex(case['table_records'])
        for address,raw in [(0x829e,bytes([0x77])*80),(0x82ee,table_records),
                            (0x8900,bytes([0xee])*20)]:
            C.memmove(C.byref(native.ram,address),raw,len(raw))
        before=bytes(native.ram);C.memmove(ram,before,65536)
        native.er(0,0x8900);ol.harness_set_sp(0x8dee)
        ol.harness_set_lr(0x2fffe);ol.harness_set_pc(0x13448)
        execution=ol.mean_run();expected=bytes(native.ram)
        floor=C.c_uint.in_dll(ol,'mean_frame_floor').value
        for optimization,lib in libraries.items():
            C.memmove(ram,before,65536)
            out=Number();status=lib.fx_stats_mean_y_prepared(C.byref(out),ram,65536)
            C.memmove(C.byref(ram,0x8900),bytes(out.bytes),10)
            actual=bytes(ram)
            differences=[[f'{a:04x}',expected[a],actual[a]]
                         for a in range(0x80dc,65536)
                         if not floor<=a<0x8dee and expected[a]!=actual[a]]
            observed=dict(index=index,input=case,optimization=optimization,stop=execution,
                          native_status=native.reg(0),actual_status=status,
                          native_record=expected[0x8900:0x890a].hex(),
                          actual_record=bytes(out.bytes).hex(),ram_differences=differences,
                          frame_exclusion=[f'{floor:04x}','8dee'])
            observations.append(observed)
            checks+=5
            unchanged=all(before[a]==expected[a] for a in range(0x829e,0x829e+80))
            if execution!=100 or status!=native.reg(0) or bytes(out.bytes)!=expected[0x8900:0x890a] or differences or not unchanged:
                failures.append(observed)
        if index%500==0:print(f'completed {index}/{len(cases)}',flush=True)
    # Real invalid-host controls preserve both output and every byte of RAM.
    for optimization,lib in libraries.items():
        sentinel=Number.from_buffer_copy(bytes([0xee])*10)
        for output,data,length in [(None,ram,65536),(C.byref(sentinel),None,65536),
                                   (C.byref(sentinel),ram,0),(C.byref(sentinel),ram,65535)]:
            before=bytes(ram)
            actual=lib.fx_stats_mean_y_prepared(output,data,length)
            checks+=3
            if actual!=-1 or bytes(sentinel.bytes)!=bytes([0xee])*10 or bytes(ram)!=before:
                failures.append(dict(host_guard=True,optimization=optimization,status=actual,length=length))
    changes=[str(p) for p in dependencies if digest(p)!=pins[str(p)]]
    report=dict(status='pass' if not failures and not changes else 'failed',
                cases=len(cases),original_calls=len(cases),c_calls=2*len(cases),checks=checks,
                failures=failures,source_changes=changes,
                tested_inputs_sha256=pins,full_firmware_complete=False,
                scope='Prepared13448 Y-mean, physical05110/05096 layouts; native original status/record/fullRAM',
                gaps=['Oversized rowcount/table overlap and malformed raw records need separate whole-expression proof; retained there unfiltered'],
                observations=observations)
    if failures or changes or source!=root or not Path(__file__).resolve().is_relative_to(root):
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(report,indent=2)+'\n')
    else:
        declared=[str(p.relative_to(root)) for p in dependencies if p.suffix not in ('.md','.asm')]
        write_report(report_path,report,declared,str(Path(__file__).resolve().relative_to(root)))
        # Assembly and the execution document are separately pinned before
        # compilation and checked unchanged above; preserve them in the audit.
        published=json.loads(report_path.read_text())
        published['tested_inputs_sha256'].update({str(p.relative_to(root)):pins[str(p)]
            for p in dependencies if p.suffix in ('.md','.asm')})
        report_path.write_text(json.dumps(published,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['status','cases','original_calls','checks','source_changes']}))
    if failures or changes:raise SystemExit(1)

if __name__=='__main__':main()
