/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_SOLVE_CONTROLLER_H
#define FX_SOLVE_CONTROLLER_H
#include "fx_input_controller.h"
#include "../numeric/fx_solve.h"

typedef enum {
    FX_SOLVE_UI_WAIT = 0,
    FX_SOLVE_UI_PROMPT = 1,
    FX_SOLVE_UI_PREPARED = 2,
    FX_SOLVE_UI_COMPLETE = 3,
    FX_SOLVE_UI_ERROR = 4,
    FX_SOLVE_UI_RESET = 5,
    FX_SOLVE_UI_EXPORT = 6,
    FX_SOLVE_UI_INPUT = 7,
    FX_SOLVE_UI_DECLINED = 8,
    FX_SOLVE_UI_INVALID = -1,
    FX_SOLVE_UI_UNIMPLEMENTED = -2,
    FX_SOLVE_UI_RESOURCE_LIMIT = -3
} fx_solve_ui_status;

typedef enum {
    FX_SOLVE_UI_VARIABLES = 1,
    FX_SOLVE_UI_EVALUATE,
    FX_SOLVE_UI_ERROR_PENDING,
    FX_SOLVE_UI_ERROR_WAIT,
    FX_SOLVE_UI_DONE,
    FX_SOLVE_UI_RESET_PENDING
} fx_solve_ui_phase;

typedef struct {
    uint8_t equation_used, restricted_state;
} fx_solve_expression_effects;

/* The expression boundary returns both unequated sides and the native input
 * cursor. It must not replace the expression by lhs-rhs or decimalize every
 * side. A NULL function selects the shared prepared evaluator. Supplying a
 * function is useful for hosts with their own expression storage. It observes
 * the same variable bank, PreAns and globals as the native171F4 callback.
 * Ordinary real-variable changes are committed through522A; C1 stores
 * preserve the imaginary bank. An external adapter needing additional physical
 * bus writes must publish them through its own platform userdata. The two named
 * effects expose8125 and8124 without inspecting a CPU workspace. */
typedef fx_eval_status (*fx_solve_expression_callback)(const uint8_t *input, size_t length,
    const fx_eval_options *options, const fx_eval_environment *environment,
    fx_eval_variables *variables, const fx_calculus_control *control,
    const fx_number *initial_secondary, const fx_number *prior_answer,
    fx_eval_result *result, fx_solve_expression_effects *effects, void *userdata);

typedef struct {
    fx_input_context context;
    fx_error_event error;
    fx_eval_variables variables;
    fx_number saved_result[2];
    fx_solve_result numerical;
    fx_calculus_control cancellation;
    fx_solve_expression_callback expression;
    void *expression_userdata;
    uint16_t prepared_source, current_source;
    uint8_t phase, active, evaluator_status, handler_action;
    uint8_t prompt_id, scanner_error, preparation_ok, unsupported_token;
    uint8_t input[1024];
    size_t input_length;
} fx_solve_controller;

/*172F6's SOLVE branch. It initializes83FE's ten-byte FF list, collects unique
 * ordinary variables, validates a terminal selected-variable suffix, and moves
 * the selected variable last. It is deliberately not a syntax checker. The
 * source is an INPUT stream, normally8398. Return0,2 or12 as native, or a
 * negative bounded-host error. It requires screen80FC.bit6. */
int fx_solve_scan_variables(fx_platform *platform, uint16_t source);

/* DE1C entered from an ordinary C1 equation. Guards decline empty input,
 * continuation and an existing value prompt without changing persistent RAM.
 * Accepted entry ends before DCA4. The host retains the complete named state;
 * no original CPU frame or register is stored in RAM. */
fx_solve_ui_status fx_solve_controller_enter(fx_platform *platform,
    fx_solve_controller *state, fx_solve_expression_callback expression, void *userdata,
    const fx_calculus_control *cancellation);
/* DCA4: scan/start a list, accept an unchanged FE4 prompt when keyF0/ED,
 * prepare the next coefficient/guess prompt, or restore the saved equation
 * and synthesize ED after the list ends. PROMPT includes presentation. */
fx_solve_ui_status fx_solve_controller_advance(fx_platform *platform,
    fx_solve_controller *state);
/* D9EE's coefficient editor boundary. Data/menu tokens and direction/delete
 * tokens use the shared editor. EXE is handled separately below. */
fx_solve_ui_status fx_solve_controller_edit(fx_platform *platform,
    fx_solve_controller *state, uint8_t token);
/* Typed EXE evaluates once and writes83FE[83FD], without Ans/history changes.
 * An unchanged prompt instead calls the next advance, preserving its bank
 * record and presenting the next cell. After typed acceptance, a separate
 * advance presents the next cell. */
fx_solve_ui_status fx_solve_controller_accept(fx_platform *platform,
    fx_solve_controller *state);
/* Prepared F12A boundary for an already selected screenC0/item4 equation.
 * This bypasses prompts and captures a fresh descriptor (special_view=0).
 * PREPARED ends before the numerical solve and preserves the old result.
 * Empty display input is DECLINED before any persistent or controller-state
 * mutation, matching F12A's early return before its preparation call. */
fx_solve_ui_status fx_solve_controller_prepare(fx_platform *platform,
    fx_solve_controller *state, fx_solve_expression_callback expression, void *userdata,
    const fx_calculus_control *cancellation);
/* PREPARED performs the bounded numeric call, variable/result commits, and
 * returns COMPLETE or ERROR before the error banner. A following ERROR tick
 * starts/resumes the existing nonblocking error controller. A negative host
 * evaluator status stops the numerical call and restores its initial selected
 * variable; other explicit stores made by that host callback remain visible.
 * Physical timing
 * and final root/residual presentation are owned by the enclosing host. */
fx_solve_ui_status fx_solve_controller_tick(fx_platform *platform,
    fx_solve_controller *state);
fx_solve_ui_status fx_solve_controller_finish(fx_solve_controller *state,
    uint8_t *handler_action);
#endif
