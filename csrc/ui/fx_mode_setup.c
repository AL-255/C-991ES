/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_mode_setup.h"
#include "../platform/fx_boot.h"
#include "../platform/fx_persistent.h"
#include <string.h>

enum { KIND_MODE = 1, KIND_SETUP = 2 };
enum { PHASE_MENU = 1, PHASE_STAT = 2, PHASE_EQUATION = 3,
       PHASE_INEQUALITY = 4, PHASE_DISTRIBUTION = 5, PHASE_PRECISION = 6,
       PHASE_CONTRAST = 7, PHASE_HANDLER = 8, PHASE_COMPLETE = 9,
       PHASE_RESET = 10 };

static uint8_t get(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void put(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

static uint16_t word(fx_platform *p, uint16_t address)
{
    uint16_t low = get(p, address);
    return (uint16_t)(low | (uint16_t)get(p, (uint16_t)(address + 1u)) << 8);
}

static void clear(fx_platform *p, uint16_t address, unsigned size)
{
    for (unsigned n = 0; n < size; ++n) put(p, (uint16_t)(address + n), 0);
}

static void small_decimal(fx_platform *p, uint16_t address, uint8_t value)
{
    /* 1CDAE's admitted small literal has no operand workspace side effects. */
    put(p, address, value);
    for (unsigned n = 1; n < 9; ++n) put(p, (uint16_t)(address + n), 0);
    put(p, (uint16_t)(address + 9u), value ? 1 : 0);
}

void fx_mode_reset_statistics(fx_platform *p)
{
    if (get(p, 0x80f9) != 3) return;
    put(p, 0x80de, 0);
    put(p, 0x80df, 0);
    fx_result_reset_layout(p);
    clear(p, 0x82ee, 800);
    put(p, 0x812a, 0);
}

void fx_mode_reset_bank(fx_platform *p)
{
    fx_result_reset_layout(p);
    clear(p, 0x80e0, 18);
    clear(p, 0x829e, 810);
}

void fx_mode_initialize_equation(fx_platform *p, uint8_t screen)
{
    fx_mode_reset_bank(p);
    for (unsigned slot = 0; slot < 3; ++slot) {
        put(p, (uint16_t)(0x80e0u + 2u*slot), 3);
        put(p, (uint16_t)(0x80e1u + 2u*slot), 3);
        /* D2C6 defines a fixed3x3 slot and clears all nine10-byte cells. */
        clear(p, (uint16_t)(0x829eu + 90u*slot), 90);
    }
    put(p, 0x80fc, screen);
}

void fx_mode_reset_table(fx_platform *p)
{
    if (get(p, 0x80f9) != 0x88) return;
    put(p, 0x8138, 0);
    clear(p, 0x85aa, 100);
}

int fx_mode_set(fx_platform *p, uint8_t mode, uint8_t submode)
{
    if (!p || !p->ram) return -1;
    uint8_t saved[4][10];
    uint16_t address[4];
    for (unsigned slot = 0; slot < 4; ++slot) {
        address[slot] = word(p, slot < 3 ? (uint16_t)(0x0ff8u + 2u*slot) : 0x100e);
        for (unsigned n = 0; n < 10; ++n)
            saved[slot][n] = get(p, (uint16_t)(address[slot] + n));
    }
    uint8_t old_mode = get(p, 0x80f9), old_submode = get(p, 0x80fa);
    if (old_mode != mode) {
        put(p, 0x80fd, 0);
        clear(p, 0x829e, 880);
    }
    fx_result_clear_flags(p);
    put(p, 0x80f9, mode);
    put(p, 0x80fa, submode);
    fx_result_clear(p);
    switch (mode) {
    case 0xc1:
        clear(p, 0x828a, 10);
        break;
    case 3:
        fx_mode_reset_statistics(p);
        put(p, 0x80fc, 18);
        if (!submode) put(p, 0x80fa, 1);
        break;
    case 6:
    case 7:
        put(p, 0x80fc, mode == 6 ? 19 : 20);
        if (old_mode != mode) fx_mode_reset_bank(p);
        break;
    case 0x45:
        if (!submode) put(p, 0x80fa, 1);
        fx_mode_initialize_equation(p, 21);
        break;
    case 0x4b:
        if (!submode) {
            put(p, 0x80fa, 3);
            put(p, 0x8131, 0);
        }
        fx_mode_initialize_equation(p, 24);
        if (old_mode == mode && get(p, 0x80fa) == old_submode) {
            unsigned slots = get(p, 0x80fa) == 4 ? 4 : 3;
            for (unsigned slot = 0; slot < slots; ++slot)
                for (unsigned n = 0; n < 10; ++n)
                    put(p, (uint16_t)(address[slot] + n), saved[slot][n]);
        }
        break;
    case 0x88:
        small_decimal(p, word(p, 0x102c), 1);
        small_decimal(p, word(p, 0x1030), 1);
        small_decimal(p, word(p, 0x102e), 5);
        fx_mode_reset_table(p);
        put(p, 0x80fc, 1);
        put(p, 0x80fd, 0);
        break;
    case 12:
        if (!submode) {
            put(p, 0x80fa, 1);
            put(p, 0x8137, 0);
        }
        if (old_mode != 12) {
            put(p, 0x80de, 0);
            put(p, 0x80df, 0);
            fx_result_reset_layout(p);
            clear(p, 0x82ee, 800);
            clear(p, 0x829e, 80);
            small_decimal(p, 0x82a8, 1);
        }
        fx_boot_initialize_mode12(p);
        break;
    default:
        break;
    }
    return 0;
}

int fx_setup_set_layout(fx_platform *p, uint8_t natural)
{
    if (!p || !p->ram) return -1;
    put(p, 0x8106, natural);
    uint8_t mode = get(p, 0x80f9), flags = get(p, 0x80fe) & 15u;
    if ((mode == 0x45 || mode == 0x4b || mode == 0x4a || mode == 12) &&
        (flags == 3 || flags == 5)) return 0;
    if (get(p, 0x80fc) & 0x80u) {
        put(p, 0x80fc, 1);
        put(p, 0x80fd, 0);
        put(p, 0x80fe, 1);
        put(p, 0x80ff, 0);
    }
    if (fx_boot_initialize_editor(p, 2) != FX_BOOT_READY) return -2;
    fx_boot_clear_result_workspaces(p);
    fx_result_clear(p);
    if (get(p, 0x80fc) != 1) fx_result_clear_flags(p);
    if (mode == 0x88) {
        clear(p, 0x85aa, 100);
        if (get(p, 0x80fc) != 18) put(p, 0x8138, 0);
    }
    return 0;
}

int fx_setup_reset_table_expression(fx_platform *p)
{
    if (!p || !p->ram) return -1;
    if (get(p, 0x80f9) != 0x88) return 0;
    /* Bound the native terminated forward copy before persistent changes. */
    unsigned size = 0;
    while (size < 100 && get(p, (uint16_t)(0x81b8u + size))) ++size;
    if (size == 100) return -2;
    put(p, 0x80fc, 1);
    put(p, 0x80fd, 0);
    if (fx_boot_initialize_editor(p, 1) != FX_BOOT_READY) return -2;
    for (unsigned n = 0; n <= size; ++n)
        put(p, (uint16_t)(0x8154u + n), get(p, (uint16_t)(0x81b8u + n)));
    fx_mode_reset_table(p);
    return 0;
}

static fx_mode_setup_status done(fx_mode_setup *state, uint8_t result)
{
    state->result = result;
    state->phase = PHASE_COMPLETE;
    return FX_MODE_SETUP_DONE;
}

static fx_mode_setup_status start_menu(fx_platform *p, fx_mode_setup *state,
    uint8_t phase, uint8_t page, uint16_t heading)
{
    state->phase = phase;
    int status = fx_menu_navigator_begin(p, &state->menu, page, heading);
    return status == FX_MENU_WAIT ? FX_MODE_SETUP_WAIT : FX_MODE_SETUP_UNIMPLEMENTED;
}

fx_mode_setup_status fx_mode_menu_begin(fx_platform *p, fx_mode_setup *state)
{
    if (!p || !p->ram || !state) return FX_MODE_SETUP_INVALID;
    memset(state, 0, sizeof(*state));
    state->kind = KIND_MODE;
    state->active = 1;
    return start_menu(p, state, PHASE_MENU, 47, 0xffff);
}

fx_mode_setup_status fx_setup_menu_begin(fx_platform *p, fx_mode_setup *state)
{
    if (!p || !p->ram || !state) return FX_MODE_SETUP_INVALID;
    memset(state, 0, sizeof(*state));
    state->kind = KIND_SETUP;
    state->active = 1;
    if (get(p, 0x80fe) & 0x40u) return done(state, 0);
    return start_menu(p, state, PHASE_MENU, 2, 0);
}

static fx_mode_setup_status finish_mode(fx_platform *p, fx_mode_setup *state,
    uint8_t subordinate_result)
{
    if (!subordinate_result) {
        put(p, 0x80fc, 1);
        if (fx_boot_initialize_editor(p, 2) != FX_BOOT_READY)
            return FX_MODE_SETUP_UNIMPLEMENTED;
    }
    return done(state, state->mode);
}

static fx_mode_setup_status precision_wait(fx_platform *p, fx_mode_setup *state)
{
    uint16_t caption = state->option == 6 ? 0x11b2 : state->option == 7 ? 0x11bb : 0x11c4;
    uint16_t lines[4] = {caption, 0x11a1, 0x11a1, 0x11a1};
    fx_menu_paint_lines(p, lines);
    state->phase = PHASE_PRECISION;
    return fx_key_controller_begin(p, &state->keys) == FX_KEY_CONTROLLER_WAIT
        ? FX_MODE_SETUP_WAIT : FX_MODE_SETUP_UNIMPLEMENTED;
}

static fx_mode_setup_status apply_setup(fx_platform *p, fx_mode_setup *state, uint8_t choice)
{
    int status = 0;
    switch (choice) {
    case 1: case 22: case 23: case 2:
        status = fx_setup_set_layout(p, choice == 2 ? 0 : 1);
        if (!status) put(p, 0x810c, choice == 1 || choice == 22 ? 0 : 1);
        break;
    case 3: case 4: case 5: put(p, 0x8105, (uint8_t)(choice + 1u)); break;
    case 6: case 7: case 8:
        state->option = choice;
        return precision_wait(p, state);
    case 9: case 10: put(p, 0x8107, choice == 9); break;
    case 11:
        state->phase = PHASE_CONTRAST;
        if (fx_diagnostic_contrast_begin(p, &state->contrast, 0) != FX_DIAGNOSTIC_CONTRAST_WAIT)
            return FX_MODE_SETUP_UNIMPLEMENTED;
        return fx_key_controller_begin(p, &state->keys) == FX_KEY_CONTROLLER_WAIT
            ? FX_MODE_SETUP_WAIT : FX_MODE_SETUP_UNIMPLEMENTED;
    case 12: case 13: put(p, 0x8108, choice == 12); break;
    case 14: case 15:
        put(p, 0x8109, choice == 14);
        fx_mode_reset_statistics(p);
        break;
    case 16: case 17: put(p, 0x810a, choice == 16); break;
    case 18: case 19: put(p, 0x8104, choice == 18); break;
    case 24:
        return start_menu(p, state, PHASE_MENU, get(p, 0x810d) == 1 ? 10 : 9, 0);
    case 25: case 26: put(p, 0x810d, choice == 26); break;
    case 27: case 28:
        put(p, 0x810e, choice == 28);
        status = fx_setup_reset_table_expression(p);
        break;
    default:
        return done(state, 0);
    }
    return status ? FX_MODE_SETUP_UNIMPLEMENTED : done(state, 0xff);
}

fx_mode_setup_status fx_mode_setup_accept_menu(fx_platform *p,
    fx_mode_setup *state, uint8_t selection, uint8_t menu_result)
{
    if (!p || !p->ram || !state || !state->active || state->phase < PHASE_MENU ||
        state->phase > PHASE_DISTRIBUTION) return FX_MODE_SETUP_INVALID;
    state->menu.active = 0;
    if (state->kind == KIND_SETUP)
        return menu_result == 3 ? apply_setup(p, state, selection) : done(state, 0);
    if (state->phase == PHASE_MENU) {
        if (menu_result != 3 || !selection) return done(state, 0);
        state->mode = selection;
        put(p, 0x8129, 0);
        fx_boot_clear_result_workspaces(p);
        switch (selection) {
        case 3: return start_menu(p, state, PHASE_STAT, 46, 0);
        case 0x45: return start_menu(p, state, PHASE_EQUATION, 43, 0);
        case 0x4b:
            put(p, 0x8131, 0);
            state->submode = 0;
            return start_menu(p, state, PHASE_INEQUALITY, 50, 0);
        case 12:
            put(p, 0x8137, 0);
            state->submode = 1;
            return start_menu(p, state, PHASE_DISTRIBUTION, 54, 0);
        case 6: case 7:
            state->request = selection == 6 ? FX_MODE_REQUEST_MATRIX : FX_MODE_REQUEST_VECTOR;
            state->phase = PHASE_HANDLER;
            return FX_MODE_SETUP_REQUEST;
        default:
            fx_mode_set(p, selection, selection == 2 ? 9 : 0);
            return finish_mode(p, state, 0);
        }
    }
    if (state->phase == PHASE_STAT) {
        if (menu_result == 1 && selection == 0xff)
            return start_menu(p, state, PHASE_STAT, 46, 0);
        uint8_t sub = menu_result == 3 && selection >= 1 && selection <= 8 ? selection : 0;
        if (menu_result == 2) { put(p, 0x80f5, selection); sub = 1; }
        fx_mode_set(p, 3, sub);
        return finish_mode(p, state, sub);
    }
    if (state->phase == PHASE_EQUATION) {
        fx_mode_set(p, 0x45, menu_result == 3 ? selection : 0);
        return finish_mode(p, state, get(p, 0x80fa));
    }
    if (state->phase == PHASE_INEQUALITY) {
        if (menu_result == 1 && selection == 0xff) {
            state->submode = 0;
            return start_menu(p, state, PHASE_INEQUALITY, 50, 0);
        }
        if (menu_result == 3) {
            if (selection == 9 || selection == 10) {
                state->submode = selection == 9 ? 3 : 4;
                return start_menu(p, state, PHASE_INEQUALITY, selection == 9 ? 51 : 52, 0);
            }
            if (selection >= 1 && selection <= 8) {
                put(p, 0x8131, get(p, (uint16_t)(selection <= 4 ? 0x2d55u + selection : 0x2d51u + selection)));
                state->submode = selection <= 4 ? 3 : 4;
            }
        }
        fx_mode_set(p, 0x4b, state->submode);
        put(p, 0x80f5, 0);
        return finish_mode(p, state, 0xff);
    }
    if (menu_result == 1 && selection == 0xff) {
        state->submode = 1;
        return start_menu(p, state, PHASE_DISTRIBUTION, 54, 0);
    }
    if (menu_result == 3) {
        if (selection >= 1 && selection <= 3) {
            state->submode = selection;
            put(p, 0x8137, 0);
        } else if (selection >= 4 && selection <= 7) {
            state->submode = selection;
            return start_menu(p, state, PHASE_DISTRIBUTION, 56, 0);
        } else if (selection == 16 || selection == 17) put(p, 0x8137, selection == 17);
    }
    fx_mode_set(p, 12, state->submode);
    put(p, 0x80f5, 0);
    return finish_mode(p, state, 0xff);
}

fx_mode_setup_status fx_mode_setup_accept_token(fx_platform *p,
    fx_mode_setup *state, uint8_t token)
{
    if (!p || !p->ram || !state || !state->active) return FX_MODE_SETUP_INVALID;
    state->keys.active = 0;
    if (state->phase == PHASE_PRECISION) {
        unsigned low = state->option == 6 || state->option == 7 ? 0x30 : 0x31;
        unsigned high = state->option == 6 || state->option == 7 ? 0x39 : 0x32;
        if (token >= low && token <= high) {
            if (state->option == 6 || state->option == 7) {
                put(p, 0x8102, state->option == 6 ? 8 : 9);
                put(p, 0x8103, token & 15u);
            } else if (state->option == 8) put(p, 0x8102, token == 0x31 ? 0 : 4);
            return done(state, 0xff);
        }
        if (token == 0xe5 || token == 0xe6) return done(state, 0);
        return precision_wait(p, state);
    }
    if (state->phase == PHASE_CONTRAST) {
        if (fx_diagnostic_contrast_step(p, &state->contrast, token) == FX_DIAGNOSTIC_CONTRAST_DONE)
            return done(state, 0);
        return fx_key_controller_begin(p, &state->keys) == FX_KEY_CONTROLLER_WAIT
            ? FX_MODE_SETUP_WAIT : FX_MODE_SETUP_UNIMPLEMENTED;
    }
    return FX_MODE_SETUP_INVALID;
}

fx_mode_setup_status fx_mode_setup_tick(fx_platform *p, fx_mode_setup *state)
{
    if (!p || !p->ram || !state || !state->active) return FX_MODE_SETUP_INVALID;
    if (state->phase == PHASE_COMPLETE) return FX_MODE_SETUP_DONE;
    if (state->phase == PHASE_RESET) return FX_MODE_SETUP_RESET;
    if (state->phase == PHASE_HANDLER) return FX_MODE_SETUP_REQUEST;
    if (state->phase <= PHASE_DISTRIBUTION) {
        fx_menu_status status = fx_menu_navigator_tick(p, &state->menu);
        if (status == FX_MENU_DONE) {
            uint8_t selection, result;
            fx_menu_navigator_finish(&state->menu, &selection, &result);
            return fx_mode_setup_accept_menu(p, state, selection, result);
        }
        if (status == FX_MENU_RESET) state->phase = PHASE_RESET;
        return (fx_mode_setup_status)status;
    }
    fx_key_controller_status event = fx_key_controller_tick(p, &state->keys);
    if (event == FX_KEY_CONTROLLER_WAIT) return FX_MODE_SETUP_WAIT;
    if (event == FX_KEY_CONTROLLER_EXPORT) return FX_MODE_SETUP_EXPORT;
    if (event == FX_KEY_CONTROLLER_RESET) {
        fx_key_controller_finish(&state->keys, NULL);
        state->phase = PHASE_RESET;
        return FX_MODE_SETUP_RESET;
    }
    if (event != FX_KEY_CONTROLLER_TOKEN) return FX_MODE_SETUP_UNIMPLEMENTED;
    uint8_t token;
    fx_key_controller_finish(&state->keys, &token);
    return fx_mode_setup_accept_token(p, state, token);
}

fx_mode_setup_status fx_mode_setup_resume_timer(fx_platform *p, fx_mode_setup *state)
{
    if (!p || !p->ram || !state || !state->active || state->phase > PHASE_DISTRIBUTION)
        return FX_MODE_SETUP_INVALID;
    fx_menu_status status = fx_menu_navigator_resume_timer(p, &state->menu);
    if (status == FX_MENU_DONE) {
        uint8_t selection, result;
        fx_menu_navigator_finish(&state->menu, &selection, &result);
        return fx_mode_setup_accept_menu(p, state, selection, result);
    }
    return (fx_mode_setup_status)status;
}

fx_mode_setup_status fx_mode_setup_accept_handler(fx_platform *p,
    fx_mode_setup *state, uint8_t result)
{
    if (!p || !p->ram || !state || !state->active || state->phase != PHASE_HANDLER)
        return FX_MODE_SETUP_INVALID;
    state->request = FX_MODE_REQUEST_NONE;
    return finish_mode(p, state, result);
}

fx_mode_setup_status fx_mode_setup_finish(fx_mode_setup *state, uint8_t *result)
{
    if (!state || !state->active ||
        (state->phase != PHASE_COMPLETE && state->phase != PHASE_RESET))
        return FX_MODE_SETUP_INVALID;
    fx_mode_setup_status status = state->phase == PHASE_RESET ? FX_MODE_SETUP_RESET : FX_MODE_SETUP_DONE;
    if (result) *result = state->result;
    state->active = 0;
    return status;
}
