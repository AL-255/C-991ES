/* Prepared native 0x1c138 quotient/remainder. GPL-3.0-or-later. */
#ifndef FX_QUOTIENT_REMAINDER_H
#define FX_QUOTIENT_REMAINDER_H
#include "fx_numeric.h"
typedef struct {
    fx_number quotient;
    fx_number remainder;
    uint8_t firmware_status;
} fx_quotient_remainder_result;
/* Inputs are copied before output writes, including partial aliases.
 * OK includes a returned native numeric error: firmware_status preserves it.
 * UNIMPLEMENTED identifies a bounded raw helper's native non-return domain
 * or unsupported surd conversion, and leaves the result untouched.
 * In the fallback, remainder is raw 70 00...00, not canonical numeric zero.
 * Early F* admission returns quotient F3 and the preprocessed divisor in the
 * second field. No parser terminal37 or persistent-bank state is included. */
fx_numeric_status fx_number_quotient_remainder(
    fx_quotient_remainder_result *result,
    const fx_number *dividend, const fx_number *divisor);
#endif
