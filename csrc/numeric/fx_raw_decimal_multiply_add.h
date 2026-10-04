/* Finite unchecked packed-decimal arithmetic. GPL-3.0-or-later. */
#ifndef FX_RAW_DECIMAL_MULTIPLY_ADD_H
#define FX_RAW_DECIMAL_MULTIPLY_ADD_H
#include "fx_numeric.h"
/* All records use packed exponent, raw sign, then eight mantissa pairs in
 * ascending significance. Exact and partial value aliases are supported.
 * Product/sum preserve the sixteen-digit workspace before normalization.
 * Multiply/add perform its normal scalar normalization afterward. */
fx_numeric_status fx_raw_decimal_product(uint8_t out[10],
                                         const uint8_t left[10],
                                         const uint8_t right[10]);
fx_numeric_status fx_raw_decimal_multiply(uint8_t out[10],
                                          const uint8_t left[10],
                                          const uint8_t right[10]);
/* Non-decimal exponent/sign pairs can make the original magnitude ordering
 * cycle. Such proven native non-return cases return UNIMPLEMENTED and leave
 * out untouched. They must be retained as architectural-boundary evidence. */
fx_numeric_status fx_raw_decimal_sum(uint8_t out[10],
                                     const uint8_t left[10],
                                     const uint8_t right[10]);
fx_numeric_status fx_raw_decimal_add(uint8_t out[10],
                                     const uint8_t left[10],
                                     const uint8_t right[10]);
#endif
