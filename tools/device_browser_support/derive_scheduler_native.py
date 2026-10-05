#!/usr/bin/env python3
"""Fresh actual-C device scheduler trace, no expected data or CPU."""
import argparse, ctypes as C, datetime as dt, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/device_browser_support'))
from combined_native_proof import configure
from helpers import json_snapshot, sources, pin
from c_build_inputs import implementation_inputs
def require(value,message):
    if not value: raise ValueError(message)
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--fixture',type=Path,default=ROOT/'tools/device_browser_support/inputs.json')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();args.library=args.library.resolve();out=(args.output or ROOT/'analysis/build/device-browser'/('scheduler-native-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))).resolve()
    require(not (out/'report.json').exists(),'Existing proof refused')
    out.mkdir(parents=True,exist_ok=True)
    fixture=args.fixture.resolve()
    closure=[ROOT/name for name in implementation_inputs(ROOT,sources())]
    closure += [Path(__file__),fixture,ROOT/'csrc/CMakeLists.txt',ROOT/'tools/c_build_inputs.py',ROOT/'tools/device_browser_support/helpers.py',ROOT/'tools/device_browser_support/combined_native_proof.py']
    before=pin(closure);library_sha=digest(args.library)
    lib=C.CDLL(str(args.library.resolve()));configure(lib)
    rows=[]
    for recipe in json.loads(fixture.read_text())['rows']:
        if recipe['variant']!=0:continue
        require(recipe['keys'],'Empty key recipe: '+recipe['id'])
        for key in recipe['keys']:
            require(all(type(key[field]) is int and 0<=key[field]<=255 for field in ('columns','rows')),'Malformed physical key width')
        handle=lib.fx_device_browser_create(0);require(handle,'Actual allocation')
        operations=[];gestures=[]
        def call(method,*arguments):
            result=getattr(lib,'fx_device_browser_'+method)(handle,*arguments)
            state=json_snapshot(lib,handle)
            operations.append({'operation':method,'args':list(arguments),'result':result,'snapshot':state})
            return state
        def settle(stage):
            timers=0
            for index in range(40):
                state=json_snapshot(lib,handle)
                if state['request']['kind'] or state['status'] in ('request','invalid','reset','export'):
                    return state['status']
                if state['timer_pending']:
                    if stage=='held':return 'timer'
                    if timers==8:return 'timer-limit'
                    state=call('ack_timer');timers+=1
                else:state=call('step',0)
                if stage=='held' and state['event']==5:return 'cycle-return'
                if state['status'] in ('wait','request','invalid','reset','export'):return state['status']
                if stage=='held' and state['timer_pending']:return 'timer'
            return 'step-limit'
        try:
            operations.append({'operation':'create','args':[0],'result':None,'snapshot':json_snapshot(lib,handle)})
            call('reset');boot_hold=settle('held');call('release');boot_release=settle('released')
            require(boot_release=='wait','Ordinary cold boot must reach actual wait')
            call('take_callback')
            for key in recipe['keys']:
                first=len(operations)
                call('submit_pair',key['columns'],key['rows'])
                held=settle('held')
                call('release')
                released=settle('released')
                call('take_callback')
                gestures.append({'input':key,'held_boundary':held,'release_boundary':released,'operations':len(operations)-first,'final':json_snapshot(lib,handle)})
                if released!='wait':break
            if recipe.get('require_all_keys'):
                require(len(gestures)==len(recipe['keys']) and all(g['release_boundary']=='wait' for g in gestures),'Authored supported workflow stopped at a retained request or other boundary: '+recipe['id'])
            rows.append({'id':recipe['id'],'boot_hold_boundary':boot_hold,'boot_release_boundary':boot_release,'operations':operations,'gestures':gestures})
        finally:lib.fx_device_browser_destroy(handle)
    require(rows,'No authored variant0 sequences')
    after=pin(closure);require(before==after and library_sha==digest(args.library),'Actual source/library drift')
    report={'schema':1,'status':'pass','source_pins_before':before,'source_pins_after':after,'library':str(args.library),'library_sha256':library_sha,'rows':rows,'max_phase_steps_per_segment':40,'max_timer_acks_per_released_segment':8,'scope':'Fresh current host-C thin device calls with authored raw pairs; bounded held/released scheduler and explicit semantic-delay acceleration. No CPU, mocked body results, expected outputs or host arithmetic.'}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'pass','sha256':digest(out/'report.json'),'sequences':len(rows),'operations':sum(len(r['operations']) for r in rows),'gestures':sum(len(r['gestures']) for r in rows),'boundaries':sorted({g['held_boundary'] for r in rows for g in r['gestures']})},indent=2))
if __name__=='__main__':main()
