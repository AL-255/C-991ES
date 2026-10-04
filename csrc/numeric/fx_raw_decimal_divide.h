/* Unchecked packed decimal quotient used by rich-reference conversion.
 * Records use native decimal coordinates: exponent, sign, eight mantissa
 * pairs from least to most significant. GPL-3.0-or-later. */
#ifndef FX_RAW_DECIMAL_DIVIDE_H
#define FX_RAW_DECIMAL_DIVIDE_H
#include "fx_numeric.h"
fx_numeric_status fx_raw_decimal_quotient(uint8_t out[10],
                                         const uint8_t left[10],
                                         const uint8_t right[10]);
fx_numeric_status fx_raw_decimal_divide(uint8_t out[10],
                                       const uint8_t left[10],
                                       const uint8_t right[10]);
#endif
