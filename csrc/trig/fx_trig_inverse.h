/* Inverse trigonometry in native decimal arithmetic. GPL-3.0-or-later. */
#ifndef FX_TRIG_INVERSE_H
#define FX_TRIG_INVERSE_H
#include "fx_trig_math.h"

/* Independent 1ACA2 kernel boundary: atan(x) as a quarter-turn fraction,
 * for an unsigned decimal argument in[0,1]. */
fx_numeric_status fx_atan_quarter_fraction(fx_number *out, const fx_number *in);
/* Same unsigned kernel with a prepared17-digit mantissa, retaining the two
 * guard digits otherwise lost at an external15-digit storage boundary.
 * The integer represents magnitude*10^(16-exponent), with exponent-99..0.
 * At exponent0 the native coordinate permits the unit value plus up to99
 * guard units; no additional metadata bias is added by this entry. */
fx_numeric_status fx_atan_quarter_fraction_guarded(fx_number *out,
                                                   uint64_t mantissa17,
                                                   int exponent);
/* Counterparts of1C568/1C556/1C544. Function identifiers select inverse
 * sine/cosine/tangent respectively; the output unit is already resolved. */
fx_numeric_status fx_trig_inverse_decimal(fx_number *out, const fx_number *in,
                                         fx_trig_function function, fx_angle_unit unit);
#endif
