/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_TOKENS_H
#define FX_TOKENS_H
#include <stdint.h>

/* Input-token grammar is distinct from the recursive display-token grammar. */
typedef struct {
    uint8_t value;
    uint8_t kind;
} fx_evaluator_token;

fx_evaluator_token fx_decode_evaluator_token(uint8_t token, uint8_t calculation_context);
uint8_t fx_classify_display_token(uint8_t token);
uint8_t fx_classify_construct_token(uint8_t token);
#endif
