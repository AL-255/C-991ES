/* Real Richardson differentiation. GPL-3.0-or-later. */
#ifndef FX_DERIVATIVE_H
#define FX_DERIVATIVE_H
#include "fx_calculus.h"

/* Native04aee: default relative tolerance1e-10 when NULL. An explicit
 * tolerance must be positive (otherwiseF8). Sampling/arithmetical errors
 * yieldF3, cancellationF1, exhausted extrapolationFB. Negative host callback
 * statuses leave out unchanged. Output may alias the point or tolerance. */
fx_numeric_status fx_number_derivative(fx_number *out, const fx_number *point,
                                       const fx_number *tolerance,
                                       fx_calculus_function function,
                                       void *userdata,
                                       const fx_calculus_control *control);
#endif
