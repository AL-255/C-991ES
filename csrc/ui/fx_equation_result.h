/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EQUATION_RESULT_H
#define FX_EQUATION_RESULT_H
#include "../platform/fx_platform.h"
#include "../numeric/fx_solver.h"
/* Prepared successful simultaneous-equation EXE boundary E862. The caller
 * owns coefficient entry. Only mode45, selector1/2, screen21, state0 and
 * decoded ED/F0 are admitted. Singular/error/cancellation return an explicit
 * unsupported result without committing calculator storage. */
int fx_equation_solve_linear(fx_platform *platform, uint8_t *action,
                             fx_solver_result *numerical);
#endif
