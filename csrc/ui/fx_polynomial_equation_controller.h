/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_POLYNOMIAL_EQUATION_CONTROLLER_H
#define FX_POLYNOMIAL_EQUATION_CONTROLLER_H
#include "fx_ui_controller.h"
#include "../numeric/fx_solver.h"

/* Mode45/screen21 quadratic and cubic coefficient workflow. Coefficients
 * are calculator RAM records: a/b/c at829E/82A8/82B2, d at82F8. Cubic page2
 * shows b/c/d. The controller performs one numerical solve, publishes its
 * work at the actual timer boundaries, then appends roots (and the quadratic
 * vertex) to native replay history. Key waits remain nonblocking.
 * Invalid host/state admission performs no calculator writes. Numerical
 * cancellation/error retains completed native work before the error dialog.
 * Nested coefficient INPUT needs the ordinary UI's polynomial admission and
 * commit dispatch; a caller must not manufacture a completion for that route.
 */
typedef struct {
    fx_ui_controller input;
    fx_calculus_control cancellation;
    fx_error_event error;
    fx_solver_result numerical;
    uint8_t phase, active, returned;
} fx_polynomial_equation_controller;

fx_ui_status fx_polynomial_equation_controller_begin(fx_platform *,
    fx_polynomial_equation_controller *, const fx_calculus_control *);
fx_ui_status fx_polynomial_equation_controller_tick(fx_platform *,
    fx_polynomial_equation_controller *);
fx_ui_status fx_polynomial_equation_controller_finish(
    fx_polynomial_equation_controller *, uint8_t *returned);
uint8_t fx_polynomial_equation_controller_export_mask(
    const fx_polynomial_equation_controller *);

int fx_polynomial_equation_move_selection(fx_platform *, uint8_t token);
int fx_polynomial_equation_commit_coefficient(fx_platform *, uint16_t source);
int fx_polynomial_equation_present_coefficients(fx_platform *);
/* 10F10/C236: root or quadratic vertex caption above the ordinary result.
 * Requires actual mode45/screen1. Quadratic8113 may retain its exhausted
 * replay index, provided raw-byte offset arithmetic selects one of the seven
 * original18-byte captions. Cubic caption admission remains a current replay
 * entry; an exhausted index can exceed native10F10's six-byte caption frame
 * and is not claimed by this bounded host entry. */
int fx_polynomial_equation_present_root_caption(fx_platform *);
#endif
