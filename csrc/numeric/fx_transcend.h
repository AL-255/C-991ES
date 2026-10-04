/* Decimal transcendental kernels for fx-991ES PLUS C. GPL-3.0-or-later. */
#ifndef FX_TRANSCEND_H
#define FX_TRANSCEND_H
#include "fx_numeric.h"

/* Real logarithms, including native rational/surd decimal conversion.
 * Domain errors are F3 numeric records; unsupported input formats return an
 * explicit status. All arithmetic uses decimal integer coordinates. */
fx_numeric_status fx_number_ln(fx_number *out, const fx_number *in);
fx_numeric_status fx_number_log10(fx_number *out, const fx_number *in);
/* Exponential kernels return the native result before evaluator cleanup. */
fx_numeric_status fx_number_exp(fx_number *out, const fx_number *in);
fx_numeric_status fx_number_exp10(fx_number *out, const fx_number *in);
/* Real evaluator power dispatch, including the exact rational integer path
 * and odd-denominator handling for negative bases. */
fx_numeric_status fx_number_power(fx_number *out, const fx_number *base,
                                  const fx_number *exponent);

#endif
