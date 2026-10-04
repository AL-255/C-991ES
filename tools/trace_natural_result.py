#!/usr/bin/env python3
"""Trace the original ROM's parser-to-pixel execution for the two-surd example.

GPL-3.0. Trace files include every instruction and data read/write. The host
supplies routine boundaries and passive peripheral state, not arithmetic or
result tokens. See the generated manifest for all initial state and limitations.
"""
import csv
import gzip
import hashlib
import json
from pathlib import Path
from decimal import Decimal, localcontext
from collections import Counter

from nxu8.decoder import Decoder
from nxu8.machine import Machine
from verify_firmware import png

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'analysis/exact-result-trace'
ROM = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
INPUT = b'(\x98998)-\x98997))\x4f99\0'
EXPECTED_RECORD = '89970199099801990106'
EXPECTED_TOKENS = bytes.fromhex('aebbb898b8393938b92d98b8393937b9b9b83939b9bc')
NAMES = {
    0x171f4: 'evaluate_expression', 0x159d0: 'decode_input_token',
    0x16828: 'parse_number', 0x16336: 'apply_pending_operator',
    0x1c870: 'square_root_dispatch_wrapper', 0x1c780: 'exact_square_root',
    0x1c690: 'subtract_numbers', 0x1c6b8: 'divide_numbers',
    0x180cc: 'subtract_surd_numbers', 0x18118: 'divide_surd_numbers',
    0x178ba: 'unpack_six_surd_components', 0x18176: 'expand_five_common_denominator_components',
    0x17616: 'pack_surd_result', 0xc034: 'select_result_format_for_key',
    0x3658: 'set_display_format_state', 0xb070: 'result_display_controller',
    0xc060: 'format_numeric_result', 0xab8e: 'format_exact_numeric_result',
    0xc35e: 'math_output_allowed', 0x8c56: 'measure_place_draw',
    0x9cd6: 'layout_expression', 0x937c: 'layout_fraction',
    0x8ea6: 'layout_radical', 0x867a: 'draw_enclosure',
    0xc634: 'initialize_layout_pass', 0xc544: 'merge_box_metrics',
    0x3a8a: 'draw_glyph', 0x3bbc: 'unpack_glyph',
    0x3c8e: 'composite_byte', 0x3cfc: 'flush_framebuffer',
}
DECODER = Decoder()
INSTRUCTIONS = {}


def instruction(pc):
    if pc not in INSTRUCTIONS:
        INSTRUCTIONS[pc] = DECODER.decode(ROM, pc)
    assert INSTRUCTIONS[pc] is not None, hex(pc)
    return INSTRUCTIONS[pc]


def cstring(ram, p, bound=160):
    return bytes(ram[p:min(65536, p + bound)]).split(b'\0')[0].hex()


def annotate(raw_path, initial_ram):
    """Replay writes, connect executed calls/returns, and annotate every opcode."""
    ram = bytearray(initial_ram)
    def data0(p, size):
        # Routine pointer arguments can refer to ROM constants as well as RAM.
        return bytes(ROM[n] if n < 0x8000 else ram[n]
                     for n in range(p, min(65536, p+size)))
    calls, selected, stack = [], [], []
    pcs, counts = set(), Counter()
    previous = None
    reads_of_input = []
    dispatches = []
    steps = writes = reads = 0
    trace_path = raw_path.with_suffix('.annotated.csv.gz')
    with raw_path.open() as src, gzip.open(trace_path, 'wt') as dst:
        dst.write('# I: step,PC,SP,EA,DSR,PSW,LR,R0..R15,assembly\n')
        dst.write('# R/W: step,PC,segment,offset,size,little_endian_value\n')
        writer = csv.writer(dst, lineterminator='\n')
        for line in src:
            row = line.rstrip('\n').split(',')
            if row[0] == 'I':
                step, pc, sp = int(row[1]), int(row[2], 16), int(row[3], 16)
                regs = bytes.fromhex(row[8])
                er = lambda n: regs[n] | regs[n+1] << 8
                if previous:
                    prev_pc, prev_step, prev_regs = previous
                    prev_ins = instruction(prev_pc)
                    if prev_ins.mnemonic == 'BL':
                        ret = (prev_pc & 0xf0000) | ((prev_pc + prev_ins.size) & 65535)
                        node = {'id': len(calls), 'parent': stack[-1]['id'] if stack else None,
                                'call_step': prev_step, 'entry_step': step,
                                'call_site': hex(prev_pc), 'entry': hex(pc),
                                'return_pc': hex(ret), 'name': NAMES.get(pc, ''),
                                'entry_registers': row[8], 'entry_sp': hex(sp)}
                        if pc in NAMES:
                            node['entry_er0'] = hex(er(0)); node['entry_er2'] = hex(er(2))
                            node['operand0_bytes'] = data0(er(0),20).hex()
                            node['operand2_bytes'] = data0(er(2),20).hex()
                            if pc == 0x9cd6:
                                node['layout'] = {'draw_mode': ram[0x8009], 'font': ram[0x811f],
                                                  'tokens': cstring(ram, er(0)),
                                                  'x': ram[sp] | ram[sp+1] << 8,
                                                  'y': ram[sp+2] - (256 if ram[sp+2] >= 128 else 0)}
                            if pc in (0xc060, 0xab8e):
                                node['output_pointer'] = hex(er(2) if pc == 0xc060 else er(0))
                            if pc == 0x17616:
                                node['component_slot'] = regs[0]
                                node['packed_destination'] = hex(er(2))
                            selected.append(node)
                        calls.append(node); stack.append(node)
                    else:
                        # A return can leave shared tails; use the observed
                        # destination, not a guessed function end address.
                        match = next((n for n in range(len(stack)-1, -1, -1)
                                      if int(stack[n]['return_pc'], 0) == pc), None)
                        if match is not None:
                            for node in stack[match:]:
                                node['exit_step'] = prev_step; node['return_step'] = step
                                node['return_registers'] = row[8]
                                node['return_r0'] = regs[0]
                                if node['name']:
                                    p = int(node['entry_er0'], 0)
                                    node['operand0_after'] = data0(p,50).hex()
                                    if 'output_pointer' in node:
                                        node['output_tokens'] = cstring(ram, int(node['output_pointer'], 0))
                                    if 'packed_destination' in node:
                                        p = int(node['packed_destination'], 0)
                                        node['packed_result'] = bytes(ram[p:p+10]).hex()
                                    if 'layout' in node:
                                        p = int(node['entry_er2'], 0)
                                        node['layout']['returned_pointer'] = hex(er(0))
                                        node['layout']['metrics'] = [ram[p] | ram[p+1] << 8, ram[p+2], ram[p+3]]
                            del stack[match:]
                ins = instruction(pc)
                writer.writerow(row + [ins.mnemonic + ' ' + ins.operands])
                pcs.add(pc); counts[hex(pc)] += 1; steps += 1
                previous = pc, step, regs
            else:
                writer.writerow(row)
                segment, offset, size = int(row[3], 16), int(row[4], 16), int(row[5])
                if row[0] == 'W':
                    writes += 1
                    if segment == 0 and offset >= 0x8000:
                        value = int(row[6], 16)
                        for n in range(size): ram[(offset+n) & 65535] = (value >> (8*n)) & 255
                else:
                    reads += 1
                    expected = 0
                    for n in range(size):
                        pos = (offset+n) & 65535
                        if segment == 0 and pos >= 0x8000:
                            byte = ram[pos]
                        else:
                            address = (segment << 16) | pos
                            if segment in (8, 9): address -= 0x80000
                            byte = ROM[address] if address < len(ROM) else 0
                        expected |= byte << (8*n)
                    assert expected == int(row[6], 16), row
                    if row[2] == '016558':
                        dispatches.append({'step':int(row[1]),'table_address':hex(offset),
                                           'index':(offset-0x291e)//2,
                                           'target':hex(0x10000|int(row[6],16))})
                    if segment == 0 and offset < 0x8200+len(INPUT) and offset+size > 0x8200:
                        reads_of_input.append({'step': int(row[1]), 'pc': '0x'+row[2], 'address': hex(offset), 'size': size})
    with gzip.open(raw_path.with_suffix('.calls.json.gz'), 'wt') as f: json.dump(calls, f)
    raw_path.with_suffix('.milestones.json').write_text(json.dumps(selected, indent=2)+'\n')
    raw_path.unlink()
    return {'instructions': steps, 'data_reads': reads, 'data_writes': writes,
            'unique_pcs': len(pcs), 'calls': len(calls),
            'dispatches': dispatches, 'every_data_read_matches_memory_replay': True,
            'input_buffer_reads': reads_of_input, 'trace': trace_path.name,
            'instruction_counts': dict(counts)}, ram


def settings(m):
    m.ram[0x80f9] = 193  # Math-capable COMP context used by the verified fixtures.
    m.ram[0x80f5] = 240  # Ordinary result selection tested by C034 (not Shift=).
    m.ram[0x8106] = 1
    m.ram[0x8121] = 1
    m.word(0x812c, 0x8200)


def main():
    OUT.mkdir(exist_ok=True, parents=True)
    m = Machine(ROM, ROOT/'analysis/build'); settings(m)
    for n, byte in enumerate(INPUT): m.ram[0x8200+n] = byte
    m.word(0x8190, 0x8200)
    manifest = {'rom_sha256': hashlib.sha256(ROM).hexdigest(),
                'expression': '(sqrt(998)-sqrt(997))/99', 'input_tokens': INPUT.hex(),
                'initial_context': {'0x80f9': 193, '0x80f5': 240, '0x8106': 1,
                                    '0x8121': 1, '0x812c': '0x8200', '0x8190': '0x8200'},
                'phases': [],
                'limitation': 'Routine-level execution with passive peripherals. Host supplies call boundaries; this is not a reset/keyscan trace. All executed instructions and memory reads/writes within each phase are saved.'}
    for name, address, arguments in [('evaluate', 0x171f4, {0:0x8190, 2:0x8300}),
                                     ('select-format', 0xc034, {}),
                                     ('display', 0xb070, {0:0x8300}),
                                     ('flush', 0x3cfc, {})]:
        for index, value in arguments.items(): m.er(index, value)
        initial = bytes(m.ram)
        with gzip.open(OUT/f'{name}.initial-ram.bin.gz', 'wb') as f: f.write(initial)
        raw = OUT/f'{name}.csv'; m.trace_open(raw)
        try: m.call(address, limit=10000000)
        finally: m.trace_close()
        result = {'phase': name, 'entry': hex(address), 'host_er_arguments': arguments,
                  'return_registers': bytes(m.reg(n) for n in range(16)).hex(),
                  'result_record': bytes(m.ram[0x8300:0x830a]).hex(),
                  'display_state_8100': m.ram[0x8100]}
        stats, replayed = annotate(raw, initial)
        assert replayed == bytes(m.ram), name
        result.update(stats); manifest['phases'].append(result)
        if name == 'evaluate':
            assert m.reg(0) == 0
            assert result['result_record'] == EXPECTED_RECORD
        if name == 'select-format': assert m.ram[0x8100] == 13
        assert result['result_record'] == EXPECTED_RECORD
    frame = bytes(m.ram[0x87d0:0x8950])
    (OUT/'result.png').write_bytes(png(frame)); (OUT/'result.bin').write_bytes(frame)
    assert any(frame)
    for y in range(32): assert bytes(m.ram[0xf800+y*16:0xf800+y*16+12]) == frame[y*12:y*12+12]
    assert m.word(0x812c) == 0x8200
    milestones = json.loads((OUT/'display.milestones.json').read_text())
    outputs = [n for n in milestones if n['entry']=='0xc060']
    assert outputs and bytes.fromhex(outputs[0]['output_tokens']) == EXPECTED_TOKENS
    manifest['formatter_tokens'] = outputs[0]['output_tokens']
    manifest['framebuffer_sha256'] = hashlib.sha256(frame).hexdigest()
    all_pcs = set().union(*(set(p['instruction_counts']) for p in manifest['phases']))
    static_starts = set()
    excerpts = [(0x159d0,0x15a0e),(0x16336,0x1635c),(0x16534,0x16588),
                (0x171f4,0x172d2),(0x1c690,0x1c768),(0x1c780,0x1c878),
                (0x17616,0x176c0),(0x178ba,0x17940),(0x18088,0x18176),
                (0x18176,0x18212),(0xc034,0xc060),(0xc1d6,0xc1f0),
                (0xad1e,0xad9e),(0x8c56,0x8ea6),(0x937c,0x93a2),
                (0x3cfc,0x3d28)]
    static_lines = []
    for line in (ROOT/'analysis/disassembly/complete.asm').read_text().splitlines():
        if len(line)>9 and line[:6].isalnum():
            try: address = int(line[:6],16)
            except ValueError: continue
            if '.db' not in line: static_starts.add(hex(address))
            if any(start<=address<end for start,end in excerpts): static_lines.append(line)
    assert all_pcs <= static_starts, sorted(all_pcs-static_starts)
    manifest['trace_audit'] = {'instructions':sum(p['instructions'] for p in manifest['phases']),
                              'unique_pcs':len(all_pcs),
                              'all_executed_pcs_in_delivered_static_listing':True,
                              'all_data_reads_and_final_ram_replayed':True}
    (OUT/'static-flow.asm').write_text('; Selected ranges from the delivered complete.asm; gaps between ranges are intentional.\n'+'\n'.join(static_lines)+'\n')
    # Decode the actual final record through the ROM's own expand routines.
    record = bytes.fromhex(EXPECTED_RECORD)
    for routine, count in [(0x178ba,6),(0x18176,5)]:
        m.reset(); settings(m)
        for n,b in enumerate(record): m.ram[0x8300+n] = b
        m.er(0,0x8300); m.reg(2,0); m.call(routine)
        base = 0x8640 if routine==0x178ba else 0x8300
        records = [bytes(m.ram[base+n*10:base+(n+1)*10]) for n in range(count)]
        strings = []
        for n, component in enumerate(records):
            for i,b in enumerate(component): m.ram[0x8500+i]=b
            m.ram[0x8100]=10; m.er(0,0x8500);m.er(2,0x8600);m.word(0x8dee,0);m.call(0xc060)
            strings.append(cstring(m.ram,0x8600))
        manifest[f'components_{routine:x}'] = {'records':[r.hex() for r in records], 'formatted_tokens': strings}
    # Remove the original expression before drawing the same numeric record.
    m.reset(); settings(m)
    for n,b in enumerate(record):m.ram[0x8300+n]=b
    for n in range(len(INPUT)):m.ram[0x8200+n]=0xa5
    m.call(0xc034);m.er(0,0x8300);m.call(0xb070)
    assert bytes(m.ram[0x87d0:0x8950]) == frame
    manifest['destroy_input_same_framebuffer'] = True
    with localcontext() as ctx:
        ctx.prec=60
        approximate=(Decimal(998).sqrt()-Decimal(997).sqrt())/99
    manifest['independent_decimal_value'] = str(approximate)
    # A decimal literal alone does not recover the original two-radical form.
    decimal_input = (format(approximate,'.15g')+'\0').encode()
    m.reset();settings(m)
    for n,b in enumerate(decimal_input):m.ram[0x8200+n]=b
    m.word(0x8190,0x8200);m.er(0,0x8190);m.er(2,0x8300);m.call(0x171f4)
    assert m.reg(0)==0
    control_record=bytes(m.ram[0x8300:0x830a]).hex()
    m.call(0xc034);m.er(0,0x8300);m.er(2,0x8500);m.word(0x8dee,0);m.call(0xc060)
    control_tokens=cstring(m.ram,0x8500)
    assert '98' not in control_tokens and m.reg(0)==10
    manifest['decimal_literal_control']={'input':decimal_input.hex(),'numeric_record':control_record,'format_kind':m.reg(0),'output_tokens':control_tokens}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k!='phases'},indent=2))
    print('Phases:',[(p['phase'],p['instructions'],p['unique_pcs']) for p in manifest['phases']])


if __name__ == '__main__': main()
