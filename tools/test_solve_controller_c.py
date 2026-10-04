#!/usr/bin/env python3
"""Live original SOLVE scanner, prompts, prepared solve and error transactions.

The optional native expression seam executes original171F4 independently; it
does not replace any callback in the expected whole-ROM controller execution.
"""
import argparse
import ctypes as C
import hashlib
import json
import random
import re
import subprocess

import c_verification
from c_verification import ROOT, write_report
from c_build_inputs import implementation_inputs
from nxu8.machine import Machine
from test_platform_c import Platform
from test_input_controller_c import Context, Variables, Number, Control
from test_error_event_c import ErrorEvent
from test_eval_complex_c import Options, Result as EvalResult
from test_numeric_c import Rational


class Environment(C.Structure):
    _fields_ = [(name, C.c_uint8) for name in ('screen', 'prior_operation',
        'complex_format', 'restricted_state', 'display_mode', 'digits', 'selected_base')]


class ExpressionEffects(C.Structure):
    _fields_ = [('equation_used', C.c_uint8), ('restricted_state', C.c_uint8)]


class SolveResult(C.Structure):
    _fields_ = [('root', Number), ('residual', Number), ('variable', Number),
        ('firmware_status', C.c_uint8), ('evaluations', C.c_uint32),
        ('checks', C.c_uint32), ('starts', C.c_uint8)]


class Controller(C.Structure):
    _fields_ = [('context', Context), ('error', ErrorEvent), ('variables', Variables),
        ('saved_result', Number*2), ('numerical', SolveResult), ('cancellation', Control),
        ('expression', C.c_void_p), ('expression_userdata', C.c_void_p),
        ('prepared_source', C.c_uint16), ('current_source', C.c_uint16),
        *[(name, C.c_uint8) for name in ('phase', 'active', 'evaluator_status',
            'handler_action', 'prompt_id', 'scanner_error', 'preparation_ok', 'unsupported_token')],
        ('input', C.c_uint8*1024), ('input_length', C.c_size_t)]


NATIVE_ADAPTER = r'''/* Test-only observation; original CPU executes every instruction. */
#include "harness.c"
unsigned solve_controller_polls, solve_controller_writes, solve_controller_evaluations;
unsigned solve_controller_kernel_polls, solve_controller_outer_poll;
unsigned solve_controller_backend_status;
unsigned solve_controller_stack_floor;
uint8_t solve_controller_poll_values[8192][10];
uint8_t solve_controller_sample_values[8192][10];
uint8_t solve_controller_write_ids[8192], solve_controller_write_pairs[8192][20];
void solve_controller_reset_observations(void) {
    solve_controller_polls=solve_controller_writes=solve_controller_evaluations=0;
    solve_controller_kernel_polls=solve_controller_outer_poll=0;
    solve_controller_backend_status=255;
    solve_controller_stack_floor=0x8dee;
}
int solve_controller_run(uint64_t limit,uint32_t stop,unsigned abort_poll) {
    for(uint64_t i=0;i<limit;++i) {
        uint32_t pc=harness_get_pc();
        unsigned sp=harness_get_sp();
        if(sp<solve_controller_stack_floor)solve_controller_stack_floor=sp;
        if(pc==stop)return 100;
        if(pc==0x5550)solve_controller_outer_poll=LCSR==1 &&
            (LR==0x01fc || LR==0x0242 || LR==0x040c);
        if(pc==0x5564) {
            if(solve_controller_polls<8192)
                memcpy(solve_controller_poll_values[solve_controller_polls],
                    ram+0x8226+10*ram[0x83fc],10);
            ++solve_controller_polls;
            if(solve_controller_outer_poll)++solve_controller_kernel_polls;
            ram[0x8e00]=abort_poll==solve_controller_polls?2:0;
        }
        if(pc==0x171f4) {
            unsigned index=solve_controller_evaluations++;
            if(index<8192)memcpy(solve_controller_sample_values[index],
                ram+0x8226+10*ram[0x83fc],10);
        }
        if(pc==0x1f2d4)solve_controller_backend_status=GR.rs[0];
        if(pc==0x522a) {
            unsigned index=solve_controller_writes++;
            if(index<8192) {
                solve_controller_write_ids[index]=GR.rs[0];
                memcpy(solve_controller_write_pairs[index],ram+(GR.rs[2]|GR.rs[3]<<8),20);
            }
        }
        int status=harness_run(1,0x2fffe,false);
        if(status!=103)return status;
    }
    return 103;
}
int solve_expression_run(uint64_t limit,int (*poll)(void *),void *userdata) {
    for(uint64_t i=0;i<limit;++i) {
        if(harness_get_pc()==0x5564)ram[0x8e00]=poll && poll(userdata)?2:0;
        int status=harness_run(1,0x2fffe,false);
        if(status!=103)return status;
    }
    return 103;
}
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value):
    """Pure fixture encoder for small exact integers; never constructs outcomes."""
    if isinstance(value, bytes): return value
    if value == 0: return bytes(10)
    text = str(abs(value)); exponent = len(text)-1; digits = text.ljust(15, '0')
    return bytes([int(digits[0]), *[int(digits[i:i+2], 16) for i in range(1, 15, 2)],
                  int(f'{exponent:02d}', 16), 1 if value > 0 else 6])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--no-report', action='store_true')
    ap.add_argument('--random-cases', type=int, default=1000)
    ap.add_argument('--native-expression', action='store_true',
        help='Isolate controller using an independent original171F4 expression seam')
    ap.add_argument('--scanner-only', action='store_true')
    args = ap.parse_args()
    if args.random_cases < 0: ap.error('--random-cases must be nonnegative')
    if args.native_expression and not args.no_report:
        ap.error('--native-expression is an isolation preview and requires --no-report')
    if args.scanner_only and not args.no_report:
        ap.error('--scanner-only requires --no-report')
    build = ROOT/'analysis/build/solve-controller'; build.mkdir(parents=True, exist_ok=True)
    source_names = ['csrc/'+name for name in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)',
        (ROOT/'csrc/CMakeLists.txt').read_text().split('target_include_directories')[0])]
    for name in ('csrc/ui/fx_solve_controller.c', 'csrc/numeric/fx_solve.c'):
        if name not in source_names: source_names.append(name)
    compiled_inputs = implementation_inputs(ROOT, source_names)
    source_hashes = {name: digest(ROOT/name) for name in compiled_inputs}
    shared = build/'controller.so'
    subprocess.run(['gcc', '-std=c99', '-O3', '-Wall', '-Wextra', '-Werror',
        '-shared', '-fPIC', '-Wl,--no-undefined', '-I', str(ROOT/'csrc'),
        *[str(ROOT/name) for name in source_names],
        '-o', str(shared)], check=True)
    lib = C.CDLL(str(shared)); pp = C.POINTER(Platform); sp = C.POINTER(Controller)
    for name in ('enter', 'prepare'):
        getattr(lib, 'fx_solve_controller_'+name).argtypes = [pp, sp, C.c_void_p, C.c_void_p,
                                                            C.POINTER(Control)]
    for name in ('advance', 'accept', 'tick'):
        getattr(lib, 'fx_solve_controller_'+name).argtypes = [pp, sp]
    lib.fx_solve_controller_edit.argtypes = [pp, sp, C.c_uint8]
    lib.fx_solve_scan_variables.argtypes = [pp, C.c_uint16]
    lib.fx_solve_controller_finish.argtypes = [sp, C.POINTER(C.c_uint8)]
    lib.fx_rational_encode.argtypes = [C.POINTER(Number), C.POINTER(Rational)]
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb = (C.c_uint8*len(rom)).from_buffer_copy(rom); ram = (C.c_uint8*65536)()
    platform = Platform(rb, len(rom), ram, 0, 0)
    native = Machine(rom, build/'oracle')
    adapter = build/'native-events.c'; adapter.write_text(NATIVE_ADAPTER)
    oracle = build/'native-events.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
        '-shared', '-fPIC', '-I', str(ROOT/'tools/nxu8'), str(adapter),
        str(ROOT/'tools/nxu8/vendor/SimU8/core.c'), '-o', str(oracle)], check=True)
    events = C.CDLL(str(oracle))
    for name in ('harness_init', 'harness_set_pc', 'harness_get_pc', 'harness_set_reg',
        'harness_get_reg', 'harness_set_sp', 'harness_get_sp', 'harness_set_lr',
        'harness_ram', 'harness_run', 'harness_trace_open'):
        getattr(events, name).argtypes = getattr(native.lib, name).argtypes
        getattr(events, name).restype = getattr(native.lib, name).restype
    events.solve_controller_run.argtypes = [C.c_uint64, C.c_uint32, C.c_uint]
    native.lib = events; native.ram = events.harness_ram().contents
    native.counts = (C.c_uint64*0x18000).in_dll(events, 'execution_counts')
    native.ram_writes = (C.c_uint64*65536).in_dll(events, 'ram_write_counts')
    native.reset()
    parser_native = Machine(rom, build/'expression-oracle')
    parser_oracle = build/'expression-native-events.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        '-I',str(ROOT/'tools/nxu8'),str(adapter),
        str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(parser_oracle)],check=True)
    parser_events = C.CDLL(str(parser_oracle))
    for name in ('harness_init','harness_set_pc','harness_get_pc','harness_set_reg',
        'harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_ram',
        'harness_run'):
        getattr(parser_events,name).argtypes=getattr(parser_native.lib,name).argtypes
        getattr(parser_events,name).restype=getattr(parser_native.lib,name).restype
    parser_native.lib=parser_events; parser_native.ram=parser_events.harness_ram().contents
    parser_native.reset()
    Expression = C.CFUNCTYPE(C.c_int, C.POINTER(C.c_uint8), C.c_size_t,
        C.POINTER(Options), C.POINTER(Environment), C.POINTER(Variables),
        C.POINTER(Control), C.POINTER(Number), C.POINTER(Number), C.POINTER(EvalResult),
        C.POINTER(ExpressionEffects), C.c_void_p)
    Cancel = C.CFUNCTYPE(C.c_int, C.c_void_p)
    parser_events.solve_expression_run.argtypes=[C.c_uint64,Cancel,C.c_void_p]
    failures, counts, observations = [], {}, []
    checks = 0; current = {}; current_polls = []; current_samples = []; stack_floors = {}
    lifetime_stack_floor = 0x8dee
    current_abort = 0; seam_errors = []

    def expression(input_pointer, length, options, environment, variables, control,
                   initial_secondary, prior_answer, result, effects, userdata):
        del userdata
        try:
            raw = C.string_at(input_pointer, length)
            current_samples.append(bytes(variables.contents.values[ram[0x83fc]][0]))
            parser_native.reset(); C.memmove(parser_native.ram, bytes(ram), 65536)
            for slot in range(10):
                for part, base in ((0, 0x8226), (1, 0x8408)):
                    C.memmove(C.byref(parser_native.ram, base+10*slot),
                              bytes(variables.contents.values[slot][part]), 10)
            for address, value in ((0x80f9, options.contents.calculation_context),
                (0x8106, options.contents.math_output), (0x8105, options.contents.angle_unit),
                (0x80fc, environment.contents.screen)):
                parser_native.ram[address] = value
            C.memmove(C.byref(parser_native.ram, 0x8600), raw+b'\0', len(raw)+1)
            C.memmove(C.byref(parser_native.ram, 0x890a), bytes(initial_secondary.contents), 10)
            C.memmove(C.byref(parser_native.ram, 0x828a), bytes(prior_answer.contents), 10)
            parser_native.word(0x9c00, 0x8600); parser_native.er(0, 0x9c00); parser_native.er(2, 0x8900)
            def parser_poll(_):
                for slot in range(10):
                    for part,base in ((0,0x8226),(1,0x8408)):
                        C.memmove(C.byref(variables.contents.values[slot][part]),
                            bytes(parser_native.ram[base+10*slot:base+10*slot+10]),10)
                if not control or not control.contents.cancelled: return 0
                return Cancel(control.contents.cancelled)(control.contents.userdata)
            parser_poll_callback=Cancel(parser_poll)
            parser_native.lib.harness_set_sp(0x8dee)
            parser_native.lib.harness_set_lr(0x2fffe)
            parser_native.lib.harness_set_pc(0x171f4)
            status=parser_events.solve_expression_run(10000000,parser_poll_callback,None)
            if status!=100:
                raise RuntimeError(('original_expression_nonreturn',status,
                    hex(parser_native.lib.harness_get_pc()),raw.hex()))
            C.memmove(result.contents.value, bytes(parser_native.ram[0x8900:0x8914]), 20)
            result.contents.consumed = (parser_native.word(0x9c00)-0x8600)&65535
            result.contents.unsupported_token = 0
            effects.contents.equation_used = parser_native.ram[0x8125]
            effects.contents.restricted_state = parser_native.ram[0x8124]
            for slot in range(10):
                for part, base in ((0, 0x8226), (1, 0x8408)):
                    C.memmove(C.byref(variables.contents.values[slot][part]),
                              bytes(parser_native.ram[base+10*slot:base+10*slot+10]), 10)
            return parser_native.reg(0)
        except Exception as error:
            seam_errors.append(str(error)); return -2
    expression_callback = Expression(expression)
    expression_pointer = C.cast(expression_callback, C.c_void_p) if args.native_expression else None

    def cancelled(_):
        current_polls.append(bytes(ram[0x8226+10*ram[0x83fc]:0x8230+10*ram[0x83fc]]))
        return int(current_abort and len(current_polls) == current_abort)
    cancel_callback = Cancel(cancelled); control = Control(C.cast(cancel_callback, C.c_void_p), None)

    def put(address, value): ram[address] = native.ram[address] = value
    def word(address, value): put(address, value&255); put(address+1, value>>8)
    def data(address, value):
        for offset, byte in enumerate(value): put(address+offset, byte)
    def string(address, value): data(address, value+b'\0\0')
    def reset(tokens=b'X=3', math=0, selected=8, initial=1, screen=0xc0, item=4,
              flags=1, token=0xf0, mode=0xc1, saved=0, special=0, poison=False,
              records=None, imaginary=None, backup=b'prior input', abort=0,
              display_mode=0, digits=0, mixed_fraction=0, decimal_dot=1, angle=4,
              replay=None):
        nonlocal current, current_abort, lifetime_stack_floor
        native.reset(); events.solve_controller_reset_observations()
        lifetime_stack_floor = 0x8dee
        if poison:
            background = random.Random(0x1f12a).randbytes(65536)
            C.memmove(native.ram, background, 65536)
        C.memmove(ram, bytes(native.ram), 65536)
        for address, value in ((0x80f9, mode), (0x80fa, 1), (0x80fc, screen), (0x80fd, item),
            (0x80fe, flags), (0x80ff, 0), (0x80f5, token), (0x80f7, 1), (0x80f8, 0),
            (0x80fb, 0), (0x80f4, 0), (0x8100, 0), (0x8101, 0), (0x8102, display_mode),
            (0x8103, digits), (0x8104, decimal_dot), (0x8105, angle), (0x8106, math), (0x8107, mixed_fraction),
            (0x8108, 1), (0x810c, 0), (0x8120, 0), (0x8121, 1), (0x8124, 0),
            (0x8125, 0xa5), (0x8113, 0), (0x8129, 0), (0x8130, 0), (0x8138, 0),
            (0x80dd, 0), (0x8114, 0), (0x8116, 0), (0x8117, 1), (0x8118, 0),
            (0x8119, 1), (0x811a, 0x7c), (0x811b, 10), (0x811c, 1), (0x811d, 1),
            (0x811e, 1), (0x811f, 10), (0x8126, 0), (0x8127, 0), (0x8128, 0),
            (0x8e00, 0), (0x8e01, 0), (0x8e02, 0), (0x83fc, selected)):
            put(address, value)
        word(0x812c, 0x8154); word(0x812e, 0x8398)
        string(0x8154, tokens); string(0x81b8, backup)
        for address in (0x829e, 0x8398): data(address, bytes(250))
        #8398's cleared editor buffer overlaps the SOLVE selected/list bytes.
        # Publish the requested selected ID after that intentional clear.
        put(0x83fc,selected)
        string(0x829e, b'7\0'+bytes([0x5a])*30)
        if replay is not None: data(0x829e,replay)
        for slot in range(11):
            data(0x8226+10*slot, number(slot+2)); data(0x8408+10*slot, number(-(slot+2)))
        data(0x8226+10*selected, number(initial)); data(0x8230, number(7)); data(0x828a, number(9))
        for slot, record in (records or {}).items(): data(0x8226+10*slot, number(record))
        for slot, record in (imaginary or {}).items(): data(0x8408+10*slot, number(record))
        data(0x8140, number(9)+number(-9)); data(0x8dee, rom[0x1f8dc:0x1f8ee])
        word(0x9d00, 0x8154); word(0x9d02, 0x8140)
        for offset, value in ((4,1), (5,0), (6,mode), (7,saved), (8,math),
                              (9,math), (10,special), (11,0)):
            put(0x9d00+offset, value)
        platform.callback_pending = platform.status = 0
        current_polls.clear(); current_samples.clear(); current_abort = abort
        current = dict(input=(tokens+b'\0').hex(), math=math, selected=selected,
            initial=number(initial).hex(), screen=screen, item=item, flags=flags,
            token=token, mode=mode, saved=saved, special=special, poison=poison,
            records={str(k): number(v).hex() for k,v in (records or {}).items()}, abort=abort,
            imaginary={str(k): number(v).hex() for k,v in (imaginary or {}).items()},
            display_mode=display_mode, digits=digits, mixed_fraction=mixed_fraction,
            decimal_dot=decimal_dot, angle=angle, replay=replay.hex() if replay is not None else None)
        for label, image in (('C',ram),('original',native.ram)):
            if image[0x83fc] != selected:
                raise AssertionError(('fixture_selected_id',label,current,image[0x83fc]))
            actual_initial = bytes(image[0x8226+10*selected:0x8230+10*selected])
            if actual_initial != number(initial):
                raise AssertionError(('fixture_selected_record',label,current,actual_initial.hex()))

    def fail(group, key, expected, actual):
        row = dict(group=group, fixture=current.copy(), key=key, expected=expected, actual=actual)
        failures.append(row)
        if len(failures) <= 20:
            printed = row.copy()
            if isinstance(actual,list) and len(actual)>12:
                printed['actual'] = {'count':len(actual),'first12':actual[:12]}
            print(json.dumps(printed), flush=True)

    def check(group, key, expected, actual):
        nonlocal checks
        checks += 1
        if expected != actual: fail(group, key, expected, actual)

    def run(entry=None, stop=0x2fffe, abort=None, limit=50000000, allow_return=False):
        if entry is not None:
            native.lib.harness_set_sp(0x8dee); native.lib.harness_set_lr(0x2fffe)
            native.lib.harness_set_pc(entry)
        outcome = events.solve_controller_run(limit, stop, current_abort if abort is None else abort)
        check('original_return', 'execution', 100, outcome)
        stops=[stop]+([0x2fffe] if allow_return and stop!=0x2fffe else [])
        pc=native.lib.harness_get_pc()
        check('original_return','requested_checkpoint',
              [f'{address:05x}' for address in stops],
              [f'{address:05x}' for address in stops] if pc in stops else [f'{pc:05x}'])
        return outcome

    def compare(group, state=None, workspace=False, descriptor=False):
        nonlocal lifetime_stack_floor
        actual = bytearray(ram); expected = bytes(native.ram)
        if descriptor and state is not None and state.context.display_address:
            actual[0x9d04] = state.context.return_value
        stack_floor = C.c_uint.in_dll(events, 'solve_controller_stack_floor').value
        lifetime_stack_floor = min(stack_floor,lifetime_stack_floor)
        stack_floor = lifetime_stack_floor
        excluded = [(stack_floor, 0x8dee)]
        stack_floors[group] = min(stack_floor, stack_floors.get(group, 0x8dee))
        if workspace: excluded += [(0x8000, 0x80dc), (0x8640, 0x87d0)]
        differences = [(f'{address:04x}', expected[address], actual[address])
            for address in range(65536) if actual[address] != expected[address]
            and not any(lo <= address < hi for lo, hi in excluded)]
        check(group, 'persistent_ram_and_framebuffer', [], differences)
        check(group, 'host_callback', native.lib.harness_callback(), platform.callback_pending)
        platform.callback_pending = 0
        counts[group] = counts.get(group, 0)+1

    def scanner(tokens, screen=0xc0, mode=0xc1, poison=False):
        reset(tokens, screen=screen, item=1, mode=mode, poison=poison)
        string(0x8398, tokens)
        actual = lib.fx_solve_scan_variables(C.byref(platform), 0x8398)
        run(0x172f6, limit=500000)
        check('scanner', 'native_status', native.reg(0), actual)
        compare('scanner')

    def compare_samples(state, group):
        polls = C.c_uint.in_dll(events, 'solve_controller_polls').value
        samples = C.c_uint.in_dll(events, 'solve_controller_evaluations').value
        values = ((C.c_uint8*10)*8192).in_dll(events, 'solve_controller_poll_values')
        sample_values = ((C.c_uint8*10)*8192).in_dll(events, 'solve_controller_sample_values')
        check(group, 'cancellation_samples', [bytes(values[i]).hex() for i in range(polls)],
              [value.hex() for value in current_polls])
        if args.native_expression and state.expression:
            check(group, 'expression_samples', [bytes(sample_values[i]).hex() for i in range(samples)],
                  [value.hex() for value in current_samples])
        check(group, 'kernel_evaluations', samples, state.numerical.evaluations)
        outer_polls=C.c_uint.in_dll(events,'solve_controller_kernel_polls').value
        check(group, 'kernel_polls', outer_polls, state.numerical.checks)

    def prepared(tokens, exercise_error=False, reuse=False, required_native_status=None, **kw):
        nonlocal current, current_abort
        if not reuse:
            reset(tokens, **kw)
        else:
            events.solve_controller_reset_observations()
            current_polls.clear(); current_samples.clear(); current_abort = kw.get('abort',0)
            math = kw.get('math',0); selected = kw.get('selected',8)
            for address,value in ((0x80fc,0xc0),(0x80fd,4),(0x80fe,1),(0x80f5,0xf0),
                                  (0x8106,math),(0x83fc,selected)):
                put(address,value)
            word(0x812c,0x8154); string(0x8154,tokens)
            for offset,value in ((4,1),(5,0),(6,0xc1),(7,0),(8,math),(9,math),(10,0),(11,0)):
                put(0x9d00+offset,value)
            platform.callback_pending = platform.status = 0
            current = dict(input=(tokens+b'\0').hex(), selected=selected, math=math,
                initial=bytes(ram[0x8226+10*selected:0x8230+10*selected]).hex(),
                reused_state=True, screen=0xc0, item=4, flags=1, token=0xf0, abort=current_abort)
        state = Controller()
        actual = lib.fx_solve_controller_prepare(C.byref(platform), C.byref(state),
                                                expression_pointer, None, C.byref(control))
        native.er(0, 0x9d00); run(0x1f12a, stop=0x1f2ac)
        check('prepared', 'ui_status', 2, actual)
        compare('prepared', state, workspace=reuse, descriptor=True)
        actual = lib.fx_solve_controller_tick(C.byref(platform), C.byref(state))
        run(stop=0x1f3a2,allow_return=True)
        expected_status = C.c_uint.in_dll(events, 'solve_controller_backend_status').value
        if required_native_status is not None:
            check('native_fixture_contract','backend_status',required_native_status,expected_status)
        expected_ui = 4 if 0 < expected_status < 32 else 3
        check('solve_commit', 'ui_status', expected_ui, actual)
        check('solve_commit', 'numeric_status', expected_status, state.evaluator_status)
        if expected_ui == 3: check('solve_commit', 'handler_action', native.reg(0), state.handler_action)
        compare('solve_commit', state, workspace=True, descriptor=True)
        compare_samples(state, 'solve_commit')
        observations.append(dict(fixture=current.copy(), status=expected_status,
            pair=bytes(native.ram[0x8140:0x8154]).hex(),
            selected=bytes(native.ram[0x8226+10*native.ram[0x83fc]:0x8230+10*native.ram[0x83fc]]).hex(),
            evaluations=state.numerical.evaluations, polls=state.numerical.checks))
        if expected_ui == 4 and exercise_error:
            error_lifecycle(state)
        return state

    def error_lifecycle(state, key_pair=(4,16)):
        actual = lib.fx_solve_controller_tick(C.byref(platform), C.byref(state))
        run(stop=0x1d8a4)
        check('error_banner', 'ui_status', 0, actual)
        compare('error_banner', state, workspace=True, descriptor=True)
        for pair in ((0,0), (1,1), (1,8), (2,64)):
            put(0x8e01,pair[0]); put(0x8e02,pair[1])
            actual = lib.fx_solve_controller_tick(C.byref(platform), C.byref(state))
            run(stop=0x1d8a6)
            if pair == (0,0): run(stop=0x1d8d2)
            else:
                run(stop=0x1dc3e)
                if 0xe8 <= native.reg(0) <= 0xec:
                    run(stop=0x1db4c)
                run(stop=0x1d8a4)
            check('error_ignored_keys', 'ui_status', 0, actual)
            compare('error_ignored_keys', state, workspace=True, descriptor=True)
        put(0x8e01,key_pair[0]); put(0x8e02,key_pair[1])
        actual = lib.fx_solve_controller_tick(C.byref(platform), C.byref(state))
        if key_pair == (16,128):
            run(stop=0x1824e)
            check('error_reset', 'ui_status', 5, actual)
            compare('error_reset', state, workspace=True, descriptor=True)
        else:
            run()
            check('error_recovery', 'ui_status', 3, actual)
            check('error_recovery', 'handler_action', native.reg(0), state.handler_action)
            compare('error_recovery', state, workspace=True, descriptor=True)
        before = bytes(ram)
        check('terminal_retained', 'ui_status', actual,
              lib.fx_solve_controller_tick(C.byref(platform), C.byref(state)))
        check('terminal_retained', 'ram_unchanged', before.hex(), bytes(ram).hex())
        action = C.c_uint8(255)
        check('terminal_finish', 'ui_status', actual,
              lib.fx_solve_controller_finish(C.byref(state), C.byref(action)))
        check('terminal_finish', 'action', state.handler_action, action.value)

    scanner_inputs = [b'X', b'X+A', b'A+X', b'X+X+A+A', b'A=2', b'A=2,A',
        b'X=A,A', b'X=A,X', b'A+X,A', b'X+Y+\x54+A+B+C+D+E+F', b'X+\x8b',
        b'\x8b=2', b'X=2,', b'X=2,1', b'X=2,Y', b'X=2,X', b'X=2,X:',
        b'X=2,A+1', b'X+A,A:', b'A=1:X=A', b'X=Y,Y', b'X=X,X,X', b'X,,X',
        b'X,\x8b', b'X,\xc8', b'X,\x54', b'\x54,X', b'X,\x54:', b'X:X',
        b'X:X,A', b'X:X,A:', b'X,X:', b'X,X\0A', b'X=2,)', b'X=2,\x98X)',
        b'X:A,B', b'X,A:B', b'X,A;B', b'X,A\xff', b'X,\x00A']
    for tokens in scanner_inputs:
        for poison in (False, True): scanner(tokens, poison=poison)
    rng = random.Random(0x172f6)
    ordinary_variables = [b'\x54', *[bytes([v]) for v in range(0x41,0x47)], b'X', b'Y']
    for index in range(args.random_cases):
        selected = rng.choice(ordinary_variables)
        values = rng.sample(ordinary_variables, rng.randrange(1,10))
        tokens = b'+'.join(values)
        tokens += rng.choice([b'', b'='+str(rng.randrange(1,10)).encode(), b':X', b',1',
                              b','+selected, b','+selected+b':', b','+selected+b'+X'])
        scanner(tokens, poison=bool(index&1))

    def enter(tokens, default_expression=False, **kw):
        reset(tokens, screen=1, item=0, flags=1, token=0xfd, **kw)
        state = Controller()
        actual = lib.fx_solve_controller_enter(C.byref(platform), C.byref(state),
                                               None if default_expression else expression_pointer,
                                               None, C.byref(control))
        native.er(0, 0xc0); run(0xde1c)
        check('entry', 'ui_status', 7, actual); compare('entry', state)
        return state

    def advance(state, group='prompt'):
        actual = lib.fx_solve_controller_advance(C.byref(platform), C.byref(state))
        run(0xdca4, stop=0xdd44 if actual == 4 else 0x2fffe)
        compare(group, state, workspace=True)
        return actual

    def edit(state, token):
        current['edit_token'] = f'{token:02x}'
        put(0x80f5, token)
        actual = lib.fx_solve_controller_edit(C.byref(platform), C.byref(state), token)
        native.er(0, 0); run(0xd9ee)
        check('edit', 'ui_status', 7, actual); compare('edit', state, workspace=True)

    def accept(state, unchanged=False):
        put(0x80f5, 0xf0)
        actual = lib.fx_solve_controller_accept(C.byref(platform), C.byref(state))
        if unchanged:
            run(0xdca4, stop=0xdd44 if actual == 4 else 0x2fffe)
        else:
            native.er(0, 0); run(0xd9ee, stop=0x1f3a2,allow_return=True)
        compare('accept_unchanged' if unchanged else 'accept_typed', state, workspace=True)
        return actual

    if not args.scanner_only:
        # The public launch boundary includes the FD caller's mode gate.
        # Execute the original D818 path, rather than calling unguarded DE1C.
        declined_inputs = [dict(mode=mode) for mode in (0xc4,0xc2,0xc3,0x49,0x4a,2)]
        declined_inputs += [dict(flags=64), dict(screen=0xc0,item=2),
                           dict(screen=0xa0,item=2), dict(tokens=b'')]
        for fixture in declined_inputs:
            for poison in (False,True):
                config = dict(tokens=b'X=3',screen=1,item=0,flags=1,token=0xfd,
                              poison=poison)
                config.update(fixture); reset(**config)
                state = Controller()
                C.memset(C.byref(state),0xa5,C.sizeof(state))
                before_state = bytes(state); before_ram = bytes(ram)
                actual = lib.fx_solve_controller_enter(C.byref(platform), C.byref(state),
                    expression_pointer,None,C.byref(control))
                native.reg(1,0xfd); run(0xd818,stop=0xd7b4)
                check('entry_declined','ui_status',8,actual)
                check('entry_declined','host_state_retained',before_state.hex(),bytes(state).hex())
                check('entry_declined','host_ram_retained',before_ram.hex(),bytes(ram).hex())
                check('entry_declined','native_launch_count',0,native.counts[0xde1c//2])
                compare('entry_declined')
        for poison in (False,True):
            reset(b'',poison=poison)
            state=Controller(); C.memset(C.byref(state),0xa5,C.sizeof(state))
            before_state=bytes(state); before_ram=bytes(ram)
            actual=lib.fx_solve_controller_prepare(C.byref(platform),C.byref(state),
                expression_pointer,None,C.byref(control))
            native.er(0,0x9d00); run(0x1f12a)
            check('prepare_empty_declined','ui_status',8,actual)
            check('prepare_empty_declined','native_return',0,native.reg(0))
            check('prepare_empty_declined','host_state_retained',before_state.hex(),bytes(state).hex())
            check('prepare_empty_declined','host_ram_retained',before_ram.hex(),bytes(ram).hex())
            compare('prepare_empty_declined')
        for tokens in (b'X+A=3', b'A+X=7,A', b'X+Y=9,Y', b'X+\x54=6,\x54',
                       b'X+B+C+D+E+F=9', b'X=3'):
            for math in (0,1):
                for poison in (False, True):
                    state = enter(tokens, math=math, poison=poison)
                    advance(state)
                    list_length = sum(native.ram[0x83fe+i] != 255 for i in range(10))
                    for index in range(list_length):
                        if index&1:
                            accept(state, unchanged=True)
                        else:
                            edit(state, ord('5')); accept(state)
                            advance(state)
                    if ram[0x80fd] == 4:
                        # The prepared host restores the equation and captures
                        # F12A together; native DCA4 restores, then F12A prepares.
                        actual = lib.fx_solve_controller_advance(C.byref(platform), C.byref(state))
                        run(0xdca4)
                        native.er(0, 0x9d00); native.ram[0x9d04] = 1
                        run(0x1f12a, stop=0x1f2ac)
                        check('restore_and_prepare', 'ui_status', 2, actual)
                        compare('restore_and_prepare', state, workspace=True, descriptor=True)

        # Keep one controller and persistent RAM from the first coefficient
        # prompt through the final numerical/result commit. This additional
        # group always uses the default prepared-memory expression callback,
        # including when other groups preview the optional native seam.
        for math in (0,1):
            for poison in (False,True):
                state = enter(b'X+A=9', math=math, poison=poison,
                              default_expression=True)
                check('continuous_prompt_flow','first_prompt_status',1,
                      advance(state,group='continuous_coefficient_prompt'))
                check('continuous_prompt_flow','coefficient_id',2,state.prompt_id)
                for token in b'1+2': edit(state,token)
                check('continuous_prompt_flow','typed_accept_status',7,accept(state))
                check('continuous_prompt_flow','coefficient_record',number(3).hex(),
                      bytes(ram[0x823a:0x8244]).hex())
                check('continuous_prompt_flow','guess_prompt_status',1,
                      advance(state,group='continuous_guess_prompt'))
                check('continuous_prompt_flow','guess_id',8,state.prompt_id)
                check('continuous_prompt_flow','unchanged_guess_status',7,
                      accept(state,unchanged=True))
                check('continuous_prompt_flow','equation_item',4,ram[0x80fd])
                actual = lib.fx_solve_controller_advance(C.byref(platform),C.byref(state))
                run(0xdca4)
                native.er(0,0x9d00); native.ram[0x9d04] = 1
                run(0x1f12a,stop=0x1f2ac)
                check('continuous_prepare','ui_status',2,actual)
                compare('continuous_prepare',state,workspace=True,descriptor=True)
                # Earlier typed acceptance has its own171F4 call. Numerical
                # observations start here while the measured stack exclusion
                # remains cumulative for this uninterrupted transaction.
                events.solve_controller_reset_observations()
                current_polls.clear(); current_samples.clear()
                actual = lib.fx_solve_controller_tick(C.byref(platform),C.byref(state))
                run(stop=0x1f3a2,allow_return=True)
                expected_status = C.c_uint.in_dll(events,'solve_controller_backend_status').value
                check('continuous_commit','native_backend_status',0,expected_status)
                check('continuous_commit','ui_status',3,actual)
                check('continuous_commit','numeric_status',expected_status,state.evaluator_status)
                check('continuous_commit','handler_action',native.reg(0),state.handler_action)
                compare('continuous_commit',state,workspace=True,descriptor=True)
                compare_samples(state,'continuous_commit')
                check('continuous_commit','selected_root',number(6).hex(),
                      bytes(ram[0x8276:0x8280]).hex())
                action = C.c_uint8(255); before = bytes(ram)
                check('continuous_finish','ui_status',3,
                      lib.fx_solve_controller_finish(C.byref(state),C.byref(action)))
                check('continuous_finish','handler_action',2,action.value)
                check('continuous_finish','ram_retained',before.hex(),bytes(ram).hex())

        solve_fixtures = [b'X=3', b'X-3', b'X\x75=2', b'X^3=2', b'X=1\xae3',
            b'X=\x982)', b'X=1\x4f0', b'=X', b'X=Y,Y', b'A+X=5,A',
            b'X\x75+1', b'X=0', b'X=3,X', b'X=3:', b'X=X', b'X=X+1']
        for tokens in solve_fixtures:
            for math in (0,1):
                for poison in (False,True):
                    selected = 9 if tokens == b'X=Y,Y' else 2 if tokens == b'A+X=5,A' else 8
                    prepared(tokens, math=math, selected=selected, poison=poison,
                             exercise_error=tokens in (b'X=1\x4f0', b'=X'))

        raw_records = [number(1), bytes.fromhex('21a30000000000000301'),
            bytes.fromhex('41000000000000000001'), bytes.fromhex('61a30000000000000301'),
            bytes.fromhex('80000001000201010100'), bytes.fromhex('40000000000000000000')]
        raw_records += [bytes([0xf0|code])+bytes(9) for code in range(16)]
        for variable, selected in zip(ordinary_variables, (0,2,3,4,5,6,7,8,9)):
            for math in (0,1):
                prepared(variable+b'=3,'+variable, selected=selected, math=math, poison=True,
                         required_native_status=0)
                for initial in raw_records[1:]:
                    prepared(variable+b'=3,'+variable,selected=selected,initial=initial,
                             math=math,poison=True)
        for initial in raw_records:
            for tokens in (b'X=3', b'X=\x8b', b'X=\xc8', b'=X'):
                for math in (0,1):
                    prepared(tokens, initial=initial, math=math, poison=True)
        for record in raw_records:
            for math in (0,1):
                prepared(b'X=A', records={2:record}, math=math, poison=True)
        for tokens in (b'X+A=3', b'X-A=0', b'X=A+1', b'X=A+A', b'X=1+A',
                       b'X=A\x75', b'X=A\x4e2', b'X=2\x4eA'):
            for code in (0,1,3,9,15):
                for math in (0,1):
                    prepared(tokens, records={2:bytes([0xf0|code])+bytes(9)},
                        imaginary={7:number(-99999)}, math=math, poison=True)
        # These are whole original F12A transactions, including callbacks
        # that reject stores or coordinates on the equation screen. They
        # retain every persistent effect even when the numerical solve fails.
        side_effect_inputs=[b'X=3\x47',b'X=3\x4b',b'X=3\x4c',b'X=3\x4d',
            b'X=3\x99',b'X=3\xa9',b'X\x47=3',b'X\x99=3',b'X=3\x47:',
            b'X=3\x47+1',b'X=\x6c3,4)',b'X=\x6d2,30)',
            b'X=10\x5f3',b'X=10\x5f3+1',b'X=\x8b+\xc8',b'X=\xc8\x47']
        for tokens in side_effect_inputs:
            for math in (0,1):
                prepared(tokens,math=math,poison=True)
        nested_inputs=[(b'X=\x6aX,0,1)',8),(b'A=\x6aX,0,1),A',2),
            (b'X=\x6bX\x75,2)',8),(b'A=\x6bX\x75,2),A',2),
            (b'X=\x69X,1,3)',8),(b'X=\x5dX,1,3)',8),
            (b'X=\x6a\x6bX,1),0,1)',8)]
        for tokens,selected in nested_inputs:
            for math in (0,1):
                for abort in (0,1,2,3,5):
                    prepared(tokens,selected=selected,math=math,abort=abort,poison=True)
        for tokens, initial in ((b'X\x75=0',1000), (b'X\x76=0',1),
                                (b'X\x76=0',-100000)):
            for math in (0,1):
                prepared(tokens, initial=initial, math=math, poison=True,
                         required_native_status=36)
        for tokens in (b'=X', b'X=1\x4f0', b'X\x75+1'):
            for math in (0,1):
                # This API captures a fresh C0 descriptor. Its native saved
                # result flag is zero because C0.bit4 is clear; an arbitrary
                # old F12A descriptor is a separate prepared boundary.
                for saved in (0,):
                    for pair in ((4,16), (128,8), (64,4), (16,128)):
                        state = prepared(tokens, math=math, saved=saved, poison=True)
                        if state.phase == 3: error_lifecycle(state, pair)
        for abort in (1,2,3,14,15,16,30,40,41,100):
            for tokens in (b'X\x75=2', b'X\x75+1', b'X=1'):
                prepared(tokens, math=abort&1, abort=abort, poison=True,
                         exercise_error=abort in (1,2))
        for tokens in (b'A=3', b'X=3,Y', b'X=3,X:', b'X=3,\x8b'):
            for math in (0,1):
                state = enter(tokens, math=math, poison=True)
                status = advance(state, group='scanner_error_prebanner')
                if status == 4:
                    check('scanner_error_prebanner', 'native_status', native.reg(1), state.evaluator_status)
                    error_lifecycle(state)
        for record in raw_records[:6]+raw_records[6:10]:
            for math in (0,1):
                state = enter(b'X+A=3', math=math, records={2:record}, poison=True)
                advance(state, group='raw_coefficient_prompt')
        # Foundation encoding only constructs rational INPUT records; every
        # expected controller/formatter effect comes from the live original.
        rational_inputs = []
        for numerator, denominator in ((1,2),(-1,2),(1,3),(-1,3),(2,3),
            (4,3),(-4,3),(5,2),(-5,2),(1,7),(12345,67),(-99999,97)):
            record = Number()
            if lib.fx_rational_encode(C.byref(record), C.byref(Rational(numerator,denominator,0))):
                raise AssertionError(('fixture_rational_encoding',numerator,denominator))
            rational_inputs.append(bytes(record))
        rational_inputs += [bytes.fromhex('60000000000000000000'),
                           bytes.fromhex('60000000000000000001')]
        for record in rational_inputs:
            marked = bytearray(record); marked[0] |= 0x40
            for math in (0,1):
                for mode, digits in ((0,0),(4,0),(8,0),(8,2),(8,9),(9,0),(9,1),(9,9)):
                    for mixed in (0,1):
                        state = enter(b'X+A=3', math=math, records={2:bytes(marked)},
                            poison=True, display_mode=mode, digits=digits, mixed_fraction=mixed)
                        advance(state, group='marked_rational_prompt_grid')
        for record in (bytes.fromhex('61230000000000000301'),
            bytes.fromhex('60a30000000000000301'), bytes.fromhex('61a3000000000000ff01'),
            bytes.fromhex('61a300000000000003ff'), bytes.fromhex('61a30000000000000305'),
            bytes.fromhex('61a30000000000000380')):
            for math in (0,1):
                state = enter(b'X+A=3', math=math, records={2:record}, poison=True)
                advance(state, group='raw_marked_fraction_prompt')
        for sequence in ((ord('1'),ord('+'),ord('2')),
            (ord('1'),ord('.'),ord('5')), (0x60,ord('2')), (ord('1'),0xae,ord('3')),
            (0x98,ord('2'),0xe2), (ord('3'),0x75), (ord('2'),ord('^'),ord('3')),
            (ord('1'),ord('2'),0xe3,ord('3'),0xe2,0xfe), (0xe2,), (0xe3,),
            (ord(':'),), (ord('='),), (0xa4,)):
            for math in (0,1):
                state = enter(b'X+A=3', math=math, poison=True)
                advance(state)
                for token in sequence: edit(state,token)
                if ram[0x80fe] == 1 and ram[0x8154]: accept(state)
        replay = bytes([0,0xad,0])+number(7)+b'3+4:\0'
        for token in (0xe0,0xe1,0xe2,0xe3,ord(':'),ord('='),0xa4,ord('5')):
            for math in (0,1):
                state = enter(b'X+A=3', math=math, poison=True, replay=replay)
                advance(state, group='history_prompt')
                check('history_prompt','history_indicator',1,ram[0x8129])
                before = bytes(ram[0x829e:0x8398])
                edit(state,token)
                if ram[0x80fe] == 1 and ram[0x8154]: accept(state)
                check('history_retained','replay_bytes',before.hex(),bytes(ram[0x829e:0x8398]).hex())
        for math in (0,1):
            state = enter(b'X+A=3', math=math, poison=True, replay=replay)
            advance(state, group='history_prompt')
            accept(state, unchanged=True)
            state = enter(b'X+A=3', math=math, poison=True, replay=replay)
            advance(state, group='history_prompt')
            edit(state,ord('5'))
            put(0x8129,1)
            accept(state)
        for index in range(args.random_cases//2):
            selected = rng.choice((0,2,3,4,5,6,7,8,9))
            variable = ordinary_variables[(0,2,3,4,5,6,7,8,9).index(selected)]
            coefficient, rhs = rng.randrange(1,100), rng.randrange(-100,101)
            literal = str(rhs).encode()
            formula = rng.choice(('affine','quadratic','cube','square_root','absolute',
                                  'reciprocal','pole','logarithm','exponential','negation'))
            if formula == 'affine':
                left = str(coefficient).encode()+b'\x4e'+variable+b'+'+str(rng.randrange(-20,21)).encode()
            elif formula == 'quadratic': left = variable+b'\x75'
            elif formula == 'cube': left = variable+b'\x76'
            elif formula == 'square_root': left = b'\x98'+variable+b')'
            elif formula == 'absolute': left = b'\x63'+variable+b')'
            elif formula == 'reciprocal': left = b'1\x4f'+variable
            elif formula == 'pole':
                left = b'1\x4f('+variable+b'-'+str(rng.randrange(-5,6)).encode()+b')'
            elif formula == 'logarithm':
                left = b'\xa3'+variable+b')'; literal = str(rng.randrange(-3,4)).encode()
            elif formula == 'exponential':
                left = b'\x73'+variable+b')'; literal = str(rng.randrange(0,9)).encode()
            else: left = b'\x60'+variable
            suffix = rng.choice((b'',b','+variable,b','+variable,b','+variable+b':',b',1'))
            tokens = left+b'='+literal+suffix
            abort = rng.choice((0,0,0,0,1,2,3,14,40))
            prepared(tokens, selected=selected, initial=rng.randrange(-100,101),
                     math=rng.randrange(2), poison=bool(index&1), abort=abort)
            if index%10 == 0:
                # Same persistent banks, replay bytes, caches, display packets
                # and numeric scratch are reused after the completed call.
                prepared(variable+b'=7,'+variable, selected=selected,
                         math=rng.randrange(2), reuse=True)

    source_changes = {name:{'before':value,'after':digest(ROOT/name)}
        for name,value in source_hashes.items() if digest(ROOT/name)!=value}
    report = dict(cases=sum(counts.values()), checks=checks, domains=counts,
        failures=failures, expression_seam='independent original171F4' if args.native_expression else 'default high-level evaluator',
        source_hashes=source_hashes, source_changes_during_run=source_changes,
        compiled_library_sha256=digest(shared), seam_errors=seam_errors,
        native_outcomes=observations,
        limits=['Fresh C1/C0/item4 descriptors; stale special-view or saved-result metadata is a separate native-only prepared boundary.',
            'C0 bit6 rejects calculus and quotient/remainder admission; these fixtures do not prove nested calculus polling.',
            'Native522A writes are observed, but no claim of transient store order is made.',
            'Passive original peripherals with explicit timer/cancellation responses; physical time and final root/residual presentation remain host-owned.'],
        native_minimum_sp_by_group={key:f'{value:04x}' for key,value in stack_floors.items()},
        excluded_native_workspace={'cpu_stack':'Measured minimum SP through8ded per original call sequence',
            'numerical_scratch':[['8000','80dc'],['8640','87d0']]},
        comparison='Live original whole controller calls versus C persistent RAM, framebuffer, host display packets and callback status; original CPU workspace is excluded explicitly.')
    (build/'diagnostics.json').write_text(json.dumps(report, indent=2)+'\n')
    if failures or seam_errors:
        raise AssertionError(f'{len(failures)} controller mismatches across {report["cases"]} observations')
    if not args.no_report:
        if source_changes:
            raise AssertionError('Linked implementation inputs changed during the native comparison')
        report = write_report('analysis/c-verification/solve_controller.json', report,
            compiled_inputs+['csrc/CMakeLists.txt', 'tools/test_input_controller_c.py',
                'tools/test_platform_c.py', 'tools/test_error_event_c.py', 'tools/test_key_controller_c.py',
                'tools/test_eval_complex_c.py', 'tools/test_numeric_c.py',
                'tools/c_build_inputs.py', 'tools/c_verification.py'],
            'tools/test_solve_controller_c.py')
    print(json.dumps({key: report[key] for key in ('cases','checks','domains','expression_seam')}, indent=2))


if __name__ == '__main__': main()
