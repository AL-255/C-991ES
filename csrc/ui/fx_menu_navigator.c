/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_menu_navigator.h"
#include "../render/fx_render_memory.h"
#include <string.h>

enum { MENU_KEY_WAIT = 1, MENU_DELAY = 2, MENU_COMPLETE = 3, MENU_RESET = 4 };

static uint8_t get(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void put(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

static uint16_t descriptor(uint8_t page)
{
    return (uint16_t)(0x0b9au + 16u*page);
}

static uint16_t word(fx_platform *p, uint16_t address)
{
    uint16_t low = get(p, address);
    return (uint16_t)(low | (uint16_t)get(p, (uint16_t)(address + 1u)) << 8);
}

static fx_render prepare_paint(fx_platform *p)
{
    fx_render render = {p->rom, p->rom_size, p->ram};
    /* 402E calls 54E6 directly, without 54E0's special-screen guard. */
    put(p, 0x811f, 7);
    put(p, 0x8121, 0);
    put(p, 0xf031, 6);
    static const struct { uint16_t address; uint8_t mask; } indicators[] = {
        {0xf800, 0x14}, {0xf801, 0x02}, {0xf802, 0x40},
        {0xf80b, 0x80}, {0xf80a, 0x08}, {0xf80b, 0x10}
    };
    for (unsigned n = 0; n < sizeof indicators / sizeof indicators[0]; ++n)
        put(p, indicators[n].address,
            (uint8_t)(get(p, indicators[n].address) & ~indicators[n].mask));
    fx_fill_display(&render, 0, 2);
    return render;
}

static void finish_paint(fx_platform *p)
{
    put(p, 0x8121, 1);
    fx_display_port_active(p);
}

void fx_menu_paint_lines(fx_platform *p, const uint16_t lines[4])
{
    if (!p || !p->ram || !lines) return;
    fx_render render = prepare_paint(p);
    for (unsigned row = 0; row < 4; ++row) {
        uint16_t text = lines[row];
        fx_draw_text(&render, 0, (int8_t)(1u + 8u*row), &text);
    }
    finish_paint(p);
}

void fx_menu_paint_body(fx_platform *p, uint16_t heading, uint16_t body)
{
    if (!p || !p->ram) return;
    fx_render render = prepare_paint(p);
    unsigned first_row = 0, rows = 4;
    if (heading) {
        fx_draw_text(&render, 0, 1, &heading);
        first_row = 1;
        rows = body ? 3 : 0;
    }
    for (unsigned row = 0; row < rows; ++row) {
        fx_draw_text(&render, 0, (int8_t)(1u + 8u*(first_row + row)), &body);
        body = (uint16_t)(body + 1u);
    }
    finish_paint(p);
}

static fx_menu_status begin_wait(fx_platform *p, fx_menu_navigator *state)
{
    if (fx_key_controller_begin(p, &state->keys) != FX_KEY_CONTROLLER_WAIT)
        return FX_MENU_UNIMPLEMENTED;
    state->phase = MENU_KEY_WAIT;
    return FX_MENU_WAIT;
}

static fx_menu_status paint_page(fx_platform *p, fx_menu_navigator *state)
{
    if (state->page) {
        uint16_t table = descriptor(state->page);
        fx_menu_paint_body(p, state->heading, word(p, table));
        if (get(p, (uint16_t)(table + 12u)))
            put(p, 0xf80b, (uint8_t)(get(p, 0xf80b) | 0x80u));
        if (get(p, (uint16_t)(table + 13u)))
            put(p, 0xf80a, (uint8_t)(get(p, 0xf80a) | 0x08u));
    }
    return begin_wait(p, state);
}

fx_menu_status fx_menu_navigator_begin(fx_platform *p,
    fx_menu_navigator *state, uint8_t selection, uint16_t heading)
{
    if (!p || !p->ram || !state) return FX_MENU_INVALID;
    memset(state, 0, sizeof(*state));
    state->selection = selection;
    state->page = selection;
    state->mode_close_policy = heading == 0xffffu;
    state->heading = heading == 0xffffu ? 0 : heading;
    state->active = 1;
    return paint_page(p, state);
}

static fx_menu_status complete(fx_menu_navigator *state, uint8_t result)
{
    state->result = result;
    state->phase = MENU_COMPLETE;
    return FX_MENU_DONE;
}

static fx_menu_status delay(fx_platform *p, fx_menu_navigator *state, int cancel)
{
    state->cancel_after_timer = (uint8_t)cancel;
    state->timer_period = 0x0770;
    fx_set_lcd_flag(p, 1);
    fx_timer_start(p, state->timer_period);
    state->phase = MENU_DELAY;
    return FX_MENU_TIMER;
}

fx_menu_status fx_menu_navigator_accept_token(fx_platform *p,
    fx_menu_navigator *state, uint8_t token)
{
    if (!p || !p->ram || !state || !state->active || state->phase != MENU_KEY_WAIT)
        return FX_MENU_INVALID;
    uint16_t table = descriptor(state->page);
    uint8_t next_page = 0;
    state->keys.active = 0;
    if (token >= 0x31 && token <= 0x38) {
        unsigned index = token - 0x31u;
        uint8_t choice = get(p, (uint16_t)(table + 4u + index));
        if (choice) {
            unsigned shift = 7u - index;
            if ((get(p, (uint16_t)(table + 2u)) >> shift) & 1u) {
                state->selection = choice;
                return complete(state,
                    ((get(p, (uint16_t)(table + 3u)) >> shift) & 1u) ? 2 : 3);
            }
            next_page = choice;
        }
    } else if (token == 0xe6) {
        put(p, 0x80f5, 0);
        return delay(p, state, 1);
    } else if (token) {
        uint8_t close = get(p, (uint16_t)(table + 15u));
        if (token == close) {
            if (state->mode_close_policy || get(p, 0x80fb) != 1) {
                state->selection = token;
                put(p, 0x80f5, 0);
                return complete(state, 1);
            }
        } else if (token == 0xe0) next_page = get(p, (uint16_t)(table + 12u));
        else if (token == 0xe1) next_page = get(p, (uint16_t)(table + 13u));
        else if (token == 0xe3) {
            next_page = get(p, (uint16_t)(table + 14u));
            if (next_page) state->heading = 0;
        }
    }
    if (next_page & 0x80u) {
        state->selection = next_page;
        return complete(state, 1);
    }
    if (next_page) {
        state->page = next_page;
        return paint_page(p, state);
    }
    return delay(p, state, 0);
}

fx_menu_status fx_menu_navigator_tick(fx_platform *p, fx_menu_navigator *state)
{
    if (!p || !p->ram || !state || !state->active) return FX_MENU_INVALID;
    if (state->phase == MENU_DELAY) return FX_MENU_TIMER;
    if (state->phase == MENU_COMPLETE) return FX_MENU_DONE;
    if (state->phase == MENU_RESET) return FX_MENU_RESET;
    if (state->phase != MENU_KEY_WAIT) return FX_MENU_INVALID;
    fx_key_controller_status event = fx_key_controller_tick(p, &state->keys);
    if (event == FX_KEY_CONTROLLER_WAIT) return FX_MENU_WAIT;
    if (event == FX_KEY_CONTROLLER_EXPORT) return FX_MENU_EXPORT;
    if (event == FX_KEY_CONTROLLER_RESET) {
        fx_key_controller_finish(&state->keys, NULL);
        state->phase = MENU_RESET;
        return FX_MENU_RESET;
    }
    if (event != FX_KEY_CONTROLLER_TOKEN) return FX_MENU_UNIMPLEMENTED;
    uint8_t token;
    fx_key_controller_finish(&state->keys, &token);
    return fx_menu_navigator_accept_token(p, state, token);
}

fx_menu_status fx_menu_navigator_resume_timer(fx_platform *p, fx_menu_navigator *state)
{
    if (!p || !p->ram || !state || !state->active || state->phase != MENU_DELAY)
        return FX_MENU_INVALID;
    fx_set_lcd_flag(p, 0);
    state->timer_period = 0;
    if (state->cancel_after_timer) return complete(state, 0);
    return begin_wait(p, state);
}

fx_menu_status fx_menu_navigator_finish(fx_menu_navigator *state,
    uint8_t *selection, uint8_t *result)
{
    if (!state || !state->active ||
        (state->phase != MENU_COMPLETE && state->phase != MENU_RESET))
        return FX_MENU_INVALID;
    fx_menu_status status = state->phase == MENU_RESET ? FX_MENU_RESET : FX_MENU_DONE;
    if (selection) *selection = state->selection;
    if (result) *result = state->result;
    state->active = 0;
    return status;
}
