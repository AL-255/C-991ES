/* Real nth-root/cube-root numeric dispatch. GPL-3.0-or-later. */
#include "fx_root.h"
#include "fx_transcend_internal.h"

static uint64_t magnitude(int64_t value) {
    return value < 0 ? (uint64_t)(-(value + 1)) + 1 : (uint64_t)value;
}

/* 0x197b8..0x19892 retains an exact rational only when both component roots
 * clean to finite integers and the constructed result still has rational tag. */
static int rational_integer_root(fx_number *out, const fx_number *radicand,
                                  const fx_number *degree) {
    fx_rational fraction, result;
    fx_number numerator, denominator, positive_degree, rooted_n, rooted_d;
    fx_decimal d;
    int64_t n, den;
    if (fx_number_kind(radicand) != FX_NUMBER_RATIONAL ||
        fx_number_kind(degree) != FX_NUMBER_DECIMAL ||
        fx_number_fractional_status(degree) ||
        fx_rational_decode(&fraction, radicand) != FX_NUMERIC_OK ||
        fx_decimal_decode(&d, degree) != FX_NUMERIC_OK) return 0;
    if (fraction.denominator > (uint64_t)INT64_MAX) return 0;
    (void)fx_decimal_from_integer(&numerator, fraction.numerator);
    (void)fx_decimal_from_integer(&denominator, (int64_t)fraction.denominator);
    positive_degree = *degree;
    if (d.sign < 0) {
        fx_number swap = numerator; numerator = denominator; denominator = swap;
        positive_degree.bytes[9] = (uint8_t)(positive_degree.bytes[9] - 5);
    }
    if (fx_transcend_root_decimal(&rooted_n, &numerator, &positive_degree) != FX_NUMERIC_OK ||
        fx_transcend_root_decimal(&rooted_d, &denominator, &positive_degree) != FX_NUMERIC_OK ||
        fx_decimal_integer_cleanup(&rooted_n) != FX_NUMERIC_OK ||
        fx_decimal_integer_cleanup(&rooted_d) != FX_NUMERIC_OK ||
        fx_number_fractional_status(&rooted_n) || fx_number_fractional_status(&rooted_d) ||
        fx_decimal_to_integer(&n, &rooted_n) != FX_NUMERIC_OK ||
        fx_decimal_to_integer(&den, &rooted_d) != FX_NUMERIC_OK || !den) return 0;
    if (den < 0) n = -n;
    result.numerator = n; result.denominator = magnitude(den); result.flags = 0;
    if (fx_rational_encode(out, &result) != FX_NUMERIC_OK ||
        fx_number_kind(out) != FX_NUMBER_RATIONAL) return 0;
    return 1;
}

fx_numeric_status fx_number_nthroot(fx_number *out, const fx_number *radicand,
                                    const fx_number *degree) {
    fx_number b = *radicand, d = *degree, decimal_degree;
    fx_number_type bkind = fx_number_kind(&b), dkind = fx_number_kind(&d);
    if (bkind == FX_NUMBER_ERROR || dkind == FX_NUMBER_ERROR) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    if (bkind == FX_NUMBER_DECIMAL) b.bytes[0] &= (uint8_t)~0x40;
    if (dkind == FX_NUMBER_DECIMAL) d.bytes[0] &= (uint8_t)~0x40;
    if (bkind == FX_NUMBER_SURD) {
        fx_numeric_status status = fx_number_to_decimal(&b, &b);
        if (status != FX_NUMERIC_OK) return status;
        bkind = fx_number_kind(&b);
    }
    if (dkind == FX_NUMBER_SURD) {
        fx_numeric_status status = fx_number_to_decimal(&d, &d);
        if (status != FX_NUMERIC_OK) return status;
        dkind = fx_number_kind(&d);
    }
    if ((b.bytes[0] & 0xf0) >= 0x30 || (d.bytes[0] & 0xf0) >= 0x30) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    if ((bkind != FX_NUMBER_DECIMAL && bkind != FX_NUMBER_RATIONAL) ||
        (dkind != FX_NUMBER_DECIMAL && dkind != FX_NUMBER_RATIONAL)) return FX_NUMERIC_UNIMPLEMENTED;
    if (b.bytes[9] >= 4 && dkind == FX_NUMBER_DECIMAL) {
        fx_rational recognized;
        if (fx_number_recognize_rational(&recognized, &d) && recognized.denominator > 1 &&
            fx_rational_encode(&decimal_degree, &recognized) == FX_NUMERIC_OK &&
            fx_number_kind(&decimal_degree) == FX_NUMBER_RATIONAL) {
            d = decimal_degree; dkind = FX_NUMBER_RATIONAL;
        }
    }
    if (b.bytes[9] >= 4 && dkind == FX_NUMBER_RATIONAL) {
        /* Root mode tests the reciprocal fraction: odd numerator is needed,
         * and denominator parity supplies the saved output sign. */
        fx_rational fraction;
        fx_number numerator, denominator;
        fx_numeric_status status;
        int negative_result;
        if (fx_rational_decode(&fraction, &d) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
        if (!(magnitude(fraction.numerator) % 2)) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
        negative_result = (int)(fraction.denominator % 2);
        b.bytes[9] = (uint8_t)(b.bytes[9] - 5);
        (void)fx_decimal_from_integer(&numerator, fraction.numerator);
        if (fraction.denominator > (uint64_t)INT64_MAX) return FX_NUMERIC_UNREPRESENTABLE;
        (void)fx_decimal_from_integer(&denominator, (int64_t)fraction.denominator);
        status = fx_decimal_binary(&decimal_degree, &numerator, &denominator, FX_DIVIDE);
        if (status != FX_NUMERIC_OK) return status;
        status = fx_transcend_root_decimal(out, &b, &decimal_degree);
        if (status == FX_NUMERIC_OK && negative_result)
            out->bytes[9] = (uint8_t)((out->bytes[9] + 5) % 10);
        return status;
    }
    if (rational_integer_root(out, &b, &d)) return FX_NUMERIC_OK;
    return fx_transcend_root_decimal(out, &b, &d);
}

fx_numeric_status fx_number_cbrt(fx_number *out, const fx_number *in) {
    fx_number source = *in, degree;
    fx_number_type kind = fx_number_kind(&source);
    /* 0x1ab50 clears header40 for both scalar formats in the unary wrapper. */
    if (kind == FX_NUMBER_DECIMAL || kind == FX_NUMBER_RATIONAL) source.bytes[0] &= (uint8_t)~0x40;
    fx_decimal_from_u8(&degree, 3);
    return fx_number_nthroot(out, &source, &degree);
}
