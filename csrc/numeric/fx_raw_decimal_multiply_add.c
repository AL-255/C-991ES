/* Bounded decimal-pair arithmetic in native finite operation order.
 * GPL-3.0-or-later. No firmware, instruction interpreter, or host libm. */
#include "fx_raw_decimal_multiply_add.h"
#include "fx_raw_decimal_parts.h"
#include <string.h>

static unsigned add_pairs(uint8_t *out, const uint8_t *left,
                          const uint8_t *right, unsigned count)
{
    unsigned carry = 0;
    for (unsigned i = 0; i < count; ++i)
        out[i] = fx_raw_decimal_pair_add(left[i], right[i], &carry);
    return carry;
}

static unsigned subtract_pairs(uint8_t *out, const uint8_t *left,
                               const uint8_t *right, unsigned count)
{
    unsigned borrow = 0;
    for (unsigned i = 0; i < count; ++i)
        out[i] = fx_raw_decimal_pair_subtract(left[i], right[i], &borrow);
    return borrow;
}

static void shift_mantissa(uint8_t pairs[8], unsigned positions, int left)
{
    if (positions > 18) positions = 18;
    for (unsigned digit = 0; digit < positions; ++digit) {
        unsigned carry = 0;
        if (left) {
            for (unsigned i = 0; i < 8; ++i) {
                unsigned pair = pairs[i];
                pairs[i] = (uint8_t)((pair << 4) | carry);
                carry = pair >> 4;
            }
        } else {
            for (unsigned i = 8; i > 0; --i) {
                unsigned pair = pairs[i - 1];
                pairs[i - 1] = (uint8_t)((pair >> 4) | carry);
                carry = (pair & 15u) << 4;
            }
        }
    }
}

fx_numeric_status fx_raw_decimal_product(uint8_t out[10],
                                         const uint8_t left[10],
                                         const uint8_t right[10])
{
    uint8_t a[10], b[10], prefix[2], twice[8], triple[8];
    uint8_t accumulator[8] = {0};
    unsigned correction = 0;
    if (!out || !left || !right) return FX_NUMERIC_INVALID;
    memcpy(a, left, sizeof a); memcpy(b, right, sizeof b);
    if (a[9] >= 240) { memcpy(out, a, sizeof a); return FX_NUMERIC_OK; }
    if (b[9] >= 240) { memcpy(out, b, sizeof b); return FX_NUMERIC_OK; }
    add_pairs(prefix, a, b, 2);
    prefix[1] = fx_raw_decimal_pair_subtract(prefix[1], 1, &correction) & 15u;
    add_pairs(twice, b + 2, b + 2, 8);
    add_pairs(triple, twice, b + 2, 8);
    /* Fifteen low-first digits contribute to the native product. A malformed
     * nibble still contributes in finite groups of three and one, rather
     * than becoming an ordinary base-ten integer. */
    for (unsigned digit = 0; digit < 15; ++digit) {
        unsigned multiplier = a[2 + digit / 2];
        multiplier = (multiplier >> ((digit & 1u) * 4)) & 15u;
        for (unsigned group = 0; group < multiplier / 3; ++group)
            add_pairs(accumulator, accumulator, triple, 8);
        for (unsigned single = 0; single < multiplier % 3; ++single)
            add_pairs(accumulator, accumulator, b + 2, 8);
        if (digit + 1 < 15) shift_mantissa(accumulator, 1, 0);
    }
    memcpy(out, prefix, 2); memcpy(out + 2, accumulator, 8);
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_raw_decimal_multiply(uint8_t out[10],
                                          const uint8_t left[10],
                                          const uint8_t right[10])
{
    fx_numeric_status status = fx_raw_decimal_product(out, left, right);
    if (status == FX_NUMERIC_OK) fx_raw_decimal_normalize(out);
    return status;
}

static uint8_t opposite_sign(uint8_t sign)
{
    unsigned carry = 0;
    return fx_raw_decimal_pair_add(sign, 5, &carry) & 15u;
}

fx_numeric_status fx_raw_decimal_sum(uint8_t out[10],
                                     const uint8_t left[10],
                                     const uint8_t right[10])
{
    uint8_t a[10], b[10], prefix[2], aligned[8];
    uint8_t order_history[5][20];
    unsigned subtract = 0, ordered = 0, positions = 0;
    if (!out || !left || !right) return FX_NUMERIC_INVALID;
    memcpy(a, left, sizeof a); memcpy(b, right, sizeof b);
    if (a[9] >= 240) { memcpy(out, a, sizeof a); return FX_NUMERIC_OK; }
    if (b[9] >= 240) { memcpy(out, b, sizeof b); return FX_NUMERIC_OK; }
    /* Every failed comparison swaps the operands. Sign adjustment can
     * produce at most four distinct (operand order, sign pair) states over
     * all 65,536 incoming sign pairs. A repeated state proves native
     * non-return; the extra entry makes this finite without dropping it. */
    for (unsigned comparison = 0; comparison < 5; ++comparison) {
        for (unsigned previous = 0; previous < comparison; ++previous)
            if (!memcmp(a, order_history[previous], 10) &&
                !memcmp(b, order_history[previous] + 10, 10))
                return FX_NUMERIC_UNIMPLEMENTED;
        memcpy(order_history[comparison], a, 10);
        memcpy(order_history[comparison] + 10, b, 10);
        subtract = (a[1] >= 5) != (b[1] >= 5);
        if (subtract) b[1] = opposite_sign(b[1]);
        unsigned borrow = subtract_pairs(prefix, a, b, 2);
        if (!borrow && !prefix[0] && !prefix[1]) {
            uint8_t difference[8];
            borrow = subtract_pairs(difference, a + 2, b + 2, 8);
        }
        if (!borrow) { ordered = 1; break; }
        uint8_t temporary[10];
        memcpy(temporary, a, 10); memcpy(a, b, 10); memcpy(b, temporary, 10);
        if (subtract) a[1] = opposite_sign(a[1]);
    }
    if (!ordered) return FX_NUMERIC_UNIMPLEMENTED;
    if (subtract) {
        const uint8_t decrement[2] = {1, 0};
        subtract_pairs(prefix, a, decrement, 2);
        a[0] = prefix[0]; a[1] = prefix[1] & 15u;
        shift_mantissa(a + 2, 1, 1);
    }
    subtract_pairs(prefix, a, b, 2);
    prefix[1] &= 15u;
    memcpy(aligned, b + 2, 8);
    if (prefix[0] == 153u && prefix[1] == 9u) {
        /* Packed exponent difference 999 represents a one-position wrap. */
        shift_mantissa(aligned, 1, 1);
    } else {
        unsigned tens = (prefix[1] << 4) | (prefix[0] >> 4);
        if (tens > 1) { memcpy(out, a, sizeof a); return FX_NUMERIC_OK; }
        positions = (prefix[0] - (tens ? 6u : 0u)) & 255u;
        shift_mantissa(aligned, positions, 0);
    }
    if (subtract) subtract_pairs(a + 2, a + 2, aligned, 8);
    else add_pairs(a + 2, a + 2, aligned, 8);
    memcpy(out, a, sizeof a);
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_raw_decimal_add(uint8_t out[10],
                                     const uint8_t left[10],
                                     const uint8_t right[10])
{
    fx_numeric_status status = fx_raw_decimal_sum(out, left, right);
    if (status == FX_NUMERIC_OK) fx_raw_decimal_normalize(out);
    return status;
}
