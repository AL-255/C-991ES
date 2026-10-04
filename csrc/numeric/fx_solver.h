/* Prepared equation solver kernels. GPL-3.0-or-later. */
#ifndef FX_SOLVER_H
#define FX_SOLVER_H
#include "../complex/fx_complex.h"

typedef enum {
    FX_SOLVER_LINEAR2 = 1, FX_SOLVER_LINEAR3 = 2,
    FX_SOLVER_QUADRATIC = 3, FX_SOLVER_CUBIC = 4
} fx_solver_kind;

typedef struct {
    uint8_t exact_math;
    /* Inequality mode discards nonreal polynomial roots. */
    uint8_t real_only;
    /* Zero never cancels; otherwise the numbered prepared timer check
     * returns cancellation. Physical timing remains outside this API. */
    uint32_t cancel_at;
} fx_solver_context;

typedef struct {
    fx_complex roots[3];
    uint8_t count, firmware_status;
    uint32_t cancellation_checks;
    /* Native numerical work banks 4 and 5, with physical stride three.
     * Partial contents are retained on numerical error/cancellation. */
    fx_number coefficient_work[9], root_work[9];
    uint8_t coefficient_rows, coefficient_columns, root_rows, root_columns;
} fx_solver_result;

void fx_solver_context_default(fx_solver_context *context);
/* The numerical boundary is 0x15658, before display/history callbacks.
 * LINEAR2 consumes six augmented row cells (a,b,rhs,a,b,rhs).
 * LINEAR3 consumes nine row-major matrix cells followed by three RHS cells.
 * Polynomial inputs contain three/four coefficients in descending powers.
 * All twelve input cells are copied before writing out, permitting aliases.
 */
fx_numeric_status fx_solver_solve(fx_solver_result *out,
                                 const fx_number coefficients[12],
                                 fx_solver_kind kind,
                                 const fx_solver_context *context);
/* Numerical part of the post-solver 0x8724 cleanup, independently callable. */
fx_numeric_status fx_solver_cleanup(fx_solver_result *out,
                                   const fx_solver_result *input);
/* Native0x112f6 classification after a simultaneous-solver status3:
 * 1 dependent, 2 inconsistent, 3 numerical error/nonzero determinant.
 * This preserves the original zero-pivot shortcuts and is not a generic
 * mathematical rank test. Inputs have the same layout as fx_solver_solve. */
fx_numeric_status fx_solver_classify_degenerate(uint8_t *classification,
                                               const fx_number coefficients[12],
                                               fx_solver_kind kind);
#endif
