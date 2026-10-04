#!/usr/bin/env python3
"""Extend saved execution coverage with clipping, control glyphs, and token domains."""
import json
from pathlib import Path
from nxu8.machine import Machine

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'analysis/verification'
ROM = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
m = Machine(ROM, ROOT / 'analysis/build')
seen = {int(x, 0) for x in json.loads((OUT / 'executed-addresses.json').read_text())}
def capture():
    seen.update(n * 2 for n, count in enumerate(m.counts) if count)
def reset():
    capture(); m.reset()

for y in range(32):
    for x in range(96):
        address = 0x87d0 + y * 12 + x // 8
        previous = m.ram[address]
        m.reg(0, x); m.reg(1, y); m.call(0x3b88)
        assert m.ram[address] == previous | (128 >> (x % 8))
assert bytes(m.ram[0x87d0:0x8950]) == b'\xff' * 384
for x, y in [(-1, 0), (96, 0), (0, -1), (0, 32), (127, 127), (-128, -128)]:
    before = bytes(m.ram)
    m.reg(0, x & 255); m.reg(1, y & 255); m.call(0x3b88)
    assert bytes(m.ram[0x87d0:0x8950]) == before[0x87d0:0x8950]
reset()
for font, base, height in [(10, 0x70c, 9), (7, 0x754, 7)]:
    for character in range(1, 13):
        m.ram[0x811f] = font; m.reg(0, character); m.er(2, 0x8500); m.call(0x3bbc)
        group, offset = divmod((character - 1) * 5, 8)
        expected = []
        for y in range(height):
            bits = ROM[base + group * height + y] << 8
            if offset > 3: bits |= ROM[base + (group + 1) * height + y]
            expected.append(((bits >> (11 - offset)) & 31) << 2)
        assert list(m.ram[0x8500:0x8500 + height]) == expected
reset()
clipping_cases = 0
for selected, base, stride in [(1, 0x87d0, 12), (0, 0xf800, 16)]:
    for font, height, character in [(10, 9, 65), (7, 6, 65), (6, 5, 208)]:
        for x in (0, 1, 7, 8, 90, 94, 95, 96, 255):
            for y in (-10, -1, 0, 1, 24, 30, 31, 32):
                reset()
                m.ram[0x8121] = selected; m.ram[0x811f] = font; m.ram[0x8120] = 1
                m.reg(0, character); m.er(2, 0x8500); m.call(0x3bbc)
                rows = list(m.ram[0x8500:0x8500 + height])
                expected = bytearray(32 * stride)
                if x <= 95 and y < 32:
                    for row, bits in enumerate(rows):
                        yy = y + row + 1
                        for column in range(8):
                            xx = x + column
                            offset = yy * stride + xx // 8
                            if 0 <= offset < len(expected) and bits & (128 >> column):
                                if selected and offset < 12: continue
                                expected[offset] |= 128 >> (xx % 8)
                m.reg(0, x); m.reg(1, y & 255); m.reg(2, character); m.call(0x3a8a)
                assert bytes(m.ram[base:base + 32 * stride]) == expected, (selected, font, x, y)
                clipping_cases += 1
reset()
frame = bytes((n * 19 + 17) & 255 for n in range(384))
for n, byte in enumerate(frame): m.ram[0x87d0 + n] = byte
for n in range(512): m.ram[0xf800 + n] = 0x5a
m.call(0x3cfc)
for row in range(32):
    assert bytes(m.ram[0xf800 + row * 16:0xf800 + row * 16 + 12]) == frame[row * 12:row * 12 + 12]
    assert bytes(m.ram[0xf800 + row * 16 + 12:0xf800 + row * 16 + 16]) == b'\x5a' * 4
m.call(0x3908)
assert bytes(m.ram[0x87d0:0x8950]) == b'\0' * 384
reset()
constructs = {0x5d, 0x5e, 0x63, 0x68, 0x69, 0x6a, 0x6b, 0x73, 0x7c, 0x93, 0x98, 0x9f, 0xa4, 0xae}
evaluator_tokens = []
m.ram[0x80f9] = 193
for token in range(256):
    m.reg(0, token); m.call(0x31e2)
    expected = (ROM[0x31fa + token // 2] >> ((token % 2) * 4)) & 15
    assert m.reg(0) == expected
    assert (expected == 1) == (token in constructs)
    m.ram[0x8200] = token; m.er(14, 0x8200); m.call(0x159d0)
    kind, value = m.reg(2), m.reg(0)
    evaluator_tokens.append({'token': hex(token), 'kind': kind, 'value': value})
    if kind == 6: assert 0 <= value <= 69
capture()
(OUT / 'evaluator-tokens.json').write_text(json.dumps(evaluator_tokens, indent=2) + '\n')
(OUT / 'executed-addresses.json').write_text(json.dumps([hex(a) for a in sorted(seen)], indent=2) + '\n')
result = {'single_pixel_cases': 3078, 'control_font_cases': 24, 'glyph_clipping_cases': clipping_cases, 'token_classifier_cases': 512, 'framebuffer_transfer_rows': 32, 'buffer_clear_bytes': 384, 'unique_executed_instruction_starts_combined': len(seen)}
(OUT / 'rendering-edges.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
