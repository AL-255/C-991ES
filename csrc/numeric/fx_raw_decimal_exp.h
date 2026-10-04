/* Prepared exponential of an unchecked converted scalar.
 * GPL-3.0-or-later. No ROM, CPU, or host libm is used. */
#ifndef FX_RAW_DECIMAL_EXP_H
#define FX_RAW_DECIMAL_EXP_H
#include "fx_numeric.h"
fx_numeric_status fx_raw_decimal_exp(fx_number *out,
                                      const fx_number *converted,
                                      unsigned *native_status);
/* Exact seventeen coefficient digits and retained guard pair, in the
 * reversed decimal coordinate used by the other raw numeric adapters. */
fx_numeric_status fx_raw_decimal_exp_argument(uint8_t out[10],
                                               uint8_t *guard,
                                               const fx_number *converted);
#endif
