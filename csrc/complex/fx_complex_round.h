/* Display-precision numeric rounding used by the CMPLX evaluator.
 * GPL-3.0-or-later. No firmware execution or host floating point. */
#ifndef FX_COMPLEX_ROUND_H
#define FX_COMPLEX_ROUND_H
#include "fx_complex.h"

/* Counterparts of 15CBE and 15D36 in a prepared display context. display_mode
 * is 8102 (Norm1=0, Norm2=4, Fix=8, Sci=9); digits is 8103 (0..9).
 * The source remains immutable and may alias out. firmware_status receives
 * the native R0 return: zero on success, three on rejected/error records.
 * This status is independent of the host API status and of an error header.
 * Scalar scratch RAM and register side effects are not represented. */
fx_numeric_status fx_scalar_display_round(fx_number *out, const fx_number *in,
                                          uint8_t display_mode, uint8_t digits,
                                          uint8_t *firmware_status);
fx_numeric_status fx_complex_display_round(fx_complex *out, const fx_complex *in,
                                           uint8_t display_mode, uint8_t digits,
                                           uint8_t *firmware_status);
#endif
