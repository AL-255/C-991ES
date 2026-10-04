/* Forward trigonometry using the firmware's decimal arithmetic. GPL-3.0-or-later. */
#ifndef FX_TRIG_MATH_H
#define FX_TRIG_MATH_H
#include "fx_trig.h"

typedef enum { FX_DEGREES, FX_RADIANS, FX_GRADIANS } fx_angle_unit;

/* Counterpart of 1C340: convert an explicitly tagged input angle into the
 * calculator's resolved angle unit. Same-unit conversion preserves its
 * original record, except that tagged surds are first made decimal. */
fx_numeric_status fx_angle_convert(fx_number *out, const fx_number *angle,
                                  fx_angle_unit from, fx_angle_unit to);

/* Decimal rotation kernel 1ACEC. The input is an unsigned fraction of a
 * quarter turn in [0, 1). Reduction normally produces at most .5; decimal
 * cancellation near a large angle can leave a value slightly above .5.
 * The returned coordinates are scaled together;
 * sine_coordinate / cosine_coordinate is its tangent. This boundary is
 * exposed to permit independent comparisons of the rotation arithmetic. */
fx_numeric_status fx_trig_decimal_pair(fx_number *cosine_coordinate,
                                      fx_number *sine_coordinate,
                                      const fx_number *quarter_turn_fraction);

/* Counterparts of the forward numeric entries 1C59E/1C58C/1C57A. The unit
 * is already resolved; this API does not read calculator configuration. */
fx_numeric_status fx_trig_decimal(fx_number *out, const fx_number *angle,
                                 fx_trig_function function, fx_angle_unit unit);
/* Numeric core followed by the special-result replacement stage. */
fx_numeric_status fx_trig_evaluate(fx_number *out, const fx_number *angle,
                                  fx_trig_function function, fx_angle_unit unit,
                                  int exact_math, unsigned *matched);
#endif
