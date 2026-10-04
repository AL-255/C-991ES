#!/usr/bin/env python3
"""Focused simulator JSON/session/LCD comparison with unchanged firmware.

This verifier calls prepared evaluator, variable publication, formatter and
result-only painter entries. It does not claim a full calculator key pipeline.
Input-only recipes are versioned for repeatable release verification.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT/'analysis/native-fixtures/simulator/inputs.json'
DEFAULT_SHA256 = '8578435bfa9f7683e887a2254db31349d2b1d85b9d329f54d2618df83ff005c7'
EXPECTED_CONTROLS = 55

class Render(C.Structure):
    _fields_ = [('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),('memory',C.POINTER(C.c_uint8))]

ABI = r'''#include <stddef.h>
#include "app/fx_simulator_engine.h"
#include "render/fx_render.h"
size_t simulator_test_abi(unsigned i) {
 const size_t v[]={sizeof(size_t),sizeof(unsigned),sizeof(void*),sizeof(fx_render),
 offsetof(fx_render,rom),offsetof(fx_render,rom_size),offsetof(fx_render,memory),
 FX_RENDER_MEMORY_BYTES,FX_FRAMEBUFFER_BYTES,FX_LCD_FRAMEBUFFER,
 FXSIM_COMP,FXSIM_CMPLX,FXSIM_BIN,FXSIM_OCT,FXSIM_DEC,FXSIM_HEX,
 FXSIM_DEG,FXSIM_RAD,FXSIM_GRAD};
 return i<sizeof(v)/sizeof(v[0])?v[i]:(size_t)-1;
}
'''

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pin(paths): return {str(Path(p).resolve()):digest(p) for p in sorted(set(map(Path,paths)))}
def changes(before):
    return {p:{'before':h,'after':digest(p) if Path(p).is_file() else None}
            for p,h in before.items() if not Path(p).is_file() or digest(p)!=h}
def closure(sources,includes):
    result=set()
    for source in sources:
        text=subprocess.check_output(['gcc','-std=c99','-MM',*includes,str(source)],text=True).replace('\\\n',' ')
        result.update(Path(p).resolve() for p in text.partition(':')[2].split())
    return result

def validate(fixture,path,canonical):
    if type(fixture)is not dict or set(fixture)!={'version','sessions','pixel_points','encoder_rejections'} or type(fixture['version'])is not int or fixture['version']!=1:
        raise ValueError('requires exact input-only fixture metadata')
    labels=set();count=0
    if type(fixture['sessions'])is not list or not fixture['sessions']:raise ValueError('requires sessions')
    for session in fixture['sessions']:
        if type(session)is not dict or set(session)!={'label','reset_each','steps'} or type(session['reset_each'])is not bool or type(session['steps'])is not list:
            raise ValueError('invalid session recipe')
        if type(session['label'])is not str or not session['label'] or session['label']in labels:raise ValueError('duplicate/invalid session label')
        labels.add(session['label'])
        step_labels=set()
        for step in session['steps']:
            if type(step)is not dict or set(step)!={'label','text','native_tokens','mode','angle','math'}:raise ValueError('invalid input-only step schema')
            if type(step['label'])is not str or not step['label']or step['label']in step_labels:raise ValueError('invalid/duplicate step label')
            step_labels.add(step['label'])
            if type(step['text'])is not str or not step['text'].isascii() or '\0'in step['text'] or len(step['text'])>4096:raise ValueError('invalid ASCII input')
            if type(step['native_tokens'])is not str or not re.fullmatch(r'(?:[0-9a-f]{2})+',step['native_tokens']) or '00'in [step['native_tokens'][i:i+2] for i in range(0,len(step['native_tokens']),2)]:raise ValueError('invalid authored native input')
            for name,maximum in [('mode',5),('angle',2),('math',1)]:
                if type(step[name])is not int or not 0<=step[name]<=maximum:raise ValueError('invalid '+name)
            count+=1
    if type(fixture['pixel_points'])is not list or any(type(p)is not list or len(p)!=2 or any(type(x)is not int for x in p) or not(0<=p[0]<96 and 0<=p[1]<32) for p in fixture['pixel_points']):raise ValueError('invalid pixel recipes')
    if type(fixture['encoder_rejections'])is not list or any(type(t)is not str or not t.isascii() or '\0'in t for t in fixture['encoder_rejections']):raise ValueError('invalid encoder rejection recipes')
    if canonical and(count!=EXPECTED_CONTROLS or digest(path)!=DEFAULT_SHA256):raise ValueError('default55 input-only workload differs from frozen inventory')
    return count

def library_sources(source_root):
    cmake=source_root/'CMakeLists.txt';text=cmake.read_text()
    result=[]
    for target in ('fx991_firmware','fx991_simulator'):
        match=re.search(r'add_library\(\s*'+target+r'\s+(?:STATIC|SHARED)\s+(.*?)\)',text,re.S)
        if not match:raise ValueError('missing declared CMake target '+target)
        result.extend(source_root/p for p in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',match[1]))
    return list(dict.fromkeys(result))

def prepare(m,step,bank=None,prior=None):
    m.reset()
    for a,v in [(0x80f9,2 if step['mode']>=2 else 0xc4 if step['mode']==1 else 0xc1),
                (0x80fa,(9,9,1,7,9,15)[step['mode']]),(0x80fc,1),(0x80f5,0xf0),
                (0x8100,13),(0x8104,1),(0x8105,4+step['angle']),(0x8106,step['math']),
                (0x8108,1),(0x811f,10),(0x8121,1)]:m.ram[a]=v
    m.word(0x812c,0xa000)
    if bank is not None:
        m.ram[0x8226:0x828a]=bank[:100];m.ram[0x8408:0x846c]=bank[100:]
    if prior is not None:m.ram[0x828a:0x8294]=prior

def bank_from(m):return bytes(m.ram[0x8226:0x828a])+bytes(m.ram[0x8408:0x846c])
def cstring(m,address):return bytes(m.ram[address:address+1024]).split(b'\0',1)[0]
def frame(m):return b''.join(bytes(m.ram[0xf800+16*y:0xf80c+16*y])for y in range(32))

class Original:
    def __init__(self,m):self.m=m;self.calls=0;self.instructions=0
    def call(self,entry):
        self.calls+=1;before=sum(self.m.counts);self.m.call(entry,limit=20000000);self.instructions+=sum(self.m.counts)-before
    def evaluate(self,step,bank,prior):
        m=self.m;prepare(m,step,bank,prior);raw=bytes.fromhex(step['native_tokens'])+b'\0';m.ram[0xa000:0xa000+len(raw)]=raw
        m.word(0x8190,0xa000);m.er(0,0x8190);m.er(2,0x8300);self.call(0x171f4)
        status=m.reg(0);record=bytes(m.ram[0x8300:0x8314]);consumed=(m.word(0x8190)-0xa000)&65535
        if status in (0,34,35,37):
            # Actual leaf calls from F12A's screen1 commit; no fabricated key return.
            if step['mode']==0:m.er(0,0x828a);m.er(2,0x8230);self.call(0x1d142)
            m.reg(0,1);m.er(2,0x8300);self.call(0x522a)
        updated_bank=bank_from(m);updated_prior=bytes(m.ram[0x828a:0x8294])
        expected=dict(status='ok'if status in(0,34,35,37)else'error',native_status=status,
                      real=record[:10].hex(),imag=record[10:].hex(),error_position=consumed,
                      error_position_kind='native-token',width=96,height=32)
        prepare(m,step);m.ram[0xa000:0xa000+len(raw)]=raw;m.ram[0x8300:0x8314]=record
        if status not in(0,34,35,37):
            m.reset();m.reg(0,status);self.call(0x4074);tokens=b''
        else:
            if status==34:m.ram[0x8101 if step['mode']==1 else 0x80ff]=2 if step['mode']==1 else 18
            elif status==35:m.ram[0x8101 if step['mode']==1 else 0x80ff]=1 if step['mode']==1 else 17
            elif status==37:
                if record[10]==0x70:m.ram[0x830a:0x8314]=bytes(10)
                else:m.ram[0x80ff]=20
            if step['mode']>=2:
                m.er(0,0x8300);m.er(2,0x9500);self.call(0x158b8);tokens=cstring(m,0x9500)
            elif step['mode']==0 and status==0:
                m.er(0,0x8300);m.er(2,0x9500);m.word(0x8dee,0);self.call(0xc060);tokens=cstring(m,0x9500)
            else:tokens=None
            # Format and draw calls start from independent fresh presentation RAM.
            prepare(m,step);m.ram[0xa000:0xa000+len(raw)]=raw;m.ram[0x8300:0x8314]=record
            if status==34:m.ram[0x8101 if step['mode']==1 else 0x80ff]=2 if step['mode']==1 else 18
            elif status==35:m.ram[0x8101 if step['mode']==1 else 0x80ff]=1 if step['mode']==1 else 17
            elif status==37:
                if record[10]==0x70:m.ram[0x830a:0x8314]=bytes(10)
                else:m.ram[0x80ff]=20
            m.er(0,0x8300);self.call(0x37bc if step['mode']>=2 else 0xb070)
            if tokens is None:tokens=cstring(m,0x8398 if step['math'] else 0x9838)
            self.call(0x3cfc)
        error_text=None
        if status not in(0,34,35,37):
            table=0x113e+2*(status-1);address=m.rom[table]|m.rom[table+1]<<8
            raw_error=m.rom[address:address+64].split(b'\0',1)[0]
            error_text=''.join(chr(c)if 32<=c<127 else'?'for c in raw_error)
        expected.update(tokens=tokens.hex(),framebuffer=frame(m).hex(),error=error_text)
        return expected,updated_bank,updated_prior

def call_engine(lib,state,step,capacity=32768):
    output=C.create_string_buffer(capacity);text=step['text'].encode('ascii')
    status=lib.fxsim_evaluate(state,text,step['mode'],step['angle'],step['math'],output,capacity)
    if status:return status,None
    return status,json.loads(output.value)

def configure(lib):
    lib.fxsim_create.argtypes=[];lib.fxsim_create.restype=C.c_void_p
    lib.fxsim_destroy.argtypes=[C.c_void_p];lib.fxsim_reset.argtypes=[C.c_void_p]
    lib.fxsim_evaluate.argtypes=[C.c_void_p,C.c_char_p,C.c_uint,C.c_uint,C.c_uint,C.c_void_p,C.c_size_t];lib.fxsim_evaluate.restype=C.c_int
    lib.fxsim_encode_expression_mode.argtypes=[C.c_char_p,C.c_uint,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t),C.POINTER(C.c_size_t)];lib.fxsim_encode_expression_mode.restype=C.c_int
    if hasattr(lib,'simulator_test_abi'):
        lib.simulator_test_abi.argtypes=[C.c_uint];lib.simulator_test_abi.restype=C.c_size_t
    lib.fx_set_pixel.argtypes=[C.POINTER(Render),C.c_int8,C.c_int8];lib.fx_flush_framebuffer.argtypes=[C.POINTER(Render)]

def host_controls(lib):
    state=lib.fxsim_create();good=dict(text='3',mode=0,angle=0,math=1);checks=[]
    try:
        assert call_engine(lib,state,good)[0]==0
        for label,args in [('null-session',(None,b'99',0,0,1)),('null-text',(state,None,0,0,1)),('bad-mode',(state,b'99',6,0,1)),('bad-angle',(state,b'99',0,3,1)),('bad-math',(state,b'99',0,0,2))]:
            output=C.create_string_buffer(b'\xa5'*32);status=lib.fxsim_evaluate(*args,output,32)
            okay=status==-1 and output.raw[0]==0 and call_engine(lib,state,dict(text='Ans',mode=0,angle=0,math=1))[1]['real']=='03000000000000000001';checks.append(dict(label=label,pass_=okay))
        for capacity in(0,1,2,32):
            output=C.create_string_buffer(b'\xa5'*64);status=lib.fxsim_evaluate(state,b'99->A',0,0,1,output,capacity)
            _,answer=call_engine(lib,state,dict(text='Ans',mode=0,angle=0,math=1));_,variable=call_engine(lib,state,dict(text='A',mode=0,angle=0,math=1))
            okay=status==-1 and (not capacity or output.raw[0]==0)and all(v==0xa5 for v in output.raw[max(1,capacity):64])and answer['real']=='03000000000000000001'and variable['real']==bytes(10).hex()
            checks.append(dict(label='transaction-capacity-'+str(capacity),pass_=okay));call_engine(lib,state,good)
        lib.fxsim_reset(state);_,answer=call_engine(lib,state,dict(text='Ans',mode=0,angle=0,math=1));checks.append(dict(label='reset-zero-Ans',pass_=answer['real']==bytes(10).hex()))
    finally:lib.fxsim_destroy(state)
    return checks

def main():
    if sys.flags.optimize:raise RuntimeError('Python assertions must remain enabled')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path);parser.add_argument('--source-root',type=Path)
    parser.add_argument('--release-library',type=Path,default=ROOT/'analysis/build/simulator/libfx991_simulator.so')
    parser.add_argument('--build-dir',type=Path,default=ROOT/'analysis/build/simulator-native-review/proof')
    parser.add_argument('--private-report',type=Path);parser.add_argument('--no-report',action='store_true')
    args=parser.parse_args()
    # This new suite deliberately has no canonical publication path yet.
    if not(args.no_report or args.private_report):parser.error('new private fixture suite requires --no-report or --private-report')
    if args.private_report and args.private_report.resolve().is_relative_to(ROOT/'analysis/c-verification'):parser.error('private proof may not replace a canonical report')
    fixture_path=(args.fixture or DEFAULT_FIXTURE).resolve();fixture=json.loads(fixture_path.read_text());count=validate(fixture,fixture_path,args.fixture is None)
    source_root=(args.source_root or ROOT/'csrc').resolve();build=args.build_dir.resolve();build.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(ROOT/'tools'));from nxu8.machine import Machine
    abi=build/'simulator-abi.c';abi.write_text(ABI);includes=['-I',str(source_root)]
    sources=library_sources(source_root)+[abi];oracle_sources=[ROOT/'tools/nxu8/harness.c',ROOT/'tools/nxu8/vendor/SimU8/core.c']
    inputs=closure(sources,includes)|closure(oracle_sources,[])|{Path(__file__).resolve(),fixture_path,source_root/'CMakeLists.txt',ROOT/'firmware/fx-991es-plus-c-ver4.bin',ROOT/'tools/nxu8/isa.txt'}
    inputs.update((ROOT/'tools/nxu8').rglob('*.py'));pre=pin(inputs);libraries={};commands={}
    for opt in ('O2','O3'):
        target=build/('simulator-'+opt+'.so');command=['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined',*includes,*map(str,sources),'-o',str(target)]
        subprocess.run(command,check=True);lib=C.CDLL(str(target));configure(lib);libraries[opt]=lib;commands[opt]=command
    release=args.release_library.resolve();release_lib=C.CDLL(str(release));configure(release_lib);libraries['Release']=release_lib
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();m=Machine(rom,build/'native');oracle=Original(m)
    artifacts=pin([build/'simulator-O2.so',build/'simulator-O3.so',build/'native/nxu8-harness.so',release]);rows=[];failures=[];abi_expected=[C.sizeof(C.c_size_t),C.sizeof(C.c_uint),C.sizeof(C.c_void_p),C.sizeof(Render),Render.rom.offset,Render.rom_size.offset,Render.memory.offset,65536,384,0xf800,0,1,2,3,4,5,0,1,2]
    for opt,lib in libraries.items():
        if opt=='Release':continue
        actual=[lib.simulator_test_abi(i)for i in range(len(abi_expected))]
        if actual!=abi_expected:failures.append(dict(stage='ABI',optimization=opt,actual=actual,expected=abi_expected))
    states={opt:lib.fxsim_create()for opt,lib in libraries.items()}
    try:
        for session in fixture['sessions']:
            bank=bytes(200);prior=bytes(10)
            for opt,lib in libraries.items():lib.fxsim_reset(states[opt])
            for step in session['steps']:
                if session['reset_each']:
                    bank=bytes(200);prior=bytes(10)
                    for opt,lib in libraries.items():lib.fxsim_reset(states[opt])
                expected,bank,prior=oracle.evaluate(step,bank,prior);variants=[]
                rejected=step['text'] in fixture['encoder_rejections']
                engine_expected=expected if not rejected else dict(status='unsupported',native_status=-1,real=bytes(10).hex(),imag=bytes(10).hex(),tokens='',framebuffer=bytes(384).hex(),width=96,height=32,error_position_kind='ascii-byte',error_position=len(step['text']),error='Unsupported expression text')
                for opt,lib in libraries.items():
                    # C receives only authored ASCII/options/session; never native output.
                    raw=(C.c_uint8*8193)();length=C.c_size_t();error=C.c_size_t()
                    encoded=lib.fxsim_encode_expression_mode(step['text'].encode(),step['mode'],raw,len(raw),C.byref(length),C.byref(error))
                    authored=bytes.fromhex(step['native_tokens'])+b'\0';encoding_okay=(encoded==-1 and length.value==0) if rejected else (encoded==0 and bytes(raw[:length.value])==authored)
                    status,actual=call_engine(lib,states[opt],step);differences={k:dict(expected=v,actual=actual.get(k))for k,v in engine_expected.items()if actual is not None and actual.get(k)!=v}
                    wire_keys={'status','native_status','error','error_position','error_position_kind','real','imag','tokens','framebuffer','width','height','plain'}
                    wire_okay=actual is not None and set(actual)==wire_keys and type(actual['plain'])is str and len(actual['framebuffer'])==768
                    okay=status==0 and encoding_okay and wire_okay and not differences
                    variants.append(dict(optimization=opt,pass_=okay,encoded=bytes(raw[:length.value]).hex(),engine_status=status,actual=actual,differences=differences))
                row=dict(session=session['label'],input=step,native=expected,encoder_admitted=not rejected,expected_engine_contract=engine_expected,variants=variants);rows.append(row)
                if not all(v['pass_']for v in variants):failures.append(row)
                print(json.dumps(dict(index=len(rows),label=step['label'],status='pass'if row not in failures else'fail')),flush=True)
    finally:
        for opt,lib in libraries.items():lib.fxsim_destroy(states[opt])
    host={opt:host_controls(lib)for opt,lib in libraries.items()}
    failures.extend(dict(stage='host',optimization=opt,control=v)for opt,controls in host.items()for v in controls if not v['pass_'])
    rb=(C.c_uint8*len(rom)).from_buffer_copy(rom);pixels=[]
    for opt,lib in libraries.items():
        m.reset();memory=(C.c_uint8*65536)();render=Render(rb,len(rom),memory)
        for x,y in fixture['pixel_points']:
            m.reg(0,x);m.reg(1,y);oracle.call(0x3b88);lib.fx_set_pixel(C.byref(render),x,y)
        oracle.call(0x3cfc);lib.fx_flush_framebuffer(C.byref(render));actual=b''.join(bytes(memory[0xf800+16*y:0xf80c+16*y])for y in range(32));expected=frame(m);formula=bytearray(384)
        for x,y in fixture['pixel_points']:formula[y*12+x//8]|=0x80>>(x&7)
        okay=actual==expected==bytes(formula);pixels.append(dict(optimization=opt,pass_=okay,packed_framebuffer=actual.hex()))
        if not okay:failures.append(dict(stage='pixel-order',optimization=opt))
    rejection=[]
    for opt,lib in libraries.items():
        state=lib.fxsim_create()
        try:
            for text in fixture['encoder_rejections']:
                status,actual=call_engine(lib,state,dict(text=text,mode=0,angle=0,math=1));okay=status==0 and actual['status']=='unsupported'and actual['error_position_kind']=='ascii-byte'
                rejection.append(dict(optimization=opt,text=text,pass_=okay,actual=actual))
                if not okay:failures.append(dict(stage='encoder-rejection',optimization=opt,text=text))
        finally:lib.fxsim_destroy(state)
    drift=changes(pre);artifact_drift=changes(artifacts)
    report=dict(status='pass'if not failures and not drift and not artifact_drift else'fail',suite='simulator_native',expression_controls=count,backend_comparisons=len(libraries)*len(rows),native_backend_parity_comparisons=len(libraries)*sum(r['encoder_admitted']for r in rows),explicit_encoder_admission_boundaries=sum(not r['encoder_admitted']for r in rows),native_calls=oracle.calls,native_instructions=oracle.instructions,compiled_ABI_checks_per_build={'O2':len(abi_expected),'O3':len(abi_expected),'Release':0},LCD_native_bytes_compared_per_build=384*sum(r['encoder_admitted']for r in rows)+384,host_controls=host,pixel_controls=pixels,encoder_rejections=rejection,failures=failures,source_changes=drift,artifact_changes=artifact_drift,before_execution_inputs_sha256=pre,compiled_artifacts_before_sha256=artifacts,compile_commands=commands,rows=rows,scope='Prepared171F4 plus actualF12A Ans/PreAns leaf calls, isolatedC060/base formatting, result-onlyB070/37BC/4074 painting and3CFC transfer. IndependentASCII/nativeinput pairs; no native output feeds C. This is not full key/UI pipeline parity.',full_firmware_complete=False)
    output=args.private_report or build/'report.json';output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k]for k in ('status','expression_controls','backend_comparisons','native_calls','native_instructions','source_changes','artifact_changes')}),flush=True)
    return 0 if report['status']=='pass'else 1

if __name__=='__main__':sys.exit(main())
