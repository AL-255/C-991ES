/* Readable real power dispatch for fx-991ES PLUS C. GPL-3.0-or-later. */
#include "fx_transcend.h"
#include "fx_transcend_internal.h"

static uint64_t magnitude(int64_t value) {
    return value < 0 ? (uint64_t)(-(value + 1)) + 1 : (uint64_t)value;
}

static int short_power(const fx_number *exponent, int *value) {
    int64_t integer;
    if (fx_number_kind(exponent) != FX_NUMBER_DECIMAL ||
        fx_number_fractional_status(exponent) ||
        fx_decimal_to_integer(&integer, exponent) != FX_NUMERIC_OK) return 0;
    if (integer != -1 && integer != 2 && integer != 3) return 0;
    *value = (int)integer;
    return 1;
}

/* 0x197b8..0x19892 raises the two expanded rational components separately.
 * It accepts the reconstructed result only when it is still a rational
 * record. A collapsed integer or an oversized fraction takes the original
 * decimal power path instead of dividing the independently rounded powers. */
static int rational_integer_power(fx_number *out, const fx_number *base,
                                   const fx_number *exponent) {
    fx_rational fraction, result;
    fx_number numerator, denominator, positive_exponent, powered_n, powered_d;
    fx_decimal e;
    int64_t n, d;
    uint64_t absolute_n;
    if (fx_number_kind(base) != FX_NUMBER_RATIONAL ||
        fx_number_kind(exponent) != FX_NUMBER_DECIMAL ||
        fx_number_fractional_status(exponent) ||
        fx_rational_decode(&fraction, base) != FX_NUMERIC_OK ||
        fx_decimal_decode(&e, exponent) != FX_NUMERIC_OK) return 0;
    absolute_n = magnitude(fraction.numerator);
    if (absolute_n > (uint64_t)INT64_MAX || fraction.denominator > (uint64_t)INT64_MAX) return 0;
    (void)fx_decimal_from_integer(&numerator, (int64_t)absolute_n);
    (void)fx_decimal_from_integer(&denominator, (int64_t)fraction.denominator);
    positive_exponent = *exponent;
    if (e.sign < 0) {
        fx_number swap = numerator; numerator = denominator; denominator = swap;
        positive_exponent.bytes[9] = (uint8_t)(positive_exponent.bytes[9] - 5);
    }
    if (fx_transcend_power_decimal(&powered_n, &numerator, &positive_exponent) != FX_NUMERIC_OK ||
        fx_transcend_power_decimal(&powered_d, &denominator, &positive_exponent) != FX_NUMERIC_OK ||
        fx_decimal_integer_cleanup(&powered_n) != FX_NUMERIC_OK ||
        fx_decimal_integer_cleanup(&powered_d) != FX_NUMERIC_OK ||
        fx_number_fractional_status(&powered_n) || fx_number_fractional_status(&powered_d) ||
        fx_decimal_to_integer(&n, &powered_n) != FX_NUMERIC_OK ||
        fx_decimal_to_integer(&d, &powered_d) != FX_NUMERIC_OK || !d) return 0;
    if (fraction.numerator < 0) {
        int64_t integer;
        if (fx_decimal_to_integer(&integer, exponent) != FX_NUMERIC_OK) return 0;
        if (magnitude(integer) % 2) n = -n;
    }
    result.numerator = n; result.denominator = (uint64_t)d; result.flags = 0;
    if (fx_rational_encode(out, &result) != FX_NUMERIC_OK ||
        fx_number_kind(out) != FX_NUMBER_RATIONAL) return 0;
    return 1;
}

fx_numeric_status fx_number_power(fx_number *out, const fx_number *base,
                                  const fx_number *exponent) {
    fx_number b = *base, e = *exponent, decimal_exponent;
    fx_number_type bkind = fx_number_kind(&b), ekind = fx_number_kind(&e);
    int fast;
    if (bkind == FX_NUMBER_ERROR || ekind == FX_NUMBER_ERROR) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    if (bkind == FX_NUMBER_DECIMAL) b.bytes[0] &= (uint8_t)~0x40;
    if (ekind == FX_NUMBER_DECIMAL) e.bytes[0] &= (uint8_t)~0x40;
    if (short_power(&e, &fast)) return fx_number_integer_power(out, &b, fast);
    /* 0x1740a converts both radical operands before the general scalar path.
     * The short reciprocal/square/cube paths above retain their exact forms. */
    if (bkind == FX_NUMBER_SURD) {
        fx_numeric_status status = fx_number_to_decimal(&b, &b);
        if (status != FX_NUMERIC_OK) return status;
        bkind = fx_number_kind(&b);
    }
    if (ekind == FX_NUMBER_SURD) {
        fx_numeric_status status = fx_number_to_decimal(&e, &e);
        if (status != FX_NUMERIC_OK) return status;
        ekind = fx_number_kind(&e);
    }
    /* 0x111be..0x111cc also rejects marked rational headers. */
    if ((b.bytes[0] & 0xf0) >= 0x30 || (e.bytes[0] & 0xf0) >= 0x30) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    if ((bkind != FX_NUMBER_DECIMAL && bkind != FX_NUMBER_RATIONAL) ||
        (ekind != FX_NUMBER_DECIMAL && ekind != FX_NUMBER_RATIONAL)) return FX_NUMERIC_UNIMPLEMENTED;
    /* Negative bases first attempt 0x112b6's short fractional recognition.
     * An integer recognition is deliberately not substituted. */
    if (b.bytes[9] >= 4 && ekind == FX_NUMBER_DECIMAL) {
        fx_rational recognized;
        if (fx_number_recognize_rational(&recognized, &e) && recognized.denominator > 1 &&
            fx_rational_encode(&decimal_exponent, &recognized) == FX_NUMERIC_OK &&
            fx_number_kind(&decimal_exponent) == FX_NUMBER_RATIONAL) {
            e = decimal_exponent; ekind = FX_NUMBER_RATIONAL;
        }
    }
    if (b.bytes[9] >= 4 && ekind == FX_NUMBER_RATIONAL) {
        /* 0x1954c accepts an odd reduced denominator, saves numerator parity,
         * then divides the fraction without the ordinary conversion cleanup. */
        fx_rational fraction;
        fx_number numerator, denominator;
        fx_numeric_status status;
        int negative_result;
        if (fx_rational_decode(&fraction, &e) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
        if (!(fraction.denominator % 2)) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
        negative_result = (int)(magnitude(fraction.numerator) % 2);
        b.bytes[9] = (uint8_t)(b.bytes[9] - 5);
        (void)fx_decimal_from_integer(&numerator, fraction.numerator);
        if (fraction.denominator > (uint64_t)INT64_MAX) return FX_NUMERIC_UNREPRESENTABLE;
        (void)fx_decimal_from_integer(&denominator, (int64_t)fraction.denominator);
        status = fx_decimal_binary(&decimal_exponent, &numerator, &denominator, FX_DIVIDE);
        if (status != FX_NUMERIC_OK) return status;
        status = fx_transcend_power_decimal(out, &b, &decimal_exponent);
        if (status == FX_NUMERIC_OK && negative_result)
            out->bytes[9] = (uint8_t)((out->bytes[9] + 5) % 10);
        return status;
    }
    if (rational_integer_power(out, &b, &e)) return FX_NUMERIC_OK;
    return fx_transcend_power_decimal(out, &b, &e);
}
