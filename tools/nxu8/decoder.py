"""nX-U8 instruction decoder, using the GPL-3.0 table in isa.txt.

This module is licensed under GPL-3.0; see COPYING and provenance.json.
"""
from dataclasses import dataclass
from pathlib import Path
import re

CONDITIONS = ('GE', 'LT', 'GT', 'LE', 'GES', 'LTS', 'GTS', 'LES',
              'NE', 'EQ', 'NV', 'OV', 'PS', 'NS', 'AL', 'INVALID')


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def tohex(value, digits):
    return f'{value & ((1 << (digits * 4)) - 1):0{digits}X}'


def signedtohex(value, bits):
    value = signed(value, bits)
    return ('-' if value < 0 else '') + f'{abs(value):0{(bits + 3) // 4}X}'


def evaluate(expression, fields):
    expression = expression.replace('i << 25 >> 25', 'signed(i, 7)')
    expression = expression.replace('(int)(signed char)r', 'signed(r, 8)')
    # The table uses only these simple C++ conditional expressions.
    match = re.fullmatch(r'(\w+)\s*==\s*(\w+)\s*\?\s*("[^"]*")\s*:\s*("[^"]*")', expression)
    if match:
        a, b, yes, no = match.groups()
        expression = f'({yes} if {a} == {b} else {no})'
    return eval(expression, {'__builtins__': {}, 'signed': signed,
                             'tohex': tohex, 'signedtohex': signedtohex,
                             'cond': CONDITIONS}, fields)


@dataclass(frozen=True)
class Instruction:
    address: int
    raw: bytes
    mnemonic: str
    operands: str
    fields: dict

    @property
    def size(self):
        return len(self.raw)

    @property
    def next_address(self):
        return self.address & ~0xFFFF | (self.address + self.size) & 0xFFFF

    @property
    def target(self):
        if self.mnemonic == 'BC':
            return self.address & ~0xFFFF | (self.address + 2 + signed(self.fields['r'], 8) * 2) & 0xFFFF
        if self.mnemonic in ('B', 'BL') and 'g' in self.fields:
            return self.fields['g'] << 16 | self.fields['D'] * 256 + self.fields['C']
        return None

    @property
    def terminates(self):
        return (self.mnemonic in ('B', 'RT', 'RTI', 'BRK') or
                self.mnemonic == 'POP' and 'PC' in self.operands or
                self.mnemonic == 'BC' and self.fields['c'] == 14)

    def line(self):
        return f'{self.address:06X}   {self.raw.hex(" ").upper():<11}   {self.mnemonic:<7} {self.operands}'.rstrip()


class Decoder:
    def __init__(self):
        self.patterns = []
        for line in (Path(__file__).parent / 'isa.txt').read_text().splitlines():
            match = re.match(r'^([01A-Za-z]{8}(?: [01A-Za-z]{8})+) (\S+)\s*(.*)$', line)
            if not match:
                continue
            bits, mnemonic, template = match.groups()
            pattern = bits.split()
            masks = [int(''.join('1' if c in '01' else '0' for c in b), 2) for b in pattern]
            values = [int(''.join(c if c in '01' else '0' for c in b), 2) for b in pattern]
            fields = {}
            for index, byte in enumerate(pattern):
                for shift, c in enumerate(reversed(byte)):
                    if c not in '01':
                        fields.setdefault(c, []).append((index, shift))
            self.patterns.append((masks, values, fields, mnemonic, template))
        self.dispatch = [None] * 65536
        for ix, (masks, values, _, _, _) in enumerate(self.patterns):
            mask, value = masks[0] | masks[1] << 8, values[0] | values[1] << 8
            varying = [b for b in range(16) if not mask & (1 << b)]
            for variant in range(1 << len(varying)):
                word = value | sum(((variant >> bit) & 1) << shift for bit, shift in enumerate(varying))
                if self.dispatch[word] is not None:
                    raise ValueError(f'Conflicting ISA patterns for {word:04x}')
                self.dispatch[word] = ix

    def decode(self, rom, address):
        if address & 1 or address + 2 > len(rom):
            return None
        word = rom[address] | rom[address + 1] << 8
        index = self.dispatch[word]
        if index is None:
            return None
        masks, values, field_bits, mnemonic, template = self.patterns[index]
        raw = bytearray()
        for offset in range(len(masks)):
            pos = address & ~0xFFFF | (address + offset) & 0xFFFF
            if pos >= len(rom):
                return None
            raw.append(rom[pos])
        if any(b & mask != value for b, mask, value in zip(raw, masks, values)):
            return None
        fields = {'pc': address}
        for name, positions in field_bits.items():
            fields[name] = sum(((raw[index] >> shift) & 1) << bit for bit, (index, shift) in enumerate(positions))
        if mnemonic == 'BC' and fields['c'] == 15:
            return None
        if 'EXTBW' in template:
            if fields['m'] != fields['n']:
                return None
            mnemonic = 'EXTBW'
            template = 'ER{n*2}'
        operands = re.sub(r'\{([^}]+)\}', lambda m: str(evaluate(m[1], fields)), template)
        ins = Instruction(address, bytes(raw), mnemonic, operands, fields)
        if mnemonic == 'BC':
            operands = f'{CONDITIONS[fields["c"]]}, {ins.target:05X}h'
            ins = Instruction(address, bytes(raw), mnemonic, operands, fields)
        return ins
