/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_table_controller.h"
#include "../ui/fx_input_prepare.h"
#include "../ui/fx_input_recover.h"
#include "../ui/fx_error_boundary.h"
#include "../platform/fx_boot.h"
#include "../platform/fx_persistent.h"
#include "../stats/fx_stats_editor.h"
#include <string.h>

enum {
    PHASE_REQUEST = 1, PHASE_ERROR, PHASE_DONE, PHASE_RESET
};

static uint8_t read_byte(fx_platform *p, uint16_t a)
{
    return fx_data_read(p, 0, a);
}

static void write_byte(fx_platform *p, uint16_t a, uint8_t v)
{
    fx_data_write(p, 0, a, v);
}

static uint16_t read_word(fx_platform *p, uint16_t a)
{
    return (uint16_t)(read_byte(p, a) |
        (uint16_t)read_byte(p, (uint16_t)(a + 1)) << 8);
}

static void write_word(fx_platform *p, uint16_t a, uint16_t v)
{
    write_byte(p, a, (uint8_t)v);
    write_byte(p, (uint16_t)(a + 1), (uint8_t)(v >> 8));
}

static fx_number read_number(fx_platform *p, uint16_t a)
{
    fx_number n;
    for (unsigned i = 0; i < 10; i++) n.bytes[i] = read_byte(p, (uint16_t)(a + i));
    return n;
}

static void write_number(fx_platform *p, uint16_t a, const fx_number *n)
{
    for (unsigned i = 0; i < 10; i++) write_byte(p, (uint16_t)(a + i), n->bytes[i]);
}

static void copy_number(fx_platform *p, uint16_t to, uint16_t from)
{
    fx_number n = read_number(p, from);
    write_number(p, to, &n);
}

static int copy_expression(fx_platform *p, uint16_t to, uint16_t from)
{
    unsigned n;
    for (n = 0; n < 100 && read_byte(p, (uint16_t)(from + n)); n++) {
    }
    if (n == 100) return -1;
    for (unsigned i = 0; i <= n; i++) write_byte(p, (uint16_t)(to + i), read_byte(p, (uint16_t)(from + i)));
    return 0;
}

static fx_table_controller_status done(fx_table_controller *s, uint8_t action)
{
    s->request = FX_TABLE_REQUEST_NONE;
    s->phase = PHASE_DONE;
    s->handler_action = action;
    return FX_TABLE_CONTROLLER_COMPLETE;
}

static fx_table_controller_status request(fx_table_controller *s, fx_table_controller_request kind)
{
    s->request = kind;
    s->phase = PHASE_REQUEST;
    return FX_TABLE_CONTROLLER_REQUEST;
}

static int valid(fx_platform *p, fx_table_controller *s)
{
    return p && p->ram && s;
}

static void commit_token(fx_platform *p, uint8_t t)
{
    write_byte(p, 0x80f5, t);
    write_byte(p, 0x80f7, 1);
}

static fx_table_controller_status accept_function(fx_platform *p, fx_table_controller *s)
{
    uint16_t display = s->context.display_address;
    if (!read_byte(p, display) && !(read_byte(p, 0x8138) & 1u)) return done(s, 0);
    if (read_byte(p, 0x810e) == 1) {
        if (!(read_byte(p, 0x8138) & 1u)) {
            if (copy_expression(p, 0x81b8, display)) return FX_TABLE_CONTROLLER_RESOURCE_LIMIT;
            if (fx_boot_initialize_editor(p, 1) != FX_BOOT_READY) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
            if (copy_expression(p, display, 0x85aa)) return FX_TABLE_CONTROLLER_RESOURCE_LIMIT;
            write_byte(p, 0x8138, 1);
            return done(s, 1);
        }
        write_byte(p, 0x8138, read_byte(p, display) ? 0 : 0x80);
        if (copy_expression(p, 0x85aa, display)) return FX_TABLE_CONTROLLER_RESOURCE_LIMIT;
    } else if (copy_expression(p, 0x81b8, display)) {
        return FX_TABLE_CONTROLLER_RESOURCE_LIMIT;
    }
    write_byte(p, 0x80fc, 6);
    write_byte(p, 0x80fd, 1);
    write_byte(p, 0x80fe, 3);
    s->context.return_value = 0;
    return done(s, 0);
}

fx_table_controller_status fx_table_controller_begin(fx_platform *p,
    fx_table_controller *s, const fx_input_context *c)
{
    if (!valid(p, s) || !c) return FX_TABLE_CONTROLLER_INVALID;
    memset(s, 0, sizeof *s);
    s->context = *c;
    s->active = 1;
    if (read_byte(p, 0x80f9) != 0x88 || c->calculation_mode != 0x88 ||
        c->natural_input || c->saved_math_result)
        return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    uint8_t screen = read_byte(p, 0x80fc), item = read_byte(p, 0x80fd);
    if (screen == 1) {
        if (c->special_view) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
        return accept_function(p, s);
    }
    if (screen != 6 || item < 1 || item > 4) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    if (!read_byte(p, c->display_address)) return done(s, 0);
    write_word(p, 0x812c, c->display_address);
    int ready = fx_input_needs_export(p)
        ? fx_input_prepare_exported(p, &s->prepared_source)
        : fx_input_prepare_direct(p, &s->prepared_source);
    if (ready < 0) return FX_TABLE_CONTROLLER_RESOURCE_LIMIT;
    s->preparation_ok = (uint8_t)ready;
    s->current_source = (read_byte(p, 0x80fe) & 64) ? read_word(p, 0x812e) : s->prepared_source;
    s->saved_result[0] = read_number(p, c->result_address);
    s->saved_result[1] = read_number(p, (uint16_t)(c->result_address + 10));
    if (!ready) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    fx_display_port_sleep(p);
    /* F2EA chooses this route before the first subordinate call. The live
     * function-count byte may subsequently change without changing that route. */
    s->two_functions = (uint8_t)(item == 4 && read_byte(p, 0x810e) == 1);
    return request(s, item == 4 ? FX_TABLE_REQUEST_GENERATION
                                : FX_TABLE_REQUEST_PARAMETER_EVALUATION);
}

static fx_table_controller_status error_begin(fx_platform *p,
    fx_table_controller *s, int position_error)
{
    if (position_error)
        write_byte(p, 0x8114, (uint8_t)((uint8_t)s->current_source -
                                     (uint8_t)s->prepared_source));
    write_byte(p, 0x80fe, 0x80);
    if (fx_error_event_begin(p, &s->error, s->execution_status) < 0) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    s->request = FX_TABLE_REQUEST_NONE;
    s->phase = PHASE_ERROR;
    return FX_TABLE_CONTROLLER_WAIT;
}

static fx_table_controller_status parameter_commit(fx_platform *p, fx_table_controller *s)
{
    fx_result_clear_flags(p);
    fx_result_set_format(p, read_byte(p, 0x80f5) == 0xf0 ? 13 : 0);
    write_byte(p, 0x80fe, 3);
    uint8_t kind = read_byte(p, s->context.result_address) & 0xf0u;
    if (kind == 0x60 || kind == 0x90) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    if (s->execution_status == 0 || s->execution_status == 36) {
        for (unsigned i = 10; i < 20; i++) write_byte(p, (uint16_t)(s->context.result_address + i), 0);
    } else if (s->execution_status == 34) write_byte(p, 0x80ff, 18);
    else if (s->execution_status == 35) write_byte(p, 0x80ff, 17);
    else if (s->execution_status == 37) {
        if (read_byte(p, (uint16_t)(s->context.result_address + 10)) == 0x70) {
            for (unsigned i = 10; i < 20; i++) write_byte(p, (uint16_t)(s->context.result_address + i), 0);
        }
        else write_byte(p, 0x80ff, 20);
    }
    if (read_byte(p, 0x80ff) & 16u) {
        for (unsigned i = 10; i < 20; i++) write_byte(p, (uint16_t)(s->context.result_address + i), 0);
    }
    write_byte(p, 0x80ff, 0);
    fx_result_clear_display_state(p);
    uint8_t item = read_byte(p, 0x80fd);
    if (item < 1 || item > 3) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    copy_number(p, (uint16_t)(0x829e + 10u * (item - 1)), s->context.result_address);
    write_byte(p, 0x80fd, (uint8_t)(item + 1));
    write_byte(p, 0x80fe, 3);
    s->context.return_value = 0;
    return done(s, 0);
}

fx_table_controller_status fx_table_controller_accept_execution(fx_platform *p,
    fx_table_controller *s, int status, uint16_t returned_source)
{
    if (!valid(p, s) || !s->active || s->phase != PHASE_REQUEST ||
        (s->request != FX_TABLE_REQUEST_GENERATION &&
         s->request != FX_TABLE_REQUEST_PARAMETER_EVALUATION)) return FX_TABLE_CONTROLLER_INVALID;
    if (status > 255 ||
        (s->request == FX_TABLE_REQUEST_GENERATION && status >= 32))
        return FX_TABLE_CONTROLLER_INVALID;
    s->current_source = returned_source;
    if (status < 0) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    s->execution_status = (uint8_t)status;
    if (status > 0 && status < 32) return error_begin(p, s, 1);
    if (s->request == FX_TABLE_REQUEST_PARAMETER_EVALUATION) return parameter_commit(p, s);
    if (s->two_functions && !s->second_pass && !(read_byte(p, 0x8138) & 0x80u)) {
        write_byte(p, 0x8138, 1);
        int ready = fx_input_prepare_saved_solve(p, &s->prepared_source);
        if (ready < 0) return FX_TABLE_CONTROLLER_RESOURCE_LIMIT;
        s->current_source = s->prepared_source;
        s->second_pass = 1;
        if (!ready) {
            s->execution_status = 2;
            /* Failed G export enters F39A directly, bypassing F36C cursor. */
            return error_begin(p, s, 0);
        }
        return request(s, FX_TABLE_REQUEST_GENERATION);
    }
    if (s->second_pass) write_byte(p, 0x8138, 0);
    write_byte(p, 0x80fc, 18);
    fx_result_reset_layout_and_flags(p);
    s->context.return_value = 0;
    return done(s, 0);
}

fx_table_controller_status fx_table_controller_range_key(fx_platform *p,
    fx_table_controller *s, uint8_t t)
{
    if (!valid(p, s)) return FX_TABLE_CONTROLLER_INVALID;
    memset(s, 0, sizeof *s);
    s->active = 1;
    if (read_byte(p, 0x80f9) != 0x88 || read_byte(p, 0x80fc) != 6) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    if (t != read_byte(p, 0x80f5)) return FX_TABLE_CONTROLLER_INVALID;
    s->handler_action = 1;
    if (fx_key_is_menu_token(p, t)) {
        s->argument = 0;
        return request(s, FX_TABLE_REQUEST_INPUT_ACTION);
    }
    if ((t == 0xed || t == 0xf0) && read_byte(p, 0x80fe) == 4) {
        write_byte(p, 0x80fd, (uint8_t)(read_byte(p, 0x80fd) + 1));
        fx_result_clear_display_state(p);
    }
    uint8_t item = read_byte(p, 0x80fd);
    if (item >= 1 && item <= 3) {
        s->argument = item;
        return request(s, FX_TABLE_REQUEST_RANGE_PROMPT);
    }
    if (item == 4) {
        commit_token(p, 0xed);
        write_byte(p, 0x80fe, 1);
        return done(s, 0);
    }
    return done(s, 1);
}

fx_table_controller_status fx_table_controller_navigate(fx_platform *p,
    fx_table_controller *s, uint8_t t)
{
    if (!valid(p, s)) return FX_TABLE_CONTROLLER_INVALID;
    memset(s, 0, sizeof *s);
    s->active = 1;
    if (read_byte(p, 0x80f9) != 0x88 || read_byte(p, 0x80fc) != 18) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    if (t != read_byte(p, 0x80f5)) return FX_TABLE_CONTROLLER_INVALID;
    s->columns = fx_stats_editor_columns(p);
    s->initial_rows = read_byte(p, 0x80de);
    if (fx_key_is_direction_token(p, t)) {
        (void)fx_acquire_busy(p);
        if (fx_stats_editor_move(p, t)) {
            fx_clear_busy(p);
            return done(s, 0);
        }
    } else if (t == 0xfe) return done(s, 0);
    /* The native byte row iterator cannot reach top+3 when top >=253. */
    if (read_byte(p, 0x811c) >= 253) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    uint8_t screen = read_byte(p, 0x811d), column = read_byte(p, 0x811e);
    if (screen < 1 || screen > 3 || column < 1 || column > s->columns) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    unsigned row = (uint8_t)(read_byte(p, 0x811c) + screen - 1);
    /*5096 performs byte row/column arithmetic before multiplying by ten.
     * Its second MUL consumes the low byte of the first product. */
    if (row <= s->initial_rows) {
        unsigned selector = column - 1;
        if (read_byte(p, 0x80fa) == 1 && selector == 2) --selector;
        s->selected_address = (uint16_t)(0x82ee + 10u * (uint8_t)((uint8_t)(row - 1) * s->columns) +
            10u * selector);
    }
    fx_number value;
    if (s->selected_address) value = read_number(p, s->selected_address);
    else fx_number_error(&value, 13);
    fx_number imaginary;
    fx_number_zero(&imaginary);
    write_number(p, 0x814a, &imaginary);
    write_number(p, 0x8140, &value);
    if (fx_key_is_menu_token(p, t)) {
        if (!s->selected_address) return done(s, 0);
        s->argument = 0;
        return request(s, FX_TABLE_REQUEST_INPUT_ACTION);
    }
    return request(s, FX_TABLE_REQUEST_GRID_PAINT);
}

fx_table_controller_status fx_table_controller_accept_handler(fx_platform *p,
    fx_table_controller *s, uint8_t returned)
{
    if (!valid(p, s) || !s->active || s->phase != PHASE_REQUEST) return FX_TABLE_CONTROLLER_INVALID;
    switch (s->request) {
    case FX_TABLE_REQUEST_INPUT_ACTION:
    case FX_TABLE_REQUEST_RANGE_PROMPT:
        return done(s, s->handler_action);
    case FX_TABLE_REQUEST_GRID_PAINT:
        (void) returned;
        write_byte(p, 0x811f, 7);
        /* E432 compares the visible screen row with the captured row count. */
        if (read_byte(p, 0x811d) > s->initial_rows) s->selected_address = 0;
        return request(s, FX_TABLE_REQUEST_SELECTED_RESULT);
    case FX_TABLE_REQUEST_SELECTED_RESULT:
        return done(s, 0);
    default:
        return FX_TABLE_CONTROLLER_INVALID;
    }
}

fx_table_controller_status fx_table_controller_tick(fx_platform *p,
    fx_table_controller *s)
{
    if (!valid(p, s) || !s->active) return FX_TABLE_CONTROLLER_INVALID;
    if (s->phase == PHASE_DONE) return FX_TABLE_CONTROLLER_COMPLETE;
    if (s->phase == PHASE_RESET) return FX_TABLE_CONTROLLER_RESET;
    if (s->phase == PHASE_REQUEST) return FX_TABLE_CONTROLLER_REQUEST;
    if (s->phase != PHASE_ERROR) return FX_TABLE_CONTROLLER_INVALID;
    fx_key_controller_status event = fx_error_event_tick(p, &s->error);
    if (event == FX_KEY_CONTROLLER_WAIT) return FX_TABLE_CONTROLLER_WAIT;
    if (event == FX_KEY_CONTROLLER_EXPORT) return FX_TABLE_CONTROLLER_EXPORT;
    if (event < 0) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    uint8_t t;
    (void)fx_error_event_finish(&s->error, &t);
    if (event == FX_KEY_CONTROLLER_RESET) {
        s->phase = PHASE_RESET;
        return FX_TABLE_CONTROLLER_RESET;
    }
    commit_token(p, t);
    fx_result_clear(p);
    fx_error_context c = {
        s->context.display_address, 0x88
    };
    int handled = fx_error_cursor_restore(p, &c);
    if (handled < 0) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    if (handled == 1) return done(s, 1);
    write_byte(p, 0x8138, 0);
    fx_input_recovery_context recovery = {
        s->context.display_address, s->context.result_address, 0x88, 0, s->context.return_value
    };
    handled = fx_input_recover_after_error(p, &recovery);
    if (handled < 0) return FX_TABLE_CONTROLLER_UNIMPLEMENTED;
    s->context.return_value = recovery.return_value;
    return done(s, (uint8_t)(handled != 0));
}

fx_table_controller_status fx_table_controller_finish(fx_table_controller *s,
    uint8_t *action)
{
    if (!s || !s->active || (s->phase != PHASE_DONE && s->phase != PHASE_RESET)) return FX_TABLE_CONTROLLER_INVALID;
    if (action) *action = s->handler_action;
    s->active = 0;
    return s->phase == PHASE_RESET ? FX_TABLE_CONTROLLER_RESET
                                   : FX_TABLE_CONTROLLER_COMPLETE;
}
