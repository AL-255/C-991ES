#!/usr/bin/env python3
"""Actual combined root dist WASM device exports against saved real root-C output."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
from helpers import ROOT,require,pin
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--native-report',type=Path,required=True)
 p.add_argument('--dist',type=Path,default=ROOT/'simulator/dist')
 p.add_argument('--build-report',type=Path,default=ROOT/'analysis/build/simulator-wasm/build-report.json')
 p.add_argument('--output',type=Path);a=p.parse_args()
 native_path=a.native_report.resolve();dist=a.dist.resolve();buildpath=a.build_report.resolve()
 native=json.loads(native_path.read_text());build=json.loads(buildpath.read_text())
 require(native['status']=='pass','Native reference not successful')
 for path,wanted in native['source_pins_after'].items():require(sha(ROOT/path)==wanted,'Native reference source drift '+path)
 require(sha(ROOT/native['actual_shared_library'])==native['library_sha256_after'],'Native root library drift')
 for name,item in build['artifacts'].items():require(sha(dist/name)==item['sha256'],'Actual combined dist differs '+name)
 for path,wanted in build['input_pins'].items():require(sha(ROOT/path)==wanted,'Actual combined builder input drift '+path)
 out=(a.output or ROOT/'analysis/build/device-browser'/('combined-wasm-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))).resolve()
 require(not (out/'report.json').exists(),'Existing proof refused');out.mkdir(parents=True,exist_ok=True)
 tmp=out/'tmp';tmp.mkdir(exist_ok=True);env=dict(os.environ,TMPDIR=str(tmp))
 sdk=ROOT/'analysis/build/emsdk';node=next(iter(sorted(sdk.glob('node/*/bin/node'))))
 helper=Path(__file__).with_name('collect_combined_wasm.mjs')
 inputs=[*[ROOT/n for n in build['input_pins']],native_path,buildpath,Path(__file__),helper,Path(__file__).with_name('helpers.py')]
 before=pin(inputs);artifacts_before={n:sha(dist/n) for n in build['artifacts']}
 inputs_only={'sequences':[{'id':r['id'],'variant':r['recipe']['variant'],'operations':[{'operation':o['operation'],'args':o['args']} for o in r['operations']]} for r in native['observations']]}
 inputpath=out/'input-only-operations.json';inputpath.write_text(json.dumps(inputs_only,indent=2)+'\n')
 run=subprocess.run([str(node),str(helper),str(inputpath),str(out/'observations.json'),str(dist/'fx991sim.js')],env=env,capture_output=True,text=True)
 (out/'execution.json').write_text(json.dumps({'exit':run.returncode,'stdout':run.stdout,'stderr':run.stderr,'node_sha256':sha(node)},indent=2)+'\n');run.check_returncode()
 actual=json.loads((out/'observations.json').read_text());require(actual['status']=='pass','Actual combined exports failed')
 require(len(actual['sequences'])==len(native['observations'])==24,'Actual combined sequence count')
 for expected,row in zip(native['observations'],actual['sequences']):
  require(expected['id']==row['id'] and [{k:v for k,v in o.items() if k!='ram_sha256'} for o in expected['operations']]==row['operations'],'Actual combined WASM differs '+expected['id'])
 after=pin(inputs);artifacts_after={n:sha(dist/n) for n in build['artifacts']}
 require(before==after and artifacts_before==artifacts_after,'Actual combined source/artifact drift')
 report={'schema':1,'status':'pass','native_report':str(native_path.relative_to(ROOT)),'native_report_sha256':sha(native_path),
  'build_report':str(buildpath.relative_to(ROOT)),'build_report_sha256':sha(buildpath),
  'source_pins_before':before,'source_pins_after':after,'artifacts_before':artifacts_before,'artifacts_after':artifacts_after,
  'observations_sha256':sha(out/'observations.json'),'input_only_transcript_sha256':sha(inputpath),
  'sequences':24,'actual_wasm_state_comparisons':sum(len(r['operations']) for r in actual['sequences']),'wasm_guards':actual['guards'],
  'scope':'Actual final combined evaluator+device module exports, not a private bridge-only rebuild; saved fresh actual root shared-library C reference, zero fresh original CPU executions, no native expected state passed into engine.'}
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'status':'pass','report':str(out/'report.json'),'sha256':sha(out/'report.json'),'comparisons':report['actual_wasm_state_comparisons']},indent=2))
if __name__=='__main__':main()
