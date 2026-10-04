import ctypes as C,gzip,hashlib,json,subprocess,sys
from decimal import Decimal
from pathlib import Path

def observe(ROOT,D,fixture):
 ROOT=Path(ROOT).resolve();D=Path(D).resolve();D.mkdir(parents=True,exist_ok=True)
 sys.path.insert(0,str(ROOT/'tools'));from nxu8.machine import Machine
 fixture=Path(fixture).resolve();data=json.loads(fixture.read_text())
 source=ROOT/'tools/finite_series_storage_support/native_v2.c'
 files=[source,source.with_name('native.c'),Path(__file__),fixture,ROOT/'analysis/disassembly/complete.asm',ROOT/'firmware/fx-991es-plus-c-ver4.bin',ROOT/'tools/nxu8/harness.c',ROOT/'tools/nxu8/machine.py',ROOT/'tools/nxu8/isa.txt',ROOT/'tools/nxu8/vendor/SimU8/core.c',*list((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h'))]
 sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();pins={str(p):sha(p)for p in files}
 subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(source),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(D/'oracle.so')],check=True)
 rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();m=Machine(rom,D/'baseline');nl=C.CDLL(str(D/'oracle.so'))
 for n in ('harness_init','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_set_pc','harness_get_pc','harness_ram','harness_run'):
  getattr(nl,n).argtypes=getattr(m.lib,n).argtypes;getattr(nl,n).restype=getattr(m.lib,n).restype
 m.lib=nl;m.ram=nl.harness_ram().contents
 for name,size,target in [('execution_counts',0x18000,'counts'),('rom_read_counts',0x30000,'rom_reads'),('ram_write_counts',65536,'ram_writes')]:setattr(m,target,(C.c_uint64*size).in_dll(nl,name))
 nl.series_observe_to.argtypes=[C.c_uint64,C.c_uint32];nl.series_lr.restype=C.c_uint32
 class Write(C.Structure):_fields_=[('pc',C.c_uint32),('address',C.c_uint16),('sp',C.c_uint16),('size',C.c_uint8),('value',C.c_uint64)]
 class Sample(C.Structure):_fields_=[('caller',C.c_uint32),('cursor',C.c_uint16),('sink',C.c_uint16),('working',C.c_uint16),('mode',C.c_uint8),('r6',C.c_uint8),('status',C.c_uint8),('delimiter',C.c_uint8),('psw',C.c_uint8),('x',C.c_uint8*20),('value',C.c_uint8*20)]
 class Stage(C.Structure):_fields_=[('pc',C.c_uint32),('base',C.c_uint16),('working',C.c_uint16),('cursor',C.c_uint16),('status',C.c_uint8),('condition',C.c_uint8),('mode',C.c_uint8),('psw',C.c_uint8),('records',C.c_uint8*40),('value',C.c_uint8*20),('x',C.c_uint8*20)]
 def num(s):
  if s.startswith('raw:'):assert len(s)==24;return bytes.fromhex(s[4:])
  d=Decimal(s)
  if not d:return bytes(10)
  t=d.copy_abs().normalize().as_tuple();digits=''.join(map(str,t.digits));e=len(digits)+t.exponent-1;assert len(digits)<=15 and abs(e)<=99
  ds=digits.ljust(15,'0');flag=(6 if d<0 else 1)if e>=0 else(5 if d<0 else 0)
  return bytes([int(ds[0]),*[int(ds[i:i+2],16)for i in range(1,15,2)],int(f'{abs(e):02d}',16),flag])
 def put(a,b):C.memmove(C.byref(m.ram,a),b,len(b))
 def count(n):return C.c_uint.in_dll(nl,'series_'+n).value
 def snap(name,base):
  working=m.er(12)
  return dict(stage=name,pc=nl.harness_get_pc(),sp=nl.harness_get_sp(),registers=[m.reg(i)for i in range(16)],lr=nl.series_lr(),base=base,workspace40=bytes(m.ram[base:base+40]).hex()if base else None,working_address=working,working20=bytes(m.ram[working:working+20]).hex(),x=(bytes(m.ram[0x8276:0x8280])+bytes(m.ram[0x8458:0x8462])).hex(),output=bytes(m.ram[0x8900:0x8914]).hex(),outer_cursor=m.word(0x8190),steps=C.c_uint64.in_dll(nl,'series_steps').value,polls=count('polls'))
 rows=[];total_steps=0;artifacts={str(D/'oracle.so'):sha(D/'oracle.so'),str(D/'baseline/nxu8-harness.so'):sha(D/'baseline/nxu8-harness.so')}
 with gzip.open(D/'observations.jsonl.gz','wt')as stream:
  for index,case in enumerate(data['rows']):
   m.reset();nl.series_observer_reset();C.c_uint.in_dll(nl,'series_abort').value=case['abort_poll']
   for a,v in [(0x80f9,case['mode']),(0x80fc,1),(0x80f5,0xf0),(0x8105,4),(0x8106,1),(0x8121,1)]:m.ram[a]=v
   for pair,addresses in [('constant',(0x823a,0x841c)),('lower',(0x8244,0x8426)),('upper',(0x824e,0x8430)),('x',(0x8276,0x8458))]:
    for value,address in zip(case[pair],addresses):put(address,num(value))
   put(0x8900,b'\xee'*20);body=case['body'].encode().replace(b'/',b'\x4f');tokens=bytes([0x69 if case['kind']=='sum'else 0x5d])+body+b',B,C)\0';put(0x8a00,tokens);m.word(0x812c,0x8a00);m.word(0x8190,0x8a00)
   m.er(0,0x8190);m.er(2,0x8900);nl.harness_set_sp(0x8dee);nl.harness_set_lr(0x2fffe);nl.harness_set_pc(0x171f4);base=0;stages=[];initial=bytes(m.ram)
   targets=[('entry',0x43a2 if case['kind']=='sum'else 0x42ae),('local',0x43b2 if case['kind']=='sum'else 0x42be),('lower_stored',0x43d0 if case['kind']=='sum'else 0x42dc),('upper_before',0x4412 if case['kind']=='sum'else 0x431e),('upper_after',0x4416 if case['kind']=='sum'else 0x4322),('identity_after',0x4420 if case['kind']=='sum'else 0x432c),('published',0x4430 if case['kind']=='sum'else 0x433c),('numeric_finish',0x447e if case['kind']=='sum'else 0x4390),('pre_return',0x448e if case['kind']=='sum'else 0x43a0)]
   for name,pc in targets:
    execution=nl.series_observe_to(1000000,pc)
    if name=='local'and nl.harness_get_pc()==pc:base=m.er(8)
    s=snap(name,base);s['execution']=execution;stages.append(s);stream.write(json.dumps(dict(index=index,input=case,kind='stage',snapshot=s,ram=bytes(m.ram).hex()))+'\n')
    if execution!=100 or nl.harness_get_pc()!=pc:break
   if stages[-1]['stage']=='pre_return'and stages[-1]['execution']==100:
    nl.harness_run(1,0x2fffe,False);stages.append(snap('after_native_return_instruction',base))
    if nl.harness_get_pc()==(0x16bce if case['kind']=='sum'else 0x16bd4):
     execution=nl.series_observe_to(1000000,0x2fffe);stages.append(dict(snap('whole_return',base),execution=execution))
   samples=(Sample*256).in_dll(nl,'series_samples');sample_rows=[{n:(bytes(getattr(e,n)).hex()if n in ('x','value')else getattr(e,n))for n,_ in Sample._fields_}for e in samples[:min(count('sample_count'),256)]]
   events=(Stage*2048).in_dll(nl,'series_stages');event_rows=[{n:(bytes(getattr(e,n)).hex()if n in ('records','value','x')else getattr(e,n))for n,_ in Stage._fields_}for e in events[:min(count('stage_count'),2048)]]
   writes=(Write*65536).in_dll(nl,'series_writes');write_rows=[{n:getattr(e,n)for n,_ in Write._fields_}for e in writes[:min(count('write_count'),65536)]]
   final=bytes(m.ram);last=stages[-1];outcome='whole_return'if nl.harness_get_pc()==0x2fffe else'driver_continuation_boundary'if last['stage']=='after_native_return_instruction'else'instruction_budget_or_native_stop'
   row=dict(index=index,input=case,tokens=tokens.hex(),outcome=outcome,stages=stages,samples=sample_rows,events=event_rows,final_pc=nl.harness_get_pc(),callback_count=sum(e['r6']==1 for e in sample_rows),polls=count('polls'),native_steps=sum(m.counts),numeric_status=next((s['registers'][0]for s in stages if s['stage']=='numeric_finish'),None),source_restored=initial[0x8276:0x8280]+initial[0x8458:0x8462]==final[0x8276:0x8280]+final[0x8458:0x8462],output=final[0x8900:0x8914].hex(),cursor=m.word(0x8190))
   rows.append(row);total_steps+=sum(m.counts);stream.write(json.dumps(dict(index=index,input=case,kind='full',initial=initial.hex(),final=final.hex(),writes=write_rows,summary=row))+'\n')
   print(json.dumps(dict(index=index,label=case['label'],outcome=outcome,pc=hex(row['final_pc']),status=row['numeric_status'],callbacks=row['callback_count'],polls=row['polls'],output=row['output'])),flush=True)
  changes={p:sha(p)for p,h in {**pins,**artifacts}.items()if sha(p)!=h}
  report=dict(status='OBSERVED'if not changes else'DRIFT',native_calls=len(rows),native_instructions=total_steps,rows=rows,pins=pins,artifacts=artifacts,changes=changes,scope='Fresh unchanged synthetic prepared171F4 ordinary calculator C4/COMP callframes and actual numerical stages. Every input is authored. Timerresponse only: native request2 is preserved on selectedabort and cleared otherwise. Actual lastreturninstruction is measured and unexpected continuation stopped immediately. No actual key/UI admission or arbitrary continuation is inferred.')
  (D/'report.json').write_text(json.dumps(report,indent=2)+'\n');assert not changes
  print(json.dumps(dict(native_calls=len(rows),native_instructions=total_steps,changes=changes)),flush=True)
 return report
