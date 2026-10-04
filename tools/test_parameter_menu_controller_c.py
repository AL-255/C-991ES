#!/usr/bin/env python3
"""Fresh original D9D2/CD66 differentials for the high-level parameter menus.

Only the native oracle executes CPU instructions. Authored input settings and
physical key recipes seed both paths independently; no native checkpoint or
returned byte is fed into C. Pending child services are arrival boundaries,
never fabricated completed bodies. GPL-3.0-only.
"""
import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zlib

from c_build_inputs import implementation_inputs
from nxu8.machine import Machine

ROOT = Path(__file__).resolve().parents[1]
MODULES = ['platform/fx_boot_events', 'platform/fx_diagnostic_rom_status', 'platform/fx_diagnostic_contrast',
    'platform/fx_result_classify', 'platform/fx_platform', 'platform/fx_boot',
    'platform/fx_host_bridge', 'platform/fx_persistent', 'platform/fx_main_loop',
    'ui/fx_keys', 'ui/fx_cursor', 'ui/fx_key_wait', 'ui/fx_key_controller',
    'ui/fx_key_dispatch', 'ui/fx_annunciator', 'ui/fx_editor', 'ui/fx_natural_editor',
    'parse/fx_tokens', 'numeric/fx_numeric', 'numeric/fx_surd_components',
    'numeric/fx_raw_decimal_parts', 'numeric/fx_raw_decimal_divide',
    'numeric/fx_raw_decimal_multiply_add', 'complex/fx_complex',
    'format/fx_format', 'format/fx_format_base', 'data/fx_rom_data',
    'render/fx_render', 'render/fx_render_context', 'render/fx_render_memory',
    'render/fx_layout_validate', 'render/fx_result_special', 'render/fx_result_verify',
    'render/fx_result_format_state', 'ui/fx_menu_navigator', 'ui/fx_mode_setup',
    'ui/fx_mode_bank_menu', 'linalg/fx_linalg_store', 'ui/fx_parameter_menu_controller']
SOURCES = ['csrc/' + name + '.c' for name in MODULES]


class Platform(C.Structure):
    _fields_ = [('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t),
               ('ram', C.POINTER(C.c_uint8)), ('callback_pending', C.c_uint8),
               ('status', C.c_int)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def authored_recipes():
    gates = [(0xc1, 1, 1, 1), (0x45, 1, 1, 1), (0x4b, 1, 1, 1),
             (12, 1, 1, 1), (12, 16, 5, 2), (12, 16, 5, 1),
             (12, 16, 4, 255), (0xc1, 1, 64, 1)]
    dispatch = [dict(label=f'dispatch-{g}-{key}', key=key, mode=mode,
        context=context, phase=phase, column=column)
        for g, (mode, context, phase, column) in enumerate(gates)
        for key in range(256)]
    bodies = []
    simple = [(2, 0xc4), (3, 2), (9, 0xc1), (10, 0xc1), (11, 0x89)]
    for key, mode in simple:
        for math in (0, 1):
            for suffix, raw in [('action', [0x31]), ('cancel', [0xe6]),
                ('ignored-cancel', [0x39, 0xe6]),
                ('navigation-cancel', [0xe1, 0xe0, 0xe3, 0xe6]),
                ('modifier-cancel', [0xe4, 0xe6]), ('idle-action', [None, 0x31])]:
                bodies.append(dict(label=f'simple-{key}-{math}-{suffix}', key=key,
                    mode=mode, math=math, raw_keys=raw))
    for key, mode in [(4, 6), (5, 7)]:
        for suffix, raw in [('cancel', [0xe6]), ('define', [0x31, 0x31, 0x31]),
                           ('data', [0x32, 0x31, 0x31]),
                           ('navigate-cancel', [0xe3, 0xe0, 0xe6])]:
            bodies.append(dict(label=f'bank-{key}-{suffix}', key=key, mode=mode,
                               raw_keys=raw))
    for key in (2, 3, 4, 5, 11):
        bodies.append(dict(label=f'inactive-{key}', key=key, mode=0xc1, raw_keys=[]))
    for key in (6, 7, 9, 10):
        bodies.append(dict(label=f'table-grid-gate-{key}', key=key, mode=0x88,
                           context=18, raw_keys=[]))
    for columns in (0x20, 0x40, 0x80):
        bodies.append(dict(label=f'base-export-{columns}', key=3, mode=2,
            raw_keys=[dict(pair=[columns, 0x80]), 0xe6]))
    bodies.append(dict(label='base-reset-request', key=3, mode=2,
                       raw_keys=[dict(pair=[0x10, 0x80])]))
    bodies.append(dict(label='matrix-reset-request', key=4, mode=6,
                       raw_keys=[dict(pair=[0x10, 0x80])]))
    bodies.append(dict(label='matrix-export-cancel', key=4, mode=6,
                       raw_keys=[dict(pair=[0x20, 0x80]), 0xe6]))
    requests = [dict(label=f'pending-{key}-{mode}-{context}-{submode}',
                     key=key, mode=mode, context=context, submode=submode)
                for key, mode, context, submode in
                [(1, 3, 18, 1), (1, 3, 1, 1), (1, 3, 1, 2),
                 (1, 12, 18, 1), (1, 12, 9, 1), (6, 0xc1, 1, 1),
                 (7, 0xc1, 1, 1), (8, 0xc1, 1, 1)]]
    return dict(schema=1, scope='Authored initial bytes and raw key recipes only.',
                dispatch=dispatch, bodies=bodies, requests=requests)


def initial_ram(rom, recipe):
    ram = bytearray(65536)
    ram[0x8dee:0x8e00] = rom[0x1f8be:0x1f8d0]
    settings = {0x80f9: recipe['mode'], 0x80fa: recipe.get('submode', 1),
        0x80fb: 3, 0x80fc: recipe.get('context', 1), 0x80fe: recipe.get('phase', 1),
        0x80f5: recipe['key'], 0x80f7: 0x73, 0x811e: recipe.get('column', 1),
        0x8105: 4, 0x8106: recipe.get('math', 1), 0x8112: 17, 0x8117: 1,
        0x8119: 1, 0x811a: 0x7c, 0x811b: 10, 0x811f: 10, 0x8121: 1,
        0xf040: 255}
    for address, value in settings.items():
        ram[address] = value
    ram[0x812c:0x8130] = bytes.fromhex('54815481')
    ram[0x8154] = 0x31
    ram[0x81b8] = 0x32
    return bytes(ram)


def configure_candidate(path):
    lib = C.CDLL(str(path))
    pp = C.POINTER(Platform)
    lib.parameter_menu_c_state_size.restype = C.c_size_t
    lib.parameter_menu_c_target.argtypes = [C.c_void_p]
    lib.parameter_menu_c_target.restype = C.c_uint32
    lib.parameter_menu_c_request.argtypes = [C.c_void_p, C.c_uint]
    for name in ('begin', 'tick', 'resume_timer'):
        getattr(lib, 'fx_parameter_menu_controller_' + name).argtypes = (
            [pp, C.c_void_p, C.c_void_p] if name == 'begin' else [pp, C.c_void_p])
    lib.fx_parameter_menu_controller_finish.argtypes = [C.c_void_p, C.POINTER(C.c_uint8)]
    lib.fx_parameter_menu_controller_export_mask.argtypes = [C.c_void_p]
    lib.fx_parameter_menu_controller_export_mask.restype = C.c_uint8
    lib.parameter_menu_c_main_complete.argtypes = [pp, C.c_uint8,
        C.POINTER(C.c_uint8), C.POINTER(C.c_uint8)]
    lib.fx_take_callback.argtypes = [pp]
    lib.fx_take_callback.restype = C.c_uint8
    return lib


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir', type=Path)
    args = ap.parse_args()
    if sys.flags.optimize:
        ap.error('Optimized Python disables differential assertions')
    out = (args.output_dir or ROOT/'analysis/build/parameter-menu-controller'/
        datetime.now(timezone.utc).strftime('proof-%Y%m%dT%H%M%SZ')).resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out/'tmp').mkdir()
    os.environ['TMPDIR'] = str(out/'tmp')
    fixture = authored_recipes()
    fixture_path = out/'inputs.json'
    fixture_path.write_text(json.dumps(fixture, indent=2) + '\n')
    inputs = implementation_inputs(ROOT, SOURCES)
    inputs += ['tools/parameter_menu_oracle.c', 'tools/parameter_menu_c_adapter.c',
        'tools/test_parameter_menu_controller_c.py', 'tools/c_build_inputs.py',
        'tools/nxu8/machine.py', 'tools/nxu8/harness.c', 'tools/nxu8/vendor/SimU8/core.c',
        'tools/nxu8/isa.txt', 'firmware/fx-991es-plus-c-ver4.bin',
        'analysis/disassembly/complete.asm']
    inputs += [str(p.relative_to(ROOT)) for p in (ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
    before = {p: sha(ROOT/p) for p in sorted(set(inputs))}
    fixture_hash = sha(fixture_path)
    report = dict(scope=__doc__, source_sha256_pre=before, fixture_sha256=fixture_hash,
                  full_firmware_complete=False, rows=[], comparisons=0, checkpoints=[])
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rd = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    libraries = []
    artifacts = []
    for opt in ('O2', 'O3'):
        path = out/f'controller-{opt}.so'
        subprocess.run(['gcc', '-std=c99', '-'+opt, '-Wall', '-Wextra', '-Werror',
            '-shared', '-fPIC', '-Wl,--no-undefined', *[str(ROOT/p) for p in SOURCES],
            str(ROOT/'tools/parameter_menu_c_adapter.c'), '-o', str(path)], check=True)
        lib = configure_candidate(path)
        libraries.append((opt, lib))
        artifacts.append(path)
    m = Machine(rom, out/'cpu')
    native_path = out/'native-observer.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
        '-fPIC', str(ROOT/'tools/parameter_menu_oracle.c'),
        str(ROOT/'tools/nxu8/vendor/SimU8/core.c'), '-o', str(native_path)], check=True)
    native = C.CDLL(str(native_path))
    for name in ('harness_init', 'harness_set_pc', 'harness_get_pc', 'harness_set_reg',
        'harness_get_reg', 'harness_set_sp', 'harness_get_sp', 'harness_set_lr',
        'harness_ram', 'harness_run', 'harness_trace_open', 'harness_trace_close'):
        getattr(native, name).argtypes = getattr(m.lib, name).argtypes
        getattr(native, name).restype = getattr(m.lib, name).restype
    native.parameter_menu_observe.argtypes = [C.c_uint64, C.c_int, C.c_int]
    native.harness_callback.restype = C.c_uint32
    m.lib = native
    m.ram = native.harness_ram().contents
    mask = (C.c_uint8*65536).in_dll(native, 'parameter_menu_frame_mask')
    artifacts.extend([native_path, out/'cpu/nxu8-harness.so'])
    artifact_pre = {str(p.relative_to(ROOT)): sha(p) for p in artifacts}
    raw = {rom[0x7fe+8*c+r]: (1 << c, 1 << r) for c in range(8) for r in range(8)}
    counts = dict(dispatch=0, bodies=0, requests=0, completed_bodies=0, main=0)
    def prepare(recipe):
        m.reset()
        seeded = initial_ram(rom, recipe)
        C.memmove(m.ram, seeded, 65536)
        native.harness_set_sp(0x8dee)
        native.harness_set_lr(0x2fffe)
        native.harness_set_pc(0xd9d2)
        m.reg(5, 1)
        native.parameter_menu_observer_clear()
        return seeded
    def observe(dispatch=False):
        status = native.parameter_menu_observe(3000000, int(dispatch), 0)
        assert status in (200, 201, 202, 203, 250), (status, hex(native.harness_get_pc()))
        return status
    def target():
        return C.c_uint32.in_dll(native, 'parameter_menu_target').value
    def compare(ram, p, lib, group):
        expected, actual = bytes(m.ram), bytes(ram)
        differences = [a for a in range(65536) if actual[a] != expected[a] and not mask[a]]
        callback = native.harness_callback()
        actual_callback = lib.fx_take_callback(C.byref(p))
        report['checkpoints'].append(dict(group=group, native_pc=hex(native.harness_get_pc()),
            native_ram_zlib_hex=zlib.compress(expected).hex(),
            candidate_ram_zlib_hex=zlib.compress(actual).hex(),
            frame_mask_zlib_hex=zlib.compress(bytes(mask)).hex(),
            differences=differences, native_callback=callback, candidate_callback=actual_callback))
        assert not differences, (group, [(hex(a), actual[a], expected[a]) for a in differences[:20]])
        assert actual_callback == callback, (group, 'callback')
        report['comparisons'] += 1
        return dict(ram_sha256=hashlib.sha256(expected).hexdigest(),
            frame_mask_sha256=hashlib.sha256(bytes(mask)).hexdigest(),
            frame_written_bytes=sum(bool(v) for v in mask), framebuffer=expected[0xf800:0xfa00].hex(),
            callback=callback)
    def candidate(lib, seeded):
        ram = (C.c_uint8*65536).from_buffer_copy(seeded)
        p = Platform(rd, len(rom), ram, 0, 0)
        state = C.create_string_buffer(lib.parameter_menu_c_state_size())
        return ram, p, state, lib.fx_parameter_menu_controller_begin(C.byref(p), state, None)
    try:
        for recipe in fixture['dispatch']:
            seeded = prepare(recipe)
            stop = observe(True)
            observed = target()
            for opt, lib in libraries:
                ram, p, state, status = candidate(lib, seeded)
                assert lib.parameter_menu_c_target(state) == observed, (recipe, opt, 'target')
                if stop == 250:
                    returned = C.c_uint8()
                    assert status == 1 and lib.fx_parameter_menu_controller_finish(state, C.byref(returned)) == 1
                    assert returned.value == m.reg(0) == 0
                    compare(ram, p, lib, recipe['label'])
            report['rows'].append(dict(group='dispatch', input=recipe, boundary=hex(native.harness_get_pc()),
                native_stop=stop, target=observed))
            counts['dispatch'] += 1
        for recipe in fixture['requests']:
            seeded = prepare(recipe)
            assert observe(True) == 201
            contracts = []
            for opt, lib in libraries:
                ram, p, state, status = candidate(lib, seeded)
                assert status == 5 and lib.parameter_menu_c_target(state) == target()
                original = bytes(ram)
                request = [lib.parameter_menu_c_request(state, n) for n in range(3)]
                contracts.append(request)
                for _ in range(3):
                    assert lib.fx_parameter_menu_controller_tick(C.byref(p), state) == 5
                    assert lib.fx_parameter_menu_controller_resume_timer(C.byref(p), state) == 5
                    assert lib.fx_parameter_menu_controller_finish(state, None) == -1
                    assert bytes(ram) == original
                compare(ram, p, lib, recipe['label'])
                report['rows'].append(dict(group='pending-arrival', input=recipe, optimization=opt,
                    target=target(), request=request, native_boundary=hex(native.harness_get_pc()), body_completed=False))
            # Continue the genuine selected child just far enough to
            # witness its real next-call arguments. The default C remains
            # pending at the earlier arrival; these are contract checks,
            # not a claim that C performed any delegated painting/body.
            if recipe['key'] in (1, 6, 7):
                assert native.parameter_menu_observe(3000000, 0, 1) == 300
                boundary = native.harness_get_pc()
                for request in contracts:
                    if recipe['key'] == 1:
                        assert boundary in (0xceb0, 0xcfa8)
                        assert request == [1 if boundary == 0xceb0 else 2, m.reg(0), m.reg(1)]
                    else:
                        assert boundary == 0xd312 and request[2] == m.reg(0)
                report['rows'].append(dict(group='native-delegate-arguments', input=recipe,
                    native_boundary=hex(boundary), registers=[m.reg(i) for i in range(4)],
                    native_ram_zlib_hex=zlib.compress(bytes(m.ram)).hex(), body_completed=False))
            elif recipe['key'] == 8:
                assert native.harness_run(3000000, 0xdfde, False) == 100
                page = m.ram[m.er(0)]
                assert all(request[0] == 5 and request[1] == page == 1 for request in contracts)
                report['rows'].append(dict(group='native-delegate-arguments', input=recipe,
                    native_boundary='0xdfde', initial_page=page,
                    native_ram_zlib_hex=zlib.compress(bytes(m.ram)).hex(), body_completed=False))
            counts['requests'] += 1
        for recipe in fixture['bodies']:
            for opt, lib in libraries:
                seeded = prepare(recipe)
                ram, p, state, status = candidate(lib, seeded)
                stop = observe()
                events = [dict(event='begin', status=status, native_stop=stop,
                               witness=compare(ram, p, lib, recipe['label']))]
                for token in recipe['raw_keys']:
                    if status == 1: break
                    assert status in (0, 3) and stop in (200, 204), (recipe, opt, status, stop)
                    pair = tuple(token['pair']) if isinstance(token, dict) else (
                        (0, 0) if token is None else raw[token])
                    for a, v in zip((0x8e01, 0x8e02), pair): ram[a] = m.ram[a] = v
                    status = lib.fx_parameter_menu_controller_tick(C.byref(p), state)
                    if token is None:
                        # D8A4 is only the initial wait entry. Witness one
                        # real idle iteration atD8D2, without forcing a fresh
                        # key wait or supplying any native poll state to C.
                        assert native.harness_run(3000000, 0x1d8a6, False) == 100
                        assert native.harness_run(1, 0x2fffe, False) == 103
                        assert native.harness_run(3000000, 0x1d8d2, False) == 100
                        stop = 204
                    else:
                        assert native.harness_run(1, 0x2fffe, False) == 103
                        stop = observe()
                    events.append(dict(event='raw-key', token=token, pair=pair, status=status,
                        native_stop=stop, witness=compare(ram, p, lib, recipe['label'])))
                    if status == 3:
                        assert stop == 200
                        assert lib.fx_parameter_menu_controller_export_mask(state) == (1 if pair[0] == 0x20 else 7)
                    if status == 2:
                        assert stop == 203 and lib.fx_parameter_menu_controller_export_mask(state) == 1
                    ram[0x8e01] = ram[0x8e02] = m.ram[0x8e01] = m.ram[0x8e02] = 0
                    if status == 4:
                        assert stop == 202
                        original = bytes(ram)
                        assert lib.fx_parameter_menu_controller_tick(C.byref(p), state) == 4
                        assert bytes(ram) == original
                        status = lib.fx_parameter_menu_controller_resume_timer(C.byref(p), state)
                        assert native.harness_run(1, 0x2fffe, False) == 103
                        stop = observe()
                        events.append(dict(event='timer', status=status, native_stop=stop,
                            witness=compare(ram, p, lib, recipe['label'])))
                returned = None
                if status == 1:
                    assert stop == 250
                    result = C.c_uint8()
                    assert lib.fx_parameter_menu_controller_finish(state, C.byref(result)) == 1
                    assert result.value == m.reg(0), (recipe, opt, result.value, m.reg(0))
                    returned = result.value
                    last, wait = C.c_uint8(), C.c_uint8()
                    assert lib.parameter_menu_c_main_complete(C.byref(p), returned,
                        C.byref(last), C.byref(wait)) == 1
                    assert native.harness_run(3000000, 0xd980, False) == 100
                    assert last.value == m.reg(4) and wait.value == m.reg(5)
                    events.append(dict(event='true-main-continuation', returned=returned,
                        last=last.value, wait=wait.value, witness=compare(ram, p, lib, recipe['label'])))
                    counts['main'] += 1
                    counts['completed_bodies'] += 1
                else:
                    assert (status == 0 and stop in (200, 204)) or (status == 2 and stop == 203)
                    if status == 2:
                        result = C.c_uint8()
                        assert lib.fx_parameter_menu_controller_finish(state, C.byref(result)) == 2
                report['rows'].append(dict(group='body', input=recipe, optimization=opt,
                    target=target(), returned=returned, events=events))
            counts['bodies'] += 1
        assert any(r.get('returned') == 255 for r in report['rows']), 'No genuine negative return witnessed'
        report['status'] = 'pass'
    except Exception as error:
        report['status'] = 'failed'
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        after = {p: sha(ROOT/p) for p in before}
        artifact_post = {p: sha(ROOT/p) for p in artifact_pre}
        report.update(source_sha256_post=after, source_drift=before != after,
            artifact_sha256_pre=artifact_pre, artifact_sha256_post=artifact_post,
            artifact_drift=artifact_pre != artifact_post, groups=counts,
            fixture_unchanged=sha(fixture_path) == fixture_hash,
            completed_utc=datetime.now(timezone.utc).isoformat())
        if report['source_drift'] or report['artifact_drift'] or not report['fixture_unchanged']:
            report['status'] = 'failed'
        (out/'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(output=str(out), status=report['status'], groups=counts,
                         comparisons=report['comparisons']), indent=2))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
