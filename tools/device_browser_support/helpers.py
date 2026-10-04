"""Shared test-only actual device API comparisons; no CLI or CPU oracle."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
FIXTURE=Path(__file__).with_name("inputs.json")
BRIDGE="csrc/app/fx_device_browser.c"
def require(v,m):
    if not v:raise ValueError(m)

def sha(b):return hashlib.sha256(b).hexdigest()

def sources():
    cmake=(ROOT/'csrc/CMakeLists.txt').read_text()
    target=re.search(r'add_library\(fx991_firmware\s+STATIC\s+(.*?)\)',cmake,re.S)
    require(target is not None,'Missing authoritative C target')
    names=re.sub(r'#[^\n]*','',target.group(1)).split()
    return ['csrc/'+p for p in names]+['csrc/app/fx_device_session.c','csrc/app/fx_device_protocol.c',BRIDGE]

def pin(paths):return {str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in sorted(set(paths))}

class Configuration(C.Structure):
    _fields_=[('initial_ram',C.c_void_p),('initial_ram_bytes',C.c_size_t),('variant',C.c_uint8)]

def json_snapshot(lib,handle,bridge=True):
    function=lib.fx_device_browser_snapshot if bridge else lib.fx_device_session_json
    pointer=function(handle);require(pointer,'Snapshot unexpectedly unavailable')
    value=C.string_at(pointer).decode()
    lib.fx_device_browser_snapshot_free(pointer)
    return json.loads(value)

def ram(lib,h):
    output=(C.c_uint8*65536)()
    require(lib.fx_device_session_read_ram(h,0,output,65536)==0,'Read-only RAM failed')
    return bytes(output)

def pair_run(lib,recipe):
    config=Configuration(None,0,recipe['variant'])
    candidate=lib.fx_device_browser_create(recipe['variant'])
    reference=lib.fx_device_session_create(C.byref(config))
    require(candidate and reference,'Cold creation failed')
    ops=[];guardcount=0
    def observe(op,args,result):
        actual=json_snapshot(lib,candidate);expected=json_snapshot(lib,reference,False)
        require(actual==expected,'JSON device comparison differs '+op)
        actualram=ram(lib,candidate);require(actualram==ram(lib,reference),'Full device RAM/MMIO differs '+op)
        require(actual['width']==96 and actual['height']==32 and len(bytes.fromhex(actual['framebuffer']))==384,'Framebuffer shape')
        require(json_snapshot(lib,candidate)==actual and ram(lib,candidate)==actualram,'Snapshot mutated session')
        ops.append({'operation':op,'args':args,'result':result,'snapshot':actual,'ram_sha256':sha(actualram)})
        return actual
    def call(op,*args):
        if op=='step':a=lib.fx_device_browser_step(candidate,*args);b=lib.fx_device_session_step(reference,None,*args)
        elif op=='ack_timer':a=lib.fx_device_browser_ack_timer(candidate);b=lib.fx_device_session_ack_timer(reference,None)
        else:a=getattr(lib,'fx_device_browser_'+op)(candidate,*args);b=getattr(lib,'fx_device_session_'+op)(reference,*args)
        require(a==b,'Return differs '+op);return a,observe(op,list(args),a)
    try:
        observe('create',[recipe['variant']],None)
        before=ram(lib,candidate);snapshot=json_snapshot(lib,candidate)
        for width in (256,65536,0xffffffff):
            require(lib.fx_device_browser_submit_pair(candidate,width,1)==-1,'Wide columns truncated')
            require(lib.fx_device_browser_submit_pair(candidate,1,width)==-1,'Wide rows truncated')
            require(ram(lib,candidate)==before and json_snapshot(lib,candidate)==snapshot,'Rejected widths mutated session')
            guardcount+=2
        for flag in (2,255,256,65536,0xffffffff):
            require(lib.fx_device_browser_step(candidate,flag)==-1 and ram(lib,candidate)==before and json_snapshot(lib,candidate)==snapshot,'Invalid timer flag mutated')
            guardcount+=1
        require(lib.fx_device_browser_ack_timer(candidate)==-1 and ram(lib,candidate)==before and json_snapshot(lib,candidate)==snapshot,'Nonpending timer ack mutated')
        guardcount+=1
        call('reset')
        for index in range(40):
            status,state=call('step',0)
            if state['event']==5:break
            require(status not in (-1,4),'Cold boot reaches unavailable controller')
        else:raise ValueError('Bounded explicit boot steps exhausted')
        call('release')
        status,state=call('step',0)
        require(status==0,'First actual key wait not reached')
        call('take_callback')
        for key in recipe['keys']:
            call('submit_pair',key['columns'],key['rows'])
            for index in range(40):
                status,state=call('step',0)
                if state['event']==5 or status in (0,2,3,4,5):break
            else:raise ValueError('Bounded explicit press steps exhausted')
            call('release')
            for index in range(40):
                if state['timer_pending']:status,state=call('ack_timer')
                else:status,state=call('step',0)
                if status in (0,4,5):break
            else:raise ValueError('Bounded explicit release steps exhausted')
            require(status!=4,'Authored ordinary key sequence retained a named gap: '+recipe['id'])
            call('take_callback')
        return {'id':recipe['id'],'recipe':recipe,'operations':ops,'guards':guardcount,'final':json_snapshot(lib,candidate)}
    finally:
        lib.fx_device_browser_destroy(candidate);lib.fx_device_session_destroy(reference)
