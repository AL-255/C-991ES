#!/usr/bin/env python3
"""Differential boot, retained-state and emulator packet checks against ROM."""
import ctypes as C
import json
from pathlib import Path
import random
import subprocess

from c_verification import write_report
from nxu8.machine import Machine

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'analysis/build/boot'


class Platform(C.Structure):
    _fields_ = [('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t),
                ('ram', C.POINTER(C.c_uint8)), ('callback_pending', C.c_uint8), ('status', C.c_int)]

class HostDescriptor(C.Structure):
    _fields_ = [(name, C.c_uint16) for name in
                ('wait_flag', 'key_columns', 'key_rows', 'numeric_packet',
                 'framebuffer_packet', 'packet_length', 'status_packet',
                 'status_details', 'text_header', 'text')]


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    modules = ['data/fx_rom_data', 'platform/fx_platform', 'platform/fx_boot', 'platform/fx_host_bridge',
               'ui/fx_keys', 'ui/fx_cursor', 'ui/fx_editor', 'ui/fx_natural_editor',
               'parse/fx_tokens', 'numeric/fx_numeric','numeric/fx_surd_components','numeric/fx_raw_decimal_parts','numeric/fx_raw_decimal_divide','numeric/fx_raw_decimal_multiply_add', 'format/fx_format',
               'format/fx_format_base', 'render/fx_render', 'render/fx_render_context',
               'render/fx_render_memory', 'render/fx_layout_validate',
               'render/fx_result_special', 'render/fx_result_verify', 'render/fx_result_format_state']
    sources = [Path('csrc') / (module + '.c') for module in modules]
    library = BUILD / 'fx_boot.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', '-Wl,--no-undefined',
                    *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    ctxarg = C.POINTER(Platform)
    word_functions = ['fx_host_write_descriptor', 'fx_host_write_status', 'fx_host_write_text_packet']
    for name in word_functions:
        getattr(lib, name).argtypes = [ctxarg, C.c_uint16]
        getattr(lib, name).restype = C.c_int if name.endswith('text_packet') else None
    noarg_functions = ['fx_host_write_framebuffer', 'fx_boot_write_signature',
                       'fx_boot_retained_state_invalid', 'fx_boot_clear_expression',
                       'fx_boot_clear_exported_input', 'fx_boot_clear_result_workspaces',
                       'fx_boot_reset_settings', 'fx_boot_cold_reset', 'fx_boot_default_screen',
                       'fx_boot_probe_welcome_key', 'fx_boot_initialize', 'fx_boot_resume',
                       'fx_boot_prepare_power_off', 'fx_boot_reset', 'fx_boot_initialize_mode12',
                       'fx_host_write_numeric_packet']
    for name in noarg_functions:
        getattr(lib, name).argtypes = [ctxarg]
        getattr(lib, name).restype = C.c_int
    lib.fx_boot_initialize_editor.argtypes = [ctxarg, C.c_uint8]
    lib.fx_boot_initialize_editor.restype = C.c_int
    lib.fx_host_descriptor_default.argtypes = [C.POINTER(HostDescriptor)]
    for name in ['fx_host_write_text_packet_fields', 'fx_host_write_numeric_packet_fields',
                 'fx_host_write_framebuffer_fields']:
        getattr(lib, name).argtypes = [ctxarg, C.POINTER(HostDescriptor)]
        getattr(lib, name).restype = None if name.endswith('framebuffer_fields') else C.c_int
    lib.fx_host_format_number.argtypes = [C.POINTER(Number), C.POINTER(C.c_uint8)]
    lib.fx_host_format_number.restype = C.c_int
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_bytes = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)()
    ctx = Platform(rom_bytes, len(rom), ram, 0, 0)
    native = Machine(rom, ROOT / 'analysis/build')
    rng = random.Random(0xb007991)
    background = bytearray(rng.randbytes(65536))
    # The startup pointer table is data belonging to the calling context.
    for n in range(0x12):
        background[0x8dee+n] = rom[0x1f8dc+n]
    counts = {}

    def restore(initial=None):
        data = background if initial is None else initial
        C.memmove(ram, bytes(data), 65536)
        C.memmove(native.ram, bytes(data), 65536)
        ctx.callback_pending = 0
        native.lib.harness_callback()

    def equal(tag, numeric_workspace=False):
        actual, expected = bytes(ram), bytes(native.ram)
        exclusions = [(0x8d00, 0x8dee)]
        if numeric_workspace:
            exclusions += [(0x8000, 0x80dc)]
        comparable = [(0, 0x8d00), (0x8dee, 65536)]
        if numeric_workspace: comparable[0:1] = [(0, 0x8000), (0x80dc, 0x8d00)]
        if any(actual[lo:hi] != expected[lo:hi] for lo, hi in comparable):
            mismatch = [n for n in range(65536) if actual[n] != expected[n]
                        and not any(lo <= n < hi for lo, hi in exclusions)]
            raise AssertionError((tag, [(hex(n), actual[n], expected[n]) for n in mismatch[:12]]))
        assert ctx.callback_pending == native.lib.harness_callback(), (tag, 'callback value')
        counts[tag.split(':')[0]] = counts.get(tag.split(':')[0], 0) + 1

    def settings_initial():
        initial = bytearray(background)
        initial[0x80f9] = 0xc1
        initial[0x80fa] = 1
        initial[0x80dd] = 0
        initial[0x80fc] = 1
        initial[0x80fe] = 1
        initial[0x80fb] = 0
        initial[0x80f8] = 0
        initial[0x8102:0x810f] = rom[0x1ffd0:0x1ffdd]
        initial[0x8112] = 17
        initial[0x811f] = 10
        initial[0x8120] = 0
        initial[0x8121] = 1
        initial[0x8154:0x81b8] = bytes(100)
        initial[0x80dc] = 3
        initial[0x860e:0x861d] = bytes(range(15, 0, -1))
        for index in range(10):
            initial[0x8226+10*index:0x8230+10*index] = bytes(10)
        initial[0xf040] = 255
        return initial

    for destination in [0x8000, 0x8154, 0x8400, 0x8e00, 0xf000, 0xfff0]:
        restore()
        lib.fx_host_write_descriptor(C.byref(ctx), destination)
        native.er(0, destination)
        native.call(0x792c)
        equal(f'descriptor:{destination:04x}')

    status_fields = [0x80dd, 0x80fb, 0x80fe, 0x80f8, 0x8105, 0x8118, 0x8119, 0x811a, 0x811b]
    initial = settings_initial()
    for field in status_fields:
        for value in range(256):
            restore(initial)
            ram[field] = native.ram[field] = value
            lib.fx_host_write_status(C.byref(ctx), 0x9804)
            native.er(0, 0x9804)
            native.call(0x796e)
            equal(f'status:{field:04x}/{value:02x}')
    for index in range(200):
        initial = settings_initial()
        initial[0xf800:0xfa00] = rng.randbytes(512)
        restore(initial)
        lib.fx_host_write_framebuffer(C.byref(ctx))
        native.call(0x742c)
        equal(f'framebuffer:{index}')
    for length in [0, 1, 2, 15, 99, 255, 256, 1023, 4095, 8191]:
        initial = settings_initial()
        restore(initial)
        lib.fx_host_write_descriptor(C.byref(ctx), 0x8400)
        C.memmove(native.ram, bytes(ram), 65536)
        # Relocate the optional text and header to avoid accidental overlap
        # with the fixed status packet for the long string boundary cases.
        ram[0x8412] = native.ram[0x8412] = 0
        ram[0x8413] = native.ram[0x8413] = 0xa0
        text = bytes(rng.randrange(1, 256) for _ in range(length)) + b'\0'
        C.memmove(C.byref(ram, 0xa000), text, len(text))
        C.memmove(C.byref(native.ram, 0xa000), text, len(text))
        assert lib.fx_host_write_text_packet(C.byref(ctx), 0x8400) == 0
        native.er(0, 0x8400)
        native.call(0xaf5a)
        equal(f'text_packet:{length}')

    descriptor = HostDescriptor()
    lib.fx_host_descriptor_default(C.byref(descriptor))
    assert list(C.cast(C.byref(descriptor), C.POINTER(C.c_uint16))[:10]) == [
        0x8e00, 0x8e01, 0x8e02, 0x8e10, 0x9000,
        0x9800, 0x9804, 0x9808, 0x9834, 0x9838]
    # The native caller's descriptor is a stack local. Only the oracle gets
    # that local; the C controller retains the fields outside calculator RAM.
    for index in range(256):
        initial = settings_initial()
        initial[0x80f8] = index
        for field in ['status_packet', 'packet_length', 'text_header', 'text']:
            setattr(descriptor, field, {'status_packet': 0xa100, 'packet_length': 0xa200,
                    'text_header': 0xa204, 'text': 0xa210}[field])
        if index & 1: descriptor.text = 0
        if index & 2: descriptor.text_header = descriptor.status_packet
        if index & 4: descriptor.packet_length = descriptor.status_packet + 7
        if index & 8: descriptor.text = descriptor.status_packet
        if index & 16: descriptor.text_header = descriptor.packet_length
        initial[0xa210:0xa217] = b'Ans=3\0\0'
        restore(initial)
        descriptor_bytes = bytes(descriptor)
        native.ram[0x8d00:0x8d14] = descriptor_bytes
        assert lib.fx_host_write_text_packet_fields(C.byref(ctx), C.byref(descriptor)) == 0
        assert bytes(descriptor) == descriptor_bytes
        native.er(0, 0x8d00)
        native.call(0xaf5a)
        equal(f'text_packet_fields:{index}')

    def native_packet_destination(entry, checkpoint, local_offset, destination):
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_lr(0x2fffe)
        native.lib.harness_set_pc(entry)
        assert native.lib.harness_run(1000000, checkpoint, False) == 100
        native.word((native.er(14) + local_offset) & 65535, destination)
        assert native.lib.harness_run(1000000, 0x2fffe, False) == 100

    for destination in [0x9000, 0x8230, 0xf800, 0xf8a0, 0xfff0, 0x7ff0]:
        restore(settings_initial())
        lib.fx_host_descriptor_default(C.byref(descriptor))
        descriptor.framebuffer_packet = destination
        lib.fx_host_write_framebuffer_fields(C.byref(ctx), C.byref(descriptor))
        native_packet_destination(0x742c, 0x743e, -12, destination)
        equal(f'framebuffer_fields:{destination:04x}')

    # Helper cases compare the actual 75A4 routine rather than the display
    # formatter. Complete RAM equality also verifies retained field tails.
    records = [bytes(10), bytes.fromhex('01234567890123456701'),
               bytes.fromhex('91234567890123456706'),
               bytes.fromhex('21a30000000000000301'),
               bytes.fromhex('89980199099701990601')]
    records += [bytes([first]) + bytes.fromhex('234567890123450001')
                for first in range(256)]
    records += [bytes([0xf0 | code]) + rng.randbytes(9) for code in range(16)]
    records += [bytes([first]) + rng.randbytes(7) + bytes(2) for first in range(256)]
    for index in range(5000):
        record = bytearray(rng.randbytes(10))
        while record[0] >> 4 in (2, 8): record[0] = rng.randrange(256)
        records.append(bytes(record))
    for index in range(4096):
        record = bytearray(rng.randbytes(10))
        record[0] = 0x80 | (record[0] & 15)
        records.append(bytes(record))
    for index in range(4096):
        record = bytearray(rng.randbytes(10))
        record[0] = 0x20 | (record[0] & 15)
        length = rng.randrange(22)
        record[8] = (length // 10)*16 + length % 10
        record[9] = rng.choice([1, 6, 22, 38, 54, 70, 230, 246])
        records.append(bytes(record))
    for index, record in enumerate(records):
        restore()
        ram[0x8700:0x870a] = native.ram[0x8700:0x870a] = record
        actual = lib.fx_host_format_number(C.cast(C.byref(ram, 0x8700), C.POINTER(Number)),
                                            C.cast(C.byref(ram, 0x8800), C.POINTER(C.c_uint8)))
        native.er(0, 0x8700); native.er(2, 0x8800)
        native.call(0x75a4)
        assert actual == native.er(0), ('numeric field status', index, actual, native.er(0))
        assert bytes(ram[0x8700:0x870a]) == record
        equal(f'numeric_export_field:{index}')
    for record in records[:5] + [records[261]]:
        for destination in range(0x86fa, 0x870b):
            restore()
            ram[0x8700:0x870a] = native.ram[0x8700:0x870a] = record
            actual = lib.fx_host_format_number(C.cast(C.byref(ram, 0x8700), C.POINTER(Number)),
                                                C.cast(C.byref(ram, destination), C.POINTER(C.c_uint8)))
            native.er(0, 0x8700); native.er(2, destination)
            native.call(0x75a4)
            assert actual == native.er(0)
            equal(f'numeric_export_overlap:{destination:04x}')

    # Native malformed rational counts can write past its 23-byte local.
    # Verify the explicit bounded C domain without executing a corrupt frame.
    for sign in range(256):
        for packed_length in range(256):
            normalized = sign - 5 if sign >= 5 else sign
            length = abs(100*(normalized & 15) + 10*(packed_length >> 4)
                         + (packed_length & 15) - 100)
            record = Number((C.c_uint8 * 10)(0x21, 0xa3, 0, 0, 0, 0, 0, 0, packed_length, sign))
            if length < 22 or not (sign or packed_length):
                restore()
                ram[0x8700:0x870a] = native.ram[0x8700:0x870a] = bytes(record)
                assert lib.fx_host_format_number(C.cast(C.byref(ram, 0x8700), C.POINTER(Number)),
                        C.cast(C.byref(ram, 0x8800), C.POINTER(C.c_uint8))) == 0
                native.er(0, 0x8700); native.er(2, 0x8800)
                native.call(0x75a4)
                equal(f'numeric_export_rational_tags:{sign}/{packed_length}')
                continue
            output = (C.c_uint8 * 23).from_buffer_copy(rng.randbytes(23))
            before = bytes(output)
            assert lib.fx_host_format_number(C.byref(record), output) == -1
            assert bytes(output) == before
            counts['numeric_export_bound'] = counts.get('numeric_export_bound', 0) + 1

    packet_records = [records[n] for n in [0, 1, 2, 3, 4, 10, 275, 543]]
    for mode in range(256):
        for index, real in enumerate(packet_records):
            initial = settings_initial()
            initial[0x80f9] = mode
            initial[0x8230:0x823a] = real
            initial[0x8412:0x841c] = packet_records[-1-index]
            restore(initial)
            assert lib.fx_host_write_numeric_packet(C.byref(ctx)) == 0
            native.call(0x747a)
            equal(f'numeric_packet:{mode}/{index}')
    for destination in [0x8e10, 0x8230, 0x8412, 0x80f9, 0xf000, 0xfff0, 0x7ff0]:
        for mode in [0xc1, 0xc4]:
            initial = settings_initial()
            initial[0x80f9] = mode
            initial[0x8230:0x823a] = packet_records[4]
            initial[0x8412:0x841c] = packet_records[3]
            restore(initial)
            lib.fx_host_descriptor_default(C.byref(descriptor))
            descriptor.numeric_packet = destination
            before_descriptor = bytes(descriptor)
            assert lib.fx_host_write_numeric_packet_fields(C.byref(ctx), C.byref(descriptor)) == 0
            assert bytes(descriptor) == before_descriptor
            native_packet_destination(0x747a, 0x751a, -84, destination)
            equal(f'numeric_packet_fields:{mode}/{destination:04x}')

    for bad_component in ['real', 'imaginary']:
        restore(settings_initial())
        ram[0x80f9] = 0xc4
        ram[0x8230:0x823a] = bytes(10)
        ram[0x8412:0x841c] = bytes(10)
        address = 0x8230 if bad_component == 'real' else 0x8412
        ram[address:address+10] = bytes.fromhex('21a30000000000009901')
        before = bytes(ram)
        assert lib.fx_host_write_numeric_packet(C.byref(ctx)) == -1
        assert bytes(ram) == before
        counts['numeric_packet_bound'] = counts.get('numeric_packet_bound', 0) + 1

    restore()
    lib.fx_boot_write_signature(C.byref(ctx))
    native.call(0x52e2)
    equal('signature:write')
    valid = settings_initial()
    for field in list(range(0x860e, 0x861d)) + [0x8112, 0x80dc] + [
            0x8226+10*n+offset for n in range(10) for offset in [0, 9]]:
        for value in range(256):
            restore(valid)
            ram[field] = native.ram[field] = value
            actual = lib.fx_boot_retained_state_invalid(C.byref(ctx))
            native.call(0x52f0)
            assert actual == native.reg(0), (hex(field), value, actual, native.reg(0))
            equal(f'validation:{field:04x}/{value:02x}')
    for address, name in [(0x1d77e, 'fx_boot_clear_expression'),
                          (0x1d78a, 'fx_boot_clear_exported_input')]:
        restore()
        getattr(lib, name)(C.byref(ctx))
        native.call(address)
        equal(f'input_clear:{address:x}')
    for mode in range(256):
        restore()
        ram[0x80f9] = native.ram[0x80f9] = mode
        lib.fx_boot_clear_result_workspaces(C.byref(ctx))
        native.call(0x1d796)
        equal(f'workspace_clear:{mode}')

    # All editor control-byte actions, natural/legacy settings, and ordinary
    # and special screens. Preserve-capable inputs remain bounded by99.
    for action in range(256):
        for mode, screen, math in [(0xc1, 1, 1), (0xc1, 1, 0), (0xc1, 17, 1),
                                   (0xc4, 1, 1), (2, 1, 0), (0x88, 1, 1), (0x89, 1, 1)]:
            initial = settings_initial()
            initial[0x80f9], initial[0x80fc], initial[0x8106] = mode, screen, math
            initial[0x8154:0x8159] = b'12+3\0'
            initial[0x8114] = 2
            # ROM startup metadata names the BASE-N label strings.
            initial[0x8df2:0x8df6] = b'\xb9\x31\xb9\x31'
            restore(initial)
            actual = lib.fx_boot_initialize_editor(C.byref(ctx), action)
            assert actual == 0, ('editor status', action, mode, screen, actual)
            native.reg(0, action)
            native.call(0x1e55e)
            equal(f'editor_init:{action}/{mode}/{screen}/{math}',
                  numeric_workspace=(action & 15) == 2 and
                  not (mode == 0x88 or mode == 0x89 or (mode & 0x80 and math and screen == 1)))

    for index in range(256):
        initial = settings_initial()
        initial[0xf050] = index
        restore(initial)
        assert lib.fx_boot_cold_reset(C.byref(ctx)) == 0
        native.call(0x1d6ec)
        equal(f'cold_reset:{index}')
    for mode in range(256):
        initial = settings_initial()
        initial[0x80f9] = mode
        restore(initial)
        assert lib.fx_boot_reset_settings(C.byref(ctx)) == 0
        native.call(0x1d71c)
        equal(f'settings_reset:{mode}')
    for value in range(256):
        initial = settings_initial()
        initial[0xf040] = value
        restore(initial)
        actual = lib.fx_boot_probe_welcome_key(C.byref(ctx))
        native.call(0x6fe6)
        assert actual == native.reg(0), (value, actual, native.reg(0))
        equal(f'welcome_probe:{value}')
    for index in range(100):
        initial = settings_initial() if index & 1 else bytearray(rng.randbytes(65536))
        restore(initial)
        assert lib.fx_boot_initialize(C.byref(ctx)) == 0
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_pc(0xd6fe)
        assert native.lib.harness_run(1000000, 0xd730, False) == 100
        equal(f'boot_prelude:{index}')
    for flags in range(256):
        initial = settings_initial()
        initial[0x80f8] = flags
        restore(initial)
        assert lib.fx_boot_default_screen(C.byref(ctx)) == 0
        native.call(0x40a2)
        equal(f'default_screen:{flags}')
    for mode in range(256):
        initial = settings_initial()
        initial[0x80f9] = mode
        initial[0x8df2:0x8df6] = b'\xb9\x31\xb9\x31'
        restore(initial)
        assert lib.fx_boot_default_screen(C.byref(ctx)) == 0, ('default mode', mode)
        native.call(0x40a2)
        equal(f'default_screen_mode:{mode}', numeric_workspace=not (mode & 0x80) and mode != 0x89)
    for value in range(256):
        initial = settings_initial()
        initial[0xf040] = value
        restore(initial)
        actual = lib.fx_boot_resume(C.byref(ctx))
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_pc(0xd730)
        stop = 0x740c if value and not (value & 0x18) else 0xd748 if value == 0x7b else 0xd7ae
        assert native.lib.harness_run(1000000, stop, False) == 100
        assert actual == (1 if stop == 0x740c else 2 if stop == 0xd748 else 0)
        equal(f'boot_resume:{value}')
    for mode in [0xc1, 0xc4, 2, 0x88, 0x89, 0x45, 0x4a, 0x4b, 12]:
        initial = settings_initial()
        initial[0x80f9] = mode
        initial[0x8df2:0x8df6] = b'\xb9\x31\xb9\x31'
        restore(initial)
        actual = lib.fx_boot_resume(C.byref(ctx))
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_pc(0xd730)
        assert native.lib.harness_run(1000000, 0xd7ae, False) == 100
        assert actual == 0, ('resume mode', mode, actual)
        equal(f'boot_resume_mode:{mode}', numeric_workspace=not (mode & 0x80) and mode != 0x89)

    for flag in range(256):
        initial = bytearray(background)
        initial[0x8137] = flag
        restore(initial)
        lib.fx_boot_initialize_mode12(C.byref(ctx))
        native.call(0x1df7e)
        equal(f'mode12_initializer:{flag}')
        initial = settings_initial()
        initial[0x80f9] = 12
        initial[0x8137] = flag
        restore(initial)
        assert lib.fx_boot_resume(C.byref(ctx)) == 0
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_pc(0xd730)
        assert native.lib.harness_run(1000000, 0xd7ae, False) == 100
        equal(f'mode12_resume:{flag}', numeric_workspace=True)

    for suppression in range(256):
        initial = settings_initial()
        initial[0x80dd] = suppression
        restore(initial)
        actual = lib.fx_boot_prepare_power_off(C.byref(ctx))
        if suppression:
            native.call(0x5338)
            assert actual == 0
        else:
            native.lib.harness_set_sp(0x8dee)
            native.lib.harness_set_pc(0x5338)
            assert native.lib.harness_run(1000000, 0x6f82, False) == 100
            assert actual == 3
        equal(f'power_off:{suppression}')
    for index in range(100):
        initial = settings_initial() if index & 1 else bytearray(rng.randbytes(65536))
        initial[0xf040] = 255
        initial[0xf050] = index & 7
        restore(initial)
        assert lib.fx_boot_reset(C.byref(ctx)) == 0
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_pc(0x6f82)
        assert native.lib.harness_run(1000000, 0xd7ae, False) == 100
        equal(f'reset_entry:{index}')

    domain_checks = counts['numeric_export_bound'] + counts['numeric_packet_bound']
    report = {'cases': sum(counts.values()), 'native_cases': sum(counts.values()) - domain_checks,
              'bounded_domain_checks': domain_checks, 'groups': counts,
              'comparison': 'Whole RAM excluding native CPU stack8d00..8ded; editor action2 branches that format zero also exclude numeric operand workspace8000..80db. Query return bytes and complete host packets compared.',
              'boot_scope': 'Full6F82 reset-entry data initialization throughD7AE, separateD6FE/D730 checkpoints and5338 power-off writes through6F82; diagnostic and welcome key branches stop at their native event boundary.',
              'limitations': ['Physical time, interrupt delivery, diagnostic screens, welcome key-wait and main calculator event loop remain incomplete.',
                              'Malformed rational host-export counts that overrun the native23-byte local are explicitly rejected without packet writes.',
                              'Oversized BASE-N labels and unterminated strings are bounded in C; native CPU stack corruption or infinite loops are excluded.']}
    inputs = [str(p) for p in sources]
    inputs += [str(Path('csrc') / (module + '.h')) for module in modules
               if (ROOT / 'csrc' / (module + '.h')).exists()]
    report = write_report(ROOT / 'analysis/c-verification/boot.json', report, inputs + ['tools/c_verification.py'], 'tools/test_boot_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
