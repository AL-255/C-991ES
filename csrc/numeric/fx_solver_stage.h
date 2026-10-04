/* Observable linear equation work at prepared timer boundaries. */
#ifndef FX_SOLVER_STAGE_H
#define FX_SOLVER_STAGE_H
#include "fx_solver.h"
typedef enum {
    FX_SOLVER_RHS_PREPARED,
    FX_SOLVER_MATRIX_INVERTING,
    FX_SOLVER_INVERSE_PREPARED,
    FX_SOLVER_MATRIX_MULTIPLYING
} fx_solver_linear_stage;
/* State includes the incremented overall cancellation_checks, physical-stride
 * work-bank payloads and their current dimensions. Zero continues; nonzero
 * cancels. The borrowed state/input cannot be changed by this hook. */
typedef int (*fx_solver_stage_callback)(const fx_solver_result *state,fx_solver_linear_stage stage,void *userdata);
/* Only LINEAR2 and LINEAR3 are admitted. Existing solve API/ABI and numerical
 * order remain unchanged. Coefficients are captured before output or callbacks.
 * Observation is synchronous and independent of timer/display mechanisms. */
fx_numeric_status fx_solver_solve_linear_observed(fx_solver_result *out,const fx_number coefficients[12],fx_solver_kind kind,const fx_solver_context *context,fx_solver_stage_callback callback,void *userdata);
#endif
