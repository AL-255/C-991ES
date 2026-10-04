/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_UI_CONTROLLER_H
#define FX_UI_CONTROLLER_H
#include "fx_input_controller.h"
#include "../table/fx_table_controller.h"

typedef enum {
    FX_UI_WAIT = 0, FX_UI_COMPLETE = 1, FX_UI_RESET = 2,
    FX_UI_EXPORT = 3, FX_UI_PREPARED = 4, FX_UI_HANDLER_REQUEST = 5,
    FX_UI_INVALID = -1, FX_UI_UNIMPLEMENTED = -2, FX_UI_RESOURCE_LIMIT = -3
} fx_ui_status;

/* These requests identify semantic subordinate operations, never CPU PCs. */
typedef enum {
    FX_UI_REQUEST_NONE = 0, FX_UI_REQUEST_SPECIAL_CONTEXT,
    FX_UI_REQUEST_RESULT_FORMAT, FX_UI_REQUEST_BASE_RESULT,
    FX_UI_REQUEST_COMPLEX_ADMISSION
} fx_ui_request_kind;

typedef struct {
    fx_input_context context;
    fx_input_controller input;
    fx_calculus_control cancellation;
    fx_ui_request_kind request;
    uint8_t phase, active, refresh_only, structured_input;
    uint8_t command_token, command_index, handler_action, saved_result_state;
    fx_table_controller table;
} fx_ui_controller;

/* D9EE normalization, font and named context preparation through DA58.
 * refresh_only is the original public nonzero argument. The ordinary entry
 * receives a mapped token in80F5; scanning/menu selection are caller-owned. */
fx_ui_status fx_ui_controller_begin(fx_platform *platform,
    fx_ui_controller *state, uint8_t refresh_only,
    const fx_calculus_control *cancellation);
/* Execute one prepared action, or resume an input/error transaction.
 * PREPARED requests another immediate semantic tick. WAIT requires host input.
 * EXPORT retains the wait. RESET requests host boot. HANDLER_REQUEST exposes
 * a subordinate operation whose implementation remains outside this module. */
fx_ui_status fx_ui_controller_tick(fx_platform *platform, fx_ui_controller *state);
/* Resume a requested subordinate handler with its native semantic action
 *0 no redraw,1 edit redraw,2 result redraw,3 result-only redraw, and its named
 * context return. This does not execute a ROM callback or CPU instruction. */
fx_ui_status fx_ui_controller_resume(fx_platform *platform,
    fx_ui_controller *state, uint8_t action, uint8_t context_return);
/* Consume completion/reset and expose the original D9EE context byte4. */
fx_ui_status fx_ui_controller_finish(fx_ui_controller *state,
    uint8_t *context_return);
/* Active retained wait exporter, including TABLE errors. */
uint8_t fx_ui_controller_export_mask(const fx_ui_controller *state);
#endif
