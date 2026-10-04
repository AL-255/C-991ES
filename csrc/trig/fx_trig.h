/* Special-result recognition after numeric trigonometry. GPL-3.0-or-later. */
#ifndef FX_TRIG_H
#define FX_TRIG_H
#include "../numeric/fx_numeric.h"

typedef enum { FX_SINE, FX_COSINE, FX_TANGENT } fx_trig_function;
/* Counterpart of the replacement stage shared by16268/16272/16308. The
 * input is the computed decimal function result, not an angle. exact_math
 * is the resolved permission from18212. matched returns0 or a one-based
 * table index; passingNULL is allowed. out may alias computed_result. */
fx_numeric_status fx_trig_special_result(fx_number *out,
                                        const fx_number *computed_result,
                                        fx_trig_function function,
                                        int exact_math, unsigned *matched);
#endif
