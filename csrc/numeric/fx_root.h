/* Real nth-root/cube-root APIs for fx-991ES PLUS C. GPL-3.0-or-later. */
#ifndef FX_ROOT_H
#define FX_ROOT_H
#include "fx_numeric.h"

/* Native0x1122c supplies degree first internally; this API names the operands
 * explicitly as radicand, degree. Rational integral-degree roots can retain
 * an exact fraction; compact radicals take the original decimal fallback.
 * Results are serialized before evaluator cleanup. Domain errors are F3
 * numeric records with statusOK; unsupported formats return an explicit status.
 * Both inputs may alias the output. Inputs are otherwise unchanged. */
fx_numeric_status fx_number_nthroot(fx_number *out, const fx_number *radicand,
                                    const fx_number *degree);
/* Native0x1c878, including unary header-marker clearing and exact fractions. */
fx_numeric_status fx_number_cbrt(fx_number *out, const fx_number *in);
#endif
