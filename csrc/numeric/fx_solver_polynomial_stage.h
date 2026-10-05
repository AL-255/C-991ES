/* Prepared polynomial equation work at the original timer boundaries. */
#ifndef FX_SOLVER_POLYNOMIAL_STAGE_H
#define FX_SOLVER_POLYNOMIAL_STAGE_H
#include "fx_solver.h"
typedef enum {
    FX_SOLVER_POLYNOMIAL_COEFFICIENTS_PREPARED,
    FX_SOLVER_POLYNOMIAL_NORMALIZED,
    FX_SOLVER_POLYNOMIAL_FORMULA_PREPARED
} fx_solver_polynomial_stage;
/* Borrowed work is current, before the corresponding timer read. Its check
 * count is already incremented. The callback may observe but not modify it;
 * nonzero requests the native cancellation result. */
typedef int (*fx_solver_polynomial_callback)(const fx_solver_result *,
    fx_solver_polynomial_stage, void *);
/* QUADRATIC/CUBIC only. One arithmetic pass; old solve ABI is preserved.
 * A zero constant's shortcut can finish after only the first two checks. */
fx_numeric_status fx_solver_solve_polynomial_observed(fx_solver_result *,
    const fx_number coefficients[12], fx_solver_kind,
    const fx_solver_context *, fx_solver_polynomial_callback, void *);
/* Optional scalar mathematical preparation runs where the formula actually
 * classifies/converts/roots/combines its named operands. NULL is value-only.
 * It may publish a prepared data pool; no CPU or finished-state snapshot is
 * supplied. Ordinary timers remain the independent stage callback above. */
fx_numeric_status fx_solver_solve_polynomial_prepared(fx_solver_result *,
    const fx_number coefficients[12], fx_solver_kind,
    const fx_solver_context *, fx_solver_polynomial_callback, void *,
    const fx_complex_preparation *);
#endif
