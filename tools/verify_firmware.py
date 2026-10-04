#!/usr/bin/env python3
"""Independent opcode-length audit and native execution of rendering routines.

The headless harness has passive peripherals. These checks establish routine
behavior, not whole-calculator correctness. GPL-3.0; see nxu8/COPYING.
"""
import hashlib
import html
import json
from pathlib import Path
import struct
import zlib
from nxu8.decoder import Decoder
from nxu8.machine import Machine

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'analysis/verification'
ROM = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def opcode_audit():
    source = json.loads((ROOT / 'tools/nxu8/reference-dispatch.json').read_text())
    reference = [None] * 65536
    for pattern in source['patterns']:
        bits = [1 << n for n in range(16) if pattern['varying_bits'] & (1 << n)]
        for permutation in range(1 << len(bits)):
            word = pattern['base']
            for n, bit in enumerate(bits):
                if permutation & (1 << n):
                    word |= bit
            if reference[word] is None:
                reference[word] = pattern['length']
    decoder = Decoder()
    differences = []
    for word, length in enumerate(reference):
        instruction = decoder.decode(struct.pack('<HH', word, 0), 0)
        actual = instruction.size if instruction else None
        if actual != length:
            differences.append({'word': hex(word), 'decoder_length': actual,
                                'reference_length': length})
    assert {x['word'] for x in differences} == {'0xf08e', '0xf0ce'}, differences
    save('decoder.json', {'reference': source['source'], 'words_examined': 65536,
                          'reference_valid': sum(x is not None for x in reference),
                          'differences': differences,
                          'explanation': 'The CPU accepts empty PUSH/POP lists as no-ops; the instruction specification omits them. Neither occurs in classified firmware code.'})


def png(framebuffer, scale=5):
    width, height = 96 * scale, 32 * scale
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            value = 28 if framebuffer[(y // scale) * 12 + (x // scale) // 8] & (128 >> ((x // scale) & 7)) else 238
            row.extend((value, value, value))
        rows.append(row)
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b'')


def behavior_audit():
    machine = Machine(ROM, ROOT / 'analysis/build')
    seen = set()
    tests = {}
    def capture():
        seen.update(n * 2 for n, count in enumerate(machine.counts) if count)
    def reset():
        capture()
        machine.reset()
    # Address calculation is compared to a mathematical pixel grid, including
    # signed Y and every X byte value, rather than to copied firmware code.
    for selected, base, stride in [(1, 0x87d0, 12), (0, 0xf800, 16)]:
        machine.ram[0x8121] = selected
        for y in range(-128, 128):
            for x in range(256):
                machine.reg(0, x); machine.reg(1, y & 255); machine.er(2, 0x8500)
                machine.call(0x3d28)
                assert machine.word(0x8500) == (base + y * stride + x // 8) & 65535
                assert machine.reg(0) == x % 8
    tests['pixel_address'] = {'cases': 131072, 'maps': ['RAM stride12', 'LCD stride16'], 'signed_y': [-128, 127], 'x': [0, 255]}
    reset()
    # Decode the packed fonts as five-bit bitstreams independently of the CPU.
    for font, base, height in [(10, 0x22, 9), (7, 0x400, 6)]:
        machine.ram[0x811f] = font
        for character in range(32, 208):
            machine.reg(0, character); machine.er(2, 0x8500); machine.call(0x3bbc)
            group, offset = divmod((character - 32) * 5, 8)
            expected = []
            for row in range(height):
                value = ROM[base + group * height + row] << 8
                if offset > 3:
                    value |= ROM[base + (group + 1) * height + row]
                expected.append(((value >> (11 - offset)) & 31) << 2)
            if character == 124:
                expected = [192] * height
            assert list(machine.ram[0x8500:0x8500 + height]) == expected
    tests['packed_fonts'] = {'cases': 352, 'glyph_range': [32, 207], 'row_heights': [9, 6], 'special_case': 'code124 is a vertical placeholder pattern C0'}
    machine.ram[0x811f] = 6
    for character in range(208, 256):
        machine.reg(0, character); machine.er(2, 0x8500); machine.call(0x3bbc)
        pair, side = divmod(character - 208, 2)
        expected = [(ROM[0x694 + pair * 5 + row] << (side * 4)) & 240 for row in range(5)]
        assert list(machine.ram[0x8500:0x8505]) == expected
    tests['tiny_font'] = {'cases': 48, 'glyph_range': [208, 255], 'row_height': 5}
    reset()
    # Exercise all byte values against five independent Boolean pixel models.
    checks = 0
    for mode in range(5):
        machine.ram[0x8120] = mode
        for mask in (1, 0x55, 0xaa, 0xff):
            for destination in range(256):
                for source in range(256):
                    machine.ram[0x8800] = destination; machine.ram[0x8500] = source
                    machine.er(0, 0x8800); machine.er(2, 0x8500); machine.word(0x8dee, mask)
                    machine.call(0x3c8e)
                    s = source & mask
                    expected = ((destination & ~mask) | s, destination | s,
                                destination & (~mask | s), destination ^ s,
                                (destination & ~mask) | (~s & mask))[mode] & 255
                    assert machine.ram[0x8800] == expected, (mode, mask, destination, source)
                    checks += 1
    for destination in (0x87db, 0x87dc):
        machine.ram[0x8120] = 1; machine.ram[destination] = 0; machine.ram[0x8500] = 255
        machine.er(0, destination); machine.er(2, 0x8500); machine.word(0x8dee, 255); machine.call(0x3c8e)
        assert machine.ram[destination] == (0 if destination < 0x87dc else 255)
    tests['compositor'] = {'cases': checks + 2, 'modes': ['replace', 'OR', 'AND', 'XOR', 'inverse replace'], 'masks': [1, 85, 170, 255], 'protected_below': '0x87dc'}
    reset()
    mapping = {}
    for token in range(256):
        machine.reg(0, token); machine.call(0x327a)
        mapping[f'{token:02x}'] = machine.reg(0)
    expected_tokens = [0x5d, 0x5e, 0x63, 0x68, 0x69, 0x6a, 0x6b, 0x73, 0x7c, 0x93, 0x98, 0x9f, 0xa4, 0xae]
    assert [int(t, 16) for t, kind in mapping.items() if kind != 15] == expected_tokens
    save('construct-tokens.json', mapping)
    tests['construct_classifier'] = {'cases': 256, 'recognized_tokens': len(expected_tokens)}
    reset()
    cases = {
        'literal': b'1+2\0',
        'power': b'2\x5e\xb83\xb9\0',
        'square-root': b'\x98\xb82\xb9\0',
        'absolute-value': b'\x63\xb82\xb9\0',
        'fraction': b'\xae\xbb\xb812\xb9\xb8345\xb9\xbc\0',
        'nested-fraction': b'\xae\xbb\xb8\x98\xb82\xb9\xb9\xb83\xb9\xbc\0',
        'sum': b'\x69\xb8X\xba1\xba5\xb9\0',
        'product': b'\x5d\xb8X\xba1\xba5\xb9\0',
        'integral': b'\x6a\xb8X\xba1\xba5\xb9\0',
        'derivative': b'\x6b\xb8X\xba1\xb9\0',
        'log-base': b'\x68\xb82\xba8\xb9\0',
        'nth-root': b'\x9f\xbb\xb83\xb9\xb88\xb9\xbc\0',
        'mixed-fraction': b'\x7c\xbd\xbb\xb82\xb9\xb81\xb9\xb83\xb9\xbc\0',
        'e-power': b'2\x73\xb83\xb9\0',
        'ten-power': b'2\x93\xb83\xb9\0',
        'repetend': b'0.\xa4\xb83\xb9\0',
    }
    samples = []
    gallery = ['<!doctype html><meta charset="utf-8"><title>Firmware rendering evidence</title><style>body{font:16px system-ui;max-width:1000px;margin:30px auto}img{image-rendering:pixelated;border:1px solid #888}pre{white-space:pre-wrap}</style><h1>Pixels drawn by the extracted firmware</h1><p>Each image is the actual 96 × 32 RAM framebuffer, enlarged 5×. Baseline 17; X coordinate 2. Measurement precedes drawing. Tall expressions are clipped by the screen.</p>']
    for name, expression in cases.items():
        reset()
        machine.ram[0x8121] = 1; machine.word(0x812c, 0x8200); machine.ram[0x8114] = 255
        for n, byte in enumerate(expression):
            machine.ram[0x8200 + n] = byte
        passes = []
        for mode in (0, 1):
            machine.reg(0, mode); machine.call(0xc634)
            machine.er(0, 0x8200); machine.er(2, 0x8500)
            machine.word(0x8dee, 2); machine.word(0x8df0, 17)
            before = sum(machine.ram_writes[0x87d0:0x8950])
            machine.call(0x9cd6)
            passes.append({'mode': mode, 'returned_pointer': hex(machine.er(0)), 'metrics': list(machine.ram[0x8500:0x8504]), 'framebuffer_writes': sum(machine.ram_writes[0x87d0:0x8950]) - before})
        assert passes[0]['returned_pointer'] != '0x0', (name, passes)
        assert passes[0]['metrics'] == passes[1]['metrics'], (name, passes)
        assert passes[0]['framebuffer_writes'] == 0
        frame = bytes(machine.ram[0x87d0:0x8950])
        (OUT / f'{name}.png').write_bytes(png(frame))
        (OUT / f'{name}.bin').write_bytes(frame)
        samples.append({'name': name, 'tokens': expression.hex(), 'passes': passes, 'framebuffer_sha256': hashlib.sha256(frame).hexdigest()})
        gallery.append(f'<h2>{html.escape(name)}</h2><img src="{name}.png"><pre>{expression.hex()}\n{html.escape(json.dumps(passes))}</pre>')
    (OUT / 'gallery.html').write_text('\n'.join(gallery) + '\n')
    tests['layout_samples'] = {'cases': len(samples), 'passes_per_case': 2, 'invariants': ['nonzero returned expression pointer', 'equal measured/drawn metrics', 'measurement writes no framebuffer pixels']}
    save('layout-samples.json', samples)
    # Native arithmetic creates the tagged values; assert exact formatter
    # tokens, then run the full result-display controller on those values.
    numeric_samples = []
    for name, numerator, denominator, operation, format_kind, expected in [
        ('exact-third', 1, 3, 0x16058, 0, 'aebbb831b9b833b9bc'),
        ('improper-fraction', 7, 3, 0x16058, 0, 'aebbb837b9b833b9bc'),
        ('exact-square-root', 2, 1, 0x1c780, 13, '98b832b9'),
        ('simplified-square-root', 8, 1, 0x1c780, 13, '3298b832b9'),
        ('square-root-twelve', 12, 1, 0x1c780, 13, '3298b833b9'),
        ('perfect-square-root', 9, 1, 0x1c780, 13, '33'),
        ('mixed-numeric-fraction', 7, 3, 0x16058, 0, '7cbdbbb832b9b831b9b833b9bc'),
        ('two-surds-over-two', 2, 3, 0x1c780, 13, 'aebbb898b833b92b98b832b9b9b832b9bc'),
    ]:
        reset()
        machine.ram[0x80f9] = 193; machine.ram[0x8106] = 1; machine.ram[0x8121] = 1
        machine.ram[0x8107] = int(name == 'mixed-numeric-fraction')
        machine.ram[0x8100] = format_kind; machine.word(0x812c, 0x8200)
        for address, value in [(0x8300, numerator), (0x8320, denominator)]:
            machine.er(0, address); machine.reg(2, value); machine.call(0x1d08c)
        machine.er(0, 0x8300); machine.er(2, 0x8320); machine.er(12, 0x8300)
        machine.reg(6, 193); machine.reg(10, 0); machine.call(operation)
        assert machine.reg(0) == 0
        if name == 'two-surds-over-two':
            machine.er(0, 0x8320); machine.call(0x1c780)
            machine.er(0, 0x8300); machine.er(2, 0x8320); machine.call(0x15f34)
            machine.er(0, 0x8320); machine.reg(2, 2); machine.call(0x1d08c)
            machine.er(0, 0x8300); machine.er(2, 0x8320); machine.call(0x15f58)
            assert machine.reg(0) == 0
        number = bytes(machine.ram[0x8300:0x830a]).hex()
        machine.er(0, 0x8300); machine.er(2, 0x8500); machine.word(0x8dee, 0); machine.call(0xc060)
        tokens = bytes(machine.ram[0x8500:0x8540]).split(b'\0')[0].hex()
        assert tokens == expected, (name, tokens)
        returned_kind = machine.reg(0)
        machine.er(0, 0x8300); machine.call(0xb070)
        assert machine.word(0x812c) == 0x8200
        frame = bytes(machine.ram[0x87d0:0x8950])
        assert any(frame)
        (OUT / f'{name}.png').write_bytes(png(frame))
        (OUT / f'{name}.bin').write_bytes(frame)
        numeric_samples.append({'name': name, 'numeric_record': number, 'formatter_tokens': tokens, 'format_kind': returned_kind, 'framebuffer_sha256': hashlib.sha256(frame).hexdigest()})
        gallery.append(f'<h2>{name}: complete result controller</h2><img src="{name}.png"><pre>{number}\n{tokens}</pre>')
        if name == 'improper-fraction':
            record = bytes.fromhex(number)
            for routine, expected_part in [(0x1c93e, b'2'), (0x1c92a, b'1'), (0x1c916, b'3')]:
                for n, byte in enumerate(record): machine.ram[0x8300 + n] = byte
                machine.er(0, 0x8300); machine.call(routine)
                machine.ram[0x8100] = 10; machine.er(0, 0x8300); machine.er(2, 0x8500)
                machine.word(0x8dee, 0); machine.call(0xc060)
                assert bytes(machine.ram[0x8500:0x8520]).split(b'\0')[0] == expected_part
        if name == 'simplified-square-root':
            machine.er(0, 0x8300); machine.call(0x18176)
            for n, expected_part in enumerate((b'2', b'2', b'0', b'0', b'1')):
                machine.ram[0x8100] = 10; machine.er(0, 0x8300 + n * 10); machine.er(2, 0x8500)
                machine.word(0x8dee, 0); machine.call(0xc060)
                assert bytes(machine.ram[0x8500:0x8520]).split(b'\0')[0] == expected_part
    save('numeric-samples.json', numeric_samples)
    tests['exact_numeric_output'] = {'cases': len(numeric_samples), 'invariants': ['arithmetic succeeded', 'formatter tokens equal independent expected form', 'controller draws pixels', 'expression pointer restored']}
    # Defined failure paths must fail without pretending to have laid out a
    # subtree. A child allocation failure leaves the outer handler count;
    # initialize_layout_pass clears that state before the following pass.
    for name, counter, slots, expression in [('recursion-limit', 27, 0, b'1\0'), ('metric-pool-limit', 0, 50, b'2\x5e\xb83\xb9\0')]:
        reset()
        machine.ram[0x8121] = 1; machine.word(0x812c, 0x8200); machine.ram[0x8114] = 255
        machine.reg(0, 0); machine.call(0xc634)
        machine.ram[0x8007] = counter; machine.ram[0x8008] = slots
        for n, byte in enumerate(expression): machine.ram[0x8200 + n] = byte
        machine.er(0, 0x8200); machine.er(2, 0x8500); machine.word(0x8dee, 2); machine.word(0x8df0, 17)
        machine.call(0x9cd6)
        assert machine.er(0) == 0, name
        assert machine.ram[0x8007] == counter + (1 if name == 'metric-pool-limit' else 0), name
        machine.reg(0, 0); machine.call(0xc634)
        assert machine.ram[0x8007] == 0 and machine.ram[0x8008] == 0
    tests['layout_limits'] = {'cases': 2, 'paths': ['recursion counter >27', 'metric slots >50']}
    (OUT / 'gallery.html').write_text('\n'.join(gallery) + '\n')
    capture()
    save('behavior.json', {'rom_sha256': hashlib.sha256(ROM).hexdigest(), 'tests': tests, 'unique_executed_instruction_starts': len(seen), 'limitation': 'Passive peripherals; finite samples do not prove every rendering or numeric formatting path.'})
    save('executed-addresses.json', [hex(a) for a in sorted(seen)])


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    opcode_audit()
    behavior_audit()
    print((OUT / 'behavior.json').read_text())
