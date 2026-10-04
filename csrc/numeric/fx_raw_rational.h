/* Prepared scalar rational arithmetic. GPL-3.0-or-later. */
#ifndef FX_RAW_RATIONAL_H
#define FX_RAW_RATIONAL_H
#include "fx_numeric.h"

/* Value boundary for original add/subtract/multiply/divide and the
 * fraction-preferred divide. Ordinary decimal records and prepared 2x/6x
 * fraction fields are admitted, including zero denominators and raw field
 * lengths. The ordinary marker policy and all returned error-record bytes
 * are preserved independently of the native status byte.
 *
 * fraction_preferred is zero for ordinary arithmetic or one for divide's
 * fraction-preferred entry. Other values and non-divide preferred requests
 * are invalid. Both inputs are copied before any caller output write;
 * complete or partial output/input aliases therefore use original values.
 *
 * OK can include a native numeric error; native_status preserves it.
 * UNIMPLEMENTED denotes a finite prepared-helper boundary and leaves output
 * and native_status untouched. The original numerical scratch arena,
 * external pointer-address alignment, and compact-surd branches belong to
 * separate APIs; this function does not expose a physical RAM image.
 */
fx_numeric_status fx_raw_rational_binary(fx_number *out,
                                         const fx_number *left,
                                         const fx_number *right,
                                         fx_binary_op operation,
                                         unsigned fraction_preferred,
                                         unsigned *native_status);
#endif
