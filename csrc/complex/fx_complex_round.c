/* Readable numeric precision policy for scalar15CBE and complex15D36.
 * GPL-3.0-or-later. Decimal values remain integers; no CPU or ROM execution. */
#include "fx_complex_round.h"

static uint64_t power10(unsigned exponent)
{
    uint64_t value = 1;
    while (exponent--) value *= 10;
    return value;
}

/* CC90 rounds retained decimal digits half away from zero. Its native R2
 * includes a leading workspace guard digit: 15CE0 passes significant+1.
 * At exponent99 the retry truncates the original rather than overflowing. */
static void round_significant(fx_decimal *value, int significant)
{
    uint64_t original, unit;
    if (!value->mantissa || significant >= 15) return;
    if (significant < 0) {
        value->mantissa = 0; value->sign = 0; value->exponent = 0; return;
    }
    if (!significant) {
        if (value->mantissa >= UINT64_C(500000000000000)) {
            value->mantissa = UINT64_C(100000000000000); ++value->exponent;
        } else {
            value->mantissa = 0; value->sign = 0; value->exponent = 0;
        }
        return;
    }
    original = value->mantissa;
    unit = power10((unsigned)(15 - significant));
    value->mantissa = ((original + unit / 2) / unit) * unit;
    if (value->mantissa < UINT64_C(1000000000000000)) return;
    if (value->exponent == 99) value->mantissa = original / unit * unit;
    else { value->mantissa /= 10; ++value->exponent; }
}

static int has_fractional_part(const fx_decimal *value)
{
    if (!value->mantissa || value->exponent >= 14) return 0;
    if (value->exponent < 0) return 1;
    return value->mantissa % power10((unsigned)(14 - value->exponent)) != 0;
}

fx_numeric_status fx_scalar_display_round(fx_number *out, const fx_number *in,
                                          uint8_t display_mode, uint8_t digits,
                                          uint8_t *firmware_status)
{
    fx_number value, scale;
    fx_decimal decimal;
    fx_numeric_status status;
    if (!out || !in || !firmware_status || digits > 9) return FX_NUMERIC_INVALID;
    value = *in;
    /* 15C82 converts a surd first, but tests the header before clearing40.
     * Thus a marked rational6x is rejected rather than converted to decimal. */
    if (fx_number_kind(&value) == FX_NUMBER_SURD) {
        status = fx_number_to_decimal(&value, &value);
        if (status != FX_NUMERIC_OK) return status;
    }
    if (value.bytes[0] > 0x4f) {
        *out = value; *firmware_status = 3; return FX_NUMERIC_OK;
    }
    value.bytes[0] &= (uint8_t)~0x40;
    status = fx_number_to_decimal(&value, &value);
    if (status != FX_NUMERIC_OK) return status;
    if (value.bytes[0] >= 0xf0) {
        *out = value; *firmware_status = 3; return FX_NUMERIC_OK;
    }
    status = fx_decimal_decode(&decimal, &value);
    if (status != FX_NUMERIC_OK) return status;
    if (display_mode == 8) {
        /* D030 computes the stored fractional part. An exact integer exits
         * before scaling, preserving all fifteen digits regardless of Fix. */
        if (has_fractional_part(&decimal)) {
            fx_decimal scale_decimal = {1, digits, UINT64_C(100000000000000), 0};
            status = fx_decimal_encode(&scale, &scale_decimal);
            if (status == FX_NUMERIC_OK)
                status = fx_decimal_binary(&value, &value, &scale, FX_MULTIPLY);
            if (status == FX_NUMERIC_OK) status = fx_decimal_decode(&decimal, &value);
            if (status != FX_NUMERIC_OK) return status;
            round_significant(&decimal, decimal.exponent + 1);
            status = fx_decimal_encode(&value, &decimal);
            if (status == FX_NUMERIC_OK)
                status = fx_decimal_binary(&value, &value, &scale, FX_DIVIDE);
            if (status != FX_NUMERIC_OK) return status;
        }
    } else {
        unsigned significant = display_mode == 9 && digits ? digits : 10;
        round_significant(&decimal, (int)significant);
        status = fx_decimal_encode(&value, &decimal);
        if (status != FX_NUMERIC_OK) return status;
    }
    *out = value; *firmware_status = value.bytes[0] >= 0xf0 ? 3 : 0;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_complex_display_round(fx_complex *out, const fx_complex *in,
                                           uint8_t display_mode, uint8_t digits,
                                           uint8_t *firmware_status)
{
    fx_complex value;
    fx_numeric_status status;
    uint8_t numerical_status;
    if (!out || !in || !firmware_status || digits > 9) return FX_NUMERIC_INVALID;
    value = *in;
    /* The wrapper completes imaginary rounding before looking at the real
     * component. A rejected imaginary record leaves the real bytes intact. */
    status = fx_scalar_display_round(&value.imaginary, &value.imaginary,
                                     display_mode, digits, &numerical_status);
    if (status != FX_NUMERIC_OK) return status;
    if (!numerical_status) {
        status = fx_scalar_display_round(&value.real, &value.real,
                                         display_mode, digits, &numerical_status);
        if (status != FX_NUMERIC_OK) return status;
    }
    *out = value; *firmware_status = numerical_status; return FX_NUMERIC_OK;
}
