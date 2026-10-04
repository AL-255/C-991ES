/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EVAL_H
#define FX_EVAL_H
#include <stddef.h>
#include <stdint.h>
#include "../numeric/fx_numeric.h"
#include "../numeric/fx_calculus.h"

typedef enum {
    FX_EVAL_OK = 0,
    FX_EVAL_CANCELLED = 1,
    FX_EVAL_SYNTAX = 2,
    FX_EVAL_MATH = 3,
    FX_EVAL_ARGUMENT = 8,
    FX_EVAL_UNIMPLEMENTED = -1,
    FX_EVAL_RESOURCE_LIMIT = -2
} fx_eval_status;

typedef struct {
    uint8_t calculation_context;
    uint8_t math_output;
    uint8_t angle_unit;
} fx_eval_options;

typedef struct {
    fx_number value[2];              /* real, imaginary */
    size_t consumed;
    uint8_t unsupported_token;
} fx_eval_result;

enum {
    FX_VARIABLE_M, FX_VARIABLE_ANS, FX_VARIABLE_A, FX_VARIABLE_B,
    FX_VARIABLE_C, FX_VARIABLE_D, FX_VARIABLE_E, FX_VARIABLE_F,
    FX_VARIABLE_X, FX_VARIABLE_Y, FX_VARIABLE_COUNT
};
typedef struct {
    fx_number values[FX_VARIABLE_COUNT][2]; /* immutable values until a store */
} fx_eval_variables;
void fx_eval_variables_clear(fx_eval_variables *variables);

fx_eval_options fx_eval_default_options(void);
/* Calculator INPUT tokens, not ASCII math or recursive DISPLAY tokens.
 * COMP(C1) and CMPLX(C4) share this grammar; CMPLX preserves both records.
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
/* The shared COMP parser also supports finite sums/products with local X.
 * Optional cancellation observes the native poll after X is installed;
 * global X is restored on every outcome, with native Math-off conversion. */
fx_eval_status fx_evaluate_controlled(const uint8_t *input, size_t length,
                           const fx_eval_options *options, fx_eval_variables *variables,
                           const fx_calculus_control *control, fx_eval_result *result);
#endif
