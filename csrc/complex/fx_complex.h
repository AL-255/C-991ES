/* Complex numeric records and finite-decimal arithmetic. GPL-3.0-or-later. */
#ifndef FX_COMPLEX_H
#define FX_COMPLEX_H
#include "../numeric/fx_numeric.h"

/* The firmware stores two consecutive ten-byte scalar records: real first. */
typedef struct { fx_number real, imaginary; } fx_complex;

typedef enum {
    FX_COMPLEX_ARITHMETIC_RETURN,
    FX_COMPLEX_CONJUGATE_RETURN,
    FX_COMPLEX_NEGATE_RETURN,
    FX_COMPLEX_CLEANUP_RETURN,
    FX_COMPLEX_MAGNITUDE_RETURN,
    FX_COMPLEX_SQRT_RETURN,
    FX_COMPLEX_ARGUMENT_RETURN,
    FX_COMPLEX_TO_POLAR_RETURN,
    FX_COMPLEX_FROM_POLAR_RETURN
} fx_complex_return_kind;

/* The handled arithmetic routines return FX_NUMERIC_OK even when their
 * numerical result is an error record. Read its numerical error with the
 * separate predicate. Sources remain immutable and either may alias out. */
/* Read the first numerical error, examining real before imaginary. This is
 * the record error predicate, not every routine's native register return. */
unsigned fx_complex_error_status(const fx_complex *value);
/* Native CCF6 scalar admission/sign classification: 1 zero, 2 negative,
 * 4 positive, F0 domain. Compact surds retain their special classification
 * even when opposite terms convert to decimal zero. Source is immutable. */
fx_numeric_status fx_scalar_numeric_classify(uint8_t *classification,
                                             const fx_number *input);
/* Recover a prepared native R0 numerical return after a successful value API
 * call. input must be the original record before an output alias overwrites
 * it. Canonical scalar records and the documented prepared contexts are
 * required; this does not reproduce register or scratch-memory side effects. */
fx_numeric_status fx_complex_firmware_status(uint8_t *firmware_status,
                                             fx_complex_return_kind kind,
                                             const fx_complex *input,
                                             const fx_complex *result);
void fx_complex_zero(fx_complex *out);
fx_numeric_status fx_complex_binary(fx_complex *out, const fx_complex *a,
                                    const fx_complex *b, fx_binary_op operation);
fx_numeric_status fx_complex_conjugate(fx_complex *out, const fx_complex *in);
fx_numeric_status fx_complex_negate(fx_complex *out, const fx_complex *in);
/* Native complex powers admit reciprocal, square and cube only. */
fx_numeric_status fx_complex_integer_power(fx_complex *out, const fx_complex *in,
                                           int exponent);
/* Complete restricted native complex-power selector186A8. Other exponent
 * records produce the native F3 numerical result. */
fx_numeric_status fx_complex_power(fx_complex *out, const fx_complex *base,
                                   const fx_complex *exponent);
fx_numeric_status fx_complex_cleanup(fx_complex *out, const fx_complex *in);
/* Magnitude1CADE; exact_math is the already resolved18212 output permission.
 * Normal outputs clear the imaginary component. Its early malformed/error
 * guard replaces only the real component, matching the original entry. */
fx_numeric_status fx_complex_magnitude(fx_complex *out, const fx_complex *in,
                                       int exact_math);
/* Optional mathematical square-root policy for a prepared data workspace.
 * It executes at the actual root step, after ordered magnitude arithmetic.
 * NULL preserves the ordinary value-only API. No CPU state is supplied. */
typedef fx_numeric_status (*fx_complex_square_root)(fx_number *out,
    const fx_number *input, int exact_math, void *userdata);
fx_numeric_status fx_complex_magnitude_prepared(fx_complex *out,
    const fx_complex *in, int exact_math, fx_complex_square_root root,
    void *userdata);
/* Native1CBFC permits a zero imaginary input only. Negative real inputs
 * produce a positive imaginary root; compact real surds are made decimal
 * before rooting. Admission errors preserve the input imaginary record. */
fx_numeric_status fx_complex_sqrt(fx_complex *out, const fx_complex *in,
                                  int exact_math);
#endif
