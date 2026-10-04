/* Inverse trigonometry in native decimal arithmetic. GPL-3.0-or-later. */
#ifndef FX_TRIG_INVERSE_H
#define FX_TRIG_INVERSE_H
#include "fx_trig_math.h"

/* Independent 1ACA2 kernel boundary: atan(x) as a quarter-turn fraction,
 * for an unsigned decimal argument in[0,1]. */
fx_numeric_status fx_atan_quarter_fraction(fx_number *out, const fx_number *in);
/* Counterparts of1C568/1C556/1C544. Function identifiers select inverse
 * sine/cosine/tangent respectively; the output unit is already resolved. */
fx_numeric_status fx_trig_inverse_decimal(fx_number *out, const fx_number *in,
                                         fx_trig_function function, fx_angle_unit unit);
#endif
