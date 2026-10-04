/* Private shared decimal-power entry. GPL-3.0-or-later. */
#ifndef FX_TRANSCEND_INTERNAL_H
#define FX_TRANSCEND_INTERNAL_H
#include "fx_numeric.h"
fx_numeric_status fx_transcend_power_decimal(fx_number *out, const fx_number *base,
                                             const fx_number *exponent);
fx_numeric_status fx_transcend_root_decimal(fx_number *out, const fx_number *radicand,
                                            const fx_number *degree);
#endif
