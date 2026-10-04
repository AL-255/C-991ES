/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EQUATION_CONTROLLER_H
#define FX_EQUATION_CONTROLLER_H
#include "fx_ui_controller.h"
/* Bounded mode45 linear2/3 coefficient grid and physical scalar commit.
 * Navigation is one semantic event; source/destination are calculator bus
 * addresses, never host-pointer-derived. Numerical solve is separate. */
typedef struct {
    fx_ui_controller input;
    fx_calculus_control cancellation;
    uint8_t phase, active, returned;
} fx_equation_controller;
fx_ui_status fx_equation_controller_begin(fx_platform *, fx_equation_controller *, const fx_calculus_control *);
fx_ui_status fx_equation_controller_tick(fx_platform *, fx_equation_controller *);
fx_ui_status fx_equation_controller_finish(fx_equation_controller *, uint8_t *);
int fx_equation_move_selection(fx_platform *, uint8_t token);
int fx_equation_commit_coefficient(fx_platform *, uint16_t source);
int fx_equation_present_coefficients(fx_platform *);
#endif
