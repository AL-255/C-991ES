/* Real hyperbolic functions. GPL-3.0-or-later. */
#ifndef FX_TRIG_HYPERBOLIC_H
#define FX_TRIG_HYPERBOLIC_H
#include "fx_trig.h"

/* FX_SINE/COSINE/TANGENT select sinh/cosh/tanh, or their inverse when
 * inverse is1. Hyperbolic arguments and results are independent of angular
 * units. Numeric errors are returned as firmware error records. */
fx_numeric_status fx_hyperbolic_decimal(fx_number *out, const fx_number *in,
                                       fx_trig_function function, int inverse);

#endif
