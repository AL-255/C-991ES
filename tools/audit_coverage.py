#!/usr/bin/env python3
"""Audit the saved listing independently and report explicit test denominators."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ROM = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
DIS = ROOT / 'analysis/disassembly'
OUT = ROOT / 'analysis/verification'
output = bytearray()
instruction_starts = set()
for line in (DIS / 'complete.asm').read_text().splitlines():
    match = re.match(r'^([0-9A-F]{6})   (.*)$', line)
    if not match:
        continue
    address = int(match[1], 16)
    assert address == len(output), (hex(address), len(output))
    tail = match[2]
    if tail.startswith('.db'):
        raw = bytes(int(x, 16) for x in re.findall(r'0x([0-9A-F]{2})', tail))
    else:
        raw = bytes.fromhex(tail[:11])
        assert len(raw) in (2, 4), line
        instruction_starts.add(address)
    assert raw == ROM[address:address + len(raw)], line
    output.extend(raw)
assert bytes(output) == ROM
static = json.loads((DIS / 'coverage.json').read_text())
assert len(instruction_starts) == static['reachable_instructions']
executed = {int(x, 0) for x in json.loads((OUT / 'executed-addresses.json').read_text())}
assert executed <= instruction_starts, sorted(executed - instruction_starts)
scopes = {
    'glyph rasterizer and pixel addressing': [(0x3a8a, 0x3d62)],
    'expression construct layout and repetend': [(0x7af4, 0x7c46), (0x8ea6, 0x9ee4)],
    'viewport placement': [(0x8c56, 0x8ea6)],
    'numeric formatting': [(0xab8e, 0xaf5a), (0xc060, 0xc236)],
    'result controller': [(0xb070, 0xb4b0)],
    'whole statically decoded ROM': [(0, len(ROM))],
}
results = {}
for name, ranges in scopes.items():
    selected = {a for a in instruction_starts if any(start <= a < end for start, end in ranges)}
    observed = selected & executed
    results[name] = {'ranges': [[hex(a), hex(b)] for a, b in ranges],
                     'static_instruction_starts': len(selected),
                     'executed_instruction_starts': len(observed),
                     'instruction_coverage_percent': round(100 * len(observed) / len(selected), 2),
                     'unexecuted': [hex(a) for a in sorted(selected - observed)]}
report = {'rom_bytes': len(ROM), 'saved_listing_roundtrip_sha256': hashlib.sha256(output).hexdigest(),
          'every_byte_reconstructed_from_saved_listing': True,
          'scope_coverage': results,
          'limitation': 'Instruction coverage is not branch coverage, operand-state coverage, hardware validation, or a proof of semantic completeness.'}
(OUT / 'coverage-audit.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({name: {k: v for k, v in row.items() if k != 'unexecuted'} for name, row in results.items()}, indent=2))
