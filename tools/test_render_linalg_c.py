#!/usr/bin/env python3
"""Prepared matrix/vector grid display versus unchanged native ROM.

The implementation reads font/table data and does not execute instructions.
Only this independent test oracle executes the original image.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import json,random,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from c_verification import write_report
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--random-cases',type=int,default=2500)
parser.add_argument('--no-report',action='store_true')
args=parser.parse_args()
BUILD=ROOT/'analysis/build/render_linalg';BUILD.mkdir(parents=True,exist_ok=True)
SOURCES=['csrc/render/fx_result_linalg.c','csrc/render/fx_render.c',
 'csrc/render/fx_render_context.c','csrc/render/fx_render_memory.c',
 'csrc/render/fx_result_special.c','csrc/render/fx_result_verify.c','csrc/render/fx_result_format_state.c',
 'csrc/format/fx_format_budget.c','csrc/format/fx_format_base.c',
 'csrc/format/fx_format.c','csrc/numeric/fx_numeric.c','csrc/numeric/fx_surd_components.c','csrc/numeric/fx_raw_decimal_parts.c','csrc/numeric/fx_raw_decimal_divide.c','csrc/numeric/fx_raw_decimal_multiply_add.c']
HEADERS=[x[:-2]+'.h' for x in SOURCES]+['csrc/linalg/fx_linalg.h']
library=BUILD/'linalg-display.so'
subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
 *(str(ROOT/x) for x in SOURCES),'-o',str(library)],check=True)
class Number(C.Structure):_fields_=[('bytes',C.c_uint8*10)]
class Value(C.Structure):_fields_=[('reference',Number),('rows',C.c_uint8),('columns',C.c_uint8),('cells',Number*9)]
class Rational(C.Structure):_fields_=[('numerator',C.c_int64),('denominator',C.c_uint64),('flags',C.c_uint8)]
class Render(C.Structure):_fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),('memory',C.POINTER(C.c_uint8))]
class FormatOptions(C.Structure):
 _fields_=[(name,C.c_uint8) for name in ['selection','math_output','mixed_fraction',
  'display_mode','digits','decimal_dot','format_context','recurring_style']]
class FormatResult(C.Structure):
 _fields_=[('length',C.c_size_t),('kind',C.c_uint8),('recognized',C.c_uint8)]
rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rbuf=(C.c_uint8*len(rom)).from_buffer_copy(rom);mem=(C.c_uint8*65536)();r=Render(rbuf,len(rom),mem)
lib=C.CDLL(str(library));m=Machine(rom,BUILD/'oracle')
lib.fx_display_linalg_cell.argtypes=[C.POINTER(Render),C.POINTER(Number),C.c_uint8,C.c_uint8,C.c_uint8]
lib.fx_display_linalg_grid.argtypes=[C.POINTER(Render),C.POINTER(Value),C.c_uint8,C.c_uint8]
lib.fx_display_linalg_caption.argtypes=[C.POINTER(Render),C.c_uint8]
lib.fx_display_linalg_border.argtypes=[C.POINTER(Render),C.c_uint8,C.c_uint8]
lib.fx_display_linalg_value.argtypes=[C.POINTER(Render),C.POINTER(Value),C.c_uint8,C.c_uint8,C.c_uint8]
lib.fx_linalg_move_selection.argtypes=[C.c_uint8,C.c_uint8,C.c_uint8,C.POINTER(C.c_uint8),C.POINTER(C.c_uint8)]
lib.fx_linalg_selection_event.argtypes=[C.POINTER(Render),C.c_uint8,C.c_uint8,C.c_uint8]
lib.fx_decimal_parse.argtypes=[C.POINTER(Number),C.c_char_p]
lib.fx_rational_encode.argtypes=[C.POINTER(Number),C.POINTER(Rational)]
lib.fx_surd_pack.argtypes=[C.POINTER(Number),C.POINTER(Number)]
lib.fx_format_default_options.restype=FormatOptions
lib.fx_format_number.argtypes=[C.POINTER(Number),C.POINTER(FormatOptions),
 C.POINTER(C.c_uint8),C.c_size_t,C.POINTER(FormatResult)]
lib.fx_display_has_natural_result.argtypes=[C.POINTER(Render)]
rng=random.Random(0x3ec0);counts={};fail=[];boundaries=[];checks=0;native_calls=0
def decimal(s):
 n=Number();assert lib.fx_decimal_parse(C.byref(n),str(s).encode())==0;return n
def ratio(a,b):
 n=Number();assert lib.fx_rational_encode(C.byref(n),C.byref(Rational(a,b,0)))==0;return n
def surd(v):
 n=Number();p=(Number*6)(*(decimal(x) for x in v));assert lib.fx_surd_pack(C.byref(n),p)==0;return n
def reset():
 m.reset();C.memset(mem,0,len(mem))
 for a,b in [(0x8121,1),(0x80f9,6),(0x80fc,19),(0x8106,1),(0x8104,1)]:mem[a]=m.ram[a]=b
 for a in list(range(0x87d0,0x8950))+list(range(0xf800,0xfa00)):
  mem[a]=m.ram[a]=rng.randrange(256)
def put(a,b):
 for i,x in enumerate(b):m.ram[a+i]=mem[a+i]=x
def equal(g,label):
 global checks,native_calls
 native_calls+=1
 counts[g]=counts.get(g,0)+1
 for a,n in [(0x8100,0x60),(0x87d0,384),(0xf800,512),(0xf031,1)]:
  checks+=1
  actual=bytes(mem[a:a+n]);expected=bytes(m.ram[a:a+n])
  if actual!=expected and len(fail)<20:
   i=next(i for i,(x,y) in enumerate(zip(actual,expected)) if x!=y)
   fail.append([g,label,hex(a+i),actual[i],expected[i]])
def selected_format(number):
 options=lib.fx_format_default_options()
 options.selection=mem[0x8100]
 options.math_output=lib.fx_display_has_natural_result(C.byref(r))
 options.mixed_fraction=mem[0x8107]
 options.display_mode=mem[0x8102]
 options.digits=mem[0x8103]
 options.decimal_dot=mem[0x8104]
 tokens=(C.c_uint8*512)();formatted=FormatResult()
 status=lib.fx_format_number(C.byref(number),C.byref(options),tokens,len(tokens),C.byref(formatted))
 return status,formatted,bytes(tokens[:formatted.length])
def native_view_stack_witness(expected_length,expected_return):
 """Observe37BC's real saved-register overwrite without patching the ROM."""
 m.er(14,0xabcd);m.lib.harness_set_sp(0x8dee)
 m.lib.harness_set_lr(0x2fffe);m.lib.harness_set_pc(0xece8)
 def run_to(pc):
  status=m.lib.harness_run(1000000,pc,False)
  if status!=100:raise RuntimeError(f'Native view witness status={status}, pc={m.lib.harness_get_pc():#x}')
 run_to(0x37c2)
 frame=m.er(14);before=bytes(m.ram[frame:frame+10])
 run_to(0x37ee)
 buffer=bytes(m.ram[frame-26:frame+64]);length=buffer.index(0)
 after=bytes(m.ram[frame:frame+10])
 run_to(0x382c);restored=m.er(14)
 run_to(0x2fffe)
 global checks
 checks+=5
 if length!=expected_length:fail.append(['native-stack-witness-length',length,expected_length])
 if before[:2]!=bytes.fromhex('cdab'):fail.append(['native-stack-witness-incoming-fp',before.hex()])
 if before==after:fail.append(['native-stack-witness-no-overwrite',length])
 if restored!=int.from_bytes(after[:2],'little'):fail.append(['native-stack-witness-restored-fp',restored,after.hex()])
 if m.reg(0)!=expected_return:fail.append(['native-stack-witness-return',m.reg(0),expected_return])
 return {'frame':hex(frame),'native_text_length':length,'native_tokens':buffer[:length].hex(),
  'saved_registers_before':before.hex(),'saved_registers_after':after.hex(),
  'restored_er14':hex(restored),'native_return':m.reg(0)}
def check_view(value,slot,sr,sc,label,stack_witness=None):
 global checks,native_calls
 number=value.cells[3*(sr-1)+sc-1]
 format_status,formatted,tokens=selected_format(number)
 checks+=1
 if format_status!=0:fail.append(['view-preflight-format',label,format_status])
 before=bytes(mem)
 # Refusal and its entire-RAM immutability are observed before the oracle
 # runs. A sentinel return alone cannot prove that native stack ABI held.
 status=lib.fx_display_linalg_value(C.byref(r),C.byref(value),slot,sr,sc)
 oversized=format_status==0 and formatted.length>=26
 checks+=1
 if oversized:
  checks+=2
  if status!=-1:fail.append(['view-stack-boundary-status',label,status,formatted.length])
  if bytes(mem)!=before:fail.append(['view-stack-boundary-mutated',label])
 elif status!=1:fail.append(['view-unexpected-refusal',label,status,formatted.length])
 witness=None;native_error=None
 try:
  if stack_witness:witness=native_view_stack_witness(*stack_witness)
  else:m.call(0xece8)
 except RuntimeError as error:native_error=str(error)
 if oversized:
  native_calls+=1;counts['view-stack-boundary']=counts.get('view-stack-boundary',0)+1
  boundary={'case':label,'slot':slot,'dimensions':[value.rows,value.columns],
   'selection':[sr,sc],'record':bytes(number).hex(),'serialized_length':formatted.length,
   'portable_status':status,'native_outcome':'fault' if native_error else 'sentinel',
   'pc':hex(m.lib.harness_get_pc()),'native_return':m.reg(0)}
  if native_error:boundary['native_error']=native_error
  if witness:
   boundary['saved_register_witness']=witness
   checks+=2
   if witness['native_text_length']!=formatted.length:fail.append(['view-stack-witness-format-length',label,formatted.length,witness['native_text_length']])
   if witness['native_tokens']!=tokens.hex():fail.append(['view-stack-witness-format-tokens',label])
  boundaries.append(boundary)
  if stack_witness and native_error:fail.append(['native-stack-witness-fault',label,native_error])
  return
 if native_error:
  native_calls+=1
  fail.append(['view-unexpected-native-fault',label,formatted.length,native_error]);return
 checks+=1
 if bytes(value.cells)!=bytes(m.ram[0x829e+90*slot:0x829e+90*(slot+1)]):fail.append(['view-backing-mutated',label])
 equal('view',[label,slot,value.rows,value.columns,sr,sc,bytes(number).hex()])
pool=[decimal(x) for x in [-999999,-8,0,1,12,9876,'0.000123456789','1e-99','-9.99999999999999e99','1e-3','1e-2','0.5']]+[ratio(1,3),ratio(-7,9),surd([1,2,1,0,1,1]),surd([-1,3,1,1,2,3])]
for header in [0xf0,0xf1,0xf3,0xf8,0xff]:pool.append(Number.from_buffer_copy(bytes([header])+bytes(9)))
pool+=[Number.from_buffer_copy(bytes([n.bytes[0]|0x40])+bytes(n)[1:]) for n in pool[:5]+pool[12:14]]
for i in range(args.random_cases):
 reset();n=rng.choice(pool) if i%19 else None;row=rng.randrange(1,4);col=rng.randrange(1,4);selected=i%2
 for a,b in [(0x8104,i%2),(0x8127,(i//2)%2),(0x80ff,20 if i%3==0 else 0),(0x8120,i%5),(0x8121,i%2)]:mem[a]=m.ram[a]=b
 if n:put(0x8500,bytes(n))
 m.er(0,0x8500 if n else 0);m.er(2,row+256*col);m.word(0x8dee,selected);m.call(0x3ec0)
 assert lib.fx_display_linalg_cell(C.byref(r),C.byref(n) if n else None,row,col,selected)==1
 checks+=1
 if n:
  checks+=1
  if bytes(n)!=bytes(m.ram[0x8500:0x850a]):fail.append(['cell-source-mutated',i])
 equal('cell',[i,bytes(n).hex() if n else None,row,col,selected])
for rows in range(1,4):
 for cols in range(1,4):
  for sr in range(4):
   for sc in range(4):
    reset();v=Value();v.rows=rows;v.columns=cols
    for i in range(9):v.cells[i]=rng.choice(pool);put(0x8500+10*i,bytes(v.cells[i]));m.word(0x8600+2*i,0x8500+10*i)
    m.er(0,rows+256*cols);m.er(2,sr+256*sc);m.word(0x8dee,0x8600);m.call(0x3e74)
    assert lib.fx_display_linalg_grid(C.byref(r),C.byref(v),sr,sc)==1
    equal('grid',[rows,cols,sr,sc])
for slot in range(4):
 reset();m.reg(0,slot);m.call(0xeeb4);assert lib.fx_display_linalg_caption(C.byref(r),slot)==1;equal('caption',slot)
for rows in range(1,4):
 for cols in range(1,4):
  reset();m.reg(0,rows);m.reg(1,cols);m.call(0xeeda);assert lib.fx_display_linalg_border(C.byref(r),rows,cols)==1;equal('border',[rows,cols])
for i in range(args.random_cases//2):
 reset();v=Value();v.rows=rng.randrange(1,4);v.columns=rng.randrange(1,4);slot=i%4;sr=rng.randrange(1,v.rows+1);sc=rng.randrange(1,v.columns+1)
 for a,b in [(0x80f9,6+i%2),(0x80fc,19+i%2),(0x8100,i%256),(0x8102,[0,4,8,9][i%4]),(0x8103,i%10),(0x8104,i%2),(0x8121,i%2),(0x8120,i%5),(0x811d,sr),(0x811e,sc)]:mem[a]=m.ram[a]=b
 for j in range(9):
  # Full selected-value formatting is defined here for ordinary scalar
  # records; grid-only cases above separately cover foreign6x spelling.
  v.cells[j]=rng.choice([n for n in pool if n.bytes[0]&0xf0 not in [0x60,0x90]])
  put(0x829e+90*slot+10*j,bytes(v.cells[j]))
 m.word(0x80e0+2*slot,v.rows+256*v.columns);m.reg(0,slot)
 check_view(v,slot,sr,sc,i)
# Both oversized native calls reach the sentinel. Length26 overwrites only
# savedER14's low byte; length34 also overwrites return data and returnsR0=0.
stack_fixtures=[
 ('length26','05054277289903229206',26,1,
  {0x80f9:7,0x80fc:20,0x8100:31,0x8101:166,0x8102:9,0x8103:3,
   0x8104:123,0x8106:1,0x8107:1,0x8120:36,0x8121:1,0x8130:52}),
 ('length34','06199811880866368406',34,0,
  {0x80f9:6,0x80fc:20,0x8100:95,0x8101:76,0x8102:4,0x8103:0,
   0x8104:213,0x8106:0,0x8107:1,0x8120:186,0x8121:1,0x8130:101})]
for label,record,length,native_return,settings in stack_fixtures:
 reset();v=Value();v.rows=v.columns=1;v.cells[0]=Number.from_buffer_copy(bytes.fromhex(record))
 for address,byte in settings.items():mem[address]=m.ram[address]=byte
 mem[0x811d]=m.ram[0x811d]=mem[0x811e]=m.ram[0x811e]=1
 put(0x829e,bytes(v.cells));m.word(0x80e0,0x0101);m.reg(0,0)
 check_view(v,0,1,1,label,(length,native_return))
for rows in range(1,4):
 for cols in range(1,4):
  for sr in range(1,rows+1):
   for sc in range(1,cols+1):
    for key in range(256):
     m.reset();C.memset(mem,0,len(mem));mem[0x811d]=m.ram[0x811d]=sr;mem[0x811e]=m.ram[0x811e]=sc
     for a in [0x8100,0x8101,0x8130]:mem[a]=m.ram[a]=0xb5
     m.word(0x80e0,rows+256*cols);m.reg(0,0);m.reg(1,key);m.call(0xedec)
     ar=C.c_uint8(sr);ac=C.c_uint8(sc);s=lib.fx_linalg_move_selection(rows,cols,key,C.byref(ar),C.byref(ac));counts['move']=counts.get('move',0)+1
     if [s,ar.value,ac.value]!=[m.reg(0),m.ram[0x811d],m.ram[0x811e]]:fail.append(['move',rows,cols,sr,sc,key,[s,ar.value,ac.value],[m.reg(0),m.ram[0x811d],m.ram[0x811e]]])
     checks+=1
     ev=lib.fx_linalg_selection_event(C.byref(r),rows,cols,key);checks+=1
     if ev!=m.reg(0):fail.append(['event-status',rows,cols,sr,sc,key,ev,m.reg(0)])
     equal('navigation-event',[rows,cols,sr,sc,key])
result={'checks':checks,'native_calls':native_calls,'groups':counts,'failures':fail,
 'scope':'Prepared matrix/vector caption, brackets, active-cell grid, selected-value line/cache and cursor navigation with selection reset.',
 'native_entries':['3E74','3EC0','ECE8-current-view','EDEC','EEB4','EEDA','1D7C6-nonnull'],
 'oracle_context':'Unchanged original ROM/CPU, fixed-stride nine-cell slots, settings and RAM/LCD maps prepared explicitly. All512LCDbytes,384RAMframebufferbytes,8100..815F andF031 compared; record/backing bytes preserved.',
 'native_stack_boundaries':boundaries,
 'limits':['Physical key scanning, editor mutation/key dispatch and user-slot switching are excluded.',
 'Foreign rich6x/9x scalar cell records produce ERROR in the tiny grid, but the full selected-value API returns-1; native scalar-reference fallback is outside this typed ABI.',
 'The selected full-value line inherits untranslated small/extended exponent contexts from the shared special-result controller; cell grid supports both.',
 'Native selected-value text uses a26-byte CPU-stack buffer; portable serialization length>=26 returns-1 without changingRAM, classified before the oracle runs. Oversized native calls may fault or reach the sentinel with saved-register corruption; both outcomes are recorded separately.',
 'Canonical scalar records and dimensions1..3 only. Stack/numeric scratch contents outside the exposed settings and framebuffers are excluded.']}
if not fail and not args.no_report:result=write_report('analysis/c-verification/render_linalg.json',result,SOURCES+HEADERS+['tools/c_verification.py'],'tools/test_render_linalg_c.py')
print(json.dumps({k:v for k,v in result.items() if k!='tested_inputs_sha256'},indent=2));sys.exit(bool(fail))
