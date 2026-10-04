/* Ordered complex argument and coordinate conversion. GPL-3.0-or-later. */
#ifndef FX_COMPLEX_ANGLE_H
#define FX_COMPLEX_ANGLE_H
#include "fx_complex.h"
#include "../trig/fx_trig_math.h"

/* Argument18708 has a zero imaginary component. Unit is already resolved. */
fx_numeric_status fx_complex_argument(fx_complex *out, const fx_complex *in,
                                       fx_angle_unit unit);
/* Polar records reuse the real/imaginary slots for radius/angle. Native
 * conversion errors18352 write F3 independently into both slots. */
fx_numeric_status fx_complex_to_polar(fx_complex *out, const fx_complex *in,
                                      fx_angle_unit unit, int exact_math);
fx_numeric_status fx_complex_from_polar(fx_complex *out, const fx_complex *in,
                                        fx_angle_unit unit, int exact_math);
#endif
