#!/usr/bin/env python3
"""Native differential checks for RAM result, variable, Ans and replay state.

The instruction emulator belongs only to this test oracle. Production code
receives records, bus addresses and prepared RAM, never a CPU stack/register
frame. GPL-3.0-only.
"""
import ctypes as C
import json
from pathlib import Path
import random
import subprocess

from c_verification import write_report
from nxu8.machine import Machine

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'analysis/build/persistent'


class Platform(C.Structure):
    _fields_ = [('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t),
                ('ram', C.POINTER(C.c_uint8)), ('callback_pending', C.c_uint8),
                ('status', C.c_int)]


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


def replay_base(mode):
    if mode in (0x45, 0x4a): return 0x8406
    if mode == 0x0c: return 0x84e2
    if mode != 0x89 and ((mode & 15) == 3 or (mode & 15) >= 6): return 0
    return 0x829e


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    modules = ['data/fx_rom_data', 'platform/fx_platform', 'platform/fx_boot',
               'platform/fx_host_bridge', 'platform/fx_persistent', 'ui/fx_keys',
               'ui/fx_cursor', 'ui/fx_editor', 'ui/fx_natural_editor',
               'parse/fx_tokens', 'numeric/fx_numeric', 'complex/fx_complex',
               'format/fx_format', 'format/fx_format_base', 'render/fx_render',
               'render/fx_render_context', 'render/fx_render_memory',
               'render/fx_layout_validate', 'render/fx_result_special',
               'render/fx_result_format_state']
    sources = [Path('csrc') / (module + '.c') for module in modules]
    library = BUILD / 'persistent.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-Wl,--no-undefined',
                    *(str(ROOT / path) for path in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    pointer = C.POINTER(Platform)
    clear_entries = {'fx_result_clear': 0x5176, 'fx_result_clear_flags': 0x5192,
                     'fx_result_clear_display_state': 0x51aa,
                     'fx_result_clear_format': 0x51ae,
                     'fx_result_reset_layout': 0x1d636,
                     'fx_result_reset_layout_and_flags': 0x1d646}
    for name in clear_entries:
        getattr(lib, name).argtypes = [pointer]
        getattr(lib, name).restype = None
    for name in ['fx_result_format_kind', 'fx_result_selection']:
        getattr(lib, name).argtypes = [pointer]
        getattr(lib, name).restype = C.c_uint8
    for name in ['fx_result_set_selection', 'fx_result_set_format']:
        getattr(lib, name).argtypes = [pointer, C.c_uint8]
        getattr(lib, name).restype = None
    for name in ['fx_store_variable_address', 'fx_store_variable_records']:
        getattr(lib, name).argtypes = [pointer, C.c_uint8,
                                     C.c_uint16 if name.endswith('address') else C.POINTER(Number)]
        getattr(lib, name).restype = None
    lib.fx_store_ans_address.argtypes = [pointer, C.c_uint16]
    lib.fx_store_ans_address.restype = None
    lib.fx_store_ans_records.argtypes = [pointer, C.POINTER(Number)]
    lib.fx_store_ans_records.restype = None
    lib.fx_replay_buffer.argtypes = [pointer]
    lib.fx_replay_buffer.restype = C.c_uint16
    lib.fx_replay_next.argtypes = [pointer, C.c_uint16, C.POINTER(C.c_uint16)]
    lib.fx_replay_count.argtypes = [pointer, C.POINTER(C.c_uint8)]
    lib.fx_replay_used.argtypes = [pointer, C.c_uint16, C.POINTER(C.c_uint8)]
    lib.fx_replay_append_prepared.argtypes = [pointer, C.c_uint8]
    for name in ['fx_replay_next', 'fx_replay_count', 'fx_replay_used',
                 'fx_replay_append_prepared', 'fx_replay_append', 'fx_replay_recall']:
        if name in ['fx_replay_append', 'fx_replay_recall']:
            getattr(lib, name).argtypes = [pointer]
        getattr(lib, name).restype = C.c_int
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_data = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)()
    platform = Platform(rom_data, len(rom), ram, 0, 0)
    native = Machine(rom, BUILD / 'oracle')
    rng = random.Random(0x1ea0c)
    background = bytearray(rng.randbytes(65536))
    background[0x8dee:0x8e00] = rom[0x1f8dc:0x1f8ee]
    counts, bounded_counts = {}, {}

    def record(value):
        number = Number()
        assert lib.fx_decimal_parse(C.byref(number), str(value).encode()) == 0
        return bytes(number.bytes)

    records = [record(value) for value in [0, 1, -1, 3, -3, '1.25', '-1.25']]
    records += [bytes.fromhex('80000001000201010100'), bytes([0xf3]) + bytes(9)]

    def restore(initial):
        C.memmove(ram, bytes(initial), 65536)
        C.memmove(native.ram, bytes(initial), 65536)
        platform.callback_pending = 0
        platform.status = 0
        native.lib.harness_callback()

    def prepared(mode=0xc1):
        initial = bytearray(background)
        for address, value in [(0x80f9, mode), (0x80fa, 1), (0x80fb, 0),
                               (0x80fc, 1), (0x80fd, 0), (0x80fe, 3),
                               (0x80ff, 0), (0x80dd, 0), (0x80f8, 0),
                               (0x8106, 1), (0x810c, 0), (0x811f, 10),
                               (0x8120, 0), (0x8121, 1)]:
            initial[address] = value
        initial[0x8154:0x81b8] = bytes(100)
        initial[0x8140:0x8154] = records[3] + records[0]
        initial[0x812c:0x812e] = (0x8154).to_bytes(2, 'little')
        base = replay_base(mode)
        if base: initial[base:base+310] = bytes(310)
        return initial

    def equal(tag, numeric_workspace=False):
        actual, expected = bytes(ram), bytes(native.ram)
        spans = [(0, 0x8d00), (0x8dee, 65536)]
        if numeric_workspace: spans[0:1] = [(0, 0x8000), (0x80dc, 0x8d00)]
        if any(actual[lo:hi] != expected[lo:hi] for lo, hi in spans):
            mismatch = [address for lo, hi in spans for address in range(lo, hi)
                        if actual[address] != expected[address]]
            raise AssertionError((tag, [(hex(a), actual[a], expected[a]) for a in mismatch[:12]]))
        assert platform.callback_pending == native.lib.harness_callback(), (tag, 'host callback')
        group = tag.split(':')[0]
        counts[group] = counts.get(group, 0) + 1

    def bounded(tag, call, expected=-1):
        before = bytes(ram)
        assert call() == expected, tag
        assert bytes(ram) == before, (tag, 'RAM mutated on rejected input')
        assert platform.callback_pending == 0, (tag, 'callback on rejected input')
        group = tag.split(':')[0]
        bounded_counts[group] = bounded_counts.get(group, 0) + 1

    def entry(flags, formatting, complex_display, real, imaginary, expression):
        return (bytes([flags, formatting, complex_display]) + real
                + (imaginary if flags & 0x80 else b'') + expression + b':')

    # Result clears change only their documented RAM fields, including when
    # initial mode/flags contain every possible byte.
    for name, address in clear_entries.items():
        for value in range(256):
            initial = bytearray(background)
            initial[0x80f9] = initial[0x80fe] = value
            restore(initial)
            getattr(lib, name)(C.byref(platform))
            native.call(address)
            equal(f'{name}:{value:02x}')
    for value in range(256):
        initial = bytearray(background); initial[0x8100] = value
        for name, address in [('fx_result_format_kind', 0x3624),
                              ('fx_result_selection', 0x362c)]:
            restore(initial)
            actual = getattr(lib, name)(C.byref(platform))
            native.call(address)
            assert actual == native.reg(0), (name, value, 'format getter')
            equal(f'{name}:{value:02x}')
        restore(initial)
        lib.fx_result_set_format(C.byref(platform), value)
        native.reg(0, value); native.call(0x3658)
        equal(f'format_set:{value:02x}')
    for previous in range(256):
        for incoming in range(16):
            initial = bytearray(background); initial[0x8100] = previous
            restore(initial)
            lib.fx_result_set_selection(C.byref(platform), incoming)
            native.reg(0, incoming); native.call(0x3644)
            equal(f'selection_set:{previous:02x}/{incoming:02x}')
    for previous in [0x00, 0x50, 0xa0, 0xf0]:
        for incoming in range(256):
            initial = bytearray(background); initial[0x8100] = previous
            restore(initial)
            lib.fx_result_set_selection(C.byref(platform), incoming)
            native.reg(0, incoming); native.call(0x3644)
            equal(f'selection_set_raw:{previous:02x}/{incoming:02x}')

    # Compare all caller-supported variable slots in every mode. These copies
    # preserve opaque numeric bytes, and C4 alone copies the imaginary record.
    for mode in range(256):
        for slot in range(10):
            initial = prepared(mode)
            source = 0x8700
            initial[source:source+20] = rng.randbytes(20)
            restore(initial)
            lib.fx_store_variable_address(C.byref(platform), slot, source)
            native.reg(0, slot); native.er(2, source); native.call(0x522a)
            equal(f'variable_address:{mode:02x}/{slot}')
            values = (Number * 2).from_buffer_copy(initial[source:source+20])
            restore(initial)
            lib.fx_store_variable_records(C.byref(platform), slot, values)
            native.reg(0, slot); native.er(2, source); native.call(0x522a)
            equal(f'variable_records:{mode:02x}/{slot}')
    # Native B942 is forward copying, so partial self-overlap must retain its
    # byte-by-byte alias effects instead of becoming a host memcpy/memmove.
    for mode in [0xc1, 0xc4]:
        for slot in range(10):
            destination = 0x8226 + 10*slot
            for source in [destination-9, destination-1, destination,
                           destination+1, destination+9, 0x8408+10*slot-1,
                           0x80f0, 0x7ffc, 0xfff8, 0xffff]:
                restore(prepared(mode))
                lib.fx_store_variable_address(C.byref(platform), slot, source)
                native.reg(0, slot); native.er(2, source); native.call(0x522a)
                equal(f'variable_alias:{mode:02x}/{slot}/{source:04x}')
    for mode in range(256):
        initial = prepared(mode)
        source = 0x8700
        initial[source:source+20] = rng.randbytes(20)
        restore(initial)
        lib.fx_store_ans_address(C.byref(platform), source)
        native.reg(0, 1); native.er(2, source); native.call(0x522a)
        equal(f'ans_address:{mode:02x}')
        restore(initial)
        values = (Number * 2).from_buffer_copy(initial[source:source+20])
        lib.fx_store_ans_records(C.byref(platform), values)
        native.reg(0, 1); native.er(2, source); native.call(0x522a)
        equal(f'ans_records:{mode:02x}')

    # The buffer selector and query-only operations must leave all RAM intact.
    for mode in range(256):
        initial = prepared(mode)
        base = replay_base(mode)
        restore(initial)
        assert lib.fx_replay_buffer(C.byref(platform)) == base
        native.call(0x11092)
        assert native.er(0) == base
        equal(f'replay_buffer:{mode:02x}')
        for screen in [1, 2]:
            initial[0x80fc] = screen
            entries = [entry(0x80 if i & 1 else 0, 0xad, i, records[3],
                             records[4], bytes([0x31+i])*(i+1)) for i in range(3)]
            if base: initial[base:base+sum(map(len, entries))] = b''.join(entries)
            restore(initial)
            count = C.c_uint8(0xab)
            assert lib.fx_replay_count(C.byref(platform), C.byref(count)) == 0
            native.call(0x1e9a0)
            assert count.value == native.reg(0), (mode, screen, 'history count')
            equal(f'replay_count:{mode:02x}/{screen}')

    for index in range(500):
        mode = rng.choice([0xc1, 0xc4, 0x45, 0x4a, 0x0c, 0x89, 2])
        initial = prepared(mode); base = replay_base(mode)
        entries = []
        for position in range(rng.randrange(1, 10)):
            flags = rng.randrange(256)
            item = entry(flags, rng.randrange(256), rng.randrange(256),
                         rng.choice(records), rng.choice(records),
                         bytes([0x31+position])*rng.randrange(0, 12))
            if sum(map(len, entries)) + len(item) > 240: break
            entries.append(item)
        initial[base:base+sum(map(len, entries))] = b''.join(entries)
        offset = 0
        for item in entries + [b'']:
            restore(initial)
            next_entry = C.c_uint16(0xabcd)
            assert lib.fx_replay_next(C.byref(platform), base+offset, C.byref(next_entry)) == 0
            native.er(0, base+offset); native.call(0x1e946)
            assert next_entry.value == native.er(0), ('next', index, offset)
            equal(f'replay_next:{index}/{offset}')
            used = C.c_uint8(0xab)
            restore(initial)
            assert lib.fx_replay_used(C.byref(platform), base+offset, C.byref(used)) == 0
            native.er(0, base+offset); native.call(0x1e9e8)
            assert used.value == native.reg(0), ('used', index, offset)
            equal(f'replay_used:{index}/{offset}')
            offset += len(item)

    def compare_append(initial, tag, prepared_classification=True, classification_override=None):
        restore(initial)
        if not prepared_classification or not replay_base(initial[0x80f9]):
            function = lib.fx_replay_append_prepared if prepared_classification else lib.fx_replay_append
            result = function(C.byref(platform), 1) if prepared_classification else function(C.byref(platform))
            assert result == 0, (tag, result)
            native.call(0x1ea0c)
            equal(tag, numeric_workspace=not prepared_classification)
            return
        # Let the oracle classify the imaginary component, then hand its RAM
        # snapshot to the semantic prepared API. CPU registers and frames stay
        # entirely inside the native oracle and are never passed to C.
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_lr(0x2fffe)
        native.lib.harness_set_pc(0x1ea0c)
        assert native.lib.harness_run(1000000, 0x1ea3e, False) == 100
        classification = native.reg(0)
        if classification_override is not None:
            classification = classification_override
            native.reg(0, classification)
        C.memmove(ram, bytes(native.ram), 65536)
        assert lib.fx_replay_append_prepared(C.byref(platform), classification) == 0, tag
        assert native.lib.harness_run(1000000, 0x2fffe, False) == 100
        equal(tag)

    for mode in range(256):
        initial = prepared(mode)
        initial[0x8154:0x8158] = b'1+2\0'
        compare_append(initial, f'replay_append_mode:{mode:02x}')
    for flags in range(256):
        for imaginary in [records[0], records[3]]:
            initial = prepared(0xc4)
            initial[0x814a:0x8154] = imaginary
            initial[0x80ff] = flags
            initial[0x8100] = (flags*13) & 255
            initial[0x8101] = (flags*7) & 255
            initial[0x8154:0x815c] = b'1+2:4+5\0'
            initial[0x80fe] = 0x43
            compare_append(initial, f'replay_append_flags:{flags:02x}/{imaginary.hex()}')
    # The prepared routine consumes native's equality-to-one decision only.
    # Preserve every classification byte, including values outside the four
    # outputs of the convenience scalar classifier.
    for classification in range(256):
        initial = prepared(0xc4)
        initial[0x8154:0x8158] = b'1+2\0'
        compare_append(initial, f'replay_append_classification:{classification:02x}',
                       classification_override=classification)
    for expression in [b':4+5', b'1+2:', b'1:2:3']:
        initial = prepared()
        initial[0x8154:0x8154+len(expression)+1] = expression + b'\0'
        initial[0x80fe] = 0x43
        compare_append(initial, f'replay_append_colon:{expression.hex()}')
    for index in range(800):
        mode = rng.choice([0xc1, 0xc4, 0x45, 0x4a, 0x0c, 0x89, 2])
        initial = prepared(mode); base = replay_base(mode)
        entries = []
        for position in range(rng.randrange(0, 16)):
            item = entry(rng.randrange(256), rng.randrange(256), rng.randrange(256),
                         rng.choice(records), rng.choice(records),
                         bytes([0x31+position%9])*rng.randrange(0, 17))
            if sum(map(len, entries)) + len(item) > 250: break
            entries.append(item)
        initial[base:base+sum(map(len, entries))] = b''.join(entries)
        initial[0x80ff] = rng.randrange(128)
        initial[0x8100] = rng.randrange(256); initial[0x8101] = rng.randrange(256)
        initial[0x814a:0x8154] = rng.choice(records)
        expression = bytes([0x31+index%9])*rng.randrange(0, 100)
        initial[0x8154:0x8154+len(expression)+1] = expression + b'\0'
        compare_append(initial, f'replay_append_eviction:{index}')
    for imaginary in [records[0], records[3]]:
        for length in [0, 99, 225, 226, 227, 231, 232, 235, 236, 237, 241]:
            actual_size = 14 + length + (10 if imaginary != records[0] else 0)
            if actual_size > 255: continue
            initial = prepared()
            initial[0x812c:0x812e] = (0x8700).to_bytes(2, 'little')
            initial[0x8700:0x8700+length+1] = b'1'*length + b'\0'
            initial[0x814a:0x8154] = imaginary
            compare_append(initial, f'replay_append_capacity:{length}/{imaginary.hex()}')
    for index in range(160):
        initial = prepared(rng.choice([0xc1, 0xc4]))
        initial[0x8154:0x8158] = b'1+2\0'
        initial[0x814a:0x8154] = records[index % len(records)]
        compare_append(initial, f'replay_append_convenience:{index}', False)

    # Recall compares every RAM effect, including editor reset and formatting
    # cache reset, with only the native CPU stack excluded.
    for mode in range(256):
        base = replay_base(mode)
        for selection in ([0, 1, 2, 3] if base else [0, 1]):
            initial = prepared(mode)
            initial[0x8113] = selection
            entries = [entry(0x80 if i & 1 else 7, 0xab, 0x3c, records[3],
                             records[4], bytes([0x31+i])*(i+1)) for i in range(3)]
            if base: initial[base:base+sum(map(len, entries))] = b''.join(entries)
            restore(initial)
            assert lib.fx_replay_recall(C.byref(platform)) == 0, (mode, selection)
            native.call(0x1eb76)
            equal(f'replay_recall_mode:{mode:02x}/{selection}')
    for flags in range(256):
        for selection in [1, 2]:
            initial = prepared(0xc4)
            initial[0x8113] = selection
            items = [entry(flags, flags ^ 0xac, flags ^ 0x39, records[3], records[4],
                           b'1+2'), entry(flags ^ 0x80, flags ^ 0xd7, flags,
                           records[4], records[3], b'98')]
            initial[0x829e:0x829e+sum(map(len, items))] = b''.join(items)
            restore(initial)
            assert lib.fx_replay_recall(C.byref(platform)) == 0
            native.call(0x1eb76)
            equal(f'replay_recall_flags:{flags:02x}/{selection}')
    for mode in [0xc1, 0xc4, 0x45, 0x0c, 0x4a, 0x89]:
        for flag in range(256):
            initial = prepared(mode); base = replay_base(mode)
            initial[0x8113] = 1; initial[0x8106] = flag
            initial[0x810c] = flag & 1
            item = entry(0, 0xab, 0x3c, records[3], records[0], b'1')
            initial[base:base+len(item)] = item
            restore(initial)
            assert lib.fx_replay_recall(C.byref(platform)) == 0
            native.call(0x1eb76)
            equal(f'replay_recall_single:{mode:02x}/{flag}')

    # These are C-only bounded-domain checks. The corresponding native input
    # can overrun RAM stores/editor arrays or walk arbitrary memory forever;
    # such behavior is deliberately never executed by the oracle.
    for size in [242, 243, 250, 255, 256, 300]:
        initial = prepared()
        initial[0x812c:0x812e] = (0x8700).to_bytes(2, 'little')
        initial[0x8700:0x8700+size+1] = b'1'*size + b'\0'
        restore(initial)
        bounded(f'append_length_bound:{size}', lambda: lib.fx_replay_append_prepared(C.byref(platform), 1))
    for imaginary_classification in [2, 4, 0xf0]:
        for size in [232, 233, 240, 255, 256]:
            initial = prepared()
            initial[0x812c:0x812e] = (0x8700).to_bytes(2, 'little')
            initial[0x8700:0x8700+size+1] = b'1'*size + b'\0'
            restore(initial)
            bounded(f'append_complex_length_bound:{imaginary_classification}/{size}',
                    lambda: lib.fx_replay_append_prepared(C.byref(platform), imaginary_classification))
    for length in [100, 150, 226, 236]:
        initial = prepared(); initial[0x8113] = 1
        item = entry(0, 0xab, 0x3c, records[3], records[0], b'1'*length)
        initial[0x829e:0x829e+len(item)] = item
        restore(initial)
        bounded(f'recall_expression_bound:{length}', lambda: lib.fx_replay_recall(C.byref(platform)))
    for selection in [4, 20, 255]:
        initial = prepared(); initial[0x8113] = selection
        item = entry(0, 0xab, 0, records[3], records[0], b'1')
        initial[0x829e:0x829e+len(item)] = item
        restore(initial)
        bounded(f'recall_index_bound:{selection}', lambda: lib.fx_replay_recall(C.byref(platform)))
    initial = prepared()
    initial[0x80fe] = 0x43
    initial[0x8154:0x8158] = b'1+2\0'
    restore(initial)
    bounded('append_colon_bound:missing', lambda: lib.fx_replay_append_prepared(C.byref(platform), 1))
    # Native finder accepts a delimiter at +250, producing a 251-byte record.
    # The bounded semantic implementation rejects that corrupted store.
    initial = prepared()
    initial[0x829e+13:0x829e+252] = b'1'*237 + b':\0'
    restore(initial)
    next_entry = C.c_uint16(0xabcd)
    bounded('history_capacity_bound:251', lambda: lib.fx_replay_next(C.byref(platform), 0x829e, C.byref(next_entry)))
    for address in [0, 0x829d, 0x8399, 0xffff]:
        restore(prepared())
        next_entry = C.c_uint16(0xabcd)
        bounded(f'history_start_bound:next/{address:04x}',
                lambda: lib.fx_replay_next(C.byref(platform), address, C.byref(next_entry)))
        used = C.c_uint8(0xab)
        bounded(f'history_start_bound:used/{address:04x}',
                lambda: lib.fx_replay_used(C.byref(platform), address, C.byref(used)))
    restore(prepared())
    for name, call in [
            ('next', lambda: lib.fx_replay_next(C.byref(platform), 0x829e, None)),
            ('used', lambda: lib.fx_replay_used(C.byref(platform), 0x829e, None)),
            ('count', lambda: lib.fx_replay_count(C.byref(platform), None))]:
        bounded(f'history_output_bound:{name}', call)
    initial = prepared()
    initial[0x829e:0x829e+251] = b'1'*251
    initial[0x8113] = 1
    restore(initial)
    next_entry = C.c_uint16(0xabcd); used = C.c_uint8(0xab); count = C.c_uint8(0xab)
    for name, call in [
            ('next', lambda: lib.fx_replay_next(C.byref(platform), 0x829e, C.byref(next_entry))),
            ('used', lambda: lib.fx_replay_used(C.byref(platform), 0x829e, C.byref(used))),
            ('count', lambda: lib.fx_replay_count(C.byref(platform), C.byref(count))),
            ('append', lambda: lib.fx_replay_append_prepared(C.byref(platform), 1)),
            ('recall', lambda: lib.fx_replay_recall(C.byref(platform)))]:
        bounded(f'history_termination_bound:{name}', call)

    inputs = [str(path) for path in sources]
    inputs += [str(Path('csrc') / (module + '.h')) for module in modules
               if (ROOT / 'csrc' / (module + '.h')).exists()]
    report = {'cases': sum(counts.values()) + sum(bounded_counts.values()),
              'native_cases': sum(counts.values()),
              'bounded_domain_checks': sum(bounded_counts.values()),
              'groups': counts, 'bounded_groups': bounded_counts,
              'comparison': 'Whole RAM and callback excluding only native CPU stack8d00..8ded. Convenience append additionally excludes operand workspace8000..80db; prepared append copies the oracle classification checkpoint RAM before comparison and excludes no operand bytes. Query return words/bytes are compared.',
              'scope': 'Result clears5176/5192/51aa/51ae/1d636/1d646, format kind/selection/read/write3624/362c/3644/3658, variable and Ans bus/record copies522a, replay buffer11092, next/count/used1e946/1e9a0/1e9e8, append1ea0c, recall1eb76.',
              'limitations': ['Caller-supported variable slots0..9 are tested; opaque record bytes are intentionally preserved.',
                              'Replay histories are prevalidated, fit250bytes, and contain terminated expressions. Recall expressions must fit the100-byte display buffer.',
                              'Native uint8 length wrapping and the finder251-byte off-by-one overflow are rejected before RAM mutation in C.',
                              'Prepared append receives an imaginary classification, not a native CPU frame. The convenience classifier excludes its native-only operand scratch writes.']}
    report = write_report('analysis/c-verification/persistent.json', report,
                          inputs + ['tools/c_verification.py'], 'tools/test_persistent_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
