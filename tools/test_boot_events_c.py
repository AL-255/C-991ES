#!/usr/bin/env python3
"""Original-ROM checkpoints for readable nonblocking boot event lifecycles.

Only the independent oracle uses registers, stack locals and execution PCs.
All comparisons cover complete RAM/MMIO outside the native CPU stack.
GPL-3.0-only.
"""
import ctypes as C
import json
from pathlib import Path
import random
import re
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from test_key_wait_c import Key, Wait
from test_key_controller_c import Controller
from test_diagnostic_contrast_c import Contrast


class Welcome(C.Structure):
    _fields_ = [('remaining', C.c_uint16), ('remembered', Key),
                ('phase', C.c_uint8), ('decision', C.c_uint8), ('active', C.c_uint8)]


class Control(C.Structure):
    _fields_ = [('active', C.c_uint8)]


class Events(C.Structure):
    _fields_ = [('welcome', Welcome), ('control', Control), ('raw_wait', Wait),
                ('keys', Controller), ('contrast', Contrast),
                *[(name, C.c_uint8) for name in ('phase', 'pattern', 'key_index',
                        'full_diagnostic', 'boot_continuation', 'active')]]


MODULES = ['platform/fx_boot_events', 'platform/fx_diagnostic_contrast',
           'platform/fx_result_classify', 'platform/fx_platform', 'platform/fx_boot', 'platform/fx_host_bridge',
           'ui/fx_keys', 'ui/fx_cursor', 'ui/fx_key_wait', 'ui/fx_key_controller',
           'ui/fx_key_dispatch', 'ui/fx_annunciator', 'ui/fx_editor', 'ui/fx_natural_editor',
           'parse/fx_tokens', 'numeric/fx_numeric','numeric/fx_surd_components','numeric/fx_raw_decimal_parts','numeric/fx_raw_decimal_divide','numeric/fx_raw_decimal_multiply_add', 'complex/fx_complex',
           'format/fx_format', 'format/fx_format_base', 'data/fx_rom_data',
           'render/fx_render', 'render/fx_render_context', 'render/fx_render_memory',
           'render/fx_layout_validate', 'render/fx_result_special', 'render/fx_result_verify',
           'render/fx_result_format_state']
SOURCES = ['csrc/' + module + '.c' for module in MODULES]


def main():
    build = ROOT / 'analysis/build/boot-events'
    build.mkdir(parents=True, exist_ok=True)
    library = build / 'events.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-Wl,--no-undefined',
                    *[str(ROOT / path) for path in SOURCES], '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    ctxarg = C.POINTER(Platform)
    for name in ['fx_welcome_draw_banner', 'fx_diagnostic_checksum', 'fx_host_control_notify']:
        getattr(lib, name).argtypes = [ctxarg]
    lib.fx_diagnostic_checksum.restype = C.c_uint16
    for name in ['fx_diagnostic_draw_screen', 'fx_diagnostic_draw_pattern',
                 'fx_diagnostic_draw_key_counter']:
        getattr(lib, name).argtypes = [ctxarg, C.c_uint8]
    lib.fx_diagnostic_single_bit.argtypes = [C.c_uint8]
    lib.fx_diagnostic_single_bit.restype = C.c_uint8
    lib.fx_host_control_clear.argtypes = [ctxarg, C.c_uint16]
    lib.fx_welcome_begin.argtypes = [C.POINTER(Welcome)]
    lib.fx_welcome_tick.argtypes = [ctxarg, C.POINTER(Welcome), C.c_void_p]
    lib.fx_welcome_accept_pair.argtypes = [ctxarg, C.POINTER(Welcome), Key]
    for name in ['fx_host_control_begin', 'fx_host_control_finish']:
        getattr(lib, name).argtypes = [ctxarg, C.POINTER(Control)]
    lib.fx_boot_events_begin.argtypes = [ctxarg, C.POINTER(Events), C.c_int]
    lib.fx_boot_diagnostic_sequence_begin.argtypes = [ctxarg, C.POINTER(Events)]
    lib.fx_boot_events_tick.argtypes = [ctxarg, C.POINTER(Events), C.c_void_p]

    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_data = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)()
    p = Platform(rom_data, len(rom), ram, 0, 0)
    native = Machine(rom, build / 'oracle')
    rng = random.Random(0x7010740c)
    background = bytearray(rng.randbytes(65536))
    background[0x8dee:0x8e00] = rom[0x1f8dc:0x1f8ee]
    counts, bounded = {}, {}

    def initial():
        data = bytearray(background)
        for a, v in [(0x80f9, 0xc1), (0x80fa, 1), (0x80fb, 0), (0x80fc, 1),
                     (0x80fd, 0), (0x80fe, 1), (0x80ff, 0), (0x80dd, 0),
                     (0x80dc, 3), (0x80f8, 0xa7), (0x80f4, 0), (0x8112, 17),
                     (0x811b, 10), (0x811f, 10), (0x8118, 0), (0x8119, 1),
                     (0x811a, 0x7c), (0x8120, 0), (0x8121, 1),
                     (0x8105, 4), (0x8106, 1), (0x810c, 0), (0x8137, 0),
                     (0x8e00, 0), (0x8e01, 0), (0x8e02, 0),
                     (0xf040, 0xff), (0xf050, 3)]: data[a] = v
        data[0x8140:0x8154] = bytes(20)
        data[0x8154:0x81b8] = bytes(100)
        data[0x8226:0x8230] = bytes(10)
        data[0x8408:0x8412] = bytes(10)
        data[0x812c:0x812e] = (0x8154).to_bytes(2, 'little')
        return data

    def restore(data=None):
        native.reset()
        data = initial() if data is None else data
        C.memmove(ram, bytes(data), 65536)
        C.memmove(native.ram, bytes(data), 65536)
        p.callback_pending = p.status = 0
        native.lib.harness_callback()

    def start(entry):
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_lr(0x2fffe)
        native.lib.harness_set_pc(entry)

    def run(stop, advance=False):
        if advance:
            status = native.lib.harness_run(1, 0x2fffe, False)
            assert status == 103
        status = native.lib.harness_run(4000000, stop, False)
        assert status == 100, (status, hex(native.lib.harness_get_pc()), hex(stop))

    def equal(tag):
        actual, expected = bytes(ram), bytes(native.ram)
        spans = [(0, 0x8d00), (0x8dee, 65536)]
        if any(actual[lo:hi] != expected[lo:hi] for lo, hi in spans):
            differences = [(hex(a), actual[a], expected[a])
                           for lo, hi in spans for a in range(lo, hi) if actual[a] != expected[a]]
            raise AssertionError((tag, differences[:24]))
        assert p.callback_pending == native.lib.harness_callback(), (tag, 'callback')
        group = tag.split(':')[0]
        counts[group] = counts.get(group, 0) + 1

    def put(a, v): ram[a] = native.ram[a] = v

    #5550's host-service split is checked for every possible response byte.
    for response in range(256):
        restore()
        state = Control()
        assert lib.fx_host_control_begin(C.byref(p), C.byref(state)) == 0
        start(0x5550); run(0x5564)
        equal(f'control_begin:{response}')
        put(0x8e00, response)
        assert lib.fx_host_control_finish(C.byref(p), C.byref(state)) == bool(response)
        run(0x2fffe)
        assert native.er(0) == bool(response)
        equal(f'control_finish:{response}')
    for period in [0, 1, 13, 20, 0x129a, 65535]:
        restore(); lib.fx_host_control_clear(C.byref(p), period)
        native.er(0, period); native.call(0x5596)
        equal(f'control_clear:{period}')
    restore(); lib.fx_host_control_notify(C.byref(p)); native.call(0x557e)
    equal('control_notify:4')

    for value in range(256):
        restore(); native.reg(0, value); native.call(0x73d8)
        assert lib.fx_diagnostic_single_bit(value) == native.reg(0)
        equal(f'single_bit:{value}')

    # Static glyph/buffer paths deliberately include nonstandard rendering
    # settings. The code preserves8120/8121 rather than imposing normal mode.
    for selected in [0, 1, 37]:
        for composite in [0, 1, 2, 3, 4]:
            data = initial(); data[0x8120] = composite; data[0x8121] = selected
            restore(data); lib.fx_welcome_draw_banner(C.byref(p))
            start(0x7010); run(0x7034)
            equal(f'welcome_banner:{selected}/{composite}')
            for pattern, entry in enumerate([0x7150, 0x7150, 0x71a6, 0x715e, 0x717e]):
                restore(data)
                assert lib.fx_diagnostic_draw_pattern(C.byref(p), pattern) == 0
                native.reg(0, 0 if pattern == 1 else 255)
                start(entry); run(0x1dd82)
                equal(f'pattern:{pattern}/{selected}/{composite}')
    for index in range(49):
        restore()
        assert lib.fx_diagnostic_draw_key_counter(C.byref(p), index) == 0
        start(0x70d4); run(0x70e6)
        # Entry's clear is outside the prepared counter boundary70E6.
        C.memmove(native.ram, bytes(ram), 65536)
        # Reset C to the same arbitrary framebuffer and let both draw once.
        data = initial(); C.memmove(ram, bytes(data), 65536)
        C.memmove(native.ram, bytes(data), 65536)
        native.word(native.er(14)+2, 0)
        native.reg(8, index); run(0x7112)
        assert lib.fx_diagnostic_draw_key_counter(C.byref(p), index) == 0
        equal(f'key_counter:{index}')

    # Architectural7334 has no persistent effects. The oracle is stopped
    # before it and supplied its result at7286, matching the explicit C API.
    for port in range(256):
        data = initial(); data[0xf050] = port
        restore(data)
        lib.fx_diagnostic_draw_screen(C.byref(p), 0xa5)
        start(0x71ec); run(0x7282)
        native.reg(0, 0xa5); native.lib.harness_set_pc(0x7286); run(0x72cc)
        equal(f'diagnostic_screen:{port}')
    for result in range(256):
        # Avoid repeating checksum work: prepare native full prefix at7286,
        # then the entire C draw overwrites the same visual region.
        restore(); start(0x71ec); run(0x7282)
        native.lib.harness_set_pc(0x7286); native.reg(0, result)
        lib.fx_diagnostic_draw_screen(C.byref(p), result)
        run(0x72cc); equal(f'read_test_caption:{result}')
    restore(); native.call(0x72ee, limit=4000000)
    assert lib.fx_diagnostic_checksum(C.byref(p)) == native.er(0) == 0xe803
    equal('checksum:original')
    # ROM metadata and stored checksum are inputs, not hardcoded captions.
    # Changes stay inside immutable test images and retain executable/font
    # bytes. The stored word is outside the checksum's own input range.
    for selected in [0,1]:
        for composite in [0,1,2,3,4]:
            for matches in [False,True]:
                variant = bytearray(rom)
                variant[0x1fff4:0x1fffc] = bytes(rng.randrange(32,127) for _ in range(8))
                checksum = (-sum(variant[:65536])-sum(variant[65536:0x1fffc])) & 65535
                variant[0x1fffc:0x1fffe] = ((checksum if matches else checksum^0x100)).to_bytes(2,'little')
                C.memmove(rom_data, bytes(variant), len(rom)); native.rom = bytes(variant)
                data = initial(); data[0x8120] = composite; data[0x8121] = selected
                restore(data)
                lib.fx_diagnostic_draw_screen(C.byref(p), 0 if composite & 1 else 0xa5)
                start(0x71ec); run(0x7282)
                native.reg(0, 0 if composite & 1 else 0xa5)
                native.lib.harness_set_pc(0x7286); run(0x72cc)
                equal(f'diagnostic_rom_metadata:{selected}/{composite}/{matches}')
                assert lib.fx_diagnostic_checksum(C.byref(p)) == checksum
    C.memmove(rom_data, rom, len(rom)); native.rom = rom

    # Welcome release/poll/scan loops: external inputs are changed only at
    # corresponding native peripheral-service boundaries.
    for columns in range(256):
        restore()
        w = Welcome(); lib.fx_welcome_begin(C.byref(w))
        start(0x1e4aa); run(0x1e4c2)
        assert (w.remaining, w.remembered.columns, w.remembered.rows) == (native.er(4), 128, 1)
        put(0xf040, columns)
        assert lib.fx_welcome_tick(C.byref(p), C.byref(w), None) == 0
        run(0x1e4c2 if (~columns & 128) else 0x1e53e, advance=True)
        assert w.remaining == native.er(4)
        assert w.phase == (1 if ~columns & 128 else 2)
        equal(f'welcome_release:{columns}')
        if w.phase == 2:
            for sample in [255, 251]:
                put(0xf040, sample)
                assert lib.fx_welcome_tick(C.byref(p), C.byref(w), None) == 0
                run(0x1e53e if sample == 255 else 0x1e4f6, advance=True)
                equal(f'welcome_poll:{columns}/{sample}')
            assert lib.fx_welcome_tick(C.byref(p), C.byref(w), None) == 0
            run(0x1e4c2)
            assert w.phase == 1 and w.remembered.columns == 4 and w.remembered.rows == 1
            equal(f'welcome_scan:{columns}')
    for pair in [(4,4), (4,16), (1,1), (128,64), (0,0), (255,255)]:
        restore(); start(0x1e4aa); run(0x1e4c2)
        w = Welcome(); lib.fx_welcome_begin(C.byref(w)); w.phase = 3
        native.ram[(native.er(14)-4)&65535] = pair[0]
        native.ram[(native.er(14)-3)&65535] = pair[1]
        native.lib.harness_set_pc(0x1e51c)
        result = lib.fx_welcome_accept_pair(C.byref(p), C.byref(w), Key(*pair))
        final = pair in [(4,4), (4,16)]
        run(0x2fffe if final else 0x1e4c2)
        assert result == int(final)
        assert w.decision == (pair == (4,4))
        equal(f'welcome_stable_pair:{pair}')
    for phase, remaining in [(1,0), (1,1), (2,1), (2,0)]:
        restore(); start(0x1e4aa); run(0x1e4c2)
        native.er(4, remaining); native.lib.harness_set_pc(0x1e4c2 if phase == 1 else 0x1e53e)
        w = Welcome(remaining, Key(128,1), phase, 0, 1)
        put(0xf040, 0x7f if phase == 1 else 0xff)
        result = lib.fx_welcome_tick(C.byref(p), C.byref(w), None)
        finished = (phase == 1 and remaining == 0) or (phase == 2 and remaining == 1)
        run(0x2fffe if finished else (0x1e4c2 if phase == 1 else 0x1e53e), advance=True)
        assert result == int(finished)
        equal(f'welcome_count_boundary:{phase}/{remaining}')

    normal = {rom[0x7fe+c*8+r]: (1 << c, 1 << r) for c in range(8) for r in range(8)}

    # Complete7010 timeout and D74C boot-tail policy for every mode byte,
    # with both mode12 initialization branches. Timeout is prepared exactly
    # at the native remaining-count check, preserving all prior display RAM.
    for mode, mode12 in [(mode,0) for mode in range(256)]+[(12,1),(12,255)]:
        data = initial(); data[0x80f9] = mode; data[0x8137] = mode12
        restore(data)
        state = Events(); assert lib.fx_boot_events_begin(C.byref(p), C.byref(state), 2) == 0
        start(0xd748); run(0x1e4c2)
        equal(f'boot_welcome_begin:{mode}/{mode12}')
        state.welcome.remaining = 0; native.er(4,0)
        assert lib.fx_boot_events_tick(C.byref(p), C.byref(state), None) == 1
        run(0xd7ae)
        equal(f'boot_welcome_tail:{mode}/{mode12}')

    # The verified stable physical pair44 transitions from7010 into7044.
    # Using the explicit stable-pair adapter permits all native matrix rows
    # without depending on the oracle's passive F040 register limitation.
    restore(); state = Events()
    assert lib.fx_boot_events_begin(C.byref(p),C.byref(state),2) == 0
    start(0xd748); run(0x1e4c2)
    native.ram[(native.er(14)-4)&65535] = 4
    native.ram[(native.er(14)-3)&65535] = 4
    native.lib.harness_set_pc(0x1e51c)
    state.welcome.phase = 3
    assert lib.fx_welcome_accept_pair(C.byref(p),C.byref(state.welcome),Key(4,4)) == 1
    assert lib.fx_boot_events_tick(C.byref(p),C.byref(state),None) == 0
    run(0x1d8a4)
    assert state.full_diagnostic and state.phase == 2
    equal('boot_welcome_full_diagnostic:44')

    # Direct740C boot branch, including host refusal/retry, cold RAM reset
    # and the ordinaryD740..D7AE continuation.
    for port in [0, 3, 7, 128, 255]:
        restore(); put(0xf050, port)
        #740C shares73F8's pushed return address; enter through that caller
        # and stop after its three qualifying reset-key samples.
        native.ram[0xf040] = 0xe7
        start(0x73f8); run(0x740c)
        native.ram[0xf040] = 0xff
        state = Events(); assert lib.fx_boot_events_begin(C.byref(p), C.byref(state), 1) == 0
        run(0x5564)
        equal(f'boot_diagnostic_begin:{port}')
        for index in range(3):
            put(0x8e00, 0)
            assert lib.fx_boot_events_tick(C.byref(p), C.byref(state), None) == 0
            run(0x5564, advance=True)
            equal(f'boot_diagnostic_retry:{port}/{index}')
        assert lib.fx_boot_events_tick(C.byref(p), C.byref(state), None) == 1
        run(0x2fffe)
        #740C returns before6FE6's probe; the C boot API includes that probe.
        native.call(0x6fe6)
        equal(f'boot_diagnostic_reset:{port}')

    # Complete7044 chain with the ordinary1DB34 header enabled. Its address
    # classifier preserves all numeric workspaces; no persistent operand or
    # header memory is excluded or copied from the oracle.
    for contrast in [0, 4, 17, 29, 31, 255]:
        restore(); put(0x8112, contrast)
        state = Events(); assert lib.fx_boot_diagnostic_sequence_begin(C.byref(p), C.byref(state)) == 0
        start(0x7044); run(0x1d8a4)
        equal(f'sequence_begin:{contrast}')
        def pair_tick(pair, stop, tag):
            put(0x8e01, pair[0]); put(0x8e02, pair[1])
            result = lib.fx_boot_events_tick(C.byref(p), C.byref(state), None)
            run(stop, advance=True)
            equal(tag)
            put(0x8e01, 0); put(0x8e02, 0)
            return result
        for pattern in range(5):
            assert pair_tick(normal[0x31], 0x1d8a4, f'pattern_wrong_key:{contrast}/{pattern}') == 0
            assert pair_tick(normal[0xe9], 0x5564 if pattern == 4 else 0x1d8a4,
                             f'pattern_advance:{contrast}/{pattern}') == 0
        assert state.phase == 3
        # Expanded contrast handler's key-controller begin remains part of
        # this full comparison, including all native classifier scratch.
        assert lib.fx_boot_events_tick(C.byref(p), C.byref(state), None) == 0
        run(0x1d8a4, advance=True)
        equal(f'sequence_contrast_begin:{contrast}')
        for token in [0xe3, 0xe2, 0x31, 0xe6]:
            assert pair_tick(normal[token], 0x1d8a4, f'sequence_contrast_key:{contrast}/{token}') == 0
        assert state.phase == 5 and state.key_index == 0
        for index, code in enumerate(rom[0x2d5a:0x2d5a+49]):
            assert pair_tick((255,255), 0x1d8a4, f'physical_key_wrong:{contrast}/{index}') == 0
            expected = (1 << ((code >> 4)-1), 1 << ((code & 15)-1))
            assert pair_tick(expected, 0x1d8a4, f'physical_key_correct:{contrast}/{index}') == 0
            assert state.key_index == index+1
        assert state.phase == 6
        # Contrast is captured after the final wait, even after external edit.
        put(0x8112, contrast)
        assert pair_tick(normal[0x31], 0x2fffe, f'sequence_reset:{contrast}') == 1
        assert ram[0x8112] == ram[0xf032] == contrast

    # C-only validation checks never execute an oracle outside its domain.
    saved = bytes(ram)
    for pattern in range(5,256):
        assert lib.fx_diagnostic_draw_pattern(C.byref(p), pattern) == -1
        assert bytes(ram) == saved
        bounded['invalid_pattern'] = bounded.get('invalid_pattern',0)+1
    for index in range(49,256):
        assert lib.fx_diagnostic_draw_key_counter(C.byref(p), index) == -1
        assert bytes(ram) == saved
        bounded['invalid_key_index'] = bounded.get('invalid_key_index',0)+1

    # Hash the exact linked dependency closure, including its headers.
    headers, pending = set(), [ROOT/source for source in SOURCES]
    while pending:
        source = pending.pop()
        for include in re.findall(r'^\s*#include\s+"([^"]+)"', source.read_text(), re.M):
            header = (source.parent/include).resolve()
            name = str(header.relative_to(ROOT))
            if name not in headers:
                headers.add(name)
                pending.append(header)
    report = {'suite': 'nonblocking boot welcome/diagnostic events',
              'cases': sum(counts.values())+sum(bounded.values()),
              'native_cases': sum(counts.values()), 'native_counts': counts,
              'explicit_c_bounds_cases': sum(bounded.values()), 'explicit_c_bounds_counts': bounded,
              'comparison': 'Full RAM/MMIO and callback, excluding only nativeCPU stack8D00..8DED',
              'architecture_test': '7334 CPU flag-test result is supplied at native7286; no C CPU or flag model',
              'sequence_preparation': 'Full7044 uses ordinary80FB=0 with the native annunciator and classifier workspaces included in complete RAM comparison',
              'failures': 0}
    write_report('analysis/c-verification/boot_events.json', report,
                 SOURCES+sorted(headers)+['tools/c_verification.py', 'tools/test_platform_c.py',
                 'tools/test_key_wait_c.py', 'tools/test_key_controller_c.py',
                 'tools/test_diagnostic_contrast_c.py'], 'tools/test_boot_events_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
