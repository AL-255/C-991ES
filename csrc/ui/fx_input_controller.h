/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_INPUT_CONTROLLER_H
#define FX_INPUT_CONTROLLER_H
#include "fx_error_event.h"
#include "../parse/fx_eval.h"

typedef enum {
    FX_INPUT_WAIT = 0,
    FX_INPUT_COMPLETE = 1,
    FX_INPUT_RESET = 2,
    FX_INPUT_EXPORT = 3,
    FX_INPUT_PREPARED = 4,
    FX_INPUT_INVALID = -1,
    FX_INPUT_UNIMPLEMENTED = -2,
    FX_INPUT_RESOURCE_LIMIT = -3
} fx_input_status;

/* Persistent bus addresses and named policies of the outer input handler.
 * This object is owned by the host; no CPU call frame is written to RAM. */
typedef struct {
    uint16_t display_address, result_address;
    uint8_t return_value, calculation_mode, saved_math_result;
    uint8_t natural_input, natural_result, special_view;
} fx_input_context;

typedef struct {
    fx_input_context context;
    fx_error_event error;
    fx_eval_variables variables, original_variables;
    fx_number saved_result[2];
    fx_calculus_control cancellation;
    uint16_t prepared_source, current_source;
    uint8_t evaluator_status, handler_action, continuation, preparation_ok;
    uint8_t phase, active, unsupported_token;
    uint8_t input[1024];
} fx_input_controller;

/* Capture the ordinary outer handler's display policies. */
fx_input_context fx_input_context_capture(fx_platform *platform,
    uint16_t display_address, uint16_t result_address);
/* F12A input gates/preparation and old-result preservation. PREPARED is the
 * native F2AC checkpoint, before evaluation. COMPLETE covers empty/reset/
 * replay gates. Prepared COMP/CMPLX, matrix/vector modes6/7 and the linear
 * equation coefficient screen21 are admitted. Rich references commit to bank
 * Ans; scalar bank and equation edits retain their distinct physical orders. */
fx_input_status fx_input_controller_begin(fx_platform *platform,
    fx_input_controller *state, const fx_input_context *context,
    const fx_calculus_control *cancellation);
/* PREPARED evaluates once and commits success or starts the error wait.
 * Subsequent WAIT ticks resume the verified error controller. EXPORT is
 * nonterminal. RESET is a host lifecycle request. Raw key bytes are retained. */
fx_input_status fx_input_controller_tick(fx_platform *platform,
    fx_input_controller *state);
/* Consume COMPLETE/RESET. Native F12A actions are0 reset/no-op,1 editable
 * recovery,2 result redraw. The final named context is retained in state. */
fx_input_status fx_input_controller_finish(fx_input_controller *state,
    uint8_t *handler_action);
/* Ordinary EE7C expression refresh after action1/2, B070 for a result, then
 * the outer replay-navigation flag. Natural and linear rows are supported.
 * Does not consume the controller completion. */
fx_input_status fx_input_controller_present(fx_platform *platform,
    fx_input_controller *state);
#endif
