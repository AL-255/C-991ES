#!/usr/bin/env python3
"""Actual root shared-library device bridge proof; no private C rebuild."""
import argparse
import ctypes as C
import datetime as dt
import json
from pathlib import Path
from helpers import ROOT,Configuration,pair_run,sources,pin,require,sha
from c_build_inputs import implementation_inputs
def configure(lib):
    lib.fx_device_browser_create.argtypes=[C.c_uint32];lib.fx_device_browser_create.restype=C.c_void_p
    lib.fx_device_session_create.argtypes=[C.POINTER(Configuration)];lib.fx_device_session_create.restype=C.c_void_p
    for prefix in ('fx_device_browser','fx_device_session'):
        for method in ('destroy','reset','release','take_callback'):
            getattr(lib,prefix+'_'+method).argtypes=[C.c_void_p]
        getattr(lib,prefix+'_destroy').restype=None
    lib.fx_device_browser_submit_pair.argtypes=[C.c_void_p,C.c_uint32,C.c_uint32]
    lib.fx_device_session_submit_pair.argtypes=[C.c_void_p,C.c_uint8,C.c_uint8]
    lib.fx_device_browser_step.argtypes=[C.c_void_p,C.c_uint32]
    lib.fx_device_session_step.argtypes=[C.c_void_p,C.c_void_p,C.c_uint8]
    lib.fx_device_browser_ack_timer.argtypes=[C.c_void_p]
    lib.fx_device_session_ack_timer.argtypes=[C.c_void_p,C.c_void_p]
    lib.fx_device_browser_snapshot.argtypes=[C.c_void_p];lib.fx_device_browser_snapshot.restype=C.c_void_p
    lib.fx_device_session_json.argtypes=[C.c_void_p];lib.fx_device_session_json.restype=C.c_void_p
    lib.fx_device_browser_snapshot_free.argtypes=[C.c_void_p]
    lib.fx_device_session_read_ram.argtypes=[C.c_void_p,C.c_uint16,C.c_void_p,C.c_size_t]

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--library',type=Path,default=ROOT/'analysis/build/simulator/libfx991_device.so')
 p.add_argument('--output',type=Path)
 a=p.parse_args();library=a.library.resolve()
 require(library.is_file(),'Actual root device library missing: '+str(library))
 out=(a.output or ROOT/'analysis/build/device-browser'/('combined-native-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))).resolve()
 require(not (out/'report.json').exists(),'Existing proof refused');out.mkdir(parents=True,exist_ok=True)
 fixture_path=Path(__file__).with_name('inputs.json');fixture=json.loads(fixture_path.read_text())
 inputs=[ROOT/n for n in implementation_inputs(ROOT,sources())]+[Path(__file__),Path(__file__).with_name('helpers.py'),ROOT/'tools/c_build_inputs.py',ROOT/'csrc/CMakeLists.txt',fixture_path]
 before=pin(inputs);artifact_before=sha(library.read_bytes());lib=C.CDLL(str(library));configure(lib)
 rows=[]
 for recipe in fixture['rows']:
  rows.append(pair_run(lib,recipe));print('ROOT',recipe['id'],len(rows[-1]['operations']),flush=True)
 after=pin(inputs);artifact_after=sha(library.read_bytes())
 require(before==after and artifact_before==artifact_after,'Actual shared-library/source drift')
 report={'schema':1,'status':'pass','actual_shared_library':str(library.relative_to(ROOT)),
  'library_sha256_before':artifact_before,'library_sha256_after':artifact_after,
  'source_pins_before':before,'source_pins_after':after,'sequences':len(rows),'observations':rows,
  'paired_snapshots':sum(len(r['operations']) for r in rows),
  'invalid_width_and_pending_guards':sum(r['guards'] for r in rows),
  'scope':'Fresh actual root shared-library C bridge vs separately allocated real device API sessions; not a private O2/O3 rebuild, zero fresh original CPU runs.'}
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'status':'pass','report':str(out/'report.json'),'sha256':sha((out/'report.json').read_bytes()),'paired_snapshots':report['paired_snapshots']},indent=2))
if __name__=='__main__':main()
