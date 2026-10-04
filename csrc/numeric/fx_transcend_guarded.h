/* Prepared finite-coordinate base-ten exponential. GPL-3.0-or-later. */
#ifndef FX_TRANSCEND_GUARDED_H
#define FX_TRANSCEND_GUARDED_H
#include "fx_numeric.h"

/* The argument is sign * coordinate *10^(exponent-16), after the original
 * coefficient product and packed-coefficient correction. Its live coordinate
 * may contain up to eighteen decimal digits; do not renormalize it. This
 * prepared boundary retains the two guard digits before final serialization.
 * Require coordinate<10^18, exponent[-99,1], and sign +1 or-1. Zero coordinate
 * gives1. Other arguments return INVALID without writing out. The kernel's
 * numerical overflow is F3; negative underflow is canonical zero. */
fx_numeric_status fx_transcend_exp10_guarded(fx_number *out,
                                             uint64_t coordinate,
                                             int exponent, int sign);
#endif
