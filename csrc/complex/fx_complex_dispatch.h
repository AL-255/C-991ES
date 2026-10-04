/* CMPLX evaluator value dispatch; no token parsing. GPL-3.0-or-later. */
#ifndef FX_COMPLEX_DISPATCH_H
#define FX_COMPLEX_DISPATCH_H
#include "fx_complex.h"

/* exact_math is the already resolved18212 permission. Other fields use the
 * native bytes80F9/8105/8102/8103, permitting a direct evaluator adapter. */
typedef struct {
    uint8_t calculation_context, exact_math, angle_unit, display_mode, digits;
} fx_complex_dispatch_context;
fx_complex_dispatch_context fx_complex_dispatch_default_context(void);

/* Successful host handling returns OK even for native numerical errors.
 * firmware_status is the native evaluator R2, not an error-record predicate.
 * Sources are immutable and either may alias out. CMPLX contextC4 is required
 * for token dispatch; unsupported tokens return UNIMPLEMENTED. This is the prepared
 * value stage: preceding163F0 rich-record rewriting and parser/workspace side effects are excluded. Each handled
 * operation includes the native16562 post-leaf context cleanup. */
fx_numeric_status fx_complex_dispatch_constant(fx_complex *out, uint8_t token,
    const fx_complex_dispatch_context *context, uint8_t *firmware_status);
fx_numeric_status fx_complex_dispatch_unary(fx_complex *out, const fx_complex *in,
    uint8_t token, const fx_complex_dispatch_context *context,
    uint8_t *firmware_status);
/* Binary tokens:2B/2D/4E/4F/5E arithmetic/power,9F degree-first root,
 * BE/BF permutation/combination,68 base-first logarithm. Real-only functions
 * admit the right operand, then the left, before their scalar leaf. */
fx_numeric_status fx_complex_dispatch_binary(fx_complex *out, const fx_complex *left,
    const fx_complex *right, uint8_t token, const fx_complex_dispatch_context *context,
    uint8_t *firmware_status);
fx_numeric_status fx_complex_dispatch_binary_with_preparation(fx_complex *out, const fx_complex *left,
    const fx_complex *right, uint8_t token, const fx_complex_dispatch_context *context,
    uint8_t *firmware_status,
    const fx_complex_preparation *preparation);
/* Cleanup alone also accepts scalar contexts: C4 skips compact-real surds,
 * marked-real decimals clean only real, other C4 records clean both; scalar
 * contexts skip headers60 and above. A nonzero leaf status bypasses cleanup. */
fx_numeric_status fx_complex_dispatch_cleanup(fx_complex *out, const fx_complex *in,
    uint8_t leaf_status, const fx_complex_dispatch_context *context,
    uint8_t *firmware_status);
#endif
