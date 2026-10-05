#!/usr/bin/env python3
"""Replay authored VERIFYD9EE keys inC against immutable fresh native archive."""
if not __debug__:raise SystemExit('Python optimization is unsupported')
import base64
import ctypes as C
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zlib

HERE=Path(__file__).resolve().parent;ROOT=Path(os.environ["VERIFY_ROOT"])
sys.path.insert(0,str(ROOT/'tools'))
from c_build_inputs import implementation_inputs

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    source=Path(os.environ['VERIFY_SOURCE_ROOT']);origin=Path(os.environ['VERIFY_FIXTURE_DIR']);observation_root=Path(os.environ['VERIFY_OBSERVATION_DIR'])
    fixture=origin/'inputs.json';inputs=json.loads(fixture.read_text())
    successor_fixture=origin/'inputs-syntax-successor.json'
    successor=json.loads(successor_fixture.read_text())
    for key in ('initial_globals','initial_words','initial_expression'):
        assert inputs[key]==successor[key]
    inputs['cases']+=successor['cases']
    native_report=observation_root/'run-3edee2aa5f89439faff24ae3f5aa93b8/report.json'
    successor_report=observation_root/'run-5e700a0a9f8f4e73a60a11b812adf116/report.json'
    archives=[];outcomes={}
    for report_path in (native_report,successor_report):
        observation=json.loads(report_path.read_text());archive=report_path.parent/'observations.jsonl.gz'
        assert observation['status']=='observed' and sha(archive)==observation['archive_sha256']
        assert not observation['source_changes'] and not observation['artifact_changes']
        archives.append(archive)
        records=[json.loads(s) for s in gzip.open(archive,'rt')]
        for row in records:
            if row['kind']=='outcome':
                key=(row['id'],row['step']);assert key not in outcomes;outcomes[key]=row
    assert len(outcomes)==96
    cmake=ROOT/'csrc/CMakeLists.txt';text=cmake.read_text()
    body=text.split('add_library(fx991_firmware STATIC',1)[1].split(')',1)[0]
    modules=re.findall(r'\b[\w/]+\.c\b',body)
    modules=list(dict.fromkeys(modules+['numeric/fx_verify_relation.c','parse/fx_verify_chain.c','ui/fx_verify_controller.c']))
    closure=implementation_inputs(source,['csrc/'+s for s in modules])
    paths=[source/p for p in closure]+[Path(__file__),HERE/'main_adapter.c',fixture,
        native_report,successor_fixture,successor_report,*archives,cmake,ROOT/'tools/c_build_inputs.py',
        ROOT/'firmware/fx-991es-plus-c-ver4.bin']
    pins={str(p):sha(p) for p in paths}
    build=Path(os.environ['VERIFY_BUILD_DIR'])/'main';build.mkdir(exist_ok=True)
    temp=build/'compiler-tmp';temp.mkdir(exist_ok=True);os.environ['TMPDIR']=str(temp)
    rom_bytes=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom=(C.c_uint8*len(rom_bytes)).from_buffer_copy(rom_bytes)
    pairs={}
    for column in range(8):
        for row in range(8):
            token=rom_bytes[0x7fe+8*column+row]
            if token:pairs.setdefault(token,(1<<column,1<<row))
    rows=[];failures=[];artifacts={}
    for opt in os.environ['VERIFY_OPTIMIZATIONS'].split(','):
        library=build/(opt+'.so');cmd=['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror',
            '-shared','-fPIC','-Wl,--no-undefined','-I',str(source/'csrc'),
            *(str(source/'csrc'/s) for s in modules),str(HERE/'main_adapter.c'),'-o',str(library)]
        subprocess.run(cmd,check=True);lib=C.CDLL(str(library))
        lib.verify_main_bind.argtypes=[C.POINTER(C.c_uint8),C.POINTER(C.c_uint8),C.c_size_t]
        lib.verify_main_begin.argtypes=[C.c_uint]
        lib.verify_main_finish.argtypes=[C.POINTER(C.c_uint8)]
        ap={str(library):sha(library)}
        for case in inputs['cases']:
            memory=(C.c_uint8*65536)();assert lib.verify_main_bind(memory,rom,len(rom_bytes))==0
            for address,value in inputs['initial_globals'].items():memory[int(address,16)]=value
            for address,value in inputs['initial_words'].items():
                a=int(address,16);memory[a]=value&255;memory[a+1]=value>>8
            memory[0x8106]=case['math']
            expression=bytes.fromhex(inputs['initial_expression'])+b'\0'
            memory[0x8154:0x8154+len(expression)]=expression
            scenario_floor=0x8dee
            for index,step in enumerate(case['steps']):
                reference=outcomes.get((case['id'],index))
                assert reference is not None,('Missing original observation',case['id'],index)
                memory[0x80f5]=step['token'];memory[0x80f7]=1
                if 'modifier' in step:memory[0x80f8]=step['modifier']
                memory[0x8e01]=memory[0x8e02]=0
                assert lib.verify_main_begin(step.get('cancel_at',0))==4
                status=4
                for _ in range(32):
                    status=lib.verify_main_tick()
                    if status!=4:break
                # Physical error keys are authored input recipes, not
                # returned actions or values drawn from native observation.
                delivered=0
                if status==0:
                    for token in step.get('recovery_keys',[]):
                        a,b=pairs[token];memory[0x8e01]=a;memory[0x8e02]=b
                        status=lib.verify_main_tick();delivered+=1
                        if status not in (0,3):break
                expected=zlib.decompress(base64.b64decode(reference['ram']))
                actual=bytes(memory)
                scenario_floor=min(scenario_floor,reference['min_sp'])
                excluded=[(0x8000,0x80dc),(0x8640,0x87d0),(scenario_floor,0x8dee)]
                differences=[{'address':hex(a),'C':actual[a],'native':expected[a]}
                    for a in range(65536) if actual[a]!=expected[a] and
                    not any(lo<=a<hi for lo,hi in excluded)]
                returned=C.c_uint8(0xad);finish=None
                if status==1:finish=lib.verify_main_finish(C.byref(returned))
                matching=(status==1 and reference['returned'] and finish==1 and
                          returned.value==reference['return_byte']) or (
                          status==0 and not reference['returned'])
                row={'id':case['id'],'step':index,'optimization':opt,'C_status':status,
                    'native_returned':reference['returned'],'native_pc':reference['pc'],
                    'C_return':returned.value if status==1 else None,
                    'native_return':reference['return_byte'],'C_polls':lib.verify_main_polls(),
                    'native_polls':reference['timer_responses'],'C_keys_delivered':delivered,
                    'native_keys_delivered':reference['physical_keys_delivered'],
                    'differences':differences[:80],'difference_count':len(differences)}
                rows.append(row)
                if not matching or differences or lib.verify_main_polls()!=reference['timer_responses'] or delivered!=reference['physical_keys_delivered']:
                    failures.append(row)
                if status!=1:break
        assert len([r for r in rows if r['optimization']==opt])==96
        assert ap=={p:sha(Path(p)) for p in ap};artifacts[opt]={'compiler':cmd,'sha256':ap}
    assert pins=={p:sha(Path(p)) for p in pins}
    report={'status':'pass' if not failures else 'fail','rows':rows,'failures':failures,
        'source_pins':pins,'artifacts':artifacts,'source_drift':False,
        'native_archived_calls':96,'C_compared_calls':len(rows),'scope':'Remaining RAM outside arithmetic scratch and the measured cumulative original stack interval (not full64KiB). ActualC D9EE/VERIFYcomposition from authored keys+independent startup-data initializer, comparedtoimmutable genuineoriginal archive. NonstackremainingRAM/LCD/history/output/variables/globals/MMIO pluspoll counts; numeric scratch8000..80DB/8640..87CFexcluded. Not hardwarekeyscan/fullboot/uninterruptedmain parity.'}
    (build/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','source_pins','artifacts')},indent=2))
    return bool(failures)

if __name__=='__main__':raise SystemExit(main())
