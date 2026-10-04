#!/usr/bin/env python3
"""Compare readable matrix/vector storage with original-ROM helpers.

No numeric arithmetic, ROM or CPU library is linked to production C. Native
oracle calls verify full dimensions, all810 payload bytes, allocator masks,
reference bytes, cell admission and observable partial alias effects.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import random
import subprocess
from c_verification import ROOT, write_report
from nxu8.machine import Machine

class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]
class Slot(C.Structure):
    _fields_ = [('rows', C.c_uint8), ('columns', C.c_uint8), ('cells', Number * 9)]
class Bank(C.Structure):
    _fields_ = [('slots', Slot * 9), ('temporary_mask', C.c_uint8)]
class Value(C.Structure):
    _fields_ = [('reference', Number), ('rows', C.c_uint8), ('columns', C.c_uint8), ('cells', Number * 9)]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=1000)
    parser.add_argument('--no-report', action='store_true')
    parser.add_argument('--optimization', choices=['O2', 'O3'], default='O2')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/linalg-store'
    build.mkdir(parents=True, exist_ok=True)
    library = build / 'linalg-store.so'
    sources = ['csrc/linalg/fx_linalg_store.c']
    headers = ['csrc/linalg/fx_linalg_store.h', 'csrc/linalg/fx_linalg.h', 'csrc/numeric/fx_numeric.h']
    subprocess.run(['gcc', '-std=c99', '-'+args.optimization, '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / path) for path in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    signatures = {
        'reset': [C.POINTER(Bank)],
        'define': [C.POINTER(Bank), C.c_uint, C.c_uint8, C.c_uint8],
        'ensure_dimensions': [C.POINTER(Bank), C.c_uint, C.c_uint8, C.c_uint8],
        'copy': [C.POINTER(Bank), C.c_uint, C.c_uint],
        'copy_answer': [C.POINTER(Bank), C.POINTER(Number)],
        'begin_evaluation': [C.POINTER(Bank), C.c_uint8],
        'first_free': [C.c_uint8],
        'mark': [C.POINTER(Bank), C.c_uint],
        'release': [C.POINTER(Bank), C.c_uint],
        'reference': [C.POINTER(Number), C.POINTER(Bank), C.c_uint8, C.c_uint, C.POINTER(C.c_uint8)],
        'write_cell': [C.POINTER(Bank), C.c_uint, C.c_uint, C.c_uint, C.POINTER(Number), C.POINTER(C.c_uint8)],
        'read_cell': [C.POINTER(Number), C.POINTER(Bank), C.c_uint, C.c_uint, C.c_uint, C.POINTER(C.c_uint8)],
        'temporary': [C.POINTER(Number), C.POINTER(Bank), C.POINTER(Number), C.POINTER(C.c_uint8)],
        'value': [C.POINTER(Value), C.POINTER(Bank), C.POINTER(Number)],
        'store_value': [C.POINTER(Bank), C.c_uint, C.POINTER(Value)],
    }
    for name, signature in signatures.items():
        getattr(lib, 'fx_linalg_bank_' + name).argtypes = signature
    machine = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), build / 'oracle')
    rng = random.Random(0x16954)
    counts, failures = {}, []
    native_calls = 0

    def check(group, actual, expected, detail):
        counts[group] = counts.get(group, 0) + 1
        if actual != expected:
            failure = {'group': group, 'actual': actual, 'expected': expected, 'detail': detail}
            failures.append(failure)
            if len(failures) <= 10: print(json.dumps({'group': group, 'detail': detail}))

    def call(entry):
        nonlocal native_calls
        machine.call(entry, limit=3000000)
        native_calls += 1

    def put(address, data):
        for index, byte in enumerate(data): machine.ram[address + index] = byte

    def prepare(rows=None, columns=None, mask=None, payload=None):
        bank = Bank()
        bank.temporary_mask = rng.randrange(256) if mask is None else mask
        machine.reset()
        machine.ram[0x8125] = bank.temporary_mask
        for identity in range(9):
            bank.slots[identity].rows = rng.randrange(1, 4) if rows is None else rows
            bank.slots[identity].columns = rng.randrange(1, 4) if columns is None else columns
            data = bytes(rng.randrange(256) for _ in range(90)) if payload is None else payload
            for cell in range(9): bank.slots[identity].cells[cell] = Number.from_buffer_copy(data[cell*10:cell*10+10])
            machine.word(0x80e0 + 2*identity, bank.slots[identity].rows + 256*bank.slots[identity].columns)
            put(0x829e + 90*identity, data)
        return bank

    def compare_bank(group, bank, detail):
        dimensions = bytes(byte for slot in bank.slots for byte in (slot.rows, slot.columns)).hex()
        payload = b''.join(bytes(slot.cells) for slot in bank.slots).hex()
        check(group, dimensions, bytes(machine.ram[0x80e0:0x80f2]).hex(), detail)
        check(group, payload, bytes(machine.ram[0x829e:0x85c8]).hex(), detail)
        check(group, bank.temporary_mask, machine.ram[0x8125], detail)

    for mask in range(256):
        machine.reset(); machine.reg(0, mask); call(0x15ba8)
        check('temporary_first_free', lib.fx_linalg_bank_first_free(mask), machine.reg(4), {'mask': mask})
        for name, entry in [('mark', 0x15bbc), ('release', 0x15bca)]:
            for identity in range(4, 9):
                bank = Bank(); bank.temporary_mask = mask
                machine.reg(0, mask); machine.reg(4, identity); call(entry)
                detail = {'mask': mask, 'identity': identity}
                check('temporary_' + name, getattr(lib, 'fx_linalg_bank_' + name)(C.byref(bank), identity), 0, detail)
                check('temporary_' + name, bank.temporary_mask, machine.reg(0), detail)

    for identity in range(9):
        for rows in range(4):
            for columns in range(4):
                bank = prepare(); detail = {'identity': identity, 'rows': rows, 'columns': columns}
                machine.reg(0, identity); machine.reg(1, rows); machine.reg(2, columns); call(0x1d2c6)
                check('dimension_define', lib.fx_linalg_bank_define(C.byref(bank), identity, rows, columns), 0, detail)
                compare_bank('dimension_define', bank, detail)
                # Same shape preserves all physical cells; changed shape clears
                # all90 bytes, including inactive cells.
                for new_rows, new_columns in [(rows, columns), (columns, rows)]:
                    bank = prepare(rows=rows, columns=columns)
                    put(0x8900, bytes([new_rows, new_columns]))
                    machine.reg(0, identity); machine.er(2, 0x8900); call(0xd2d8)
                    check('dimension_ensure', lib.fx_linalg_bank_ensure_dimensions(C.byref(bank), identity, new_rows, new_columns), 0, detail)
                    compare_bank('dimension_ensure', bank, detail)

    for source in range(9):
        for destination in range(9):
            for entry in [0x1694c, 0x1695c]:
                bank = prepare(); detail = {'source': source, 'destination': destination, 'entry': hex(entry)}
                if entry == 0x1694c: machine.reg(0, destination); machine.reg(1, source)
                else: machine.reg(4, 0x60 | source); machine.reg(5, 0x90 | destination)
                call(entry)
                check('full_slot_copy', lib.fx_linalg_bank_copy(C.byref(bank), destination, source), 0, detail)
                compare_bank('full_slot_copy', bank, detail)
        for kind in [0x60, 0x90]:
            bank = prepare(); reference = Number.from_buffer_copy(bytes([kind | source]) + bytes(range(1, 10)))
            put(0x8900, bytes(reference)); machine.er(0, 0x8900); call(0x16954)
            detail = {'source': source, 'kind': kind}
            check('answer_copy', lib.fx_linalg_bank_copy_answer(C.byref(bank), C.byref(reference)), 0, detail)
            compare_bank('answer_copy', bank, detail)
            check('answer_copy', bytes(reference).hex(), bytes(machine.ram[0x8900:0x890a]).hex(), detail)

    bank = prepare(); call(0x1d2fc); lib.fx_linalg_bank_reset(C.byref(bank))
    compare_bank('storage_reset', bank, {})
    for context in [0xc1, 6, 7, 8, 0xc4]:
        lib.fx_linalg_bank_begin_evaluation(C.byref(bank), context)
        check('context_mask', bank.temporary_mask, 0x18 if context == 6 else 0, {'context': context})

    for kind in [0x60, 0x90]:
        for identity in range(4):
            for dimension in [0, 0x202, 0x100, 1]:
                bank = prepare(); bank.slots[identity].rows = dimension & 255; bank.slots[identity].columns = dimension >> 8
                machine.word(0x80e0 + 2*identity, dimension)
                number = Number.from_buffer_copy(bytes([0xee])*10); put(0x8900, bytes(number)); machine.er(12, 0x8900); machine.reg(7, 0); machine.reg(0, kind | identity); call(0x1705c)
                firmware_status = C.c_uint8(255); detail = {'kind': kind, 'identity': identity, 'dimension': dimension}
                check('reference_admission', lib.fx_linalg_bank_reference(C.byref(number), C.byref(bank), kind, identity, C.byref(firmware_status)), 0, detail)
                check('reference_admission', firmware_status.value, machine.reg(2), detail)
                check('reference_admission', bytes(number).hex(), bytes(machine.ram[0x8900:0x890a]).hex(), detail)
                compare_bank('reference_admission', bank, detail)

    for index in range(args.random_cases):
        bank = prepare(); identity = rng.randrange(9); row = rng.randrange(1, 5); column = rng.randrange(1, 5)
        number = Number.from_buffer_copy(bytes(rng.randrange(256) for _ in range(10))); put(0x8900, bytes(number))
        machine.er(0, 0x8900); machine.reg(2, identity); machine.reg(3, row); machine.ram[0x8dee] = column
        write = bool(index % 2); call(0x1d362 if write else 0x1d3c4)
        firmware_status = C.c_uint8(255); group = 'cell_write' if write else 'cell_read'; detail = {'identity': identity, 'row': row, 'column': column}
        if write: host = lib.fx_linalg_bank_write_cell(C.byref(bank), identity, row, column, C.byref(number), C.byref(firmware_status))
        else: host = lib.fx_linalg_bank_read_cell(C.byref(number), C.byref(bank), identity, row, column, C.byref(firmware_status))
        check(group, host, 0, detail); check(group, firmware_status.value, machine.reg(0), detail)
        check(group, bytes(number).hex(), bytes(machine.ram[0x8900:0x890a]).hex(), detail); compare_bank(group, bank, detail)

    for write in [True, False]:
        for delta in range(-10, 11):
            bank = prepare(rows=2, columns=3, payload=bytes(range(90)))
            pointer = C.cast(C.byref(bank.slots[0].cells, 10 + delta), C.POINTER(Number))
            machine.er(0, 0x829e + 10 + delta); machine.reg(2, 0); machine.reg(3, 1); machine.ram[0x8dee] = 2
            call(0x1d362 if write else 0x1d3c4); firmware_status = C.c_uint8(255); detail = {'write': write, 'delta': delta}
            if write: host = lib.fx_linalg_bank_write_cell(C.byref(bank), 0, 1, 2, pointer, C.byref(firmware_status))
            else: host = lib.fx_linalg_bank_read_cell(pointer, C.byref(bank), 0, 1, 2, C.byref(firmware_status))
            check('partial_cell_alias', host, 0, detail); check('partial_cell_alias', firmware_status.value, machine.reg(0), detail); compare_bank('partial_cell_alias', bank, detail)

    for mask in [0, 0x80, 0xc0, 0xe0, 0xf0, 0xf8, 0xff]:
        for kind in [0x60, 0x90]:
            for identity in [0, 1, 2, 3, 4, 8]:
                bank = prepare(mask=mask); reference = Number.from_buffer_copy(bytes([kind | identity]) + bytes(rng.randrange(256) for _ in range(9)))
                number = Number(); firmware_status = C.c_uint8(255); machine.reg(0, mask); call(0x15ba8); chosen = machine.reg(4)
                if identity < 4 and chosen:
                    # Exact prepared stage1648E..1653C, stopping naturally
                    # before numerical dispatch. No instruction is replaced.
                    put(0x8900, bytes(reference)); machine.er(12, 0x8900); machine.reg(0, mask); machine.reg(1, 0)
                    machine.lib.harness_set_sp(0x8dee); machine.lib.harness_set_lr(0x2fffe); machine.lib.harness_set_pc(0x1648e)
                    stop = machine.lib.harness_run(3000000, 0x1653c, False); native_calls += 1
                    if stop != 100: raise RuntimeError('Temporary reference stage did not reach1653C')
                check('temporary_reference', lib.fx_linalg_bank_temporary(C.byref(number), C.byref(bank), C.byref(reference), C.byref(firmware_status)), 0, {'mask': mask, 'kind': kind, 'identity': identity})
                expected = bytearray(bytes(reference))
                if identity < 4 and chosen: expected[0] = kind | chosen
                detail = {'mask': mask, 'kind': kind, 'identity': identity}
                check('temporary_reference', bytes(number).hex(), expected.hex(), detail)
                if identity < 4 and chosen: check('temporary_reference', bytes(number).hex(), bytes(machine.ram[0x8900:0x890a]).hex(), detail)
                check('temporary_reference', firmware_status.value, 7 if identity < 4 and not chosen else 0, detail)
                compare_bank('temporary_reference', bank, detail)

    for identity in range(9):
        bank = prepare(rows=2, columns=3)
        reference = Number.from_buffer_copy(bytes([0x60 | identity]) + bytes(range(1, 10))); value = Value(); detail = {'identity': identity}
        check('value_adapters', lib.fx_linalg_bank_value(C.byref(value), C.byref(bank), C.byref(reference)), 0, detail)
        check('value_adapters', bytes(value.reference), bytes(reference), detail)
        check('value_adapters', bytes(value.cells), bytes(bank.slots[identity].cells), detail)
        check('value_adapters', (value.rows, value.columns), (2, 3), detail)
        value.reference.bytes[0] = 0xf3; value.rows = 1; value.columns = 2; value.cells[8].bytes[0] = 0x77
        check('value_adapters', lib.fx_linalg_bank_store_value(C.byref(bank), identity, C.byref(value)), 0, detail)
        check('value_adapters', bytes(bank.slots[identity].cells), bytes(value.cells), detail)
        check('value_adapters', (bank.slots[identity].rows, bank.slots[identity].columns), (1, 2), detail)

    report = {'optimization': args.optimization, 'cases': sum(counts.values()), 'native_calls': native_calls, 'domains': counts, 'failures': failures,
              'comparison': 'Full18 dimension bytes,810 payload bytes, independent temporary bitmap, reference bytes, native R2/R0 statuses and descending-word partial-cell aliases.',
              'scope': 'Prepared nine-slot shared Mat/Vct bank, definition/ensure/reset/copy/Ans copy, temporary choose/reserve/release/reference rewrite, variable-reference early type admission, positive one-based cell0..5 access, host leaf state adapters. No complete parser/controller/display/hardware implementation. Native zero/OOB address arithmetic outside prepared contract; UI cursor reset is outside numerical bank.'}
    if failures:
        (build / 'failures.json').write_text(json.dumps(report, indent=2) + '\n')
        raise AssertionError(f'{len(failures)} matrix/vector storage mismatches')
    if not args.no_report:
        report = write_report('analysis/c-verification/linalg_store.json', report, sources + headers + ['tools/c_verification.py'],
                              'tools/test_linalg_store_c.py')
    print(json.dumps({'status': 'pass', 'cases': report['cases'], 'native_calls': native_calls, 'domains': counts}, indent=2))

if __name__ == '__main__': main()
