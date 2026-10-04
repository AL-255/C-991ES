/* Finite packed-field construction and scalar normalization.
 * GPL-3.0-or-later. See fx_raw_decimal_parts.h for the record coordinate. */
#include "fx_raw_decimal_parts.h"
#include <string.h>

uint8_t fx_raw_decimal_pair_add(uint8_t left, uint8_t right,
                                unsigned *carry) {
    unsigned total = (unsigned)left + right + *carry;
    unsigned adjusted = total & 255u;
    if ((left & 15u) + (right & 15u) + *carry > 9u)
        adjusted += 6u;
    if ((adjusted & 240u) > 144u || total > 255u || adjusted > 255u)
        adjusted += 96u;
    *carry = total > 255u || adjusted > 255u;
    return (uint8_t)adjusted;
}

uint8_t fx_raw_decimal_pair_subtract(uint8_t left, uint8_t right,
                                     unsigned *borrow) {
    int difference = (int)left - right - (int)*borrow;
    int low_difference = (int)(left & 15u) - (int)(right & 15u) - (int)*borrow;
    unsigned adjusted = (unsigned)difference & 255u;
    if ((adjusted & 15u) > 9u || low_difference < 0)
        adjusted = (adjusted - 6u) & 65535u;
    if ((adjusted & 240u) > 144u || difference < 0)
        adjusted = (adjusted - 96u) & 65535u;
    *borrow = difference < 0 || (adjusted & 256u) != 0;
    return (uint8_t)adjusted;
}

/* Shift a finite field of little-endian packed pairs by decimal positions.
 * The fraction field includes its raw sign pair because padding in that pair
 * is part of the native unchecked denominator construction. */
static void shift_pairs(uint8_t *pairs, unsigned count, unsigned positions,
                         int left) {
    positions = positions > 18u ? 18u : positions;
    for (unsigned position = 0; position < positions; ++position) {
        unsigned carry = 0;
        if (left) {
            for (unsigned i = 0; i < count; ++i) {
                unsigned pair = pairs[i];
                pairs[i] = (uint8_t)((pair << 4) | carry);
                carry = pair >> 4;
            }
        } else {
            for (unsigned i = count; i > 0; --i) {
                unsigned pair = pairs[i - 1];
                pairs[i - 1] = (uint8_t)((pair >> 4) | carry);
                carry = (pair & 15u) << 4;
            }
        }
    }
}

static unsigned separator_position(const uint8_t record[10]) {
    for (unsigned i = 0; i < 8; ++i) {
        unsigned pair = record[i + 2];
        unsigned position;
        if ((pair & 15u) == 10u)
            position = 2u * i + 1u;
        else if (pair >= 160u)
            position = 2u * i + 2u;
        else
            continue;
        return position < 15u ? position : 0u;
    }
    return 0;
}

static uint8_t packed_modulo_100(int value) {
    value %= 100;
    if (value < 0) value += 100;
    return (uint8_t)((value / 10) * 16 + value % 10);
}

static void aligned_component(uint8_t out[10], const uint8_t source[10],
                               unsigned delimiter, uint8_t sign) {
    unsigned positions = 16u - delimiter;
    if (positions > 18u) positions = 18u;
    memcpy(out, source, 10);
    shift_pairs(out + 1, 9, positions, 1);
    out[0] = packed_modulo_100(14 - (int)positions);
    out[1] = sign;
    out[9] &= 15u;
}

void fx_raw_fraction_split(fx_raw_fraction_parts *out,
                           const fx_number *external) {
    uint8_t source[10], aligned[10], remaining[10];
    source[0] = external->bytes[8];
    source[1] = external->bytes[9];
    for (unsigned i = 0; i < 8; ++i)
        source[i + 2] = external->bytes[7 - i];
    source[9] &= 15u;
    unsigned length = source[0];
    if (length >= 16u) length = (length - 6u) & 255u;
    memcpy(aligned, source, 10);
    shift_pairs(aligned + 1, 9, (15u - length) & 255u, 0);
    unsigned first = separator_position(aligned);
    aligned_component(out->denominator, aligned, first, 1);
    aligned[0] = source[0];
    aligned[1] = source[1];
    memcpy(remaining, aligned, 10);
    shift_pairs(remaining + 1, 9, first, 0);
    remaining[0] = remaining[1] = 0;
    unsigned second = separator_position(remaining);
    out->has_middle = second != 0;
    memset(out->middle, 0, sizeof(out->middle));
    if (second) {
        aligned_component(out->middle, remaining, second, source[1]);
        shift_pairs(remaining + 1, 9, second, 0);
    }
    memcpy(out->whole, remaining, 10);
    out->whole[0] = 20;
    out->whole[1] = source[1];
}

void fx_raw_decimal_normalize(uint8_t record[10]) {
    if (record[9] >= 240u) return;
    if (record[9] >= 16u) {
        unsigned carry = 0;
        shift_pairs(record + 2, 8, 1, 0);
        record[0] = fx_raw_decimal_pair_add(record[0], 1, &carry);
        record[1] = fx_raw_decimal_pair_add(record[1], 0, &carry);
    } else {
        unsigned positions = 0;
        if (record[9] == 0) {
            positions = 1;
            unsigned i;
            for (i = 8; i > 1; --i) {
                if (record[i] >= 15u) break;
                ++positions;
                if (record[i] != 0) break;
                ++positions;
            }
            if (i == 1) {
                memset(record, 0, 10);
                return;
            }
        }
        if (positions) {
            unsigned borrow = 0;
            shift_pairs(record + 2, 8, positions, 1);
            unsigned packed_positions = positions < 10u ? positions : positions + 6u;
            record[0] = fx_raw_decimal_pair_subtract(record[0],
                                  (uint8_t)packed_positions, &borrow);
            record[1] = fx_raw_decimal_pair_subtract(record[1], 0, &borrow);
        }
    }
    /* Classification does not rewrite the stored raw sign. */
    uint8_t kind = record[1] & 15u;
    for (unsigned i = 0; i < 16; ++i) {
        unsigned borrow = 0;
        kind = fx_raw_decimal_pair_subtract(kind & 15u, 5, &borrow);
        if (!borrow) break;
    }
    if (kind == 2) {
        memset(record, 0, 10);
        record[9] = 243;
    } else if (kind > 2 || (kind == 0 && record[0] == 0)) {
        memset(record, 0, 10);
    }
}

void fx_raw_decimal_cleanup(uint8_t record[10]) {
    if (record[9] >= 240u) return;
    unsigned tail = (unsigned)record[2] | ((unsigned)record[3] << 8);
    if (tail >= 39313u) { /* packed 0x9991 */
        unsigned carry = 0;
        for (unsigned i = 2; i < 10; ++i)
            record[i] = fx_raw_decimal_pair_add(record[i], i == 4 ? 1 : 0, &carry);
        record[2] = record[3] = 0;
    } else if (tail < 16u) {
        record[2] = record[3] = 0;
    }
    fx_raw_decimal_normalize(record);
}
