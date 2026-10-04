#!/usr/bin/env python3
"""Reproducible nX-U8 decode, control-flow graph, and byte coverage audit.

GPL-3.0; see nxu8/COPYING. Reachability is evidence of code, not a claim
that every code path is discovered. Unknown bytes remain explicitly unknown.
"""
import argparse
from collections import Counter, deque
import csv
import hashlib
import json
from pathlib import Path
import re
from nxu8.decoder import Decoder


def dump_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def analyze(rom, decoder, seeds, jump_tables, far_call_tables):
    decoded = {}
    edges = set()
    pending = deque(seeds)
    failures = {}
    indirect = {}
    owners = {}
    while pending:
        address = pending.popleft()
        if address in decoded or address in failures:
            continue
        ins = decoder.decode(rom, address)
        if ins is None:
            failures[address] = 'unaligned, outside ROM, or invalid encoding'
            continue
        decoded[address] = ins
        for offset in range(ins.size):
            byte = address & ~0xFFFF | (address + offset) & 0xFFFF
            owners.setdefault(byte, []).append(address)
        if ins.target is not None:
            edges.add((address, ins.target, 'call' if ins.mnemonic == 'BL' else 'branch'))
            pending.append(ins.target)
            if address in far_call_tables:
                item = far_call_tables[address]
                start = int(item['start'], 0)
                for offset in range(item['count']):
                    pointer = start + offset * 4
                    target = int.from_bytes(rom[pointer:pointer + 2], 'little') | int.from_bytes(rom[pointer+2:pointer+4], 'little') << 16
                    edges.add((address, target, 'far_table_call'))
                    pending.append(target)
        elif ins.mnemonic in ('BL', 'B'):
            if address in jump_tables:
                item = jump_tables[address]
                start = int(item['start'], 0)
                for offset in range(item['count']):
                    pointer = start + offset * 2
                    target = item['segment'] << 16 | int.from_bytes(rom[pointer:pointer + 2], 'little')
                    edges.add((address, target, 'table_call' if ins.mnemonic == 'BL' else 'table_branch'))
                    pending.append(target)
            else:
                indirect[address] = {'instruction': ins.line(), 'reason': 'register branch target unresolved'}
        if ins.mnemonic == 'SWI':
            vector = 0x80 + ins.fields['i'] * 2
            target = int.from_bytes(rom[vector:vector + 2], 'little')
            edges.add((address, target, 'software_interrupt'))
            pending.append(target)
        if not ins.terminates:
            edges.add((address, ins.next_address, 'fallthrough'))
            pending.append(ins.next_address)
    return decoded, edges, failures, indirect, owners


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, default=root / 'firmware/fx-991es-plus-c-ver4.bin')
    parser.add_argument('--output', type=Path, default=root / 'analysis/disassembly')
    parser.add_argument('--seed', type=lambda value: int(value, 0), action='append', default=[])
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    decoder = Decoder()
    seeds = {int.from_bytes(rom[a:a + 2], 'little'): f'vector at {a:#x}' for a in (2, 4)}
    for seed in args.seed:
        seeds[seed] = 'explicit analysis seed'
    config = root / 'analysis/annotations.json'
    annotations = json.loads(config.read_text()) if config.exists() else {}
    for item in annotations.get('code_seeds', []):
        seeds[int(item['address'], 0)] = item['evidence']
    jump_tables = {int(item['site'], 0): item for item in annotations.get('jump_tables', [])}
    far_call_tables = {int(item['site'], 0): item for item in annotations.get('far_call_tables', [])}
    decoded, edges, failures, indirect, owners = analyze(rom, decoder, seeds, jump_tables, far_call_tables)
    labels = {int(a, 0): name for a, name in annotations.get('labels', {}).items()}
    with (out / 'reachable.asm').open('w') as stream:
        stream.write('; Instructions decoded from vectors, call tables, and manual detached-code seeds.\n; Manual seed and table evidence is in annotations.json; see coverage.json.\n')
        for address, ins in sorted(decoded.items()):
            if address in labels:
                stream.write(f'\n{labels[address]}:\n')
            stream.write(ins.line() + '\n')
    # Catalogue every aligned start independently, including starts embedded
    # inside long instructions. This is deliberately not a code classification.
    catalogue = []
    with (out / 'all-aligned.asm').open('w') as stream:
        stream.write('; Hypothetical decode at EVERY aligned start; includes DATA.\n')
        for address in range(0, len(rom), 2):
            ins = decoder.decode(rom, address)
            if ins:
                stream.write(ins.line() + '\n')
                catalogue.append({'address': address, 'raw': ins.raw.hex(), 'mnemonic': ins.mnemonic,
                                  'operands': ins.operands, 'target': ins.target})
            else:
                stream.write(f'{address:06X}   {rom[address:address+2].hex(" ").upper():<11}   .word   ; invalid instruction encoding\n')
    dump_json(out / 'instruction-catalogue.json', catalogue)
    with (out / 'edges.csv').open('w') as stream:
        writer = csv.writer(stream)
        writer.writerow(('source', 'target', 'kind'))
        writer.writerows((f'{a:06x}', f'{b:06x}', kind) for a, b, kind in sorted(edges))
    with (out / 'memory-references.csv').open('w') as stream:
        writer = csv.writer(stream)
        writer.writerow(('instruction', 'mnemonic', 'operands', 'direct_offset'))
        for address, ins in sorted(decoded.items()):
            if ins.mnemonic in ('L', 'ST', 'LEA', 'SB', 'RB', 'TB', 'INC', 'DEC'):
                match = re.search(r'\b0([0-9A-F]{4})h(?!\[)', ins.operands)
                writer.writerow((f'{address:06x}', ins.mnemonic, ins.operands, match[1] if match else ''))
    classes = ['unresolved'] * len(rom)
    # The extraction records which zero bytes were supplied versus synthesized.
    extraction = json.loads((root / 'firmware/extraction.json').read_text())
    explicit = bytearray(len(rom))
    for interval in extraction['written_ranges']:
        begin, end = int(interval['start'], 0), int(interval['end_exclusive'], 0)
        explicit[begin:end] = b'\1' * (end - begin)
    for address, flag in enumerate(explicit):
        if not flag:
            classes[address] = 'synthesized-zero'
    for address in range(6):
        classes[address] = 'vector-data'
    for item in jump_tables.values():
        start = int(item['start'], 0)
        end = start + item['count'] * 2
        classes[start:end] = ['jump-table-data'] * (end - start)
    for item in far_call_tables.values():
        start = int(item['start'], 0)
        end = start + item['count'] * 4
        classes[start:end] = ['far-pointer-table-data'] * (end - start)
    for item in annotations.get('data_ranges', []):
        begin, end = int(item['start'], 0), int(item['end'], 0)
        if not 0 <= begin < end <= len(rom):
            raise ValueError('Invalid annotated range')
        classes[begin:end] = [item['kind']] * (end - begin)
    conflicts = []
    for address, instruction_owners in sorted(owners.items()):
        if classes[address] not in ('unresolved', 'synthesized-zero'):
            conflicts.append({'byte': hex(address), 'previous_class': classes[address]})
        classes[address] = 'decoded-code'
    ranges = []
    begin = 0
    for end in range(1, len(rom) + 1):
        if end == len(rom) or classes[end] != classes[begin]:
            ranges.append({'start': f'0x{begin:05x}', 'end': f'0x{end:05x}',
                           'bytes': end - begin, 'classification': classes[begin]})
            begin = end
    dump_json(out / 'byte-ranges.json', ranges)
    # A complete lossless listing: actual classified instruction starts,
    # followed by raw directives for every other byte. Unlike all-aligned.asm,
    # this never silently treats a font or constant as executable code.
    roundtrip = bytearray()
    with (out / 'complete.asm').open('w') as stream:
        stream.write('; Lossless ROM listing. Data and unknown bytes use .db.\n')
        address = 0
        previous_class = None
        while address < len(rom):
            kind = classes[address]
            if kind != previous_class:
                stream.write(f'\n; {kind}\n')
                previous_class = kind
            if address in labels:
                stream.write(f'{labels[address]}:\n')
            if address in decoded:
                ins = decoded[address]
                stream.write(ins.line() + '\n')
                raw = ins.raw
            else:
                end = address + 1
                while end < min(address + 16, len(rom)) and end not in decoded and classes[end] == kind:
                    end += 1
                raw = rom[address:end]
                stream.write(f'{address:06X}   .db     ' + ', '.join(f'0x{byte:02X}' for byte in raw) + '\n')
            roundtrip.extend(raw)
            address += len(raw)
    assert bytes(roundtrip) == rom
    call_edges = [(a, b, kind) for a, b, kind in edges if kind in ('call', 'table_call', 'far_table_call')]
    entries = sorted({b for _, b, _ in call_edges} | set(seeds))
    with (out / 'function-entries.csv').open('w') as stream:
        writer = csv.writer(stream)
        writer.writerow(('entry', 'label', 'incoming_call_sites', 'evidence'))
        for entry in entries:
            writer.writerow((f'{entry:06x}', labels.get(entry, ''),
                             '|'.join(f'{a:06x}' for a, b, _ in sorted(call_edges) if b == entry),
                             seeds.get(entry, 'direct or annotated table call target')))
    dump_json(out / 'unresolved-branches.json', indirect)
    dump_json(out / 'decode-failures.json', failures)
    overlap = {hex(a): [hex(x) for x in starts] for a, starts in owners.items() if len(starts) > 1}
    unmodeled_far_calls = [hex(a) for a, target, kind in edges
                          if kind == 'call' and target in decoded
                          and decoded[target].mnemonic == 'POP'
                          and decoded[target].operands == 'PC'
                          and a not in far_call_tables]
    counts = dict(Counter(classes))
    assert sum(counts.values()) == len(rom)
    assert sum(item['bytes'] for item in ranges) == len(rom)
    assert ranges[0]['start'] == '0x00000' and int(ranges[-1]['end'], 0) == len(rom)
    report = {'rom_sha256': hashlib.sha256(rom).hexdigest(), 'rom_bytes': len(rom),
              'isa_patterns': len(decoder.patterns), 'aligned_starts_examined': len(rom) // 2,
              'valid_hypothetical_starts': len(catalogue), 'reachable_instructions': len(decoded),
              'byte_classification': counts, 'seeds': {hex(a): why for a, why in seeds.items()},
              'control_flow_edges': len(edges), 'indirect_branches_unresolved': len(indirect),
              'decode_failures': len(failures), 'overlapping_instruction_bytes': overlap,
              'unmodeled_pop_pc_call_sites': unmodeled_far_calls,
              'classification_conflicts': conflicts,
              'address_accounting_complete': True,
              'lossless_listing_roundtrip': hashlib.sha256(roundtrip).hexdigest(),
              'call_target_entries': len(entries),
              'semantic_analysis_complete': False,
              'data_object_typing_complete': False,
              'inferred_table_extents': [item for item in annotations.get('jump_tables', []) + annotations.get('far_call_tables', []) if item.get('extent_confidence') == 'inferred'],
              'warning': 'Address accounting is not proof that all executable code or semantics have been recovered.'}
    dump_json(out / 'coverage.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
