/* Prepared compact-radical component policy. GPL-3.0-or-later. */
#ifndef FX_NUMERIC_COMPONENTS_H
#define FX_NUMERIC_COMPONENTS_H
#include "fx_numeric.h"

/* The existing component square-root policy, including active positive zero.
 * This entry accepts the component records produced by surd unpacking; it
 * preserves the short unnormalized exponent-prefix result for radicand zero
 * with exponent0/sign1. Canonical ordinary zero keeps the ordinary guard.
 * Numerical error records are FX_NUMERIC_OK results. Unsupported host input
 * formats remain distinct statuses. Input/output may alias; null pointers
 * return FX_NUMERIC_INVALID without an output commit. */
fx_numeric_status fx_numeric_component_sqrt(fx_number *out,
                                          const fx_number *radicand);
#endif
