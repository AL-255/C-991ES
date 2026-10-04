/* Prepared random-number generation for the fx-991ES PLUS C firmware.
 * GPL-3.0-or-later. */
#ifndef FX_RANDOM_H
#define FX_RANDOM_H
#include "fx_numeric.h"

/* The caller owns the persistent seed (native RAM 0x821c). The returned seed
 * is the full fraction; Ran#'s value has only three fractional places. */
typedef struct {
    fx_number value;
    fx_number seed;
    uint8_t firmware_status;
} fx_random_result;

uint32_t fx_random_xorshift32(uint32_t state);
fx_numeric_status fx_random_next(fx_random_result *out,
                                  const fx_number *seed);
/* Native 0x13ebe: integral bounds and their difference must fit the original
 * ten-digit integer gate. Equal/reversed bounds return Argument ERROR (8),
 * and leave the seed unchanged. Inputs are copied before output is written. */
fx_numeric_status fx_random_integer(fx_random_result *out,
                                     const fx_number *seed,
                                     const fx_number *lower,
                                     const fx_number *upper);
#endif
