/* Readable decimal factor algorithms, translated from extracted firmware.
 * GPL-3.0-or-later. No firmware execution or host floating-point arithmetic. */
#include "fx_transcend.h"
#include "fx_transcend_internal.h"

#define COORDINATE_MODULUS UINT64_C(1000000000000000000)
#define COORDINATE_ONE UINT64_C(10000000000000000)

/* 0x1966..0x1a23: scaled log10(1 + 10^-k), retained as the exact
 * eighteen-digit decimal coordinates loaded by original 0x1b11a.
 * Entry zero is the limiting coefficient log10(e). */
static const uint64_t logarithm_coefficient[19] = {
    UINT64_C(43429448190325183), UINT64_C(30102999566398120),
    UINT64_C(41392685158225041), UINT64_C(43213737826425743),
    UINT64_C(43407747931864067), UINT64_C(43427276862669637),
    UINT64_C(43429231044531869), UINT64_C(43429426475615564),
    UINT64_C(43429446018852918), UINT64_C(43429447973177943),
    UINT64_C(43429448168610459), UINT64_C(43429448188153710),
    UINT64_C(43429448190108036), UINT64_C(43429448190303468),
    UINT64_C(43429448190323011), UINT64_C(43429448190324966),
    UINT64_C(43429448190325161), UINT64_C(43429448190325181),
    UINT64_C(43429448190325183)
};

/* Normalized seventeen-digit value. The two extra digits are significant:
 * 0x18b30 preserves them in workspace8021, and ln's 0x1b788 division uses
 * them before the final fifteen-digit external record is serialized. */
typedef struct { uint64_t mantissa; int exponent, sign; } guarded_decimal;

static uint64_t decimal_power(unsigned exponent) {
    uint64_t value = 1;
    while (exponent--) value *= 10;
    return value;
}

static guarded_decimal logarithm_mantissa(uint64_t residual, uint64_t product) {
    guarded_decimal result = {0, 0, 0};
    uint64_t counts = 0;
    unsigned factor = 0, pass;
    int position = -1;
    if (!residual) return result;

    /* 0x1acb6 forward decomposition. Before the eighteenth factor, every
     * subtraction advances product by product/10^factor. Beyond that point
     * the fixed precision uses plain decimal quotient digits. */
    for (;;) {
        while (residual >= product) {
            residual -= product;
            ++counts;
            if (factor < 18)
                product = (product + product / decimal_power(factor)) % COORDINATE_MODULUS;
        }
        if (counts >= COORDINATE_ONE) break;
        residual = residual * 10 % COORDINATE_MODULUS;
        counts = counts * 10 % COORDINATE_MODULUS;
        --position;
        ++factor;
    }

    /* The saved pass counter starts at hexadecimal10 and decrements without
     * decimal adjustment: there are exactly seventeen reconstruction passes.
     * Each count selects a ROM logarithm coefficient at its decimal scale. */
    for (pass = 0; pass < 17; ++pass) {
        unsigned index = factor < 18 ? factor + 1 : 0;
        residual = (residual + counts % 10 * logarithm_coefficient[index]) % COORDINATE_MODULUS;
        counts /= 10;
        if (pass != 16) {
            residual /= 10;
            ++position;
            --factor;
        }
    }

    /* 0x1af04 normalizes eighteen working digits, then adds half of the two
     * discarded guard digits before preserving the fifteen-digit mantissa. */
    while (residual < COORDINATE_ONE) { residual *= 10; --position; }
    while (residual >= COORDINATE_ONE * 10) { residual /= 10; ++position; }
    result.mantissa = (residual + 50) / 100 * 100;
    result.exponent = position;
    result.sign = 1;
    if (result.mantissa >= COORDINATE_ONE * 10) {
        result.mantissa /= 10;
        ++result.exponent;
    }
    return result;
}

static guarded_decimal logarithm_value(const fx_decimal *input) {
    guarded_decimal fraction, result;
    unsigned whole;
    int exponent = 0, gap;
    uint64_t mantissa;
    if (input->exponent < 0) {
        /* 0x1abf4 uses 10-m and starting product m. This computes log10(10/m)
         * directly, avoiding cancellation when a value is just below one. */
        fraction = logarithm_mantissa((UINT64_C(1000000000000000) - input->mantissa) * 100,
                                      input->mantissa * 100);
        whole = (unsigned)(-input->exponent - 1);
    } else {
        fraction = logarithm_mantissa((input->mantissa - UINT64_C(100000000000000)) * 100,
                                      COORDINATE_ONE);
        whole = (unsigned)input->exponent;
    }
    if (!whole) {
        fraction.sign = fraction.mantissa ? (input->exponent < 0 ? -1 : 1) : 0;
        return fraction;
    }
    mantissa = whole;
    while (mantissa >= 10) { mantissa /= 10; ++exponent; }
    mantissa = (uint64_t)whole * decimal_power((unsigned)(16 - exponent));
    gap = exponent - fraction.exponent;
    if (fraction.mantissa && gap <= 17)
        mantissa += fraction.mantissa / decimal_power((unsigned)gap);
    if (mantissa >= COORDINATE_ONE * 10) { mantissa /= 10; ++exponent; }
    result.mantissa = mantissa;
    result.exponent = exponent;
    result.sign = input->exponent < 0 ? -1 : 1;
    return result;
}

static fx_numeric_status logarithm(fx_number *out, const fx_number *in, int natural) {
    fx_number decimal;
    fx_decimal input, result;
    guarded_decimal value;
    fx_numeric_status status = fx_number_to_decimal(&decimal, in);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_number_kind(&decimal) == FX_NUMBER_ERROR) {
        fx_number_error(out, 3);
        return FX_NUMERIC_OK;
    }
    if (fx_decimal_decode(&input, &decimal) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    if (input.sign <= 0) {
        fx_number_error(out, 3);
        return FX_NUMERIC_OK;
    }
    /* Native working records are normalized. Reject a malformed external
     * record before the unsigned mantissa differences enter the factor loop. */
    if (input.mantissa < UINT64_C(100000000000000)) return FX_NUMERIC_INVALID;
    value = logarithm_value(&input);
    result.sign = value.sign;
    result.exponent = value.exponent;
    result.flags = 0;
    result.mantissa = value.mantissa / 100;
    if (natural && value.mantissa) {
        /* 0x1ac84 loads the stored fifteen-digit log10(e), then 0x1b788
         * divides the seventeen-digit numerator without discarding its tail. */
        const uint64_t divisor = UINT64_C(43429448190325100);
        uint64_t remainder = value.mantissa;
        unsigned digit;
        ++result.exponent;
        result.mantissa = 0;
        if (remainder < divisor) { remainder *= 10; --result.exponent; }
        for (digit = 0; digit < 15; ++digit) {
            result.mantissa = result.mantissa * 10 + remainder / divisor;
            remainder = remainder % divisor * 10;
        }
    }
    return fx_decimal_encode(out, &result);
}

fx_numeric_status fx_number_ln(fx_number *out, const fx_number *in) {
    return logarithm(out, in, 1);
}

fx_numeric_status fx_number_log10(fx_number *out, const fx_number *in) {
    return logarithm(out, in, 0);
}

/* 0x1b8d0 multiplies by the seventeen stored digits of log10(e), retaining
 * two guard digits for the exponentiator. The product needs thirty-two digits;
 * schoolbook decimal multiplication avoids a nonportable wide integer type. */
static guarded_decimal guarded_product(const guarded_decimal *coefficient, const fx_decimal *input) {
    guarded_decimal result = {0, 0, 0};
    unsigned char xdigits[15], ydigits[17], product[33] = {0};
    uint64_t x = input->mantissa, y = coefficient->mantissa;
    unsigned i, j, count = 32;
    for (i = 0; i < 15; ++i) { xdigits[i] = (unsigned char)(x % 10); x /= 10; }
    for (i = 0; i < 17; ++i) { ydigits[i] = (unsigned char)(y % 10); y /= 10; }
    for (i = 0; i < 15; ++i) {
        unsigned carry = 0;
        for (j = 0; j < 17; ++j) {
            unsigned value = product[i+j] + xdigits[i] * ydigits[j] + carry;
            product[i+j] = (unsigned char)(value % 10);
            carry = value / 10;
        }
        product[i+17] = (unsigned char)carry;
    }
    while (count && !product[count-1]) --count;
    if (!count) return result;
    result.exponent = input->exponent + coefficient->exponent + (int)count - 31;
    if (result.exponent < -99) return result;
    for (i = 0; i < 17; ++i)
        result.mantissa = result.mantissa * 10 + product[count-1-i];
    result.sign = input->sign * coefficient->sign;
    return result;
}

/* 0x1acd8 is the reverse factor algorithm. Decompose the logarithmic input
 * by coefficient subtraction, then reconstruct the multiplicative factors.
 * Its result is 10^input - 1; the caller separately adds one at stored precision. */
static guarded_decimal exponential_remainder(uint64_t residual, int position) {
    guarded_decimal result = {0, 0, 0};
    uint64_t counts = 0, product = COORDINATE_ONE * 10;
    unsigned factor = (unsigned)(-1 - position), pass;
    if (!residual) return result;
    for (;;) {
        unsigned index = factor < 18 ? factor + 1 : 0;
        uint64_t coefficient = logarithm_coefficient[index];
        while (residual >= coefficient) { residual -= coefficient; ++counts; }
        if (counts >= COORDINATE_ONE) break;
        residual = residual * 10 % COORDINATE_MODULUS;
        counts = counts * 10 % COORDINATE_MODULUS;
        --position;
        ++factor;
    }
    for (pass = 0; pass < 17; ++pass) {
        unsigned count = (unsigned)(counts % 10);
        while (count--) {
            residual = (residual + product) % COORDINATE_MODULUS;
            if (factor < 18)
                product = (product + product / decimal_power(factor)) % COORDINATE_MODULUS;
        }
        counts /= 10;
        if (pass != 16) {
            residual /= 10;
            ++position;
            --factor;
        }
    }
    while (residual < COORDINATE_ONE) { residual *= 10; --position; }
    while (residual >= COORDINATE_ONE * 10) { residual /= 10; ++position; }
    result.mantissa = (residual + 50) / 100 * 100;
    result.exponent = position;
    result.sign = 1;
    if (result.mantissa >= COORDINATE_ONE * 10) {
        result.mantissa /= 10;
        ++result.exponent;
    }
    return result;
}

static fx_numeric_status exponentiate_guarded(fx_number *out, guarded_decimal argument, int round_integer) {
    fx_number one, remainder, value;
    fx_decimal result;
    guarded_decimal fraction;
    uint64_t coordinate;
    unsigned whole = 0;
    fx_numeric_status status;
    (void)fx_decimal_from_integer(&one, 1);
    if (!argument.mantissa) { *out = one; return FX_NUMERIC_OK; }
    if (argument.exponent >= 2) {
        if (argument.sign < 0) fx_number_zero(out);
        else fx_number_error(out, 3);
        return FX_NUMERIC_OK;
    }
    coordinate = argument.mantissa;
    if (argument.exponent >= 0) {
        whole = (unsigned)(coordinate / decimal_power((unsigned)(16 - argument.exponent)));
        coordinate = coordinate * decimal_power((unsigned)(argument.exponent + 1)) % (COORDINATE_ONE * 10);
        argument.exponent = -1;
    }
    /* 0x1aa2a reserves the low nibble of the guard byte: the logarithmic
     * argument reaches the factor loop with sixteen significant digits. */
    coordinate = coordinate / 10 * 10;
    fraction = exponential_remainder(coordinate, argument.exponent);
    result.sign = fraction.sign; result.exponent = fraction.exponent;
    result.mantissa = fraction.mantissa / 100; result.flags = 0;
    status = fx_decimal_encode(&remainder, &result);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_decimal_binary(&value, &remainder, &one, FX_ADD);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_decimal_decode(&result, &value) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    result.exponent += (int)whole;
    status = fx_decimal_encode(&value, &result);
    if (status != FX_NUMERIC_OK) return status;
    /* 0x1b332 rounds the finite positive result to an integer when both
     * original power operands were classified integral. It runs before the
     * reciprocal for a negative logarithmic argument. */
    if (round_integer && fx_number_kind(&value) != FX_NUMBER_ERROR && result.exponent < 14) {
        uint64_t integral = 0;
        if (result.exponent >= -1)
            integral = (result.mantissa / decimal_power((unsigned)(13 - result.exponent)) + 5) / 10;
        status = fx_decimal_from_integer(&value, (int64_t)integral);
        if (status != FX_NUMERIC_OK) return status;
    }
    if (argument.sign < 0) {
        if (fx_number_kind(&value) == FX_NUMBER_ERROR) { fx_number_zero(out); return FX_NUMERIC_OK; }
        return fx_decimal_binary(out, &one, &value, FX_DIVIDE);
    }
    *out = value;
    return FX_NUMERIC_OK;
}

static fx_numeric_status exponential(fx_number *out, const fx_number *in, int natural) {
    fx_number source;
    fx_decimal input;
    guarded_decimal argument;
    fx_numeric_status status = fx_number_to_decimal(&source, in);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_number_kind(&source) == FX_NUMBER_ERROR) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
    if (fx_decimal_decode(&input, &source) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    if (!input.sign) { (void)fx_decimal_from_integer(out, 1); return FX_NUMERIC_OK; }
    if (input.mantissa < UINT64_C(100000000000000)) return FX_NUMERIC_INVALID;
    if (natural) {
        guarded_decimal coefficient = {logarithm_coefficient[0], -1, 1};
        argument = guarded_product(&coefficient, &input);
    } else {
        argument.mantissa = input.mantissa * 100;
        argument.exponent = input.exponent;
        argument.sign = input.sign;
    }
    return exponentiate_guarded(out, argument, 0);
}

fx_numeric_status fx_number_exp(fx_number *out, const fx_number *in) {
    return exponential(out, in, 1);
}

fx_numeric_status fx_number_exp10(fx_number *out, const fx_number *in) {
    return exponential(out, in, 0);
}

static int power_integer(const fx_decimal *value, int *odd) {
    *odd = 0;
    if (!value->sign) return 1;
    if (value->exponent < 0) return 0;
    if (value->exponent > 14) return 1;
    if (value->exponent == 14) { *odd = (int)(value->mantissa % 2); return 1; }
    if (value->exponent >= 10) {
        /* 0x1b542's middle-exponent branch checks the stored low digit and
         * takes parity from the next digit, preserving its original policy. */
        if (value->mantissa % 10) return 0;
        *odd = (int)(value->mantissa / 10 % 2);
        return 1;
    }
    {
        uint64_t divisor = decimal_power((unsigned)(14 - value->exponent));
        if (value->mantissa % divisor) return 0;
        *odd = (int)(value->mantissa / divisor % 2);
        return 1;
    }
}

static guarded_decimal guarded_quotient(const guarded_decimal *numerator, const fx_decimal *denominator) {
    guarded_decimal result = {0, 0, 0};
    uint64_t remainder = numerator->mantissa, divisor = denominator->mantissa * 100;
    unsigned digit;
    int shifted = 0;
    if (!remainder) return result;
    result.exponent = numerator->exponent - denominator->exponent;
    if (remainder < divisor) { remainder *= 10; --result.exponent; shifted = 1; }
    for (digit = 0; digit < 17; ++digit) {
        result.mantissa = result.mantissa * 10 + remainder / divisor;
        remainder = remainder % divisor * 10;
    }
    /* 0x1ba42 shifts a leading-zero quotient by one nibble. The last
     * division guard digit is lost only in that normalization branch. */
    if (shifted) result.mantissa = result.mantissa / 10 * 10;
    result.sign = numerator->sign * denominator->sign;
    if (result.exponent < -99) { result.mantissa = 0; result.sign = 0; }
    return result;
}

static fx_numeric_status real_power_decimal(fx_number *out, const fx_number *base,
                                             const fx_number *exponent, int initial_root) {
    fx_number brecord, erecord, one, reciprocal;
    fx_decimal b, e, degree;
    guarded_decimal logarithm, argument;
    int exponent_integral, base_integral, exponent_odd, unused_odd, root = initial_root, negate = 0;
    fx_numeric_status status;
    if ((base->bytes[0] & 0xf0) >= 0x30 || (exponent->bytes[0] & 0xf0) >= 0x30) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    status = fx_number_to_decimal(&brecord, base);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_number_to_decimal(&erecord, exponent);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_number_kind(&brecord) == FX_NUMBER_ERROR || fx_number_kind(&erecord) == FX_NUMBER_ERROR) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    if (fx_decimal_decode(&b, &brecord) != FX_NUMERIC_OK ||
        fx_decimal_decode(&e, &erecord) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    if ((b.sign && b.mantissa < UINT64_C(100000000000000)) ||
        (e.sign && e.mantissa < UINT64_C(100000000000000))) return FX_NUMERIC_INVALID;
    if (initial_root && !e.sign) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
    exponent_integral = power_integer(&e, &exponent_odd);
    degree = e;
    if (!exponent_integral) {
        (void)fx_decimal_from_integer(&one, 1);
        status = fx_decimal_binary(&reciprocal, &one, &erecord, FX_DIVIDE);
        if (status != FX_NUMERIC_OK) return status;
        if (fx_decimal_decode(&degree, &reciprocal) != FX_NUMERIC_OK) {
            fx_number_error(out, 3); return FX_NUMERIC_OK;
        }
        /* 0x1a8a4 flips between root and power once for an integral
         * reciprocal. If both classify nonintegral, it restores the original
         * operand and operation rather than using a twice-rounded reciprocal. */
        exponent_integral = power_integer(&degree, &exponent_odd);
        if (exponent_integral) root = !root;
        else degree = e;
    }
    if (b.sign < 0) {
        if (!exponent_integral || (root && !exponent_odd)) {
            fx_number_error(out, 3); return FX_NUMERIC_OK;
        }
        negate = exponent_odd;
        b.sign = 1;
    }
    if (!b.sign) {
        if (e.sign <= 0) fx_number_error(out, 3);
        else fx_number_zero(out);
        return FX_NUMERIC_OK;
    }
    base_integral = power_integer(&b, &unused_odd);
    logarithm = logarithm_value(&b);
    argument = root ? guarded_quotient(&logarithm, &degree) : guarded_product(&logarithm, &degree);
    if (argument.mantissa && argument.exponent > 99) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
    status = exponentiate_guarded(out, argument, exponent_integral && base_integral && !root);
    /* 0x1a92e adds the saved sign directly even to zero and error records. */
    if (status == FX_NUMERIC_OK && negate) out->bytes[9] = (uint8_t)((out->bytes[9] + 5) % 10);
    return status;
}

fx_numeric_status fx_transcend_power_decimal(fx_number *out, const fx_number *base,
                                             const fx_number *exponent) {
    return real_power_decimal(out, base, exponent, 0);
}

fx_numeric_status fx_transcend_root_decimal(fx_number *out, const fx_number *radicand,
                                            const fx_number *degree) {
    return real_power_decimal(out, radicand, degree, 1);
}
