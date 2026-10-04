#!/usr/bin/env python3
"""Live original171F4 checks for hand-built typed Mat/Vct expression trees.

This is a test corpus, not a second parser. Every tree supplies its native
raw token bytes and its prepared C calls independently. Importable helper
for tools/test_linalg_dispatch_c.py; no production source changes.
"""
import ctypes as C,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class Number(C.Structure):_fields_=[('bytes',C.c_uint8*10)]
class Complex(C.Structure):_fields_=[('real',Number),('imaginary',Number)]
class Slot(C.Structure):_fields_=[('rows',C.c_uint8),('columns',C.c_uint8),('cells',Number*9)]
class Bank(C.Structure):_fields_=[('slots',Slot*9),('temporary_mask',C.c_uint8)]
class NumericContext(C.Structure):_fields_=[('exact_math',C.c_uint8),('display_mode',C.c_uint8),('digits',C.c_uint8),('cancel_at',C.c_uint32)]
class Context(C.Structure):_fields_=[('calculation_context',C.c_uint8),('numeric',NumericContext)]
class Result(C.Structure):_fields_=[('value',Complex),('firmware_status',C.c_uint8),('cancellation_checks',C.c_uint32)]
ORACLE=r'''
#include "HARNESS_PATH"
unsigned raw_linalg_polls;
int raw_linalg_run(uint64_t limit) {
 raw_linalg_polls=0;
 harness_set_sp(0x8dee);harness_set_lr(0x2fffe);harness_set_pc(0x171f4);
 for(uint64_t i=0;i<limit;++i) {
  if(harness_get_pc()==0x5564){++raw_linalg_polls;ram[0x8e00]=0;}
  int status=harness_run(1,0x2fffe,false);if(status!=103)return status;
 }
 return 103;
}
'''
def reference(token):return ('reference',token)
def scalar(value):return ('scalar',str(value))
def error(header):return ('error',header)
def unary(token,value):return ('unary',token,value)
def binary(token,left,right):return ('binary',token,left,right)
def raw(tree,nested=False):
 tag=tree[0]
 if tag=='reference':return bytes([tree[1]])
 if tag=='scalar':return tree[1].encode()
 if tag=='error':return b'A'
 if tag=='unary':
  token,child=tree[1:];argument=raw(child,True)
  if token in [0x75,0x76,0x77]:return argument+bytes([token])
  if token==0x60:return bytes([token])+argument
  return bytes([token])+argument+b')'
 token,left,right=tree[1:];lhs=raw(left,True);rhs=raw(right,True)
 if token==0x68:return bytes([token])+lhs+b','+rhs+b')'
 result=lhs+bytes([token])+rhs+(b')' if token==0x9f else b'')
 return b'('+result+b')' if nested else result

def run_raw_regressions(library_path,build_dir,root=ROOT):
 root=Path(root);build_dir=Path(build_dir);build_dir.mkdir(parents=True,exist_ok=True)
 lib=C.CDLL(str(library_path));lib.fx_decimal_parse.argtypes=[C.POINTER(Number),C.c_char_p]
 lib.fx_linalg_dispatch_unary.argtypes=[C.POINTER(Result),C.POINTER(Bank),C.POINTER(Complex),C.c_uint8,C.POINTER(Context)]
 lib.fx_linalg_dispatch_binary.argtypes=[C.POINTER(Result),C.POINTER(Bank),C.POINTER(Complex),C.POINTER(Complex),C.c_uint8,C.POINTER(Context)]
 helper=build_dir/'raw-linalg-oracle.c';helper.write_text(ORACLE.replace('HARNESS_PATH',str(root/'tools/nxu8/harness.c')))
 oracle_path=build_dir/'raw-linalg-oracle.so'
 subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(helper),str(root/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(oracle_path)],check=True)
 native=C.CDLL(str(oracle_path));native.harness_init.argtypes=[C.c_void_p,C.c_size_t];native.harness_ram.restype=C.POINTER(C.c_uint8*65536);native.harness_set_reg.argtypes=[C.c_uint,C.c_uint8];native.harness_get_reg.argtypes=[C.c_uint];native.harness_get_reg.restype=C.c_uint8;native.raw_linalg_run.argtypes=[C.c_uint64]
 polls=C.c_uint.in_dll(native,'raw_linalg_polls');rom=(root/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rb=C.create_string_buffer(rom)
 counts={};failures=[];calls=0;examples=[]
 def dec(value):
  n=Number();assert not lib.fx_decimal_parse(C.byref(n),str(value).encode());return bytes(n)
 def operand(real):return Complex.from_buffer_copy(real+bytes([0xee])*10)
 def initial_bank(shape,context):
  b=Bank();b.temporary_mask=0x18 if context==6 else 0
  for identity,slot in enumerate(b.slots):
   slot.rows,slot.columns=(2,2) if shape=='matrix' else (1,3)
   values=[identity+1,identity+2,91,identity+3,identity+5,92,93,94,95] if shape=='matrix' else [identity+1,identity+2,identity+3,91,92,93,94,95,96]
   for i,value in enumerate(values):slot.cells[i]=Number.from_buffer_copy(dec(value))
  return b
 def evaluate(tree,b,ctx):
  tag=tree[0]
  if tag=='reference':
   token=tree[1];kind,identity=(0x60,token-0xc8) if token<=0xcb else (0x90,token-0xcc)
   return 0,operand(bytes([kind|identity])+bytes(9)),0,0
  if tag=='scalar':return 0,operand(dec(tree[1])),0,0
  if tag=='error':return 0,operand(bytes([tree[1]])+bytes(9)),0,0
  if tag=='unary':
   token=tree[1];h,a,s,n=evaluate(tree[2],b,ctx)
   if h or s:return h,a,s,n
   out=Result();h=lib.fx_linalg_dispatch_unary(C.byref(out),C.byref(b),C.byref(a),token,C.byref(ctx));return h,out.value,out.firmware_status,n+out.cancellation_checks
  token=tree[1];h,a,s,n=evaluate(tree[2],b,ctx)
  if h or s:return h,a,s,n
  h,z,s,p=evaluate(tree[3],b,ctx);n+=p
  if h or s:return h,z,s,n
  out=Result();h=lib.fx_linalg_dispatch_binary(C.byref(out),C.byref(b),C.byref(a),C.byref(z),token,C.byref(ctx));return h,out.value,out.firmware_status,n+out.cancellation_checks
 def check(group,actual,expected,detail):
  counts[group]=counts.get(group,0)+1
  if actual!=expected:
   failures.append({'group':group,'actual':actual,'expected':expected,'fixture':detail})
 def one(tree,context,shape,label):
  nonlocal calls
  initial=initial_bank(shape,context);b=Bank.from_buffer_copy(bytes(initial));ctx=Context(context,NumericContext(1,0,0,0));tokens=raw(tree)
  h,result,status,num_polls=evaluate(tree,b,ctx)
  # Final171F4 maps nonzero preparedR2 to a canonical error record before
  # copying only the real10 bytes to caller output. Prepared bridge values
  # deliberately expose the earlier work record instead.
  actual_result=(bytes([0xf0|status])+bytes(9) if status else bytes(result.real))+bytes([0xee])*10
  native.harness_init(rb,len(rom));ram=native.harness_ram().contents
  def put(addr,data):
   for i,v in enumerate(data):ram[addr+i]=v
  for addr,v in [(0x80f9,context),(0x80fc,1),(0x80f5,0xf0),(0x8105,4),(0x8106,1),(0x8121,1)]:ram[addr]=v
  for identity,slot in enumerate(initial.slots):
   put(0x80e0+2*identity,bytes([slot.rows,slot.columns]));put(0x829e+90*identity,bytes(slot.cells))
  for identity in range(10):put(0x8226+10*identity,dec(2))
  # All error leaves in a tree use A; fixtures never combine differentA values.
  def find_error(node):
   if node[0]=='error':return node[1]
   for child in node[2:]:
    if isinstance(child,tuple):
     found=find_error(child)
     if found is not None:return found
   return None
  e=find_error(tree)
  if e is not None:put(0x823a,bytes([e])+bytes(9))
  put(0x8900,bytes([0xee])*20);put(0x8600,tokens+b'\0');put(0x8190,b'\0\x86')
  for i,v in enumerate([0x90,0x81,0,0x89]):native.harness_set_reg(i,v)
  stop=native.raw_linalg_run(30000000);calls+=1
  detail={'label':label,'tokens':tokens.hex(),'context':context,'shape':shape,'tree':tree,'native_cursor':ram[0x8190]+256*ram[0x8191]-0x8600,'initial_bank':bytes(initial).hex()}
  check('raw-host',h,0,detail);check('raw-stop',stop,100,detail);check('raw-record',actual_result.hex(),bytes(ram[0x8900:0x8914]).hex(),detail)
  check('raw-status',status,native.harness_get_reg(0),detail);check('raw-polls',num_polls,polls.value,detail);check('raw-mask',b.temporary_mask,ram[0x8125],detail)
  check('raw-dimensions',bytes(v for slot in b.slots for v in [slot.rows,slot.columns]).hex(),bytes(ram[0x80e0:0x80f2]).hex(),detail)
  check('raw-payload',bytes(v for slot in b.slots for v in bytes(slot.cells)).hex(),bytes(ram[0x829e:0x85c8]).hex(),detail)
  examples.append({'tokens':tokens.hex(),'context':context,'shape':shape,'status':native.harness_get_reg(0),'cursor':detail['native_cursor'],'polls':polls.value,'mask':ram[0x8125]})
 for context in [6,7]:
  for shape,base in [('matrix',0xc8),('vector',0xcc)]:
   names=[reference(base+i) for i in range(4)]
   for name in names:
    for token in [0xc0,0xc1,0x5a,0x5b,0x63,0xb3,0x60,0x75,0x76,0x77]:
     if base==0xcc and token in [0x5a,0x5b]:continue
     one(unary(token,name),context,shape,'raw-named-unary')
   for token in [0x2b,0x2d,0x4e,0x4f,0x9e,0x5e,0x9f,0xbe,0xbf,0x68]:
    for left,right in [(names[0],names[1]),(names[3],names[2]),(names[0],scalar(2)),(scalar(2),names[0])]:one(binary(token,left,right),context,shape,'raw-named-binary')
   # Genuine temporary operands arise from expression evaluation, not fabricated
   # loaded headers. These trees are intentionally small and explicit.
   temporary=binary(0x2b,names[0],names[1])
   for token in [0x2b,0x2d,0x4e,0x4f,0x9e,0x5e,0x9f,0xbe,0xbf,0x68]:
    for left,right in [(temporary,names[2]),(names[2],temporary),(temporary,temporary)]:one(binary(token,left,right),context,shape,'raw-nested-binary')
   for token in [0xc0,0xc1,0x63,0xb3,0x60,0x75,0x76,0x77]:one(unary(token,temporary),context,shape,'raw-nested-unary')
   for header in range(0xf0,0x100):
    for token in [0x2b,0x2d,0x4e,0x4f,0x9e,0x5e,0x9f,0xbe,0xbf,0x68]:
     for left,right in [(names[0],error(header)),(error(header),names[0])]:one(binary(token,left,right),context,shape,'raw-all-error-headers')
   other=reference(0xcc if base==0xc8 else 0xc8)
   for token in [0x2b,0x2d,0x4e,0x4f,0x9e,0x5e]:one(binary(token,names[0],other),context,shape,'raw-mixed-kinds')
   pairs=binary(0x2b,names[0],names[0]);tree=pairs
   for depth in range(1,7):
    tree=binary(0x2b,pairs,tree);one(tree,context,shape,'raw-temporary-pressure-'+str(depth))
 return {'checks':sum(counts.values()),'native_calls':calls,'groups':counts,'failures':failures,'examples':examples,
 'scope':'Original171F4 rawtoken mapping and hand-built typed expression sequences; compare result20, status, allbanks, mask, cumulative timerpolls.',
 'limits':['No general parser is implemented by this test helper; each corpus tree defines its raw bytes and prepared calls.',
 'Vector-tagREF/RREF andrichconjugate/argument remain explicit bridge gaps.',
 'Invalid genuine6x/9x richID>=9 excluded; all16 canonicalF0..FF error headers included.']}
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--library',type=Path,default=ROOT/'analysis/build/linalg_dispatch/dispatch.so');p.add_argument('--build',type=Path,default=Path('/tmp/linalg-raw-live-build'));a=p.parse_args()
 report=run_raw_regressions(a.library,a.build);Path('/tmp/linalg-raw-live-review.json').write_text(json.dumps(report,indent=2))
 print(json.dumps({k:v for k,v in report.items() if k not in ['failures','examples']},indent=2));print(json.dumps(report['failures'][:12],indent=2));raise SystemExit(bool(report['failures']))
