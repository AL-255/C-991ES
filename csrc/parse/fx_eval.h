/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EVAL_H
#define FX_EVAL_H
#include <stddef.h>
#include <stdint.h>
#include "../numeric/fx_numeric.h"
#include "../numeric/fx_calculus.h"
#include "../numeric/fx_base.h"
#include "../linalg/fx_linalg_store.h"
#include "fx_eval_storage.h"

typedef enum {
    FX_EVAL_OK = 0,
    FX_EVAL_CANCELLED = 1,
    FX_EVAL_SYNTAX = 2,
    FX_EVAL_MATH = 3,
    FX_EVAL_STACK = 7,
    FX_EVAL_ARGUMENT = 8,
    FX_EVAL_CONVERGENCE = 11,
    FX_EVAL_POLAR_PAIR = 34,
    FX_EVAL_RECTANGULAR_PAIR = 35,
    FX_EVAL_QUOTIENT_PAIR = 37,
    FX_EVAL_UNIMPLEMENTED = -1,
    FX_EVAL_RESOURCE_LIMIT = -2
} fx_eval_status;

typedef struct {
    uint8_t calculation_context;
    uint8_t math_output;
    uint8_t angle_unit;
} fx_eval_options;

/* Native evaluator globals omitted by the ordinary prepared entry points.
 * Math remains the global8106 byte in options; exact-output permission is
 * resolved separately from these fields by18212. selected_base is the80FA
 * mask. Keeping this separate preserves the original three-byte options ABI. */
typedef struct {
    uint8_t screen, prior_operation, complex_format, restricted_state;
    uint8_t display_mode, digits, selected_base;
} fx_eval_environment;

/* Observable evaluator policy globals, separate from numeric result/status.
 *171F4 starts equation_used at0; an admitted '=' sets it before any pending
 * arithmetic reduction. The storage entry reports the final shared8125.bit0;
 * releasing a wrapped rich identity can clear that bit. Every native return
 * clears restricted_state.bit0. */
typedef struct {
    uint8_t equation_used;
    uint8_t restricted_state;
} fx_eval_effects;

typedef struct {
    fx_number value[2];              /* real/imaginary, or the native result pair */
    size_t consumed;
    uint8_t unsupported_token;
} fx_eval_result;

enum {
    FX_VARIABLE_M, FX_VARIABLE_ANS, FX_VARIABLE_A, FX_VARIABLE_B,
    FX_VARIABLE_C, FX_VARIABLE_D, FX_VARIABLE_E, FX_VARIABLE_F,
    FX_VARIABLE_X, FX_VARIABLE_Y, FX_VARIABLE_COUNT
};
typedef struct {
    fx_number values[FX_VARIABLE_COUNT][2]; /* logical real/imaginary records */
} fx_eval_variables;
void fx_eval_variables_clear(fx_eval_variables *variables);

/* Separate typed storage preserves the ordinary variable-bank ABI. In the
 * ordinary typed entry points, NULL
 * members select fresh zero banks for this evaluation. Matrix/vector cells
 * can change during the native expression-finish cleanup, even if the
 * returned reference becomes an error. */
typedef struct {
    fx_eval_variables *variables;
    fx_linalg_bank *linear_algebra;
} fx_eval_state;

fx_eval_options fx_eval_default_options(void);
fx_eval_environment fx_eval_default_environment(void);
/* Calculator INPUT tokens, not ASCII math or recursive DISPLAY tokens.
 * COMP(C1), CMPLX(C4) and BASE-N(2) share this grammar. CMPLX preserves both
 * records; the ordinary entry points select DEC and zero secondary for BASE-N.
 * Unsupported functions return an explicit status rather than approximate
 * using host libm or falling back to original-ROM execution. */
fx_eval_status fx_evaluate(const uint8_t *input, size_t length,
                           const fx_eval_options *options, fx_eval_result *result);
/* Prepared ordinary COMP/CMPLX variable bank (native screen80FC=1), without
 * bus or CPU-frame aliases.
 * Decimal, rational and compact-surd scalar records are supported. Terminal
 * stores commit only after syntax/admission succeeds; M+/M- return the input
 * expression value while updating M. NULL variables uses a fresh zero bank.
 * Variables and result must occupy separate host storage. */
fx_eval_status fx_evaluate_with_variables(const uint8_t *input, size_t length,
                           const fx_eval_options *options, fx_eval_variables *variables,
                           fx_eval_result *result);
/* The shared COMP parser supports sums/products, adaptive integrals and
 * Richardson derivatives with local X and default/explicit tolerances.
 * Optional cancellation observes native polling and the current sample X;
 * global X is restored on every outcome, with native Math-off conversion. */
fx_eval_status fx_evaluate_controlled(const uint8_t *input, size_t length,
                           const fx_eval_options *options, fx_eval_variables *variables,
                           const fx_calculus_control *control, fx_eval_result *result);
/* Prepared COMP continuous-calculus callbacks admit stored matrix/vector
 * references and perform1415A cleanup against the supplied bank. Arithmetic
 * on rich references requires the physical-storage entry point below, which
 * composes the prepared rich dispatcher after physical operand staging.
 * State, input and result must occupy separate host storage. */
fx_eval_status fx_evaluate_with_state(const uint8_t *input, size_t length,
                           const fx_eval_options *options, const fx_eval_state *state,
                           const fx_calculus_control *control, fx_eval_result *result);
/* Prepared shared grammar with explicit evaluator globals. The supported
 * calculation contexts are those of fx_evaluate. A screen with bit6 set
 * enables SOLVE's equation grammar: one admitted '=' exports separate raw
 * lhs/rhs records; a bare expression exports RHS0. A terminal comma-variable
 * suffix is admitted by the shared grammar. The outer SOLVE controller is
 * separate. NULL environment selects screen1,
 * ordinary operation/complex format, unrestricted state, Norm1 and DEC. */
fx_eval_status fx_evaluate_prepared(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment,
                           const fx_eval_state *state,
                           const fx_calculus_control *control,
                           const fx_number *initial_secondary, fx_eval_result *result);
/* Prepared evaluator with optional policy observations and the separate
 * PreAns input. Existing options/state/result ABIs are unchanged. Sides keep
 * their actual native rational/decimal records; this does not calculate a
 * residual or globally decimalize both sides. On a native failure only the
 * primary error record replaces caller output; initial_secondary is retained.
 * effects may be NULL. Prior answer, state, result and effects must use
 * separate host storage. */
fx_eval_status fx_evaluate_prepared_observed(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment,
                           const fx_eval_state *state,
                           const fx_calculus_control *control,
                           const fx_number *initial_secondary,
                           const fx_number *prior_answer,
                           fx_eval_effects *effects, fx_eval_result *result);

/* Prepared evaluator with the complete segment-zero data view. Working
 * records and state containers occupy separate host storage. Supplied
 * variables are the current logical bank, including a published SOLVE trial;
 * NULL variables loads the physical banks at8226 and8408. Temporary-object
 * copies use the provided RAM and can change both banks in every mode.
 * NULL options/environment captures their native globals from RAM. Explicit
 * options must use the same calculation context as RAM80F9. NULL PreAns
 * reads828A. Caller output/CPU-frame aliases are outside this named API. */
fx_eval_status fx_evaluate_prepared_with_storage(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment,
                           const fx_eval_state *state,
                           const fx_calculus_control *control,
                           const fx_number *initial_secondary,
                           const fx_number *prior_answer,
                           fx_eval_storage *storage,
                           fx_eval_effects *effects, fx_eval_result *result);
/* COMP's context override for rawC8 loads variable ID10, the separately
 * stored PreAns record at828A. NULL selects a fresh zero PreAns. This additive
 * entry keeps the ten ordinary variable pairs and both existing ABIs intact.
 * PreAns is copied before evaluation and is not a store destination here. */
fx_eval_status fx_evaluate_prepared_with_prior_answer(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment,
                           const fx_eval_state *state,
                           const fx_calculus_control *control,
                           const fx_number *initial_secondary,
                           const fx_number *prior_answer, fx_eval_result *result);
/* Prepared BASE-N screen (80F9=2,80FC=1). selected_base is the native 80FA
 * mask, not a radix number. Shared grammar admits exact fractions and real
 * functions; stored variables are converted/truncated on load. The native
 * evaluator writes only the real output in this mode, so initial_secondary
 * explicitly supplies the caller's retained second record; NULL selects zero.
 * The ordinary entry points select DEC for context2 and a zero secondary.
 * Initial secondary, input, variable bank and result must not overlap. */
fx_eval_status fx_evaluate_base_n(const uint8_t *input, size_t length,
                           uint8_t selected_base, const fx_eval_options *options,
                           fx_eval_variables *variables,
                           const fx_number *initial_secondary, fx_eval_result *result);
/* Explicit session seed. The seed is published eagerly at
 * every draw, including draws preceding a later expression error. NULL uses
 * a fresh zero seed for this complete evaluation. Storage entry points share
 * the physical RAM821C seed instead; existing public struct ABIs are unchanged. */
fx_eval_status fx_evaluate_prepared_random(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment,
                           const fx_eval_state *state,
                           const fx_calculus_control *control,
                           const fx_number *initial_secondary,
                           const fx_number *prior_answer, fx_number *seed,
                           fx_eval_effects *effects, fx_eval_result *result);
#endif
