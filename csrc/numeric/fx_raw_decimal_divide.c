/* Finite quotient digits in original decimal-pair operation order.
 * This numeric adapter has no instruction, CPU or memory-map model.
 * GPL-3.0-or-later. */
#include "fx_raw_decimal_divide.h"
#include "fx_raw_decimal_parts.h"
#include <string.h>

static unsigned add(uint8_t out[8], const uint8_t left[8],
                    const uint8_t right[8])
{
    unsigned pair, carry = 0;
    for (pair = 0; pair < 8; ++pair)
        out[pair] = fx_raw_decimal_pair_add(left[pair],right[pair],&carry);
    return carry;
}
static unsigned subtract(uint8_t out[8], const uint8_t left[8],
                         const uint8_t right[8])
{
    unsigned pair, borrow = 0;
    for (pair = 0; pair < 8; ++pair)
        out[pair] = fx_raw_decimal_pair_subtract(left[pair],right[pair],&borrow);
    return borrow;
}
static void append_zero_digit(uint8_t *pairs, unsigned count)
{
    unsigned pair, previous = 0;
    for (pair = 0; pair < count; ++pair) {
        unsigned next = pairs[pair] >> 4;
        pairs[pair] = (uint8_t)((pairs[pair] << 4) | previous);
        previous = next;
    }
}
fx_numeric_status fx_raw_decimal_quotient(uint8_t out[10],
                                         const uint8_t left[10],
                                         const uint8_t right[10])
{
    uint8_t a[10], b[10], prefix[2], remainder[8], triple[8], twice[8];
    uint8_t quotient[9] = {0};
    unsigned carry = 0, digit, attempt, estimate;
    if (!out || !left || !right) return FX_NUMERIC_INVALID;
    memcpy(a,left,sizeof a); memcpy(b,right,sizeof b);
    if (a[9] >= 0xf0) { memcpy(out,a,sizeof a); return FX_NUMERIC_OK; }
    if (b[9] >= 0xf0) { memcpy(out,b,sizeof b); return FX_NUMERIC_OK; }
    if (!b[9]) {
        memset(out,0,10); out[9] = 0xf3; return FX_NUMERIC_OK;
    }
    prefix[0] = fx_raw_decimal_pair_subtract(a[0],b[0],&carry);
    prefix[1] = fx_raw_decimal_pair_subtract(a[1],b[1],&carry);
    carry = 0;
    prefix[1] = fx_raw_decimal_pair_add(prefix[1],1,&carry) & 15;
    carry = 0;
    prefix[0] = fx_raw_decimal_pair_subtract(prefix[0],1,&carry);
    prefix[1] = fx_raw_decimal_pair_subtract(prefix[1],0,&carry) & 15;
    memcpy(remainder,a+2,sizeof remainder);
    add(twice,b+2,b+2); add(triple,twice,b+2);
    for (digit = 0; digit < 18; ++digit) {
        /* Subtract groups of three, then restore individual divisors.
         * Packed correction acts on each raw pair, so invalid nibbles
         * cannot be replaced by an ordinary integer division. */
        estimate = 2;
        for (attempt = 0; attempt < 256; ++attempt) {
            if (subtract(remainder,remainder,triple)) break;
            estimate = (estimate + 3) & 255;
        }
        if (attempt == 256) return FX_NUMERIC_UNIMPLEMENTED;
        for (attempt = 0; attempt < 256; ++attempt) {
            if (add(remainder,remainder,b+2)) break;
            estimate = (estimate - 1) & 255;
        }
        if (attempt == 256) return FX_NUMERIC_UNIMPLEMENTED;
        if (digit + 1 < 18) {
            quotient[0] |= (uint8_t)estimate;
            append_zero_digit(quotient,9);
            append_zero_digit(remainder,8);
        }
    }
    out[0] = prefix[0]; out[1] = prefix[1];
    memcpy(out+2,quotient+1,8);
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_raw_decimal_divide(uint8_t out[10],
                                       const uint8_t left[10],
                                       const uint8_t right[10])
{
    fx_numeric_status status = fx_raw_decimal_quotient(out,left,right);
    if (status == FX_NUMERIC_OK) fx_raw_decimal_normalize(out);
    return status;
}
