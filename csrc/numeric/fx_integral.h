/* Real adaptive quadrature. GPL-3.0-or-later. */
#ifndef FX_INTEGRAL_H
#define FX_INTEGRAL_H
#include "fx_calculus.h"

/* Native046ee: signed real bounds, default tolerance1e-5 when NULL.
 * Negative tolerance is F8. Both endpoints are evaluated before quadrature,
 * including equal bounds. Callback/native arithmetic errors are F3; timer
 * cancellation is F1 and exhausted refinement is FB. Negative host callback
 * returns leave out unchanged. The API owns local X; output may alias inputs. */
fx_numeric_status fx_number_integral(fx_number *out, const fx_number *lower,
                                     const fx_number *upper,
                                     const fx_number *tolerance,
                                     fx_calculus_function function,
                                     void *userdata,
                                     const fx_calculus_control *control);
#endif
