#!/usr/bin/env python3
"""Compare explicit evaluator storage with original native data helpers.

All65536 RAM bytes are compared, excluding only bytes actually written in the
prepared CPU frame. Numerical operand-stack data and variable aliases remain
observable. Native instructions are never substituted or executed by C.
"""
import argparse
import ctypes as C
import hashlib
import itertools
import json
import random
import subprocess

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report
from nxu8.machine import Machine


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


class Storage(C.Structure):
    _fields_ = [('ram', C.POINTER(C.c_uint8)), ('ram_size', C.c_size_t),
                ('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t)]


class StageResult(C.Structure):
    _fields_ = [('operation', C.c_uint8), ('native_status', C.c_uint8),
                ('route', C.c_uint8)]


SHIM = r'''
#include <stdint.h>
#include <stdbool.h>
extern uint32_t harness_get_pc(void);
extern int harness_run(uint64_t, uint32_t, bool);
int storage_oracle_stage(uint64_t limit) {
    uint64_t index;
    for (index=0; index<limit; ++index) {
        uint32_t pc=harness_get_pc();
        int status;
        if (pc==0x16538) return 1;
        if (pc==0x16598) return 0;
        if (pc==0x1658e) return 7;
        if (pc==0x16592) return 3;
        status=harness_run(1, 0x2fffe, false);
        if (status!=103) return -100-status;
    }
    return -2;
}
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=1000)
    ap.add_argument('--optimization', choices=('O2', 'O3'), default='O2')
    ap.add_argument('--no-report', action='store_true')
    args = ap.parse_args()
    build = ROOT/'analysis/build/eval-storage'
    build.mkdir(parents=True, exist_ok=True)
    sources = implementation_inputs(ROOT, ['csrc/parse/fx_eval_storage.c'])
    sources += ['tools/test_eval_storage_c.py', 'tools/c_verification.py',
                'tools/c_build_inputs.py', 'tools/nxu8/machine.py',
                'tools/nxu8/harness.c', 'tools/nxu8/vendor/SimU8/core.c',
                'firmware/fx-991es-plus-c-ver4.bin',
                'csrc/parse/eval_storage_manifest.json',
                'csrc/parse/storage/understood_ranges.json']
    sources += [str(p.relative_to(ROOT)) for p in
                (ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
    pins = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            for name in sorted(set(sources))}
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    machine = Machine(rom, build/'oracle')
    # The shim only supplies several natural stop addresses to the existing
    # unmodified native harness. It is not linked into production storage.
    machine.lib = C.CDLL(str((build/'oracle/nxu8-harness.so').resolve()), mode=C.RTLD_GLOBAL)
    library = build/('eval-storage-'+args.optimization+'.so')
    subprocess.run(['gcc', '-std=c99', '-'+args.optimization, '-Wall', '-Wextra',
        '-Werror', '-pedantic', '-shared', '-fPIC',
        str(ROOT/'csrc/parse/fx_eval_storage.c'), '-x', 'c', '-', '-o', str(library)],
        input=SHIM, text=True, check=True)
    lib = C.CDLL(str(library))
    # Restore ctypes annotations on the promoted handle.
    machine.lib.harness_set_pc.argtypes = [C.c_uint32]
    machine.lib.harness_get_pc.restype = C.c_uint32
    machine.lib.harness_set_reg.argtypes = [C.c_uint, C.c_uint8]
    machine.lib.harness_get_reg.argtypes = [C.c_uint]
    machine.lib.harness_get_reg.restype = C.c_uint8
    machine.lib.harness_set_sp.argtypes = [C.c_uint16]
    machine.lib.harness_set_lr.argtypes = [C.c_uint32]
    machine.lib.harness_run.argtypes = [C.c_uint64, C.c_uint32, C.c_bool]
    machine.lib.harness_init.argtypes = [C.c_void_p, C.c_size_t]
    signatures = {
        'first_free': [C.c_uint8], 'reserve': [C.c_uint8, C.c_uint8],
        'release': [C.c_uint8, C.c_uint8],
        'copy_slot': [C.POINTER(Storage), C.c_uint8, C.c_uint8],
        'copy_bytes': [C.POINTER(Storage), C.c_uint16, C.c_uint16, C.c_size_t],
        'temporary': [C.POINTER(Storage), C.POINTER(Number), C.POINTER(C.c_uint8), C.POINTER(C.c_uint8)],
        'temporary_address': [C.POINTER(Storage), C.c_uint16, C.POINTER(C.c_uint8), C.POINTER(C.c_uint8)],
        'stage': [C.POINTER(Storage), C.POINTER(Number), C.POINTER(Number),
                  C.c_uint8, C.c_uint8, C.c_uint8, C.POINTER(C.c_uint8), C.POINTER(StageResult)],
        'stage_address': [C.POINTER(Storage), C.c_uint16, C.c_uint8, C.c_uint8,
                          C.c_uint8, C.POINTER(C.c_uint8), C.POINTER(StageResult)]}
    for name, signature in signatures.items():
        fn = getattr(lib, 'fx_eval_storage_'+name); fn.argtypes = signature
        fn.restype = C.c_uint8 if name in ('first_free', 'reserve', 'release') else C.c_int
    lib.storage_oracle_stage.argtypes = [C.c_uint64]
    lib.storage_oracle_stage.restype = C.c_int
    rom_buffer = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    rng = random.Random(0x163f01695c)
    baseline = bytes(rng.randrange(256) for _ in range(65536))
    failures, domains, limits = [], {}, []
    native_calls = 0

    def compare(group, expected, actual, detail):
        domains[group] = domains.get(group, 0)+1
        if expected != actual:
            failures.append(dict(group=group, expected=expected, actual=actual, **detail))
            if len(failures) <= 12: print(json.dumps(failures[-1]), flush=True)

    def prepare(updates=(), initial_memory=None):
        memory = bytearray(baseline if initial_memory is None else initial_memory)
        for address, data in updates: memory[address:address+len(data)] = data
        buffer = (C.c_uint8*65536).from_buffer(memory)
        storage = Storage(buffer, 65536, rom_buffer, len(rom))
        machine.reset()
        C.memmove(C.addressof(machine.ram), C.addressof(buffer), 65536)
        return memory, buffer, storage

    def full_ram(group, memory, detail):
        native = bytearray(machine.ram)
        # These are actual writes in the chosen CPU-frame region. No data
        # arena, numeric stack, controller byte or variable bank is omitted.
        for address in range(0x8d00, 0x8df0):
            if machine.ram_writes[address]: native[address] = memory[address]
        if memory != native:
            differences = [dict(address=f'{i:04x}', native=native[i], c=memory[i])
                           for i in range(65536) if memory[i] != native[i]]
            compare(group, [], differences[:30], dict(total_differences=len(differences), **detail))
        else: compare(group, True, True, detail)

    def call(entry):
        nonlocal native_calls
        machine.call(entry, limit=3000000); native_calls += 1

    for mask in range(256):
        memory, buffer, storage = prepare()
        machine.reg(0, mask); call(0x15ba8)
        compare('all_mask_first_free', machine.reg(4), lib.fx_eval_storage_first_free(mask), dict(mask=mask))
        full_ram('allocator_RAM', memory, dict(mask=mask))
        for identity in range(16):
            for name, entry in (('reserve', 0x15bbc), ('release', 0x15bca)):
                memory, buffer, storage = prepare(); machine.reg(0, mask); machine.reg(4, identity); call(entry)
                compare('raw_mask_'+name, machine.reg(0), getattr(lib, 'fx_eval_storage_'+name)(mask, identity), dict(mask=mask, identity=identity))
                full_ram('allocator_RAM', memory, dict(mask=mask, identity=identity))
    for identity, mask in itertools.product(range(256), (0, 0x55, 0xaa, 0xf8, 255)):
        for name, entry in (('reserve', 0x15bbc), ('release', 0x15bca)):
            memory, buffer, storage = prepare(); machine.reg(0, mask); machine.reg(4, identity); call(entry)
            compare('all_byte_slot_'+name, machine.reg(0), getattr(lib, 'fx_eval_storage_'+name)(mask, identity), dict(mask=mask, identity=identity))
    for source, destination in itertools.product(range(256), range(16)):
        memory, buffer, storage = prepare()
        destination_header = ((source & 0xf0) ^ 0xf0) | destination
        machine.reg(4, source); machine.reg(5, destination_header); call(0x1695c)
        compare('all_header_slot_copy_status', 0, lib.fx_eval_storage_copy_slot(C.byref(storage), destination_header, source), dict(source=source, destination=destination_header))
        full_ram('all_header_slot_copy_RAM', memory, dict(source=source, destination=destination_header))

    copies = [(0x8900, 0x2800, 100), (0x8900, 0x7ff8, 24),
              (0xffff, 0x2800, 1), (0x8000, 0, 0), (0x7fff, 0, 0)]
    copies += [(0x8900+delta, 0x8900, length)
               for delta, length in itertools.product(range(-12, 13), (1, 2, 10, 90, 256))]
    for destination, source, length in copies:
        memory, buffer, storage = prepare([(0x8dee, length.to_bytes(2, 'little'))])
        machine.er(0, destination); machine.er(2, source); machine.word(0x8dee, length); call(0xb942)
        compare('forward_byte_copy_status', 0, lib.fx_eval_storage_copy_bytes(C.byref(storage), destination, source, length), dict(destination=destination, source=source, length=length))
        full_ram('forward_byte_copy_RAM', memory, dict(destination=destination, source=source, length=length))

    # Original stage stops naturally before a scalar/rich leaf or native error.
    # All temporary aliases and operation/data-stack writes remain visible.
    def run_stage(header, other_header, operation, count, depth, mask, context,
                  address=0x8900, named=False, group='stage', unary_boundary=False):
        initial_memory = None
        if unary_boundary:
            initial_memory = bytearray(65536)
            for identity in range(16):
                initial_memory[0x80e0+2*identity:0x80e2+2*identity] = b'\x01\x01'
                initial_memory[0x829e+90*identity:0x829e+90*(identity+1)] = bytes(
                    (identity+offset)&255 for offset in range(90))
            current = bytes([header])+bytes(range(1,20))
            other = bytes([other_header])+bytes(range(21,40))
        else:
            current = bytes([header])+bytes(rng.randrange(256) for _ in range(19))
            other = bytes([other_header])+bytes(rng.randrange(256) for _ in range(19))
        memory, buffer, storage = prepare([(address, current+other),
            (0x8125, bytes([mask])), (0x80f9, bytes([context]))], initial_memory)
        pre_native = bytes(memory)
        current, other = bytes(memory[address:address+20]), bytes(memory[address+20:address+40])
        machine.er(12, address); machine.reg(1, operation); machine.reg(5, count); machine.reg(11, depth)
        machine.lib.harness_set_sp(0x8dee); machine.lib.harness_set_lr(0x2fffe); machine.lib.harness_set_pc(0x163f0)
        route = lib.storage_oracle_stage(3000000)
        nonlocal native_calls
        native_calls += 1
        if route not in (0, 1, 3, 7): raise RuntimeError(f'Stage did not reach a boundary: {route}')
        expected = [machine.reg(1), route if route in (3, 7) else 0,
                    2 if route in (3, 7) else route,
                    mask if operation == 3 else machine.reg(0)]
        host_mask = C.c_uint8(mask); result = StageResult()
        if named:
            first = (Number*2).from_buffer_copy(current); second = (Number*2).from_buffer_copy(other)
            status = lib.fx_eval_storage_stage(C.byref(storage), first, second,
                operation, count, depth, C.byref(host_mask), C.byref(result))
            # Named records replace the separate native prepared work buffer.
            # This is only the comparison adapter, never production scratch.
            memory[address:address+20] = bytes(first)
            memory[address+20:address+40] = bytes(second)
        else:
            status = lib.fx_eval_storage_stage_address(C.byref(storage), address,
                operation, count, depth, C.byref(host_mask), C.byref(result))
        detail = dict(header=header, other_header=other_header, operation=operation,
                      count=count, depth=depth, mask=mask, context=context,
                      address=address, named=named)
        compare(group+'_status', 0, status, detail)
        compare(group+'_route_operation_mask', expected,
                [result.operation, result.native_status, result.route, host_mask.value], detail)
        full_ram(group+'_RAM', memory, detail)
        if unary_boundary:
            # Reuse the fresh original observation for the separate named
            # adapter, seeded from exactly the same pre-native RAM image.
            named_memory=bytearray(pre_native)
            named_buffer=(C.c_uint8*65536).from_buffer(named_memory)
            named_storage=Storage(named_buffer,65536,rom_buffer,len(rom))
            first=(Number*2).from_buffer_copy(current)
            second=(Number*2).from_buffer_copy(other)
            named_mask=C.c_uint8(mask);named_result=StageResult()
            named_status=lib.fx_eval_storage_stage(C.byref(named_storage),first,second,
                operation,count,depth,C.byref(named_mask),C.byref(named_result))
            named_memory[address:address+20]=bytes(first)
            named_memory[address+20:address+40]=bytes(second)
            named_detail=dict(detail,named=True)
            compare(group+'_named_status',0,named_status,named_detail)
            compare(group+'_named_route_operation_mask',expected,
                [named_result.operation,named_result.native_status,named_result.route,named_mask.value],named_detail)
            full_ram(group+'_named_RAM',named_memory,named_detail)

    def run_temporary(header, mask, address=0x8900, named=False):
        record = bytes([header])+bytes(rng.randrange(256) for _ in range(9))
        memory, buffer, storage = prepare([(address, record), (0x8125, bytes([mask]))])
        original = bytes(memory[address:address+10])
        machine.er(12, address); machine.reg(0, mask); machine.reg(1, 0)
        machine.lib.harness_set_sp(0x8dee); machine.lib.harness_set_lr(0x2fffe)
        machine.lib.harness_set_pc(0x1648e)
        route = lib.storage_oracle_stage(3000000)
        nonlocal native_calls
        native_calls += 1
        if route not in (1, 7): raise RuntimeError(f'Temporary boundary: {route}')
        host_mask, status = C.c_uint8(mask), C.c_uint8(255)
        if named:
            reference = Number.from_buffer_copy(original)
            actual = lib.fx_eval_storage_temporary(C.byref(storage), C.byref(reference),
                                                   C.byref(host_mask), C.byref(status))
            memory[address:address+10] = bytes(reference)
        else:
            actual = lib.fx_eval_storage_temporary_address(C.byref(storage), address,
                                                          C.byref(host_mask), C.byref(status))
        detail = dict(header=header, original_record=original.hex(), mask=mask,
                      address=address, named=named)
        compare('selected_temporary_status', [0, 7 if route == 7 else 0, machine.reg(0)],
                [actual, status.value, host_mask.value], detail)
        full_ram('selected_temporary_RAM', memory, detail)

    for header, mask, named in itertools.product(range(256),
            (0, 0x80, 0xc0, 0xe0, 0xf0, 0xf7, 0xf8, 255), (False, True)):
        run_temporary(header, mask, named=named)
    for address, header, mask in itertools.product(
            (0x80e0, 0x80e1, 0x80f0, 0x8125, 0x8406, 0x8407, 0x845f, 0x8835),
            (0x60, 0x69, 0x90, 0xf1, 0xf3, 0xf9, 255), (0, 0xf0, 0xf8)):
        run_temporary(header, mask, address=address)

    for operation, header, other_header, count, mask in itertools.product(
            (3, 11, 13, 35, 45, 47, 85, 108, 122, 123, 132, 255),
            (2, 0x60, 0x63, 0x64, 0x69, 0x90, 0x9f, 0xf1, 0xf3, 0xf6, 0xf9),
            (2, 0x60, 0x69, 0xf1), (1, 2, 0xff), (0, 0x80, 0xf0, 0xf8, 255)):
        run_stage(header, other_header, operation, count, 0, mask, 0xc1)
    for index in range(args.random_cases):
        run_stage(rng.randrange(256), rng.randrange(256), rng.randrange(256),
                  rng.choice((1, 2, 255)), rng.randrange(10), rng.randrange(256),
                  rng.choice((0xc1, 0xc4, 2, 6, 7)), named=bool(index & 1), group='random_stage')
    for address, context, depth in itertools.product(
            (0x8078, 0x80df, 0x80e0, 0x80f0, 0x8125, 0x8406, 0x845c),
            (0xc1, 0xc4), (0, 8, 9)):
        for header, other_header in ((0xf1, 2), (2, 0xf3), (0x63, 0x69)):
            run_stage(header, other_header, 45, 255, depth, 0, context,
                      address=address, group='physical_stage_alias')

    # Fresh original163F0 observations reproduce the independent336-case
    # count1/depth9-vs10 input corpus. Held outputs are never an oracle.
    for header,operation,mask,depth in itertools.product(
            (0x61,0x64,0x6b,0x90,0x94,0x9b,0xf3),
            (11,12,13,14,95,107,108,109),(0,0x80,0xf8),(9,10)):
        run_stage(header,1,operation,1,depth,mask,0xc4,
                  group='unary_depth_boundary',unary_boundary=True)

    for destination, source, length in ((0x7fff, 0x2800, 1), (0xfffe, 0x8900, 3),
            (0x8900, 0xfffe, 3), (0x8900, 0x2800, 65537)):
        memory, buffer, storage = prepare(); before = bytes(memory)
        compare('bounded_copy_rejection', -3, lib.fx_eval_storage_copy_bytes(C.byref(storage), destination, source, length), dict(destination=destination, source=source, length=length))
        compare('bounded_copy_no_mutation', before == bytes(memory), True, {})
        if length <= 65535:
            machine.er(0, destination); machine.er(2, source); machine.word(0x8dee, length)
            machine.lib.harness_set_sp(0x8dee); machine.lib.harness_set_lr(0x2fffe); machine.lib.harness_set_pc(0xb942)
            native_run = machine.lib.harness_run(100000, 0x2fffe, False)
            limits.append(dict(destination=destination, source=source, length=length,
                               native_run=native_run, native_pc=hex(machine.lib.harness_get_pc())))
    memory, buffer, storage = prepare(); before = bytes(memory)
    mask, status, result = C.c_uint8(0), C.c_uint8(0), StageResult()
    for address in (0x7fff, 65527):
        compare('bounded_reference_rejection', -3,
            lib.fx_eval_storage_temporary_address(C.byref(storage), address, C.byref(mask), C.byref(status)), dict(address=address))
    for depth, count in ((10, 255), (255, 1), (0, 0), (0, 3)):
        compare('bounded_stage_rejection', -3,
            lib.fx_eval_storage_stage_address(C.byref(storage), 0x8900, 45, count,
                depth, C.byref(mask), C.byref(result)), dict(depth=depth, count=count))
    compare('bounded_reference_stage_no_mutation', before == bytes(memory), True, {})

    for depth,count,named in itertools.product(
            (10,11,255),(2,255),(False,True)):
        memory,buffer,storage=prepare()
        first=(Number*2).from_buffer_copy(memory[0x8900:0x8914])
        second=(Number*2).from_buffer_copy(memory[0x8914:0x8928])
        mask=C.c_uint8(0xa5);result=StageResult(0x91,0x92,0x93)
        before=(hashlib.sha256(memory).hexdigest(),bytes(first).hex(),bytes(second).hex(),
                mask.value,bytes(result).hex())
        if named:
            status=lib.fx_eval_storage_stage(C.byref(storage),first,second,45,count,
                depth,C.byref(mask),C.byref(result))
        else:
            status=lib.fx_eval_storage_stage_address(C.byref(storage),0x8900,45,count,
                depth,C.byref(mask),C.byref(result))
        detail=dict(depth=depth,count=count,named=named)
        compare('bounded_binary_depth_rejection',-3,status,detail)
        compare('bounded_binary_depth_no_mutation',before,
            (hashlib.sha256(memory).hexdigest(),bytes(first).hex(),bytes(second).hex(),
             mask.value,bytes(result).hex()),detail)
    for depth,named in itertools.product((11,255),(False,True)):
        memory,buffer,storage=prepare()
        first=(Number*2).from_buffer_copy(memory[0x8900:0x8914])
        second=(Number*2).from_buffer_copy(memory[0x8914:0x8928])
        mask=C.c_uint8(0xa5);result=StageResult(0x91,0x92,0x93)
        before=(hashlib.sha256(memory).hexdigest(),bytes(first).hex(),bytes(second).hex(),
                mask.value,bytes(result).hex())
        if named:
            status=lib.fx_eval_storage_stage(C.byref(storage),first,second,45,1,
                depth,C.byref(mask),C.byref(result))
        else:
            status=lib.fx_eval_storage_stage_address(C.byref(storage),0x8900,45,1,
                depth,C.byref(mask),C.byref(result))
        detail=dict(depth=depth,count=1,named=named)
        compare('bounded_unary_depth_rejection',-3,status,detail)
        compare('bounded_unary_depth_no_mutation',before,
            (hashlib.sha256(memory).hexdigest(),bytes(first).hex(),bytes(second).hex(),
             mask.value,bytes(result).hex()),detail)

    changed = [name for name, digest in pins.items()
               if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest]
    report = dict(optimization=args.optimization, cases=sum(domains.values()),
        native_calls=native_calls, domains=domains, failures=failures,
        source_changed_during_run=changed, tested_inputs_sha256=pins, limits=limits,
        comparison='Native all65536 RAM bytes except actual preparedCPU-frame writes; rawmask allocation/reserve/release, allheader low-slot resolution, route/mappedoperation/status/localmask and numeric operand-stack data.',
        scope='Prepared segmentzero storage helpers and163F0..16538 selector before numeric leaves. Depth0..9 admits prepared count1/2/FF; only count1 also admits depth10. All16 masked slot identities and rawF metadata aliases are included. CPUframes, nonreturning/out-of-bounds writes, numeric leaves, peripheral callback metadata and the complete evaluator/controller are excluded explicitly.',
        unary_depth_boundary_native_calls=336,
        unary_depth_boundary_adapters=['physical_address','named_records'],
        unary_depth_boundary_inputs='C4; headers61/64/6B/90/94/9B/F3; other scalar1; operations11/12/13/14/95/107/108/109; masks0/80/F8; depths9/10; sixteen1x1 dimension words and slot payload byte(slot+offset); working pair8900.')
    if failures or changed:
        (build/'failures.json').write_text(json.dumps(report, indent=2)+'\n')
        raise AssertionError(f'{len(failures)} storage mismatches; changed={changed}')
    (build/('preview-'+args.optimization+'.json')).write_text(json.dumps(
        dict(report, status='pass'), indent=2)+'\n')
    if not args.no_report:
        write_report('analysis/c-verification/eval_storage.json', report, sources,
                     'tools/test_eval_storage_c.py')
    print(json.dumps(dict(status='pass', cases=report['cases'], native_calls=native_calls,
                         domains=domains), indent=2))


if __name__ == '__main__': main()
