#!/usr/bin/env python3
"""Execute and record the ROM's approximate pi-recognition path (GPL-3.0)."""
import csv
import gzip
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import trace_natural_result as trace
from nxu8.machine import Machine

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'analysis/pi-result-trace'
ROM = trace.ROM
trace.NAMES.update({
    0x10c1e: 'recognize_ordinary_fraction',
    0x10b7e: 'ordinary_fraction_core',
    0x10c2c: 'recognize_pi_coefficient',
    0x10b60: 'round_and_test_integer',
    0x1d16e: 'construct_numeric_pi',
    0x1bfcc: 'decimal_multiply',
    0x1bfe0: 'decimal_divide',
    0x1c982: 'integer_gcd',
    0x1cef0: 'round_near_integer',
    0x1cabe: 'has_fractional_digits',
    0x1c3fa: 'split_integer_part_and_remainder',
})
POINTS = {
    0x10c3c: 'copied numeric input',
    0x10c52: 'constructed numeric pi',
    0x10c5a: 'after division by pi',
    0x10c64: 'after multiplication by 25200',
    0x10c68: 'after rounding and integer test',
    0x10c82: 'after gcd with 25200',
    0x10c8c: 'after division of candidate integer by gcd',
    0x10c96: 'after division of 25200 by gcd',
    0x10ca0: 'copied denominator to fraction workspace',
    0x10ca6: 'split coefficient into integer part and remainder',
    0x10cbc: 'recognition failure',
}
CASES = [
    ('asin-half-rad', 'asin(0.5), radians', b'\xb00.5)\0', {}, 13, 'aebbb831b9b836b9bc82'),
    ('four-atan-one-rad', '4*atan(1), radians', b'4\x4e\xb21)\0', {}, 13, '82'),
    ('decimal-pi-sixth', '0.523598775598299', b'0.523598775598299\0', {}, 13, 'aebbb831b9b836b9bc82'),
    ('decimal-equation', '3.14159265358979/6', b'3.14159265358979\x4f6\0', {}, 13, 'aebbb831b9b836b9bc82'),
    ('pi-sixth', 'pi/6', b'\x82\x4f6\0', {}, 13, 'aebbb831b9b836b9bc82'),
    ('pi-sixteenth', 'pi/16', b'\x82\x4f16\0', {}, 13, 'aebbb831b9b83136b9bc82'),
    ('five-pi-sixths', '5*pi/6', b'5\x4e\x82\x4f6\0', {}, 13, 'aebbb835b9b836b9bc82'),
    ('smallest-positive-coefficient', 'pi/25200', b'\x82\x4f25200\0', {}, 13, 'aebbb831b9b83235323030b9bc82'),
    ('pi-eleventh', 'pi/11', b'\x82\x4f11\0', {}, 10, None),
    ('rounded-ten-digits', '0.5235987756', b'0.5235987756\0', {}, 10, None),
    ('ordinary-half', '0.5', b'0.5\0', {}, 11, 'aebbb831b9b832b9bc'),
    ('asin-half-deg', 'asin(0.5), degrees', b'\xb00.5)\0', {0x8105:4}, 10, '3330'),
    ('decimal-output', 'pi/6, decimal output requested', b'\x82\x4f6\0', {0x80f5:0xf2}, 10, None),
    ('linear-output', 'pi/6, Math output disabled', b'\x82\x4f6\0', {0x8106:0}, 10, None),
    ('negative-pi-sixth', '-pi/6', b'\x60\x82\x4f6\0', {}, 13, None),
    ('in-range', '300000*pi', b'300000\x4e\x82\0', {}, 13, '33303030303082'),
    ('out-of-range', '400000*pi', b'400000\x4e\x82\0', {}, 10, None),
    ('decimal-sqrt-two', '1.414213562373095', b'1.414213562373095\0', {}, 10, None),
    ('decimal-e', '2.718281828459045', b'2.718281828459045\0', {}, 10, None),
]


def decimal_record(record):
    """Decode normal ten-byte numbers, not packed surds or format workspaces."""
    digits = record[:8].hex()
    assert all(c.isdigit() for c in digits), record.hex()
    if int(digits)==0: return '0'
    exponent = int(f'{record[8]:02x}')
    if record[9] in (0, 5): exponent -= 100
    assert record[9] in (0, 1, 5, 6), record.hex()
    number = Decimal(int(digits)).scaleb(exponent-14)
    if record[9] >= 5: number = -number
    return str(number)


def snapshots(raw, initial):
    ram = bytearray(initial)
    result = []
    with raw.open() as f:
        for line in f:
            row = line.rstrip('\n').split(',')
            if row[0] == 'W' and row[3] == '00':
                p, size, value = int(row[4],16), int(row[5]), int(row[6],16)
                if p >= 0x8000:
                    for n in range(size): ram[(p+n)&65535] = value >> (n*8) & 255
            if row[0] != 'I': continue
            pc = int(row[2],16)
            if pc not in POINTS: continue
            regs = bytes.fromhex(row[8])
            er = lambda n: regs[n] | regs[n+1] << 8
            p = er(12)
            slots = {}
            for offset in (-10, 0, 10, 20):
                record = bytes(ram[p+offset:p+offset+10])
                slots[str(offset)] = {'record':record.hex()}
                try: slots[str(offset)]['decimal_interpretation'] = decimal_record(record)
                except (AssertionError, ValueError): pass
            result.append({'step':int(row[1]), 'pc':hex(pc), 'event':POINTS[pc],
                           'er12':hex(p), 'er14':hex(er(14)), 'r0':regs[0],
                           'slots_relative_to_er12':slots})
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    m = Machine(ROM, ROOT/'analysis/build')
    manifest = {'rom_sha256':hashlib.sha256(ROM).hexdigest(),
                'limitation':'Original ROM executed at routine boundaries with passive peripherals; not a reset/keyboard trace. Host supplies input bytes and documented context, not arithmetic results or output tokens.',
                'initial_context':{'0x80f9':193, '0x80f5':240, '0x8105':5, '0x8106':1,
                                   '0x8121':1, '0x812c':'0x8200', '0x8190':'0x8200'},
                'cases':[]}
    for name, expression, input_bytes, overrides, expected_kind, expected_tokens in CASES:
        m.reset(); trace.settings(m); m.ram[0x8105] = 5
        for p,v in overrides.items(): m.ram[p]=v
        for i,b in enumerate(input_bytes): m.ram[0x8200+i]=b
        m.word(0x8190,0x8200); trace.INPUT=input_bytes
        case={'name':name, 'expression':expression, 'input_tokens':input_bytes.hex(),
              'context_overrides':{hex(p):v for p,v in overrides.items()}, 'phases':[]}
        phases = [('evaluate',0x171f4,{0:0x8190,2:0x8300}),
                  ('select-format',0xc034,{}),
                  ('format',0xc060,{0:0x8300,2:0x8500})]
        if name=='asin-half-rad': phases += [('display',0xb070,{0:0x8300}),('flush',0x3cfc,{})]
        for phase,address,args in phases:
            for n,v in args.items(): m.er(n,v)
            if phase=='format': m.word(0x8dee,0)
            initial=bytes(m.ram)
            stem=OUT/f'{name}.{phase}'
            with gzip.open(str(stem)+'.initial-ram.bin.gz','wb') as f: f.write(initial)
            raw=Path(str(stem)+'.csv'); m.trace_open(raw)
            try: m.call(address,limit=10000000)
            finally: m.trace_close()
            points=snapshots(raw,initial)
            if points: Path(str(stem)+'.recognition.json').write_text(json.dumps(points,indent=2)+'\n')
            stats,replayed=trace.annotate(raw,initial)
            assert replayed==bytes(m.ram), (name,phase)
            stats.update({'phase':phase,'entry':hex(address),'return_r0':m.reg(0),
                          'format_selection':m.ram[0x8100]})
            case['phases'].append(stats)
            if phase=='evaluate':
                assert m.reg(0)==0, (name,m.reg(0))
                record=bytes(m.ram[0x8300:0x830a])
                case['numeric_record']=record.hex();case['numeric_value']=decimal_record(record)
            if phase=='format':
                tokens=bytes(m.ram[0x8500:0x8600]).split(b'\0')[0]
                case['formatter_tokens']=tokens.hex();case['return_kind']=m.reg(0)
                assert m.reg(0)==expected_kind, (name,m.reg(0),tokens.hex())
                if expected_tokens: assert tokens.hex()==expected_tokens,(name,tokens.hex())
                assert bytes(m.ram[0x8300:0x830a]).hex()==case['numeric_record']
                case['pi_recognizer_executed']='0x10c2c' in stats['instruction_counts']
        if name=='asin-half-rad':
            frame=bytes(m.ram[0x87d0:0x8950])
            assert any(frame)
            for y in range(32): assert bytes(m.ram[0xf800+y*16:0xf800+y*16+12])==frame[y*12:y*12+12]
            (OUT/'asin-half-rad.png').write_bytes(trace.png(frame))
        manifest['cases'].append(case)
        print(name,case['numeric_value'],case['return_kind'],case['formatter_tokens'],flush=True)
    static_starts={int(s,16) for s in re.findall(r'^([0-9A-F]{6}) +[0-9A-F]{2} ',
                   (ROOT/'analysis/disassembly/complete.asm').read_text(),re.M)}
    executed={int(pc,16) for c in manifest['cases'] for p in c['phases'] for pc in p['instruction_counts']}
    assert executed <= static_starts, sorted(executed-static_starts)
    manifest['unique_executed_pcs']=len(executed)
    manifest['all_executed_pcs_are_static_instruction_starts']=True
    boundary=[]
    for value in ['4200.00000000049','4200.00000000050','4199.99999999950','4199.99999999949']:
        m.reset();trace.settings(m)
        for i,b in enumerate(value.encode()+b'\0'):m.ram[0x8200+i]=b
        m.word(0x8190,0x8200);m.er(0,0x8190);m.er(2,0x8300);m.call(0x171f4)
        m.er(12,0x8300);m.call(0x10b60)
        success=m.reg(0)==0
        assert success==(value in ['4200.00000000049','4199.99999999950'])
        boundary.append({'input':value,'return_r0':m.reg(0),'output':decimal_record(bytes(m.ram[0x8300:0x830a]))})
    manifest['integer_helper_boundary_tests']=boundary
    sweep=[]
    for denominator in range(1,129):
        m.reset();trace.settings(m)
        input_bytes=b'\x82\x4f'+str(denominator).encode()+b'\0'
        for i,b in enumerate(input_bytes):m.ram[0x8200+i]=b
        m.word(0x8190,0x8200);m.er(0,0x8190);m.er(2,0x8300);m.call(0x171f4)
        m.call(0xc034);m.er(0,0x8300);m.er(2,0x8500);m.word(0x8dee,0);m.call(0xc060)
        assert (m.reg(0)==13)==(25200%denominator==0), (denominator,m.reg(0))
        sweep.append({'denominator':denominator,'return_kind':m.reg(0)})
    manifest['pi_over_denominator_sweep']=sweep
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__': main()
