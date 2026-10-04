#!/usr/bin/env python3
"""Verify exact-output permission across original application state fields.

GPL-3.0-or-later. Original firmware executes only in the independent oracle.
"""
import ctypes as C
from itertools import product
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
from trace_natural_result import settings
from c_verification import write_report


def main():
    directory = ROOT / 'analysis/build/trig/context'
    directory.mkdir(parents=True, exist_ok=True)
    library = directory / 'context.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', str(ROOT / 'csrc/trig/fx_math_context.c'),
                    '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_exact_output_allowed.argtypes = [C.POINTER(C.c_uint8)]
    lib.fx_exact_output_allowed.restype = C.c_int
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    assert rom[0x1ffe1] == 0
    machine = Machine(rom, directory / 'oracle')
    addresses = [0x80f5, 0x80fc, 0x8106, 0x810c, 0x80f9, 0x8124]
    baseline = [0, 0, 1, 0, 0xc1, 0]
    cases = [('all-gates-enabled', baseline)]
    for position, address in enumerate(addresses):
        for value in range(256):
            context = baseline[:]; context[position] = value
            cases.append((f'field-{address:04x}-{value:02x}', context))
    # Cross gated states to verify that the original fallthrough/return
    # behavior remains correct when several restrictions are active.
    choices = [[0, 0xed, 0xff], [0, 0x40, 0xff], [0, 1, 255],
               [0, 1, 2], [0, 0xc1, 0xff], [0, 1, 0xff]]
    for combination in product(*choices): cases.append(('gate-combination', list(combination)))
    failures = []
    for name, values in cases:
        machine.reset(); settings(machine)
        for address, value in zip(addresses, values): machine.ram[address] = value
        memory = (C.c_uint8 * 65536).from_buffer_copy(bytes(machine.ram))
        before = bytes(memory)
        actual = lib.fx_exact_output_allowed(memory)
        machine.call(0x18212)
        expected = machine.reg(0)
        if actual != expected or bytes(memory) != before:
            failures.append({'case': name, 'context': values,
                             'actual': actual, 'expected': expected,
                             'immutable': bytes(memory) == before})
    assert lib.fx_exact_output_allowed(None) == 0
    report = {'cases': len(cases), 'failures': len(failures), 'mismatches': failures,
              'scope': 'original18212 exact-output eligibility for this fixed firmware variant',
              'input': 'all256 values of each of six application-state fields plus729 gate combinations',
              'output': 'native permission byte and immutable source state',
              'limitation': 'fixed zero capability byte1FFE1; native call-stack writes and full evaluator/UI I/O are outside this predicate suite'}
    path = ROOT / 'analysis/c-verification/math_context.json'
    if failures:
        report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, ['csrc/trig/fx_math_context.c', 'csrc/trig/fx_math_context.h',
                                   'tools/trace_natural_result.py', 'tools/c_verification.py'],
                     'tools/test_math_context_c.py')
    print(f'{len(cases)} exact-output context checks, {len(failures)} mismatches')
    for failure in failures[:12]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
