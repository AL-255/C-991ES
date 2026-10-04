/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_mode_bank_menu.h"
#include "fx_mode_setup.h"
#include "../platform/fx_persistent.h"
#include "../linalg/fx_linalg_store.h"
#include <string.h>

enum { BANK_MENU_WAIT = 1, BANK_MENU_COMPLETE = 2, BANK_MENU_RESET = 3 };

static uint8_t get(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void put(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

int fx_mode_bank_ensure_dimensions(fx_platform *p, uint8_t slot,
    uint8_t rows, uint8_t columns)
{
    if (!p || !p->ram || slot >= 9) return -1;
    uint16_t dimensions = (uint16_t)(0x80e0u + 2u*slot);
    if (get(p, dimensions) == rows && get(p, (uint16_t)(dimensions + 1u)) == columns)
        return 0;
    fx_linalg_bank bank;
    memset(&bank, 0, sizeof bank);
    bank.slots[slot].rows = get(p, dimensions);
    bank.slots[slot].columns = get(p, (uint16_t)(dimensions + 1u));
    uint16_t payload = (uint16_t)(0x829eu + 90u*slot);
    for (unsigned cell = 0; cell < 9; ++cell)
        for (unsigned n = 0; n < 10; ++n)
            bank.slots[slot].cells[cell].bytes[n] =
                get(p, (uint16_t)(payload + 10u*cell + n));
    if (fx_linalg_bank_ensure_dimensions(&bank, slot, rows, columns) != FX_NUMERIC_OK)
        return -1;
    put(p, dimensions, bank.slots[slot].rows);
    put(p, (uint16_t)(dimensions + 1u), bank.slots[slot].columns);
    for (unsigned cell = 0; cell < 9; ++cell)
        for (unsigned n = 0; n < 10; ++n)
            put(p, (uint16_t)(payload + 10u*cell + n), bank.slots[slot].cells[cell].bytes[n]);
    return 0;
}

static fx_menu_status wait_menu(fx_platform *p, fx_mode_bank_menu *state)
{
    state->phase = BANK_MENU_WAIT;
    return fx_menu_navigator_begin(p, &state->menu, state->page, state->heading);
}

fx_menu_status fx_mode_bank_menu_begin(fx_platform *p,
    fx_mode_bank_menu *state, uint8_t page, uint8_t mode_entry)
{
    if (!p || !p->ram || !state) return FX_MENU_INVALID;
    memset(state, 0, sizeof(*state));
    state->initial_page = state->page = state->action = state->return_page = page;
    state->mode_entry = mode_entry;
    state->screen = mode_entry ? (page == 44 ? 19 : 20) : (get(p, 0x80f9) == 6 ? 19 : 20);
    state->heading = mode_entry ? (page == 44 ? 0x1379 : 0x141e) : 0;
    state->active = 1;
    return wait_menu(p, state);
}

static fx_menu_status complete(fx_mode_bank_menu *state, uint8_t result)
{
    state->result = result;
    state->phase = BANK_MENU_COMPLETE;
    return FX_MENU_DONE;
}

static fx_menu_status ordinary_begin(fx_platform *p, fx_mode_bank_menu *state,
    int matrix)
{
    if (!p || !p->ram || !state) return FX_MENU_INVALID;
    if (get(p, 0x80f9) != (matrix ? 6 : 7)) {
        memset(state, 0, sizeof(*state));
        state->active = 1;
        return complete(state, 0);
    }
    int named_data = get(p, 0x80fc) == (matrix ? 19 : 20) && get(p, 0x80fa) != 3;
    uint8_t page = matrix ? (named_data ? 12 : 17) : (named_data ? 19 : 23);
    return fx_mode_bank_menu_begin(p, state, page, 0);
}

fx_menu_status fx_matrix_menu_begin(fx_platform *p, fx_mode_bank_menu *state)
{
    return ordinary_begin(p, state, 1);
}

fx_menu_status fx_vector_menu_begin(fx_platform *p, fx_mode_bank_menu *state)
{
    return ordinary_begin(p, state, 0);
}

static fx_menu_status edit_slot(fx_platform *p, fx_mode_bank_menu *state)
{
    put(p, 0x80fc, state->screen);
    put(p, 0x80fa, state->slot);
    fx_result_reset_layout_and_flags(p);
    return complete(state, 0xff);
}

static fx_menu_status cancel(fx_platform *p, fx_mode_bank_menu *state)
{
    if (state->mode_entry) fx_mode_set(p, state->screen == 19 ? 6 : 7, 0);
    put(p, 0x80f5, 0);
    return complete(state, 0);
}

fx_menu_status fx_mode_bank_menu_accept_menu(fx_platform *p,
    fx_mode_bank_menu *state, uint8_t selection, uint8_t result)
{
    if (!p || !p->ram || !state || !state->active || state->phase != BANK_MENU_WAIT)
        return FX_MENU_INVALID;
    state->menu.active = 0;
    /* The native caller discards the heading after every DFDE return. */
    state->heading = 0;
    if (result == 1) {
        if (selection == 0xff || selection == 0xfc) {
            state->heading = selection == 0xff ? 0x1379 : 0x141e;
            state->page = state->previous_page;
            return wait_menu(p, state);
        }
        if (selection == 0xfd || selection == 0xfa) {
            state->page = state->return_page;
            return wait_menu(p, state);
        }
        return cancel(p, state);
    }
    if (result == 2) {
        put(p, 0x80f5, selection);
        return complete(state, 1);
    }
    if (result != 3) return cancel(p, state);
    if (selection == 1 || selection == 2 || selection == 18 || selection == 19) {
        state->action = selection;
        state->return_page = state->page;
        state->page = selection <= 2 ? 13 : 20;
        state->heading = selection <= 2 ? 0x1379 : 0x141e;
        return wait_menu(p, state);
    }
    if ((selection >= 3 && selection <= 5) || (selection >= 20 && selection <= 22)) {
        int matrix = selection <= 5;
        static const uint16_t headings[6] = {0x1381, 0x1390, 0x139f, 0x1426, 0x1431, 0x143c};
        state->previous_page = state->page;
        state->slot = matrix ? (uint8_t)(selection - 3u) : (uint8_t)(selection - 20u);
        state->page = matrix ? 15 : 22;
        state->heading = headings[state->slot + (matrix ? 0u : 3u)];
        if (state->mode_entry) fx_mode_set(p, matrix ? 6 : 7, state->slot);
        uint16_t dimensions = (uint16_t)(0x80e0u + 2u*state->slot);
        if (state->action == (matrix ? 2 : 19) && get(p, dimensions) &&
            get(p, (uint16_t)(dimensions + 1u))) return edit_slot(p, state);
        return wait_menu(p, state);
    }
    uint16_t dimensions = 0;
    if (selection >= 9 && selection <= 17) dimensions = (uint16_t)(0x0f78u + 2u*selection);
    else if (selection == 26 || selection == 27) dimensions = (uint16_t)(0x0fb0u + 2u*selection);
    if (dimensions && fx_mode_bank_ensure_dimensions(p, state->slot,
        get(p, dimensions), get(p, (uint16_t)(dimensions + 1u)))) return FX_MENU_UNIMPLEMENTED;
    return edit_slot(p, state);
}

fx_menu_status fx_mode_bank_menu_tick(fx_platform *p, fx_mode_bank_menu *state)
{
    if (!p || !p->ram || !state || !state->active) return FX_MENU_INVALID;
    if (state->phase == BANK_MENU_COMPLETE) return FX_MENU_DONE;
    if (state->phase == BANK_MENU_RESET) return FX_MENU_RESET;
    if (state->phase != BANK_MENU_WAIT) return FX_MENU_INVALID;
    fx_menu_status status = fx_menu_navigator_tick(p, &state->menu);
    if (status == FX_MENU_DONE) {
        uint8_t selection, result;
        fx_menu_navigator_finish(&state->menu, &selection, &result);
        return fx_mode_bank_menu_accept_menu(p, state, selection, result);
    }
    if (status == FX_MENU_RESET) state->phase = BANK_MENU_RESET;
    return status;
}

fx_menu_status fx_mode_bank_menu_resume_timer(fx_platform *p, fx_mode_bank_menu *state)
{
    if (!p || !p->ram || !state || !state->active || state->phase != BANK_MENU_WAIT)
        return FX_MENU_INVALID;
    fx_menu_status status = fx_menu_navigator_resume_timer(p, &state->menu);
    if (status == FX_MENU_DONE) {
        uint8_t selection, result;
        fx_menu_navigator_finish(&state->menu, &selection, &result);
        return fx_mode_bank_menu_accept_menu(p, state, selection, result);
    }
    return status;
}

fx_menu_status fx_mode_bank_menu_finish(fx_mode_bank_menu *state, uint8_t *result)
{
    if (!state || !state->active ||
        (state->phase != BANK_MENU_COMPLETE && state->phase != BANK_MENU_RESET))
        return FX_MENU_INVALID;
    fx_menu_status status = state->phase == BANK_MENU_RESET ? FX_MENU_RESET : FX_MENU_DONE;
    if (result) *result = state->result;
    state->active = 0;
    return status;
}
