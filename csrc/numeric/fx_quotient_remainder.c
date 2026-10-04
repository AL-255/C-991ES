/* Named finite decimal policies for native prepared quotient/remainder.
 * GPL-3.0-or-later. No firmware, CPU, register or memory-map model. */
#include "fx_quotient_remainder.h"
#include "fx_raw_decimal_parts.h"
#include "fx_raw_decimal_divide.h"
#include "fx_raw_decimal_multiply_add.h"
#include "fx_raw_fraction_convert.h"
#include <string.h>

typedef uint8_t decimal_scratch[10];

static void unpack(decimal_scratch out, const fx_number *input)
{
    out[0] = input->bytes[8]; out[1] = input->bytes[9];
    for (unsigned i = 0; i < 8; ++i) out[i + 2] = input->bytes[7 - i];
}
static void pack(fx_number *out, const decimal_scratch input)
{
    for (unsigned i = 0; i < 8; ++i) out->bytes[i] = input[9 - i];
    out->bytes[8] = input[0]; out->bytes[9] = input[1];
}
static unsigned unpack_bcd(uint8_t x) { return 10u * (x >> 4) + (x & 15u); }
static unsigned biased_exponent(const decimal_scratch x)
{
    return unpack_bcd(x[0]) + 100u * unpack_bcd(x[1]);
}
static unsigned subtract_prefix(uint8_t difference[2], const uint8_t left[2],
                                 const uint8_t right[2])
{
    unsigned borrow = 0;
    difference[0] = fx_raw_decimal_pair_subtract(left[0],right[0],&borrow);
    difference[1] = fx_raw_decimal_pair_subtract(left[1],right[1],&borrow);
    return borrow;
}
static int exponent_at_least_ten(const decimal_scratch number)
{
    const uint8_t threshold[2] = {0x10,1};
    uint8_t difference[2];
    return !subtract_prefix(difference,number,threshold);
}
static fx_numeric_status normalize_scalar(decimal_scratch out,
                                           const fx_number *input)
{
    fx_number converted;
    unsigned kind = input->bytes[0] & 0xf0;
    if (kind == 0x20) {
        fx_numeric_status status = fx_raw_fraction_convert(&converted,input);
        if (status != FX_NUMERIC_OK) return status;
        unpack(out,&converted);
    } else if (kind == 0) {
        unpack(out,input);
    } else {
        memset(out,0,10); out[9] = 0xf3;
    }
    return FX_NUMERIC_OK;
}
static int initial_eligibility(const decimal_scratch dividend,
                                const decimal_scratch divisor)
{
    const uint8_t threshold[2] = {0x10,0};
    uint8_t distance[2], difference[2];
    if (dividend[1] >= 5 || divisor[1] >= 5 ||
        exponent_at_least_ten(dividend) || exponent_at_least_ten(divisor) ||
        dividend[9] == 0 || divisor[9] == 0) return 0;
    if (subtract_prefix(distance,dividend,divisor))
        (void)subtract_prefix(distance,divisor,dividend);
    return subtract_prefix(difference,distance,threshold) != 0;
}
static void truncate_integral(decimal_scratch number)
{
    /* The preceding raw division has normalized its result and corrected
     * both packed prefix pairs. Live wrapper traces verify this precondition
     * before every non-F truncation, including all raw exponent/sign bytes. */
    unsigned biased;
    if (number[9] >= 0xf0) return;
    biased = biased_exponent(number);
    if (biased < 100) { memset(number,0,10); return; }
    if (biased >= 114) return;
    unsigned fractional_positions = 114u - biased;
    for (unsigned i = 0; i < fractional_positions; ++i)
        number[2 + i / 2] &= (i & 1u) ? 0x0f : 0xf0;
    fx_raw_decimal_normalize(number);
}
/* Native cancellation policy counts vanished high nibbles before ordinary
 * normalization. Thirteen vanished positions clear all low four digits. */
static void suppress_cancellation(decimal_scratch number)
{
    unsigned vanished = 0;
    if (number[9] >= 0xf0) return;
    for (unsigned i = 10; i > 2; --i) {
        uint8_t pair = number[i - 1];
        if (pair >= 15) break;
        ++vanished;
        if (pair != 0) break;
        ++vanished;
    }
    if (vanished >= 13) number[2] = number[3] = 0;
    fx_raw_decimal_normalize(number);
}
static unsigned trailing_zeros(const decimal_scratch x)
{
    unsigned count = 0;
    for (unsigned i = 2; i < 10; ++i) {
        if (x[i] & 15u) break;
        ++count;
        if (x[i]) break;
        ++count;
    }
    return count;
}
static int remainder_eligibility(const decimal_scratch quotient,
                                  const decimal_scratch remainder)
{
    /* The original accepts an internal error-valued quotient before the
     * ordinary exponent/remainder gates; two normalized F3 inputs expose it. */
    if (quotient[9] >= 0xf0) return 1;
    if (exponent_at_least_ten(quotient)) return 0;
    if (!remainder[9]) return 1;
    if (exponent_at_least_ten(remainder)) return 0;
    const uint8_t threshold[2] = {0x11,1};
    uint8_t adjusted[2], difference[2];
    unsigned count = trailing_zeros(remainder), carry = 0;
    uint8_t packed_count = (uint8_t)(count < 10 ? count : count + 6);
    adjusted[0] = fx_raw_decimal_pair_add(remainder[0],packed_count,&carry);
    adjusted[1] = fx_raw_decimal_pair_add(remainder[1],0,&carry);
    return !subtract_prefix(difference,adjusted,threshold);
}

fx_numeric_status fx_number_quotient_remainder(
    fx_quotient_remainder_result *result,
    const fx_number *dividend, const fx_number *divisor)
{
    fx_number a, b;
    fx_quotient_remainder_result value;
    decimal_scratch left, right, quotient, product, remainder;
    fx_numeric_status status;
    int accepted = 0;
    if (!result || !dividend || !divisor) return FX_NUMERIC_INVALID;
    a = *dividend; b = *divisor;
    /* Native preprocessor replaces the second surd, then the first surd,
     * in their source slots before the ordinary scalar admission test. */
    if ((b.bytes[0] & 0xf0) == 0x80) {
        status = fx_number_to_decimal(&b,&b);
        if (status != FX_NUMERIC_OK) return FX_NUMERIC_UNIMPLEMENTED;
    }
    if ((a.bytes[0] & 0xf0) == 0x80) {
        status = fx_number_to_decimal(&a,&a);
        if (status != FX_NUMERIC_OK) return FX_NUMERIC_UNIMPLEMENTED;
    }
    if (a.bytes[0] >= 0xf0 || b.bytes[0] >= 0xf0) {
        fx_number_error(&value.quotient,3);
        value.remainder = b; value.firmware_status = 3;
        *result = value; return FX_NUMERIC_OK;
    }
    /* The ordinary marker is cleared in scratch, not in the source copies.
     * Both normal and fallback paths export newly packed scratch records. */
    a.bytes[0] &= 0xbf; b.bytes[0] &= 0xbf;
    status = normalize_scalar(left,&a);
    if (status != FX_NUMERIC_OK) return status;
    status = normalize_scalar(right,&b);
    if (status != FX_NUMERIC_OK) return status;
    if (initial_eligibility(left,right)) {
        status = fx_raw_decimal_divide(quotient,left,right);
        if (status != FX_NUMERIC_OK) return status;
        truncate_integral(quotient);
        status = fx_raw_decimal_multiply(product,quotient,right);
        if (status != FX_NUMERIC_OK) return status;
        if (product[9] < 0xf0) {
            unsigned carry = 0;
            product[1] = fx_raw_decimal_pair_add(product[1],5,&carry) & 15u;
        }
        status = fx_raw_decimal_sum(remainder,product,left);
        if (status != FX_NUMERIC_OK) return status;
        suppress_cancellation(remainder);
        accepted = remainder_eligibility(quotient,remainder);
    }
    if (!accepted) {
        status = fx_raw_decimal_divide(quotient,left,right);
        if (status != FX_NUMERIC_OK) return status;
        memset(remainder,0,10); remainder[9] = 0x70;
    }
    pack(&value.quotient,quotient); pack(&value.remainder,remainder);
    value.firmware_status = quotient[9] >= 0xf0 ? quotient[9] & 15u : 0;
    *result = value;
    return FX_NUMERIC_OK;
}
