/* Prepared SOLVE expression adapter. GPL-3.0-or-later. */
#ifndef FX_SOLVE_EXPRESSION_H
#define FX_SOLVE_EXPRESSION_H
#include "fx_eval.h"
#include "../numeric/fx_solve.h"

/* The caller owns tokens, variables, optional rich bank and control for the
 * whole solve. Publication changes only the selected real variable. The
 * numerical backend separately owns trial cleanup, source-error guards and
 * error-pair normalization. prior_answer is copied at initialization. */
typedef struct {
    const uint8_t *input;
    size_t length;
    fx_eval_options options;
    fx_eval_environment environment;
    fx_eval_state state;
    const fx_calculus_control *control;
    fx_number prior_answer;
    uint8_t selected_id;
    fx_eval_result last_evaluation;
    fx_eval_effects effects;
    uint32_t evaluations;
    fx_eval_storage *storage;
} fx_solve_expression;

/* Prepare COMP screenC0 with the saved Math setting unchanged. IDs0..9
 * include native numerical preparation of Ans; user-prompt eligibility is a
 * separate controller/scanner decision. A variable bank is required. */
fx_numeric_status fx_solve_expression_init(fx_solve_expression *expression,
    const uint8_t *input, size_t length, uint8_t selected_id,
    const fx_eval_options *options, const fx_eval_environment *environment,
    const fx_eval_state *state, const fx_calculus_control *control,
    const fx_number *prior_answer);

/* Attach a prepared segment-zero data view after initialization. NULL
 * restores the ordinary adapter. Storage remains caller-owned for the solve;
 * its calculation context must match the prepared COMP context. */
fx_numeric_status fx_solve_expression_set_storage(fx_solve_expression *expression,
    fx_eval_storage *storage);

/* fx_solve_equation callback: variable is already guarded and cleaned by
 * fx_solve_root. Return raw lhs/rhs, never an eagerly computed residual.
 * last_evaluation retains the prepared parser cursor and effects. */
fx_numeric_status fx_solve_expression_evaluate(fx_number sides[2],
    const fx_number *variable, void *userdata);

/* Compose the handwritten numerical kernel and expression adapter. The
 * final selected real variable follows the kernel's retained/restored record,
 * including a failed solve. This boundary does not commit Ans or history. */
fx_numeric_status fx_solve_expression_root(fx_solve_result *out,
    fx_solve_expression *expression);
#endif
