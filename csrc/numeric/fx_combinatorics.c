/* Scalar factorial, permutations, combinations and percent.
 * GPL-3.0-or-later. No CPU execution or host floating-point arithmetic. */
#include "fx_combinatorics.h"

/* Native191e8 validates both operands against10^10 before entering the
 * shared19300 descending-product loop. Immediate16 is the packed BCD
 * exponent0x10, hence ten and not sixteen. */
static fx_numeric_status nonnegative_integer(int64_t *value, const fx_number *in,
                                             int *valid) {
    fx_number decimal;
    fx_decimal decoded;
    fx_numeric_status status = fx_number_to_decimal(&decimal, in);
    *valid = 0;
    if (status != FX_NUMERIC_OK) return status;
    if (fx_number_kind(&decimal) == FX_NUMBER_ERROR) return FX_NUMERIC_OK;
    if (fx_decimal_decode(&decoded, &decimal) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    if (decoded.sign && decoded.mantissa < UINT64_C(100000000000000))
        return FX_NUMERIC_INVALID;
    if (decoded.sign < 0 || decoded.exponent >= 10 ||
        fx_decimal_to_integer(value, &decimal) != FX_NUMERIC_OK) return FX_NUMERIC_OK;
    *valid = 1;
    return FX_NUMERIC_OK;
}

/* Preserve the firmware's descending order and truncate to its fifteen
 * stored mantissa digits after each multiplication. Do not replace this
 * with an exact integer factorial or a combination recurrence:
 * those change its last stored digits and its intermediate overflow. */
static fx_numeric_status descending_product(fx_number *out, int64_t upper,
                                             int64_t lower) {
    fx_number factor;
    (void)fx_decimal_from_integer(out, 1);
    while (upper > lower) {
        fx_numeric_status status;
        (void)fx_decimal_from_integer(&factor, upper);
        status = fx_decimal_binary(out, out, &factor, FX_MULTIPLY);
        if (status != FX_NUMERIC_OK || fx_number_kind(out) == FX_NUMBER_ERROR)
            return status;
        --upper;
    }
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_number_factorial(fx_number *out, const fx_number *in) {
    int64_t n = 0;
    int valid;
    fx_numeric_status status = nonnegative_integer(&n, in, &valid);
    if (status != FX_NUMERIC_OK) return status;
    if (!valid) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
    return descending_product(out, n, 0);
}

static fx_numeric_status combinatorial(fx_number *out, const fx_number *n_record,
                                        const fx_number *r_record, int combination) {
    fx_number divisor;
    int64_t n = 0, r = 0;
    int n_valid, r_valid;
    fx_numeric_status status = nonnegative_integer(&n, n_record, &n_valid);
    if (status != FX_NUMERIC_OK) return status;
    status = nonnegative_integer(&r, r_record, &r_valid);
    if (status != FX_NUMERIC_OK) return status;
    if (!n_valid || !r_valid || r > n) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    /*19262 compares n-r with r, swaps the saved bound when needed and keeps
     * the smaller of the two as the factorial divisor. This finite decimal
     * order is symmetric, but differs from a stepwise binomial recurrence. */
    if (combination && r > n - r) r = n - r;
    status = descending_product(out, n, n - r);
    if (status != FX_NUMERIC_OK || fx_number_kind(out) == FX_NUMBER_ERROR || !combination)
        return status;
    /* Native1933e runs a second factorial only after the numerator succeeds.
     * nCr can therefore overflow even when its mathematical result fits. */
    status = descending_product(&divisor, r, 0);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_number_kind(&divisor) == FX_NUMBER_ERROR) {
        *out = divisor; return FX_NUMERIC_OK;
    }
    return fx_decimal_binary(out, out, &divisor, FX_DIVIDE);
}

fx_numeric_status fx_number_permutation(fx_number *out, const fx_number *n,
                                        const fx_number *r) {
    return combinatorial(out, n, r, 0);
}

fx_numeric_status fx_number_combination(fx_number *out, const fx_number *n,
                                        const fx_number *r) {
    return combinatorial(out, n, r, 1);
}

static uint64_t gcd(uint64_t a, uint64_t b) {
    while (b) { uint64_t remainder = a % b; a = b; b = remainder; }
    return a;
}

/*18118 scales each unpacked surd term and reduces its coefficient/divisor
 * independently. If17616 cannot repack the two terms,1770c evaluates those
 * scaled components in their original order. Combining equal radicands
 * before this fallback would change the last decimal digit. */
static fx_numeric_status surd_percent_fallback(fx_number *out, const fx_number *in) {
    fx_number components[6], sum;
    unsigned term;
    fx_numeric_status status = fx_surd_unpack(components, in);
    if (status != FX_NUMERIC_OK) return status;
    fx_number_zero(&sum);
    for (term = 0; term < 2; ++term) {
        int64_t coefficient, radicand, denominator;
        uint64_t common, absolute;
        unsigned factor;
        fx_number c, rad, den, value;
        if (fx_decimal_to_integer(&coefficient, &components[term * 3]) != FX_NUMERIC_OK ||
            fx_decimal_to_integer(&radicand, &components[term * 3 + 1]) != FX_NUMERIC_OK ||
            fx_decimal_to_integer(&denominator, &components[term * 3 + 2]) != FX_NUMERIC_OK)
            return FX_NUMERIC_INVALID;
        if (!coefficient) continue;
        if (radicand < 1 || radicand > 999 || denominator < 1 || denominator > 99)
            return FX_NUMERIC_INVALID;
        for (factor = 2; factor * factor <= (unsigned)radicand; ++factor) {
            while (radicand % (int64_t)(factor * factor) == 0) {
                radicand /= (int64_t)(factor * factor);
                coefficient *= (int64_t)factor;
            }
        }
        denominator *= 100;
        absolute = (uint64_t)(coefficient < 0 ? -coefficient : coefficient);
        common = gcd(absolute, (uint64_t)denominator);
        coefficient /= (int64_t)common; denominator /= (int64_t)common;
        (void)fx_decimal_from_integer(&c, coefficient);
        (void)fx_decimal_from_integer(&rad, radicand);
        (void)fx_decimal_from_integer(&den, denominator);
        status = fx_decimal_sqrt(&value, &rad);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&value, &value, &c, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&value, &value, &den, FX_DIVIDE);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&sum, &sum, &value, FX_ADD);
        if (status != FX_NUMERIC_OK) return status;
    }
    *out = sum; return FX_NUMERIC_OK;
}

fx_numeric_status fx_number_percent(fx_number *out, const fx_number *in) {
    fx_number input = *in, hundred;
    fx_numeric_status status;
    if (fx_number_kind(in) == FX_NUMBER_ERROR) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    input.bytes[0] &= (uint8_t)~0x40;
    (void)fx_decimal_from_integer(&hundred, 100);
    status = fx_number_binary(out, &input, &hundred, FX_DIVIDE);
    if (status == FX_NUMERIC_OK && fx_number_kind(&input) == FX_NUMBER_SURD &&
        fx_number_kind(out) == FX_NUMBER_DECIMAL)
        return surd_percent_fallback(out, &input);
    return status;
}
