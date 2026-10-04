/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EQUATION_RESULT_H
#define FX_EQUATION_RESULT_H
#include "../platform/fx_platform.h"
#include "../numeric/fx_solver.h"
#include "../numeric/fx_calculus.h"
/* Bounded simultaneous-equation EXE boundary E862. The caller
 * owns coefficient entry. Only mode45, selector1/2, screen21, state0 and
 * decoded ED/F0 are admitted. Invalid host/state admission leaves storage and
 * output unchanged. Admitted singular/error/cancellation paths retain the
 * actual solver prefix banks/dimensions/MMIO and return unsupported before
 * error presentation. Cancellation is sampled after publishing each native
 * timer boundary; successful output still commits roots/history. */
int fx_equation_solve_linear(fx_platform *platform, uint8_t *action,
                             fx_solver_result *numerical);
int fx_equation_solve_linear_controlled(fx_platform *platform, uint8_t *action,
    fx_solver_result *numerical,const fx_calculus_control *control);
#endif
