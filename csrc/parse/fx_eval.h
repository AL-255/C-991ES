/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EVAL_H
#define FX_EVAL_H
#include <stddef.h>
#include <stdint.h>
#include "../numeric/fx_numeric.h"

typedef enum {
    FX_EVAL_OK = 0,
    FX_EVAL_SYNTAX = 2,
    FX_EVAL_MATH = 3,
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

fx_eval_options fx_eval_default_options(void);
/* Calculator INPUT tokens, not ASCII math or recursive DISPLAY tokens.
 * Unsupported functions return an explicit status rather than approximate
 * using host libm or falling back to original-ROM execution. */
fx_eval_status fx_evaluate(const uint8_t *input, size_t length,
                           const fx_eval_options *options, fx_eval_result *result);
#endif
