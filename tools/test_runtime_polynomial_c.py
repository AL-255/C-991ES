#!/usr/bin/env python3
"""Run all28 authored polynomial runtime sessions against original ROM in O2/O3.

This private producer writes a unique build report, never a canonical registry.
The retained historical pending artifact remains separate. Its exact variant0
initial RAM and physical recipe are replayed as a new successor observation.
All runs enter original6F82 once, then use physical packets and timer readiness.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import uuid

SCRIPT_ROOT=Path(__file__).resolve().parents[1]
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'firmware/fx-991es-plus-c-ver4.bin').is_file())

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(value,message):
    if not value:raise ValueError(message)

def firmware_sources(source_root, cmake_text):
    """Derive the ordered production target, including later additive modules."""
    block=re.search(r'add_library\(\s*fx991_firmware\s+STATIC\s+(.*?)\)',cmake_text,re.S)
    require(block is not None,'Missing fx991_firmware STATIC target')
    names=re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',block.group(1))
    require(names and len(names)==len(set(names)),'Empty or repeated production source list')
    require('ui/fx_polynomial_equation_controller.c' in names,'Polynomial workflow is not in the production target')
    return [str((source_root/'csrc'/name).resolve()) for name in names]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--candidate-root',type=Path)
    parser.add_argument('--optimization',choices=('O2','O3'))
    parser.add_argument('--verbose',action='store_true')
    args=parser.parse_args()
    if sys.flags.optimize:parser.error('Optimized Python disables proof assertions')
    if (args.candidate_root or args.optimization) and not args.output_dir:
        parser.error('Custom source or single build requires --output-dir')
    out=(args.output_dir or ROOT/'analysis/build/runtime-polynomial'/uuid.uuid4().hex).resolve()
    if out.is_relative_to(ROOT/'analysis/verification') or out.is_relative_to(ROOT/'analysis/c-verification'):
        parser.error('Private proof cannot replace canonical reports')
    out.mkdir(parents=True,exist_ok=False)
    worker=Path(__file__).with_name('runtime_polynomial_variant.py')
    fixture=SCRIPT_ROOT/'analysis/native-fixtures/runtime-polynomial/inputs.json'
    source_root=(args.candidate_root or SCRIPT_ROOT).resolve()
    cmake=source_root/'csrc/CMakeLists.txt'
    cmake_bytes=cmake.read_bytes()
    expected_sources=firmware_sources(source_root,cmake_bytes.decode())
    wrapper_pins={str(p):sha(p) for p in (Path(__file__).resolve(),worker,fixture)}
    wrapper_pins[str(cmake)]=hashlib.sha256(cmake_bytes).hexdigest()
    report=dict(schema=1,status='running',scope=__doc__,created_at=datetime.now(timezone.utc).isoformat(),builds={},source_sha256_pre=wrapper_pins,default_workload=not args.optimization,successful_external_body_completion_calls=0)
    try:
        for opt in ([args.optimization] if args.optimization else ('O2','O3')):
            command=[sys.executable,str(worker),'--build-dir',str(out/opt),'--optimization',opt]
            if args.candidate_root:command+=['--candidate-root',str(args.candidate_root.resolve())]
            if args.verbose:command+=['--verbose']
            report.setdefault('commands',[]).append(command)
            with (out/(opt+'.log')).open('w') as log:
                subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT)
            files=list((out/opt).rglob('proof.json'))
            require(len(files)==1,'Missing or ambiguous actual '+opt+' proof')
            proof=json.loads(files[0].read_text())
            require(proof['status']=='pass-with-numeric-residuals' and proof['optimization']==opt,'Wrong worker status')
            require(proof['corpus']=='all' and proof['sequences']==28,'Default workload changed')
            require(proof['successful_external_body_completion_calls']==0 and not proof['failures'] and not proof['source_changes'],'Unexpected injection, failure or source drift')
            require(proof['poll_snapshot_persistent_gap_count']==0,'Unresolved persistent poll mismatch')
            require(proof['compiled_sources']==expected_sources,'Worker did not compile the exact current fx991_firmware target')
            require(all(sha(p)==h for p,h in proof['source_pins'].items()),'Worker source drift')
            require(all(sha(p)==h for p,h in proof['artifacts'].items()),'Worker artifact drift')
            report['builds'][opt]=dict(proof_path=str(files[0]),proof_sha256=sha(files[0]),archive_path=str(files[0].with_name('observations.jsonl.gz')),archive_sha256=sha(files[0].with_name('observations.jsonl.gz')),sequences=proof['sequences'],observations=proof['observations'],checks=proof['checks'],poll_count=proof['poll_count'],completed_main_cycles=proof['completed_main_cycles'],outer_returns=proof['outer_returns'],exports=proof['exports'],resets=proof['resets'],nonzero_callbacks=proof['nonzero_callbacks'],source_pins=proof['source_pins'],artifacts=proof['artifacts'])
        if not args.optimization:
            a,b=[json.loads(Path(report['builds'][opt]['proof_path']).read_text()) for opt in ('O2','O3')]
            require(a['rows']==b['rows'] and a['poll_rows']==b['poll_rows'],'Builds disagree in actual checkpoint or poll results')
            require(a['source_pins']==b['source_pins'],'Builds use different inputs')
        require(all(sha(p)==h for p,h in wrapper_pins.items()),'Wrapper input drift')
        report['status']='pass-with-numeric-residuals'
        for key in ('sequences','observations','checks','poll_count','completed_main_cycles','outer_returns','exports','resets'):
            report[key]=sum(v[key] for v in report['builds'].values())
    except Exception as error:
        report['status']='failed';report['failure']=repr(error)
        raise
    finally:
        report['source_sha256_post']={p:sha(p) for p in wrapper_pins}
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','sequences','observations','checks','poll_count','exports','resets')},indent=2))

if __name__=='__main__':main()
