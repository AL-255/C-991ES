#!/usr/bin/env python3
"""Trace ROM trigonometric evaluation and its exact-value tables (GPL-3.0)."""
import gzip
import hashlib
import json
import re
from pathlib import Path

import trace_natural_result as trace
from nxu8.machine import Machine

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'analysis/special-angle-trace'
ROM = trace.ROM
trace.NAMES.update({0x16268:'sine_with_special_values',0x16272:'cosine_with_special_values',
                    0x16308:'tangent_with_special_values',0x1c59e:'numeric_sine',
                    0x1c58c:'numeric_cosine',0x1c57a:'numeric_tangent',
                    0x18212:'exact_output_allowed',0x169ae:'copy_numeric_record'})
CASES = [
    ('sin15',b'\xa015)\0',4,1,13,'80020104000601040106'),
    ('sin30',b'\xa030)\0',4,1,11,'21a20000000000000301'),
    ('sin45',b'\xa045)\0',4,1,13,'80000001000201020100'),
    ('sin60',b'\xa060)\0',4,1,13,'80000001000301020100'),
    ('sin75',b'\xa075)\0',4,1,13,'80020104000601040101'),
    ('sin18',b'\xa018)\0',4,1,10,None),
    ('sin390',b'\xa0390)\0',4,1,11,'21a20000000000000301'),
    ('cos120',b'\xa1120)\0',4,1,11,'21a20000000000000306'),
    ('tan75',b'\xa275)\0',4,1,13,'80010201000301010101'),
    ('sin45-linear',b'\xa045)\0',4,0,10,'07071067811865489900'),
    ('sin-approx-pi-fourth',b'\xa00.7853981633974483)\0',5,1,13,'80000001000201020100'),
    ('sin45-near',b'\xa045.00000000001)\0',4,1,13,'80000001000201020100'),
    ('sin45-further',b'\xa045.000000001)\0',4,1,10,None),
    ('literal-sqrt-half',b'0.707106781186548\0',4,1,10,'07071067811865489900'),
]


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    m=Machine(ROM,ROOT/'analysis/build')
    manifest={'rom_sha256':hashlib.sha256(ROM).hexdigest(),
              'initial_context':{'0x80f9':193,'0x80f5':240,'0x8106':1,'0x8121':1,
                                 '0x812c':'0x8200','0x8190':'0x8200'},
              'limitation':'Original ROM executed at routine boundaries with passive peripherals. Evaluation has complete traces; later native format selection and formatting are executed without full CSV recording.',
              'cases':[]}
    executed=set()
    for name,input_bytes,angle,mathmode,kind,expected in CASES:
        m.reset();trace.settings(m);m.ram[0x8105]=angle;m.ram[0x8106]=mathmode
        trace.INPUT=input_bytes
        for i,b in enumerate(input_bytes):m.ram[0x8200+i]=b
        m.word(0x8190,0x8200);m.er(0,0x8190);m.er(2,0x8300)
        initial=bytes(m.ram);raw=OUT/f'{name}.csv'
        with gzip.open(OUT/f'{name}.initial-ram.bin.gz','wb') as f:f.write(initial)
        m.trace_open(raw)
        try:m.call(0x171f4,limit=3000000)
        finally:m.trace_close()
        assert m.reg(0)==0,name
        record=bytes(m.ram[0x8300:0x830a]).hex()
        if expected:assert record==expected,(name,record)
        stats,replayed=trace.annotate(raw,initial)
        assert replayed==bytes(m.ram),name
        executed.update(int(pc,16) for pc in stats['instruction_counts'])
        milestones=json.loads((OUT/f'{name}.milestones.json').read_text())
        numeric=[c for c in milestones if c['entry'] in ('0x1c59e','0x1c58c','0x1c57a')]
        m.call(0xc034);m.er(0,0x8300);m.er(2,0x8500);m.word(0x8dee,0);m.call(0xc060,limit=3000000)
        assert m.reg(0)==kind,(name,m.reg(0))
        assert bytes(m.ram[0x8300:0x830a]).hex()==record
        case={'name':name,'input_tokens':input_bytes.hex(),'angle_setting_8105':angle,
              'math_output_8106':mathmode,'numeric_record_before_table':numeric[0]['operand0_after'][:20] if numeric else None,
              'evaluator_result_record':record,'formatter_kind':kind,
              'formatter_tokens':bytes(m.ram[0x8500:0x8600]).split(b'\0')[0].hex(),
              'evaluation_trace':stats}
        manifest['cases'].append(case)
        print(name,case['numeric_record_before_table'],record,kind,flush=True)
    # Copy each stored record through native routines and serialize its output.
    # This is separate table inspection, not a host-produced calculation result.
    tables=[]
    for count,base,offset,family in [(5,0x29f6,50,'sin/cos'),(4,0x2a5a,40,'tan')]:
        for n in range(count):
            p=base+n*10;exact=p+offset
            m.reset();trace.settings(m);m.er(0,0x8300);m.er(2,exact);m.call(0x1d142)
            m.call(0xc034);m.er(0,0x8300);m.er(2,0x8500);m.word(0x8dee,0);m.call(0xc060,limit=3000000)
            tables.append({'family':family,'numeric_address':hex(p),'numeric_record':ROM[p:p+10].hex(),
                           'exact_address':hex(exact),'exact_record':ROM[exact:exact+10].hex(),
                           'formatter_tokens':bytes(m.ram[0x8500:0x8600]).split(b'\0')[0].hex()})
    manifest['tables']=tables
    starts={int(s,16) for s in re.findall(r'^([0-9A-F]{6}) +[0-9A-F]{2} ',
             (ROOT/'analysis/disassembly/complete.asm').read_text(),re.M)}
    assert executed<=starts,sorted(executed-starts)
    manifest['unique_executed_pcs']=len(executed)
    manifest['all_executed_pcs_are_static_instruction_starts']=True
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__':main()
