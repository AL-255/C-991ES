"""Input-only prepared main/UI recipes, executed exclusively by original ROM.

No expected result records are stored here. The two groups retain all102
SOLVE/main controls and450 CALC/error/presentation/cancellation controls.
GPL-3.0-or-later.
"""
import ctypes as C
import json
from pathlib import Path

INPUT_PATH = Path(__file__).resolve().parents[1] / "analysis/native-fixtures/solve-outer/inputs.json"

def collect(machine, observer, base_stream, lifecycle_stream):
    catalog = json.loads(INPUT_PATH.read_text())
    cases = {row["name"]: row for row in catalog["base"] + catalog["lifecycle"]}
    m = machine
    native = observer
    WATCH = {0xd9ee: 'UI_input', 0xda58: 'UI_prepared_context', 0xdaa2: 'subordinate_action', 0xdc78: 'UI_context_return', 0xdca4: 'special_screen', 0xde1c: 'select_CALC_or_SOLVE', 0xde7e: 'coefficient_or_guess_prompt', 0x1f12a: 'evaluate', 0x1f268: 'evaluation_clear_outer_return', 0x1f2d0: 'SOLVE_numeric', 0x1f2d4: 'SOLVE_status', 0x1f592: 'evaluation_result_action', 0x1d8a4: 'error_key_wait'}

    def number(n):
        if not n:
            return bytes(10)
        text = str(abs(n)).ljust(15, '0')
        return bytes([int(text[0]), *[int(text[i:i + 2], 16) for i in range(1, 15, 2)], len(str(abs(n))) - 1, 1 if n > 0 else 6])

    def text(a):
        return bytes(m.ram[a:a + 100]).split(b'\x00')[0].hex()

    def state():
        return dict(screen=m.ram[0x80fc], item=m.ram[0x80fd], flags=m.ram[0x80fe], token=m.ram[0x80f5], decoded=m.ram[0x80f7], selected=m.ram[0x83fc], list_index=m.ram[0x83fd], list=bytes(m.ram[0x83fe:0x8408]).hex(), display=text(0x8154), backup=text(0x81b8), result=bytes(m.ram[0x8140:0x8154]).hex(), A=bytes(m.ram[0x823a:0x8244]).hex(), X=bytes(m.ram[0x8276:0x8280]).hex(), wait_required=m.reg(5), cursor=m.ram[0x8114])

    def context(pointer):
        raw = bytes(m.ram[pointer:pointer + 12])
        return dict(display=int.from_bytes(raw[:2], 'little'), result=int.from_bytes(raw[2:4], 'little'), return_value=raw[4], mode=raw[6], saved_result=raw[7], natural_input=raw[8], natural_result=raw[9], special_view=raw[10])

    def reset(math=0, mode=193, formula=b'X+A=9', screen=1, item=0, flags=1):
        m.reset()
        native.outer_reset_floor()
        for a, v in [(0x80f9, mode), (0x80fa, 1), (0x80fb, 0), (0x80fc, screen), (0x80fd, item), (0x80fe, flags), (0x80ff, 0), (0x80f5, 0), (0x80f7, 1), (0x80f8, 0), (0x8100, 0), (0x8101, 0), (0x8102, 0), (0x8103, 0), (0x8104, 1), (0x8105, 4), (0x8106, math), (0x8107, 0), (0x8108, 1), (0x810c, 0), (0x8113, 0), (0x8114, 0), (0x8116, 0), (0x8117, 1), (0x8118, 0), (0x8119, 1), (0x811a, 124), (0x811b, 10), (0x811c, 1), (0x811d, 1), (0x811e, 1), (0x811f, 10), (0x8120, 0), (0x8121, 1), (0x8124, 0), (0x8125, 0), (0x8126, 0), (0x8127, 0), (0x8128, 0), (0x8129, 0), (0x8130, 0), (0x8138, 0), (0x80dd, 0), (0x8e00, 0), (0x8e01, 0), (0x8e02, 0)]:
            m.ram[a] = v
        for a, size in [(0x829e, 250), (0x8398, 100), (0x81b8, 100), (0x8140, 20), (0x8408, 110)]:
            C.memset(C.byref(m.ram, a), 0, size)
        for i in range(11):
            C.memmove(C.byref(m.ram, 0x8226 + 10 * i), number(i + 2), 10)
        C.memmove(C.byref(m.ram, 0x8276), number(1), 10)
        m.ram[0x83fc] = 8
        C.memmove(C.byref(m.ram, 0x8154), formula + b'\x00', len(formula) + 1)
        C.memmove(C.byref(m.ram, 0x81b8), b'stale backup\x00', 13)
        m.word(0x812c, 0x8154)
        m.word(0x812e, 0x8398)
        m.reg(4, 0)
        m.reg(5, 1)
        m.lib.harness_set_sp(0x8dee)
        m.lib.harness_set_lr(0x2fffe)

    def run(name, entry, token=None, stop=0xd7b4, limit=5000000, refresh=0):
        case = cases[name]
        assert entry == int(case["entry"], 16) and token == case["supplied_token"] and stop == int(case["requested_stop"], 16)
        entry, token, stop = int(case["entry"], 16), case["supplied_token"], int(case["requested_stop"], 16)
        before = bytes(m.ram)
        pre = state()
        if token is not None:
            if entry == 0xd7c2:
                m.reg(0, token)
            else:
                m.ram[0x80f5] = token
                m.ram[0x80f7] = 1
                m.reg(0, refresh)
        m.lib.harness_set_pc(entry)
        events = []
        execution = 103
        for steps in range(limit):
            pc = m.lib.harness_get_pc()
            if steps and pc == stop:
                execution = 100
                break
            if pc in WATCH:
                e = dict(pc=f'{pc:05x}', meaning=WATCH[pc], state=state(), r0=m.reg(0))
                if pc in (0xda58, 0xdc78):
                    e['context'] = context(m.er(14) - 12 & 0xffff)
                if pc in (0x1f12a, 0x1f268):
                    e['context'] = context(m.er(0) if pc == 0x1f12a else m.er(8))
                events.append(e)
                if pc == 0x1d8a4:
                    execution = 200
                    break
            execution = native.outer_step()
            if execution != 103:
                break
        row = dict(name=name, entry=f'{entry:05x}', supplied_token=token, pre=pre, post=state(), execution=execution, pc=f'{m.lib.harness_get_pc():05x}', steps=steps, callback_pending=native.harness_callback(), stack_floor=C.c_uint.in_dll(native, 'outer_floor').value, events=events)
        rows.append(row)
        snapshots.write(json.dumps(dict(row, before=before.hex(), after=bytes(m.ram).hex())) + '\n')
        return row
    rows = []
    snapshots = base_stream
    for math in (0, 1):
        reset(math=math)
        run(f'SOLVE_launch_math{math}', 0xd7c2, 253)
        for token in b'1+2':
            run(f'coefficient_edit_math{math}_{token}', 0xd7c2, token)
        run(f'coefficient_EXE_math{math}', 0xd7c2, 240)
        if m.reg(5) == 0:
            run(f'auto_next_guess_math{math}', 0xd7b4)
        run(f'unchanged_guess_EXE_math{math}', 0xd7c2, 240)
        for auto in range(4):
            if m.reg(5):
                break
            run(f'auto_equation_restore_and_solve_math{math}_{auto}', 0xd7b4)
    for mode in (193, 196):
        for token in (252, 253):
            reset(mode=mode)
            run(f'outer_mode_gate_{mode}_{token}', 0xd7c2, token)
    for token in (252, 253):
        reset(formula=b'X=3')
        run(f'direct_UI_raw_{token}', 0xd9ee, token, stop=0x2fffe)
    for token in (253, 252):
        reset(screen=192, item=2, flags=4, formula=b'A?')
        run(f'coefficient_prompt_selection_block_{token}', 0xd7c2, token)
    for token in (ord(':'), ord('='), 164, 224, 225, 226, 227, 254):
        reset()
        run(f'prompt_control_setup_{token}', 0xd7c2, 253)
        run(f'prompt_control_{token}', 0xd7c2, token)
    for math in (0, 1):
        reset(math=math)
        run(f'raw_ED_setup_math{math}', 0xd7c2, 253)
        for token in b'1+2':
            run(f'raw_ED_edit_math{math}_{token}', 0xd7c2, token)
        run(f'raw_ED_accept_math{math}', 0xd7c2, 237)
    for token in (224, 225, 226, 227, 240, 237, 252, 253):
        reset()
        run(f'result_setup_launch_{token}', 0xd7c2, 253)
        run(f'result_setup_accept_A_{token}', 0xd7c2, 240)
        run(f'result_setup_accept_X_{token}', 0xd7c2, 240)
        run(f'result_setup_restore_{token}', 0xd7b4)
        run(f'result_setup_solve_{token}', 0xd7b4)
        run(f'result_control_{token}', 0xd7c2, token)
    for screen, item, flags, formula in ((192, 2, 4, b'A?'), (192, 32, 3, b'X+A=9')):
        reset(screen=screen, item=item, flags=flags, formula=formula)
        run(f'direct_UI_refresh_{item}', 0xd9ee, 0, stop=0x2fffe, refresh=1)
    base_rows = rows
    rows = []
    snapshots = lifecycle_stream
    oldstate = state

    def state():
        v = oldstate()
        v.update(status=m.ram[0x80ff], source=text(0x8398), source_cursor=m.word(0x8190), imag_A=bytes(m.ram[0x841c:0x8426]).hex(), imag_X=bytes(m.ram[0x8458:0x8462]).hex(), M=bytes(m.ram[0x8226:0x8230]).hex(), Ans=bytes(m.ram[0x8230:0x823a]).hex(), PreAns=bytes(m.ram[0x828a:0x8294]).hex(), mask=m.ram[0x8125], error=m.ram[0x8122])
        return v

    def run_resume(name, entry, token=None, stop=0xd7b4, limit=5000000, refresh=0):
        case = cases[name]
        assert entry == int(case["entry"], 16) and token == case["supplied_token"] and stop == int(case["requested_stop"], 16)
        entry, token, stop = int(case["entry"], 16), case["supplied_token"], int(case["requested_stop"], 16)
        before = bytes(m.ram)
        pre = state()
        if token is not None:
            if entry == 0xd7c2:
                m.reg(0, token)
            else:
                m.ram[0x80f5] = token
                m.ram[0x80f7] = 1
                m.reg(0, refresh)
        m.lib.harness_set_pc(entry)
        events = []
        execution = 103
        for steps in range(limit):
            pc = m.lib.harness_get_pc()
            if steps and pc == stop:
                execution = 100
                break
            if pc in WATCH:
                e = dict(pc=f'{pc:05x}', meaning=WATCH[pc], state=state(), r0=m.reg(0))
                if pc in (0xda58, 0xdc78):
                    e['context'] = context(m.er(14) - 12 & 0xffff)
                if pc in (0x1f12a, 0x1f268):
                    e['context'] = context(m.er(0) if pc == 0x1f12a else m.er(8))
                events.append(e)
                if pc == 0x1d8a4 and steps:
                    execution = 200
                    break
            execution = native.outer_step()
            if execution != 103:
                break
        row = dict(name=name, entry=f'{entry:05x}', supplied_token=token, pre=pre, post=state(), execution=execution, pc=f'{m.lib.harness_get_pc():05x}', steps=steps, callback_pending=native.harness_callback(), stack_floor=C.c_uint.in_dll(native, 'outer_floor').value, events=events)
        rows.append(row)
        snapshots.write(json.dumps(dict(row, before=before.hex(), after=bytes(m.ram).hex())) + '\n')
        return row
    WATCH = {0xd9ee: 'UI_input', 0xda58: 'UI_prepared_context', 0xdaa2: 'subordinate_action', 0xdc78: 'UI_context_return', 0xdca4: 'special_screen', 0xde1c: 'select_CALC_or_SOLVE', 0xde7e: 'coefficient_or_guess_prompt', 0xdd84: 'begin_variable_list', 0xddda: 'variable_list_end', 0xddf8: 'restore_equation', 20938: 'load_coefficient_pair', 21034: 'store_coefficient_pair', 0x173fa: 'decimalize_display_reference', 0x172f6: 'scan_variables', 0x1f12a: 'evaluate', 0x1f268: 'evaluation_clear_outer_return', 0x1f2d0: 'SOLVE_numeric', 0x1f2d4: 'SOLVE_status', 0x1f366: 'ordinary_parser_call', 0x1f36a: 'ordinary_parser_status', 0x1f592: 'evaluation_result_action', 0x1d8a4: 'error_key_wait'}
    for mode in (193, 196):
        for math in (0, 1):
            reset(math=math, mode=mode, formula=b'X+A')
            C.memmove(C.byref(m.ram, 0x841c), number(9), 10)
            C.memmove(C.byref(m.ram, 0x8458), number(2), 10)
            prefix = f'CALC_{mode:02x}_math{math}'
            run(prefix + '_launch', 0xd7c2, 252)
            run(prefix + '_accept_unchanged_X', 0xd7c2, 240)
            for token in b'2+3':
                run(prefix + f'_edit_A_{token}', 0xd7c2, token)
            run(prefix + '_accept_typed_A', 0xd7c2, 240)
            for auto in range(4):
                if m.reg(5):
                    break
                run(prefix + f'_auto_{auto}', 0xd7b4)
    for mode in (193, 196):
        reset(mode=mode, formula=b'X+A')
        C.memmove(C.byref(m.ram, 0x841c), number(9), 10)
        C.memmove(C.byref(m.ram, 0x8458), number(2), 10)
        prefix = f'CALC_{mode:02x}_unchanged'
        run(prefix + '_launch', 0xd7c2, 252)
        run(prefix + '_accept_X', 0xd7c2, 240)
        run(prefix + '_accept_A', 0xd7c2, 240)
        for auto in range(4):
            if m.reg(5):
                break
            run(prefix + f'_auto_{auto}', 0xd7b4)
    for mode in (193, 196):
        reset(mode=mode, formula=b'X+A')
        prefix = f'CALC_{mode:02x}_coefficient_error'
        run(prefix + '_launch', 0xd7c2, 252)
        for token in b'1O0':
            run(prefix + f'_edit_{token}', 0xd7c2, token)
        run(prefix + '_accept', 0xd7c2, 240)
    for mode in (193, 196):
        reset(mode=mode, formula=b'XO0')
        prefix = f'CALC_{mode:02x}_equation_error'
        run(prefix + '_launch', 0xd7c2, 252)
        run(prefix + '_accept_X', 0xd7c2, 240)
        for auto in range(4):
            if m.reg(5):
                break
            row = run(prefix + f'_auto_{auto}', 0xd7b4)
            if row['execution'] == 200:
                break
    for mode in (193, 196):
        reset(mode=mode, formula=b'1+2')
        prefix = f'CALC_{mode:02x}_no_variables'
        run(prefix + '_launch', 0xd7c2, 252)
        for auto in range(4):
            if m.reg(5):
                break
            row = run(prefix + f'_auto_{auto}', 0xd7b4)
            if row['execution'] == 200:
                break
    for mode in (193, 196):
        for screen in (1, 160, 192):
            for math in (0, 1):
                reset(mode=mode, screen=screen, math=math)
                C.memmove(C.byref(m.ram, 0x841c), number(9), 10)
                C.memset(C.byref(m.ram, 0x8500), 170, 20)
                m.reg(0, 2)
                m.er(2, 0x8500)
                run(f'load51CA_{mode:02x}_{screen:02x}_{math}', 20938, stop=0x2fffe)
                rows[-1]['loaded_pair'] = bytes(m.ram[0x8500:0x8514]).hex()
    for mode in (193, 196):
        for stage in ('coefficient', 'equation'):
            for kind, pair, target in [('AC', (4, 16), 0xd7b4), ('left', (128, 8), 0xd7b4), ('right', (64, 4), 0xd7b4), ('reset', (16, 128), 0x1824e), ('export', (128, 128), 0x1db56)]:
                reset(mode=mode, formula=b'X+A' if stage == 'coefficient' else b'XO0')
                prefix = f'CALC_{mode:02x}_{stage}_{kind}'
                run(prefix + '_launch', 0xd7c2, 252)
                if stage == 'coefficient':
                    for token in b'1O0':
                        run(prefix + f'_edit_{token}', 0xd7c2, token)
                    run(prefix + '_error_wait', 0xd7c2, 240)
                else:
                    run(prefix + '_accept_X', 0xd7c2, 240)
                    run(prefix + '_restore', 0xd7b4)
                    run(prefix + '_error_wait', 0xd7b4)
                assert m.lib.harness_get_pc() == 0x1d8a4
                m.ram[0x8e01] = pair[0]
                m.ram[0x8e02] = pair[1]
                run_resume(prefix + '_resume', 0x1d8a4, stop=target)
                rows[-1]['raw_host_pair'] = list(pair)
                rows[-1]['continuation_boundary'] = 'natural outer return' if target == 0xd7b4 else 'original reset request before BRK' if target == 0x1824e else 'original completed export before next wait'
                if target == 0x1db56:
                    run_resume(prefix + '_export_next_wait', 0x1db56, stop=0x1d8a4)
    surd = bytes.fromhex('80000001000201010100')
    for mode in (193, 196):
        for screen in (1, 160, 192):
            for math in (0, 1):
                reset(mode=mode, screen=screen, math=math)
                C.memmove(C.byref(m.ram, 0x823a), surd, 10)
                C.memmove(C.byref(m.ram, 0x841c), surd, 10)
                C.memset(C.byref(m.ram, 0x8500), 170, 20)
                m.reg(0, 2)
                m.er(2, 0x8500)
                run(f'load51CA_SURD_{mode:02x}_{screen:02x}_{math}', 20938, stop=0x2fffe)
                rows[-1]['loaded_pair'] = bytes(m.ram[0x8500:0x8514]).hex()
    for math in (0, 1):
        for body in (b'X', b'X+1'):
            for cancel_at in (0, 1, 2, 3):
                reset(math=math, formula=b'i' + body + b',1,3)')
                C.c_uint.in_dll(native, 'outer_cancel_at').value = cancel_at
                prefix = f'CALC_SUM_math{math}_body{body.hex()}_cancel{cancel_at}'
                run(prefix + '_launch', 0xd7c2, 252)
                run(prefix + '_accept_X', 0xd7c2, 240)
                run(prefix + '_restore', 0xd7b4)
                run(prefix + '_evaluate', 0xd7b4)
                rows[-1]['cancel_at'] = cancel_at
                rows[-1]['polls'] = C.c_uint.in_dll(native, 'outer_polls').value
                samples = (C.c_uint8 * (256 * 20)).in_dll(native, 'outer_poll_X')
                rows[-1]['poll_X'] = [bytes(samples[20 * i:20 * i + 20]).hex() for i in range(rows[-1]['polls'])]
                if m.lib.harness_get_pc() == 0x1d8a4:
                    m.ram[0x8e01] = 4
                    m.ram[0x8e02] = 16
                    run_resume(prefix + '_AC_resume', 0x1d8a4, stop=0xd7b4)
    for mode in (193, 196):
        for math in (0, 1):
            for token in (224, 225, 226, 227, 254, 240, 237):
                reset(mode=mode, math=math, formula=b'X+A')
                prefix = f'CALC_result_{mode:02x}_math{math}_token{token:02x}'
                run(prefix + '_launch', 0xd7c2, 252)
                run(prefix + '_accept_X', 0xd7c2, 240)
                run(prefix + '_accept_A', 0xd7c2, 240)
                run(prefix + '_restore', 0xd7b4)
                run(prefix + '_evaluate', 0xd7b4)
                run(prefix + '_control', 0xd7c2, token)
    return (base_rows, rows)
