/* Bounded packed-decimal fields used by unchecked rich-reference conversion.
 * GPL-3.0-or-later. No firmware, instruction decoder, CPU state, or host libm. */
#ifndef FX_RAW_DECIMAL_PARTS_H
#define FX_RAW_DECIMAL_PARTS_H
#include "fx_numeric.h"

/* Arithmetic records store packed exponent, raw sign, then eight packed
 * mantissa pairs in ascending significance. This is the firmware numerical
 * coordinate, not a CPU register representation. */
typedef struct {
    uint8_t denominator[10], whole[10], middle[10];
    uint8_t has_middle;
} fx_raw_fraction_parts;

void fx_raw_fraction_split(fx_raw_fraction_parts *out,
                           const fx_number *external);
void fx_raw_decimal_normalize(uint8_t record[10]);
/* The finite low-four-digit adjustment performed by native 0x1a6da. */
void fx_raw_decimal_cleanup(uint8_t record[10]);
/* The pointer supplies and receives a one-bit carry or borrow. Malformed
 * packed nibbles retain their finite native decimal-correction behavior. */
uint8_t fx_raw_decimal_pair_add(uint8_t left, uint8_t right,
                                unsigned *carry);
uint8_t fx_raw_decimal_pair_subtract(uint8_t left, uint8_t right,
                                     unsigned *borrow);
#endif
