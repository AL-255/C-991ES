/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_LINALG_CONTROLLER_H
#define FX_LINALG_CONTROLLER_H
#include "fx_ui_controller.h"
#include "../render/fx_result_linalg.h"

typedef enum {
    FX_LINALG_UI_WAIT=0, FX_LINALG_UI_COMPLETE=1, FX_LINALG_UI_RESET=2,
    FX_LINALG_UI_EXPORT=3, FX_LINALG_UI_PREPARED=4,
    FX_LINALG_UI_REQUEST=5, FX_LINALG_UI_INVALID=-1,
    FX_LINALG_UI_UNIMPLEMENTED=-2
} fx_linalg_ui_status;
typedef struct {
    fx_ui_controller input;
    fx_calculus_control cancellation;
    uint16_t selected_address;
    uint8_t slot, rows, columns, returned, phase, active;
} fx_linalg_controller;

/* ECAA/ECE8 bank view, actualmode6/7 and physicalslots0..3. Positive native
 * UI dimensions/coordinates1..3 form the bounded renderer contract. Body
 * requests retain the actual nested wholeD9EE continuation in input. */
fx_linalg_ui_status fx_linalg_controller_begin(fx_platform *,
    fx_linalg_controller *, const fx_calculus_control *);
fx_linalg_ui_status fx_linalg_controller_tick(fx_platform *,
    fx_linalg_controller *);
fx_linalg_ui_status fx_linalg_controller_resume_input(fx_platform *,
    fx_linalg_controller *, uint8_t action, uint8_t context_return);
fx_linalg_ui_status fx_linalg_controller_finish(fx_linalg_controller *,
    uint8_t *returned);

/* D362 physical scalar-cell store. Five descending word reads/writes keep
 * source/destination aliases live. Native upper-bound failure is status2;
 * row/column0, CPU-frame source window8B00..8DFF and unchecked address
 * domains are explicit host gaps. */
fx_numeric_status fx_linalg_ui_store_cell(fx_platform *, uint16_t source,
    uint8_t slot, uint8_t row, uint8_t column, uint8_t *native_status);
#endif
