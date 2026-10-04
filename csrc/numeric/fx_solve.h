/* Prepared finite-decimal SOLVE iteration. GPL-3.0-or-later. */
#ifndef FX_SOLVE_H
#define FX_SOLVE_H
#include "fx_calculus.h"

/* Evaluate the two sides of an equation at the published local variable.
 * Return zero on success (including an F-valued variable), a positive native
 * evaluator error code on expression failure, or a negative host status.
 * The adapter must preserve SOLVE's ordinary real decimal evaluation policy.
 * Successful numeric sides use normalized packed records; malformed zero
 * mantissas carrying a nonzero exponent are outside the prepared contract.
 * A bare expression has a zero right side. */
typedef fx_numeric_status (*fx_solve_equation)(fx_number sides[2],
                                              const fx_number *variable,
                                              void *userdata);
typedef struct {
    fx_number root;
    fx_number residual;
    fx_number variable;
    uint8_t firmware_status;
    uint32_t evaluations;
    uint32_t cancellation_checks;
    uint8_t alternate_starts;
} fx_solve_result;

/* Native010000 numerical boundary, before history or display. Status0 is a
 * converged root,36 a retained finite estimate,10 Can't Solve and1 cancelled.
 * Other positive codes retain the evaluator's failure status. On a numerical
 * failure root is an F record, residual is zero and variable is restored to
 * the complete initial record after SOLVE's forced decimal surd read. Other
 * formats retain their original metadata. Host failures leave out unchanged.
 * Successful variable is the final root, with the original operation order.
 * Cancellation is sampled only at native iteration polls. Inputs may alias
 * fields in out. There is no user-supplied tolerance in this routine. */
fx_numeric_status fx_solve_root(fx_solve_result *out,
                                const fx_number *initial_variable,
                                fx_solve_equation equation, void *userdata,
                                const fx_calculus_control *control);
#endif
