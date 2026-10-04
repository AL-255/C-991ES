/* Typed evaluator matrix/vector dispatch; no parsing. GPL-3.0-or-later. */
#ifndef FX_LINALG_DISPATCH_H
#define FX_LINALG_DISPATCH_H
#include "fx_linalg_store.h"
#include "../complex/fx_complex.h"

typedef struct {
    uint8_t calculation_context;
    fx_linalg_context numeric;
} fx_linalg_dispatch_context;
typedef struct {
    fx_complex value;
    uint8_t firmware_status;
    uint32_t cancellation_checks;
} fx_linalg_dispatch_result;

void fx_linalg_dispatch_context_default(fx_linalg_dispatch_context *context,
                                        uint8_t calculation_context);
/* Prepared16336 value selection for MATRIX6/VECTOR7. At least one operand
 * must contain a6x/9x reference; scalar-only calls return UNIMPLEMENTED.
 * All nine slots and their inactive cells are observable. References use
 * low identities0..8 and dimensions0..3; native unchecked addresses beyond
 * these fixed banks are outside this safe typed API.
 * Sources may alias out.value, but not mutable bank storage. Binary entry
 * preserves the right operand's imaginary record, as the non-CMPLX native
 * work record does. Numerical errors return hostOK and a separate native
 * status; status must not be inferred from the output header.
 * Native wrapped scalar selections for vector5A/5B, rich88/C3 are retained.
 * Matrix88 can reinterpret reference metadata as marked fraction digits;
 * its original allocation/copy/release occurs before scalar conversion.
 * Unknown raw tokens return UNIMPLEMENTED before any mutation. A proven
 * native non-return after allocation also returns UNIMPLEMENTED, retaining
 * those prior bank mutations while leaving the output uncommitted. */
fx_numeric_status fx_linalg_dispatch_unary(fx_linalg_dispatch_result *out,
    fx_linalg_bank *bank, const fx_complex *input, uint8_t token,
    const fx_linalg_dispatch_context *context);
fx_numeric_status fx_linalg_dispatch_binary(fx_linalg_dispatch_result *out,
    fx_linalg_bank *bank, const fx_complex *left, const fx_complex *right,
    uint8_t token, const fx_linalg_dispatch_context *context);
#endif
