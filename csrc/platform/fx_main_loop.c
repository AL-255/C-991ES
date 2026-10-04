/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_main_loop.h"
#include "fx_boot.h"
#include "fx_persistent.h"
#include "../render/fx_render_memory.h"
#include <string.h>

static uint8_t read_byte(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void write_byte(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

static void flush(fx_platform *p)
{
    fx_render render = {p->rom, p->rom_size, p->ram};
    fx_flush_framebuffer(&render);
}

void fx_main_loop_begin(fx_main_loop *state)
{
    if (!state) return;
    memset(state, 0, sizeof *state);
    state->phase = FX_MAIN_NEXT_CYCLE;
    state->active = 1;
}

uint8_t fx_main_routes_input(fx_platform *p)
{
    uint8_t flags = read_byte(p, 0x80fe);
    uint8_t token = read_byte(p, 0x80f5);
    return (uint8_t)(read_byte(p, 0x80fc) == 1 || flags == 1 || (flags & 0xf0) ||
                    fx_key_is_data_token(p, token) ||
                    (read_byte(p, 0x80f7) && token >= 14 && token <= 22));
}

static fx_main_status request(fx_main_loop *state, fx_main_request kind,
                              uint8_t argument)
{
    state->pending_request = (uint8_t)kind;
    state->argument = argument;
    state->phase = FX_MAIN_HANDLER_PENDING;
    return FX_MAIN_REQUEST;
}

static fx_main_status finish_cycle(fx_platform *p, fx_main_loop *state,
                                    int repaint)
{
    if (repaint) flush(p);
    state->pending_request = 0;
    state->argument = 0;
    state->phase = FX_MAIN_NEXT_CYCLE;
    return FX_MAIN_ADVANCED;
}

static fx_main_status dispatch(fx_platform *p, fx_main_loop *state)
{
    state->wait_required = 1;
    uint8_t menu = read_byte(p, 0x80fb);
    if (menu == 1 || menu == 2) {
        write_byte(p, 0x812a, 0);
        return request(state, menu == 1 ? FX_MAIN_MODE_MENU : FX_MAIN_SETUP_MENU, 0);
    }
    if (menu == 3) return request(state, FX_MAIN_PARAMETER_MENU, 0);
    if (menu) {
        int repaint = !state->last_menu_result;
        if (!repaint) state->wait_required = 0;
        write_byte(p, 0x80fb, 0);
        return finish_cycle(p, state, repaint);
    }
    if (fx_main_routes_input(p)) return request(state, FX_MAIN_INPUT, 0);

    uint8_t screen = read_byte(p, 0x80fc);
    uint8_t mode = read_byte(p, 0x80f9);
    uint8_t token = read_byte(p, 0x80f5);
    int dedicated = screen == 21 || screen == 24 || screen == 23 || screen == 9 ||
                    (mode == 12 && screen == 18);
    if (!dedicated && token == 0xe6) {
        write_byte(p, 0x80fc, 1);
        if (fx_boot_initialize_editor(p, 1) != FX_BOOT_READY) return FX_MAIN_UNIMPLEMENTED;
        state->wait_required = 0;
        if (mode == 0x88) write_byte(p, 0x8138, 0);
        return finish_cycle(p, state, 1);
    }
    if (mode == 12 && (screen == 9 || screen == 18) && token == 0xe6) {
        fx_boot_initialize_mode12(p);
        write_byte(p, 0x80f5, 0);
        state->wait_required = 0;
        return finish_cycle(p, state, 1);
    }
    if (screen == 18) return request(state, FX_MAIN_SCREEN18_ADMISSION, 0);
    fx_main_request kind;
    switch (screen) {
    case 19: kind = FX_MAIN_SCREEN19; break;
    case 20: kind = FX_MAIN_SCREEN20; break;
    case 21: kind = FX_MAIN_SCREEN21; break;
    case 6: kind = FX_MAIN_SCREEN6; break;
    case 0xa0: case 0xc0: kind = FX_MAIN_SCREEN_A0_C0; break;
    case 24: kind = FX_MAIN_SCREEN24; break;
    case 9: kind = FX_MAIN_SCREEN9; break;
    default: return finish_cycle(p, state, 1);
    }
    return request(state, kind, state->last_menu_result);
}

static int selection_blocked(fx_platform *p)
{
    return (read_byte(p, 0x80fe) & 0x40) ||
           ((read_byte(p, 0x80fc) & 0x80) && read_byte(p, 0x80fd) == 2) ||
           !read_byte(p, 0x8154);
}

static fx_main_status select_screen(fx_platform *p, fx_main_loop *state,
                                    uint8_t screen)
{
    if (read_byte(p, 0x80fc) & 0x80) {
        unsigned length;
        for (length = 0; length < 100 && read_byte(p, (uint16_t)(0x81b8+length)); ++length) {}
        if (length == 100) return FX_MAIN_UNIMPLEMENTED;
        for (unsigned n = 0; n <= length; ++n)
            write_byte(p, (uint16_t)(0x8154+n), read_byte(p, (uint16_t)(0x81b8+n)));
    }
    write_byte(p, 0x80fc, screen);
    write_byte(p, 0x80fd, 1);
    write_byte(p, 0x80fe, 4);
    fx_result_clear_display_state(p);
    return dispatch(p, state);
}

fx_main_status fx_main_loop_accept_token(fx_platform *p, fx_main_loop *state,
                                        uint8_t token)
{
    if (!p || !p->ram || !state || !state->active || !state->wait_required ||
        (state->phase != FX_MAIN_NEXT_CYCLE && state->phase != FX_MAIN_KEY_WAIT))
        return FX_MAIN_INVALID;
    write_byte(p, 0x80f5, token);
    write_byte(p, 0x80f7, 1);
    if (token == 0xe4) write_byte(p, 0x80fb, 1);
    else if (token == 0xe5) write_byte(p, 0x80fb, 2);
    else if (token >= 1 && token <= 11) write_byte(p, 0x80fb, 3);
    else if (token == 0xfc || token == 0xfd) {
        uint8_t mode = read_byte(p, 0x80f9);
        if (selection_blocked(p) ||
            (token == 0xfc ? mode != 0xc1 && mode != 0xc4 : mode != 0xc1)) {
            state->phase = FX_MAIN_NEXT_CYCLE;
            return FX_MAIN_ADVANCED;
        }
        return select_screen(p, state, token == 0xfc ? 0xa0 : 0xc0);
    } else write_byte(p, 0x80fb, 0);
    return dispatch(p, state);
}

fx_main_status fx_main_loop_accept_handler(fx_platform *p, fx_main_loop *state,
                                          uint8_t returned)
{
    if (!p || !p->ram || !state || !state->active ||
        state->phase != FX_MAIN_HANDLER_PENDING) return FX_MAIN_INVALID;
    switch ((fx_main_request)state->pending_request) {
    case FX_MAIN_INPUT:
        state->wait_required = returned;
        return finish_cycle(p, state, 1);
    case FX_MAIN_MODE_MENU: case FX_MAIN_SETUP_MENU: case FX_MAIN_PARAMETER_MENU: {
        fx_main_request kind = (fx_main_request)state->pending_request;
        state->last_menu_result = returned;
        if (kind == FX_MAIN_SETUP_MENU && returned) {
            fx_result_clear_format(p);
            if ((read_byte(p, 0x80fc) & 0x10) &&
                !(read_byte(p, 0x80f9) == 12 && read_byte(p, 0x80fe) == 5))
                fx_result_clear_flags(p);
        }
        if (kind == FX_MAIN_PARAMETER_MENU && returned && returned < 128)
            write_byte(p, 0x80f7, 0);
        if (returned) state->wait_required = 0;
        write_byte(p, 0x80fb, 0);
        return finish_cycle(p, state, !returned);
    }
    case FX_MAIN_SCREEN18_ADMISSION:
        if (!returned) return request(state, FX_MAIN_SCREEN18, 0);
        state->wait_required = 0;
        return finish_cycle(p, state, 1);
    case FX_MAIN_SCREEN18:
        state->wait_required = 1;
        return finish_cycle(p, state, 1);
    default:
        if (state->pending_request < FX_MAIN_SCREEN19 ||
            state->pending_request > FX_MAIN_SCREEN9) return FX_MAIN_INVALID;
        state->wait_required = returned;
        return finish_cycle(p, state, 1);
    }
}

fx_main_status fx_main_loop_tick(fx_platform *p, fx_main_loop *state)
{
    if (!p || !p->ram || !state || !state->active) return FX_MAIN_INVALID;
    if (state->phase == FX_MAIN_HANDLER_PENDING) return FX_MAIN_REQUEST;
    if (state->phase == FX_MAIN_NEXT_CYCLE) {
        if (!state->wait_required) return dispatch(p, state);
        (void)fx_display_port_active(p);
        if (fx_key_controller_begin(p, &state->keys) != FX_KEY_CONTROLLER_WAIT)
            return FX_MAIN_UNIMPLEMENTED;
        state->phase = FX_MAIN_KEY_WAIT;
        return FX_MAIN_WAIT;
    }
    if (state->phase != FX_MAIN_KEY_WAIT) return FX_MAIN_INVALID;
    fx_key_controller_status status = fx_key_controller_tick(p, &state->keys);
    if (status == FX_KEY_CONTROLLER_WAIT) return FX_MAIN_WAIT;
    if (status == FX_KEY_CONTROLLER_EXPORT) return FX_MAIN_EXPORT;
    if (status == FX_KEY_CONTROLLER_RESET) return FX_MAIN_RESET;
    if (status != FX_KEY_CONTROLLER_TOKEN) return FX_MAIN_UNIMPLEMENTED;
    uint8_t token;
    if (fx_key_controller_finish(&state->keys, &token) != FX_KEY_CONTROLLER_TOKEN)
        return FX_MAIN_UNIMPLEMENTED;
    return fx_main_loop_accept_token(p, state, token);
}
