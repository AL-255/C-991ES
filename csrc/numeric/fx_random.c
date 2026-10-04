/* Finite decimal preparation around the original xorshift32 generator.
 * GPL-3.0-or-later. No CPU model, firmware execution, host RNG or libm. */
#include "fx_random.h"
#include "fx_raw_decimal_parts.h"
#include "fx_raw_decimal_multiply_add.h"
#include "fx_raw_fraction_convert.h"
#include <string.h>

static void unpack(uint8_t out[10], const fx_number *in)
{
    out[0] = in->bytes[8]; out[1] = in->bytes[9];
    for (unsigned i = 0; i < 8; ++i) out[i + 2] = in->bytes[7 - i];
}
static void pack(fx_number *out, const uint8_t in[10])
{
    for (unsigned i = 0; i < 8; ++i) out->bytes[i] = in[9 - i];
    out->bytes[8] = in[0]; out->bytes[9] = in[1];
}
static void positive_fraction_mantissa(fx_number *number)
{
    number->bytes[8] = 0x99; number->bytes[9] = 0;
}
static fx_numeric_status decimal_add(fx_number *out, const fx_number *a,
                                      const fx_number *b, int subtract)
{
    uint8_t left[10], right[10];
    unsigned carry = 0;
    unpack(left,a); unpack(right,b);
    if (subtract)
        right[1] = fx_raw_decimal_pair_add(right[1],5,&carry) & 15u;
    fx_numeric_status status = fx_raw_decimal_add(left,left,right);
    if (status == FX_NUMERIC_OK) pack(out,left);
    return status;
}
static fx_numeric_status decimal_multiply(fx_number *out, const fx_number *a,
                                           const fx_number *b)
{
    uint8_t left[10], right[10];
    unpack(left,a); unpack(right,b);
    fx_numeric_status status = fx_raw_decimal_multiply(left,left,right);
    if (status == FX_NUMERIC_OK) pack(out,left);
    return status;
}
static fx_numeric_status truncate_integer(fx_number *number)
{
    uint8_t raw[10];
    unsigned exponent;
    if (fx_number_kind(number) == FX_NUMBER_ERROR) return FX_NUMERIC_OK;
    unpack(raw,number);
    if ((raw[0] >> 4) > 9 || (raw[0] & 15u) > 9 ||
        (raw[1] != 0 && raw[1] != 1 && raw[1] != 5 && raw[1] != 6))
        return FX_NUMERIC_UNIMPLEMENTED;
    if (raw[1] == 0 || raw[1] == 5) {
        fx_number_zero(number); return FX_NUMERIC_OK;
    }
    exponent = 10u * (raw[0] >> 4) + (raw[0] & 15u);
    if (exponent < 14) {
        for (unsigned i = 0; i < 14 - exponent; ++i)
            raw[2 + i / 2] &= i & 1u ? 0x0f : 0xf0;
    }
    fx_raw_decimal_normalize(raw);
    pack(number,raw); return FX_NUMERIC_OK;
}

uint32_t fx_random_xorshift32(uint32_t state)
{
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

/* 0x8078 extracts four bytes using decimal division by 256. Preserve that
 * operation order: casting the scaled seed directly would skip the finite
 * decimal remainders used by the original generator. */
static fx_numeric_status decimal_to_u32(uint32_t *out, fx_number number)
{
    fx_number base, remainder, quotient;
    uint32_t result = 0;
    (void)fx_decimal_from_integer(&base,256);
    for (unsigned position = 0; position <= 24; position += 8) {
        int64_t byte;
        if (position < 24) {
            fx_numeric_status status = fx_number_divmod(&remainder,&quotient,&number,&base);
            if (status != FX_NUMERIC_OK) return status;
            number = remainder;
        }
        if (truncate_integer(&number) != FX_NUMERIC_OK ||
            fx_decimal_to_integer(&byte,&number) != FX_NUMERIC_OK)
            return FX_NUMERIC_UNIMPLEMENTED;
        result |= (uint32_t)(uint8_t)byte << position;
        if (position < 24) number = quotient;
    }
    *out = result; return FX_NUMERIC_OK;
}

static fx_numeric_status prepare_seed(fx_number *out, const fx_number *seed)
{
    fx_number number = *seed, term;
    unsigned kind = number.bytes[0] & 0xf0;
    uint8_t old_exponent = number.bytes[8];
    positive_fraction_mantissa(&number);
    fx_decimal_from_u8(&term,old_exponent);
    positive_fraction_mantissa(&term);
    /* 0x1c6a4 is generic ADD. The old exponent byte is an unsigned binary
     * integer before its own normalized decimal mantissa is selected. */
    if (kind == 0 || kind == 0x40) {
        number.bytes[0] &= 0xbf;
        fx_numeric_status status = decimal_add(&number,&number,&term,0);
        if (status != FX_NUMERIC_OK) return status;
    } else if (kind == 0x80) {
        /* The forced sign bytes are not ordinary compact-surd signs. This
         * path remains explicit until its unchecked component policy is
         * proved; it is never replaced by an unrelated seed. */
        return FX_NUMERIC_UNIMPLEMENTED;
    } else {
        fx_number_error(&number,3);
    }
    if (number.bytes[0] >= 0xf0 || !(number.bytes[0] & 15u)) {
        fx_decimal_from_u8(&number,1);
        positive_fraction_mantissa(&number);
        fx_numeric_status status = decimal_add(&number,&number,&term,0);
        if (status != FX_NUMERIC_OK) return status;
    }
    positive_fraction_mantissa(&number);
    *out = number; return FX_NUMERIC_OK;
}

fx_numeric_status fx_random_next(fx_random_result *out, const fx_number *seed)
{
    fx_random_result result;
    fx_number number, scale, integer;
    fx_decimal decimal;
    uint32_t state;
    fx_numeric_status status;
    if (!out || !seed) return FX_NUMERIC_INVALID;
    status = prepare_seed(&number,seed);
    if (status != FX_NUMERIC_OK) return status;
    /* ROM 0x2aaa: 04 29 49 67 29 50 00 00 09 01 = 2^32 - 1. */
    (void)fx_decimal_from_integer(&scale,UINT32_MAX);
    status = decimal_multiply(&number,&number,&scale);
    if (status != FX_NUMERIC_OK) return status;
    status = decimal_to_u32(&state,number);
    if (status != FX_NUMERIC_OK) return status;
    state = fx_random_xorshift32(state);
    /* The inverse four-byte conversion is exact throughout uint32_t. */
    (void)fx_decimal_from_integer(&number,state);
    status = fx_number_binary(&number,&number,&scale,FX_DIVIDE);
    if (status != FX_NUMERIC_OK) return status;
    integer = number;
    status = truncate_integer(&integer);
    if (status != FX_NUMERIC_OK) return status;
    status = decimal_add(&number,&number,&integer,1);
    if (status != FX_NUMERIC_OK) return status;
    result.seed = number;
    if (fx_decimal_decode(&decimal,&number) != FX_NUMERIC_OK)
        return FX_NUMERIC_UNIMPLEMENTED;
    decimal.exponent += 3;
    (void)fx_decimal_encode(&number,&decimal);
    status = truncate_integer(&number);
    if (status != FX_NUMERIC_OK) return status;
    (void)fx_decimal_decode(&decimal,&number);
    if (decimal.sign) decimal.exponent -= 3;
    (void)fx_decimal_encode(&result.value,&decimal);
    result.firmware_status = 0;
    *out = result; return FX_NUMERIC_OK;
}

/* 0x194e4, selected by 0x1caa8. The stored trailing zero positions must
 * make the value integral, and the exponent byte must be at most nine. */
static int bounded_integer(const fx_number *number)
{
    uint8_t raw[10];
    unsigned zero_positions = 0, borrow = 0;
    unpack(raw,number);
    if (!raw[9]) return 1;
    if (raw[9] >= 10) return 0;
    for (unsigned i = 2; i < 10; ++i) {
        if (raw[i] & 15u) break;
        ++zero_positions;
        if (raw[i]) break;
        ++zero_positions;
    }
    unsigned sign = raw[1] >= 5 ? raw[1] - 5u : raw[1];
    if (!sign || raw[0] > 9) return 0;
    unsigned fractional_positions = fx_raw_decimal_pair_subtract(0x14,raw[0],&borrow);
    unsigned packed_zeros = zero_positions < 10 ? zero_positions : zero_positions + 6;
    return packed_zeros >= fractional_positions;
}
static fx_numeric_status prepare_bound(fx_number *out, const fx_number *input)
{
    fx_number number = *input;
    if ((number.bytes[0] & 0xf0) == 0x80) {
        fx_numeric_status status = fx_number_to_decimal(&number,&number);
        if (status != FX_NUMERIC_OK) return FX_NUMERIC_UNIMPLEMENTED;
    }
    if (number.bytes[0] <= 0x4f) {
        number.bytes[0] &= 0xbf;
        if ((number.bytes[0] & 0xf0) == 0x20) {
            fx_numeric_status status = fx_raw_fraction_convert(&number,&number);
            if (status != FX_NUMERIC_OK) return status;
        }
    }
    *out = number; return FX_NUMERIC_OK;
}

fx_numeric_status fx_random_integer(fx_random_result *out, const fx_number *seed,
                                     const fx_number *lower, const fx_number *upper)
{
    fx_random_result result;
    fx_number a, b, span, one, original_seed;
    fx_numeric_status status;
    if (!out || !seed || !lower || !upper) return FX_NUMERIC_INVALID;
    original_seed = *seed;
    status = prepare_bound(&a,lower);
    if (status != FX_NUMERIC_OK) return status;
    status = prepare_bound(&b,upper);
    if (status != FX_NUMERIC_OK) return status;
    if (!bounded_integer(&a) || !bounded_integer(&b)) goto argument_error;
    status = decimal_add(&span,&b,&a,1);
    if (status != FX_NUMERIC_OK) return status;
    if (!bounded_integer(&span) || !span.bytes[0] ||
        (!span.bytes[8] && !span.bytes[9]) || span.bytes[9] >= 4)
        goto argument_error;
    fx_decimal_from_u8(&one,1);
    status = decimal_add(&span,&span,&one,0);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_random_next(&result,&original_seed);
    if (status != FX_NUMERIC_OK) return status;
    status = decimal_multiply(&span,&span,&result.seed);
    if (status != FX_NUMERIC_OK) return status;
    status = decimal_add(&result.value,&a,&span,0);
    if (status != FX_NUMERIC_OK) return status;
    fx_number original = result.value;
    int negative = result.value.bytes[0] && result.value.bytes[0] < 0x50 &&
                   (result.value.bytes[8] || result.value.bytes[9]) &&
                   result.value.bytes[9] >= 4;
    status = truncate_integer(&result.value);
    if (status != FX_NUMERIC_OK) return status;
    if (negative && memcmp(&original,&result.value,sizeof original)) {
        status = decimal_add(&result.value,&result.value,&one,1);
        if (status != FX_NUMERIC_OK) return status;
    }
    result.firmware_status = 0;
    *out = result; return FX_NUMERIC_OK;
argument_error:
    fx_number_error(&result.value,8);
    result.seed = original_seed; result.firmware_status = 8;
    *out = result; return FX_NUMERIC_OK;
}
