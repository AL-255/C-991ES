/* Readable decimal factor algorithms, translated from extracted firmware.
 * GPL-3.0-or-later. No firmware execution or host floating-point arithmetic. */
#include "fx_transcend.h"

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
