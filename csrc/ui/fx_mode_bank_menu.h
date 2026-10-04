/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_MODE_BANK_MENU_H
#define FX_MODE_BANK_MENU_H
#include "fx_menu_navigator.h"

/* Named D0CC locals. mode_entry is its caller flagR1, not a CPU register
 * retained by this object. All display/storage fields remain observable RAM. */
typedef struct {
    fx_menu_navigator menu;
    uint16_t heading;
    uint8_t initial_page;
    uint8_t page;
    uint8_t action;
    uint8_t previous_page;
    uint8_t return_page;
    uint8_t slot;
    uint8_t screen;
    uint8_t mode_entry;
    uint8_t result;
    uint8_t phase;
    uint8_t active;
} fx_mode_bank_menu;

/* MODE supplies page44/45 and mode_entry1; ordinary MATRIX/VECTOR parameter
 * callers supply their actual data-table page and mode_entry0. */
fx_menu_status fx_mode_bank_menu_begin(fx_platform *platform,
    fx_mode_bank_menu *state, uint8_t page, uint8_t mode_entry);
/* D074/D0A0 ordinary parameter gates; a different mode completes with0. */
fx_menu_status fx_matrix_menu_begin(fx_platform *platform, fx_mode_bank_menu *state);
fx_menu_status fx_vector_menu_begin(fx_platform *platform, fx_mode_bank_menu *state);
fx_menu_status fx_mode_bank_menu_tick(fx_platform *platform, fx_mode_bank_menu *state);
fx_menu_status fx_mode_bank_menu_resume_timer(fx_platform *platform, fx_mode_bank_menu *state);
/* Prepared D2A0 adapter after DFDE returns its host selection/result pair. */
fx_menu_status fx_mode_bank_menu_accept_menu(fx_platform *platform,
    fx_mode_bank_menu *state, uint8_t selection, uint8_t result);
fx_menu_status fx_mode_bank_menu_finish(fx_mode_bank_menu *state, uint8_t *result);
/* Supplied dimension fields of00D2D8. The frozen high-level linalg bank API
 * decides preservation versus clearing all nine cells; no numeric conversion
 * or fabricated CPU operand pointer is involved. */
int fx_mode_bank_ensure_dimensions(fx_platform *platform, uint8_t slot,
    uint8_t rows, uint8_t columns);
#endif
