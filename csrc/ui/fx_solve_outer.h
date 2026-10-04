/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_SOLVE_OUTER_H
#define FX_SOLVE_OUTER_H
#include "platform/fx_main_loop.h"
#include "ui/fx_solve_controller.h"
#include "ui/fx_ui_controller.h"

typedef enum {
    FX_SOLVE_OUTER_COMPLETE = 1,
    FX_SOLVE_OUTER_WAIT = 0,
    FX_SOLVE_OUTER_CALC_PENDING = 2,
    FX_SOLVE_OUTER_RESET = 3,
    FX_SOLVE_OUTER_EXPORT = 4,
    FX_SOLVE_OUTER_INVALID = -1,
    FX_SOLVE_OUTER_UNIMPLEMENTED = -2,
    FX_SOLVE_OUTER_RESOURCE_LIMIT = -3
} fx_solve_outer_status;

typedef struct {
    fx_solve_controller solve;
    fx_ui_controller ui;
    fx_solve_expression_callback expression;
    void *expression_userdata;
    fx_calculus_control cancellation;
    uint8_t handler_action, context_return, active, pending_owner;
    fx_error_event scanner_error;
    uint8_t scanner_error_pending;
} fx_solve_outer;

/* Host ownership only; does not repeat main's selection or mutate RAM. */
void fx_solve_outer_begin(fx_solve_outer *state,
    fx_solve_expression_callback expression, void *userdata,
    const fx_calculus_control *cancellation);
/* Adopt main's already-selected C0 variables transaction, without DE1C.
 * This also permits a host attaching at a prepared prompt/result checkpoint.
 * An owned evaluator/error/reset transaction must be resumed, not adopted. */
fx_solve_outer_status fx_solve_outer_adopt(fx_platform *platform,
    fx_solve_outer *state);
/* DCA4 C0/item4 or A0/item3: restore81B8 and return0. Only item4
 * synthesizesED. Evaluation is deferred until the following INPUT request. */
fx_solve_outer_status fx_solve_outer_restore(fx_platform *platform,
    fx_solve_outer *state);
/* One pending main INPUT or SCREEN_A0_C0 request. Completion retains
 * evaluator action and D9EE/screen return separately. CALC uses ordinary
 * evaluation; no SOLVE numerical call runs for A0. WAIT owns a retained error
 * transaction. RESET is retained; EXPORT returns after completed packets,
 * before the next wait begins. A following dispatch resumes that wait. */
fx_solve_outer_status fx_solve_outer_dispatch(fx_platform *platform,
    fx_solve_outer *state, fx_main_request request, uint8_t refresh_only);
/*51CA supplied variable pair load, preserving the exact-output and C4 policy. */
fx_solve_outer_status fx_solve_outer_load_variable(fx_platform *platform,
    uint8_t id, uint16_t destination);
#endif
