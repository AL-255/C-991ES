#!/usr/bin/env python3
"""Live native checks for independent BASE word selected/global/operation policies.

Run tools/test_numeric_base_c.py --random-cases 8000 --exhaustive-bin first when
publishing a canonical report. The original ROM is only the test oracle.
"""
import ctypes as C, json, sys, time, hashlib, random
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
from trace_natural_result import settings
from test_numeric_base_c import Number, NativeRegisters, Rational
from c_verification import write_report
import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/base-word'
    build.mkdir(parents=True, exist_ok=True)
    source_files = ['csrc/numeric/fx_base.c', 'csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_base_literal.c', 'csrc/parse/fx_tokens.c', 'csrc/data/fx_rom_data.c']
    dependencies = source_files + ['csrc/numeric/fx_base.h', 'csrc/numeric/fx_base_word.h', 'csrc/numeric/fx_numeric.h', 'csrc/parse/fx_tokens.h', 'csrc/data/fx_rom_data.h', 'tools/test_base_word_c.py', 'tools/test_numeric_base_c.py', 'tools/c_verification.py', 'tools/trace_natural_result.py', 'tools/nxu8/machine.py', 'tools/nxu8/harness.c', 'tools/nxu8/vendor/SimU8/core.c', 'firmware/fx-991es-plus-c-ver4.bin', 'csrc/numeric/base_word/manifest.json']
    dependencies += [str(p.relative_to(ROOT)) for p in (ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h')]
    extra_pins = ['analysis/disassembly/complete.asm', 'csrc/numeric/base_word/EXECUTION.md']
    if not args.no_report:
        dependencies += ['analysis/c-verification/numeric_base.json']
    source_pins = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(set(dependencies + extra_pins))}
    import subprocess
    subprocess.run(['gcc', '-std=c99', '-O3', '-Wall', '-Wextra', '-Werror', '-pedantic', '-shared', '-fPIC', *[str(ROOT / path) for path in source_files], '-o', str(build / 'base.so')], check=True)
    lib = C.CDLL(str(build / 'base.so'))
    ptr = C.POINTER(Number)
    uptr = C.POINTER(C.c_uint)

    class Context(C.Structure):
        _fields_ = [('selected_mask', C.c_uint8), ('calculation_context', C.c_uint8), ('operation_context', C.c_uint8)]
    lib.fx_decimal_parse.argtypes = [ptr, C.c_char_p]
    lib.fx_rational_encode.argtypes = [ptr, C.POINTER(Rational)]
    lib.fx_base_word_decode.argtypes = [C.POINTER(C.c_uint32), uptr, ptr, C.c_uint8]
    lib.fx_base_word_encode.argtypes = [ptr, C.c_uint32, C.c_uint8, C.c_uint8, uptr]
    lib.fx_base_word_validate.argtypes = [ptr, C.POINTER(Context), uptr]
    lib.fx_base_word_unary.argtypes = [ptr, ptr, C.POINTER(Context), C.c_int, uptr]
    lib.fx_base_word_binary.argtypes = [ptr, ptr, ptr, C.POINTER(Context), C.c_int, uptr]
    m = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), build / 'oracle')
    registers = NativeRegisters.in_dll(m.lib, 'CoreRegister')
    checks = {}
    failures = []
    limits = []
    calls = 0
    start = time.time()
    unary = [0x15c1c, 0x15c46]
    binary = [0x15f34, 0x15f40, 0x15f4c, 0x15f58, 0x15d62, 0x15d9e, 0x15dda, 0x15e1e]

    def decimal(t):
        n = Number()
        assert lib.fx_decimal_parse(C.byref(n), str(t).encode()) == 0
        return n.raw()

    def rational(n, d, flags=0):
        out = Number()
        assert lib.fx_rational_encode(C.byref(out), C.byref(Rational(n, d, flags))) == 0
        return out.raw()

    def reset(mask, globalctx):
        m.reset()
        settings(m)
        m.ram[0x80f9] = globalctx
        m.ram[0x80fa] = mask
        m.ram[0x82f0:0x8370] = b'\xa5' * 0x80

    def check(group, got, want, detail):
        checks[group] = checks.get(group, 0) + 1
        if got != want:

            def encode(x):
                return x.hex() if isinstance(x, bytes) else [encode(y) for y in x] if isinstance(x, (list, tuple, set)) else x
            failures.append({'group': group, 'got': encode(got), 'native': encode(want), 'input': detail})
            if len(failures) < 4:
                print(json.dumps(failures[-1]), flush=True)

    def call(address, limit=100000):
        nonlocal calls
        calls += 1
        m.call(address, limit)

    def operation(a, b, mask, gctx, octx, op, isunary=False):
        reset(mask, gctx)
        m.ram[0x8300:0x830a] = a
        m.ram[0x8350:0x835a] = b
        m.er(0, 0x8300)
        m.er(12, 0x8300)
        m.er(2, 0x8350)
        m.reg(6, octx)
        detail = {'a': a.hex(), 'b': b.hex(), 'selected': mask, 'global': gctx, 'operation_context': octx, 'operation': op, 'unary': isunary}
        aC, bC = (Number.from_buffer_copy(a), Number.from_buffer_copy(b))
        out = Number.from_buffer_copy(b'\xa5' * 10)
        ns = C.c_uint(0x55)
        ctx = Context(mask, gctx, octx)
        st = lib.fx_base_word_unary(C.byref(out), C.byref(aC), C.byref(ctx), op, C.byref(ns)) if isunary else lib.fx_base_word_binary(C.byref(out), C.byref(aC), C.byref(bC), C.byref(ctx), op, C.byref(ns))
        try:
            call((unary if isunary else binary)[op])
        except RuntimeError as e:
            limits.append({'input': detail, 'Cstatus': st, 'native': str(e), 'last_pc': m.lib.harness_get_pc()})
            check('native_nonreturn_boundary', (st, ns.value, out.raw(), aC.raw(), bC.raw()), (-3, 0x55, b'\xa5' * 10, a, b), detail)
            return
        group = 'unary' if isunary else 'binary'
        check(group, (st, ns.value, out.raw()), (0, m.reg(0), bytes(m.ram[0x8300:0x830a])), detail)
        for target in range(1, 2 if isunary else 3):
            aa, bb = (Number.from_buffer_copy(a), Number.from_buffer_copy(b))
            aliased = aa if target == 1 else bb
            ans = C.c_uint(0x55)
            ast = lib.fx_base_word_unary(C.byref(aliased), C.byref(aa), C.byref(ctx), op, C.byref(ans)) if isunary else lib.fx_base_word_binary(C.byref(aliased), C.byref(aa), C.byref(bb), C.byref(ctx), op, C.byref(ans))
            check(group + '_alias', (ast, ans.value, aliased.raw()), (0, m.reg(0), bytes(m.ram[0x8300:0x830a])), dict(detail, target=target))
        check(group + '_immutable', (aC.raw(), bC.raw(), bytes(m.ram[0x8350:0x835a]), bytes(m.ram[0x82f0:0x8300]), bytes(m.ram[0x830a:0x8328]), bytes(m.ram[0x8332:0x8350]), bytes(m.ram[0x835a:0x8370])), (a, b, b, b'\xa5' * 16, b'\xa5' * 30, b'\xa5' * 30, b'\xa5' * 22), detail)
    values = [0, 1, -1, 32767, -32768, 32768, -32769, 65535, 65536, 0x7fffffff, -0x80000000, 0x80000000, -0x80000001, '.5', '-.5']
    records = [decimal(v) for v in values] + [rational(1, 2), rational(-1, 3, 0x40), bytes.fromhex('80000001000201020100'), bytes.fromhex('f3000000000000000000')]
    words = [0, 1, 0xffffffff, 32767, 32768, 0xffff8000, 0xffff7fff, 65535, 65536, 0x7fffffff, 0x80000000, 0x80000001]
    for mask in range(256):
        for a in records:
            reset(mask, 0xc1)
            m.ram[0x8300:0x830a] = a
            m.er(0, 0x8300)
            m.er(12, 0x8300)
            call(0x15a1e)
            call(0x15a94)
            expected = (sum((m.reg(i) << 8 * i for i in range(4))), int(bool(registers.psw & 0x80)))
            word, carry = (C.c_uint32(), C.c_uint())
            src = Number.from_buffer_copy(a)
            st = lib.fx_base_word_decode(C.byref(word), C.byref(carry), C.byref(src), mask)
            check('decode', (st, word.value, carry.value, src.raw()), (0, *expected, a), {'record': a.hex(), 'selected': mask})
        for gctx in [2, 6, 7, 0xc1]:
            for w in words:
                reset(mask, gctx)
                m.ram[0x8300:0x830a] = b'\xa5' * 10
                for i in range(4):
                    m.reg(i, w >> 8 * i & 255)
                call(0x15b00)
                rejected = m.reg(9) == 255
                if not rejected:
                    m.er(14, 0x8300)
                    call(0x15a64)
                expected = (3 if rejected else 0, bytes(m.ram[0x8300:0x830a]))
                out = Number.from_buffer_copy(b'\xa5' * 10)
                ns = C.c_uint(55)
                st = lib.fx_base_word_encode(C.byref(out), w, mask, gctx, C.byref(ns))
                check('encode', (st, ns.value, out.raw()), (0, *expected), {'word': w, 'selected': mask, 'global': gctx})
            for a in records:
                for op in range(2):
                    operation(a, decimal(0), mask, gctx, gctx, op, True)
            pairs = [(0, 1), (32767, 1), (-32768, -1), (0x7fffffff, 1), (-0x80000000, -1), (7, 2), (-7, 2), ('.5', '-.25')]
            for va, vb in pairs:
                for op in range(8):
                    operation(decimal(va), decimal(vb), mask, gctx, gctx, op)
        if mask % 0x40 == 63:
            print('mask', mask, 'calls', calls, 'checks', sum(checks.values()), 'failures', len(failures), 'limits', len(limits), 'seconds', round(time.time() - start, 2), flush=True)
    for mask in [1, 0, 2, 3, 4, 7, 9, 15, 255]:
        for gctx in [2, 6, 7, 0xc1]:
            for octx in [2, 6, 7, 0xc1]:
                for a, b in [(decimal(32768), decimal(1)), (decimal('7.5'), decimal(2)), (rational(1, 2), decimal(1))]:
                    for op in range(8):
                        operation(a, b, mask, gctx, octx, op)
                for prior in [0, 2, 3, 8, 255]:
                    for a in [decimal(32768), decimal(-32769), decimal(0x80000000), rational(1, 2), bytes.fromhex('f3000000000000000000')]:
                        reset(mask, gctx)
                        m.ram[0x8300:0x830a] = a
                        m.er(12, 0x8300)
                        m.reg(0, prior)
                        m.reg(6, octx)
                        call(0x15e82)
                        src = Number.from_buffer_copy(a)
                        ns = C.c_uint(prior)
                        ctx = Context(mask, gctx, octx)
                        st = lib.fx_base_word_validate(C.byref(src), C.byref(ctx), C.byref(ns))
                        check('validate', (st, ns.value, src.raw()), (0, m.reg(0), bytes(m.ram[0x8300:0x830a])), {'record': a.hex(), 'selected': mask, 'global': gctx, 'operation_context': octx, 'prior': prior})
    for mask in range(256):
        for gctx in [2, 6, 7, 0xc1]:
            for a, b in [(rational(1, 2), rational(-1, 3, 0x40)), (bytes.fromhex('80000001000201020100'), decimal(32768)), (bytes.fromhex('f5000000000000000000'), decimal(1))]:
                for op in range(8):
                    operation(a, b, mask, gctx, gctx, op)
    expected_limits = {(1, 2, 2, 0, True, decimal(32768).hex(), decimal(0).hex()), *((1, 2, 2, op, False, bytes.fromhex('80000001000201020100').hex(), decimal(32768).hex()) for op in (4, 5, 6))}
    actual_limits = {(row['input']['selected'], row['input']['global'], row['input']['operation_context'], row['input']['operation'], row['input']['unary'], row['input']['a'], row['input']['b']) for row in limits}
    check('native_nonreturn_controls', actual_limits, expected_limits, 'Every original nonreturn remains explicit; unexpected timeouts fail verification.')
    source_changes = {name: [value, hashlib.sha256((ROOT / name).read_bytes()).hexdigest()] for name, value in source_pins.items() if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != value}
    legacy = None
    if not args.no_report:
        legacy = json.loads((ROOT / 'analysis/c-verification/numeric_base.json').read_text())
        assert legacy['status'] == 'pass' and legacy['cases'] == 1881017 and (not legacy['failures'])
        for name in source_files + ['csrc/numeric/fx_base.h', 'csrc/numeric/fx_base_word.h', 'csrc/numeric/fx_numeric.h', 'tools/test_numeric_base_c.py']:
            assert legacy['tested_inputs_sha256'][name] == source_pins[name], f'Run the legacy BASE suite against current source first: {name}'
    report = {'cases': sum(checks.values()), 'original_calls': calls, 'groups': checks, 'failures': failures, 'limits': limits, 'source_changes': source_changes, 'source_pins_before_build': source_pins, 'compiled_library_sha256': hashlib.sha256((build / 'base.so').read_bytes()).hexdigest(), 'legacy_validation': None if legacy is None else {'path': 'analysis/c-verification/numeric_base.json', 'checks': legacy['cases'], 'status': legacy['status']}, 'scope': 'Prepared scalar word value APIs on all256 incoming selected bytes. Decode selected-byte equality, independent global-mode serialization, independent operation-context range/division and prior-status preservation; returning native records/statuses/carry, immutable input records/guards and output aliases.', 'comparison': 'Live original routines15A1E/15A94,15B00/15A64,15E82,15C1C/15C46,15F34/15F40/15F4C/15F58 and15D62/15D9E/15DDA/15E1E. Native output+40 range-comparator workspace is explicitly outside sentinel comparisons; these value APIs do not export a physical-RAM image.', 'gaps': ['Known zero-residual BIN logical serializer cycles return hostUNIMPLEMENTED without mutating output/status; native controls remain in limits.', 'Typed literal/UI-mask admission is preserved by legacy APIs; expression dispatch and physical workspaces have separate owners.', 'Malformed numeric records and caller/context/CPU-frame memory aliases are outside the documented value API.']}
    (build / 'diagnostics.json').write_text(json.dumps(report, indent=2) + '\n')
    assert calls == 170377
    print(json.dumps({'original_calls': calls, 'checks': report['cases'], 'failures': len(failures), 'limits': len(limits), 'source_changes': source_changes}, sort_keys=True))
    if failures or source_changes:
        raise AssertionError('Unfiltered BASE word discrepancy or changed source pins')
    if not args.no_report:
        write_report('analysis/c-verification/base_word.json', report, sorted(set(dependencies)), 'tools/test_base_word_c.py')
    print('PASS (known native nonreturns retained)')


if __name__ == "__main__":
    main()
