/* Decimal inverse angular rotations. GPL-3.0-or-later. */
#include "fx_trig_inverse.h"

#define DECIMAL_COORDINATE_LIMIT UINT64_C(1000000000000000000)
#define SAVED_ROTATION_LIMIT UINT64_C(10000000000000000)
static const uint64_t inverse_steps[10] = {
    UINT64_C(50000000000000000), UINT64_C(63451034861107139),
    UINT64_C(63659855298165103), UINT64_C(63661956016111788),
    UINT64_C(63661977024551545), UINT64_C(63661977234636068),
    UINT64_C(63661977236736914), UINT64_C(63661977236757922),
    UINT64_C(63661977236758132), UINT64_C(63661977236758134)
};

static unsigned inverse_position(unsigned index, int passed_zero)
{
    unsigned ones = index % 10;
    return index >= 90 && ones && !passed_zero ? 10 - ones : 0;
}
static uint64_t decimal_shift(uint64_t coordinate, unsigned positions)
{
    if (positions >= 18) return 0;
    while (positions--) coordinate /= 10;
    return coordinate;
}

fx_numeric_status fx_atan_quarter_fraction(fx_number *out, const fx_number *in)
{
    fx_decimal argument, result;
    uint64_t residual, horizontal = SAVED_ROTATION_LIMIT, rotations = 0;
    unsigned index, position, level;
    int passed_zero = 0;
    if (!out || !in || fx_decimal_decode(&argument, in) != FX_NUMERIC_OK ||
        argument.flags || argument.sign < 0 ||
        (argument.mantissa && (argument.exponent > 0 ||
         (argument.exponent == 0 && argument.mantissa > UINT64_C(100000000000000)))))
        return FX_NUMERIC_INVALID;
    residual = argument.mantissa * 100 +
               (argument.mantissa && argument.exponent == 0 ? 1 : 0);
    index = (unsigned)((argument.exponent + 99) % 100);
    if (residual) {
        do {
            unsigned displacement = 2 * inverse_position(index, passed_zero);
            while (residual >= horizontal) {
                uint64_t previous = residual;
                residual -= horizontal;
                rotations = (rotations + 1) % DECIMAL_COORDINATE_LIMIT;
                if (displacement >= 2)
                    horizontal = (horizontal + decimal_shift(previous, displacement - 2))
                                 % DECIMAL_COORDINATE_LIMIT;
            }
            if (rotations >= SAVED_ROTATION_LIMIT) break;
            residual = residual * 10 % DECIMAL_COORDINATE_LIMIT;
            rotations = rotations * 10 % DECIMAL_COORDINATE_LIMIT;
            if (!index) { index = 99; passed_zero = 1; }
            else --index;
        } while (1);
    }
    for (level = 0; level < 17; ++level) {
        position = inverse_position(index, passed_zero);
        residual = (residual + inverse_steps[position ? position - 1 : 9] * (rotations % 10))
                   % DECIMAL_COORDINATE_LIMIT;
        rotations -= rotations % 10;
        if (level != 16) {
            residual /= 10; rotations /= 10; index = (index + 1) % 100;
        }
    }
    result.sign = 1; result.exponent = (int)index - 100; result.flags = 0;
    if (!residual) { fx_number_zero(out); return FX_NUMERIC_OK; }
    while (residual < SAVED_ROTATION_LIMIT) { residual *= 10; --result.exponent; }
    while (residual >= SAVED_ROTATION_LIMIT * 10) { residual /= 10; ++result.exponent; }
    result.mantissa = (residual + 50) / 100;
    if (result.mantissa >= UINT64_C(1000000000000000)) {
        result.mantissa /= 10; ++result.exponent;
    }
    if (result.exponent < -99) { fx_number_zero(out); return FX_NUMERIC_OK; }
    return fx_decimal_encode(out, &result);
}

static int decimal_less(const fx_number *a, const fx_number *b)
{
    fx_decimal x, y;
    (void)fx_decimal_decode(&x, a); (void)fx_decimal_decode(&y, b);
    if (!x.mantissa) return y.mantissa != 0;
    if (!y.mantissa) return 0;
    return x.exponent < y.exponent || (x.exponent == y.exponent && x.mantissa < y.mantissa);
}

fx_numeric_status fx_trig_inverse_decimal(fx_number *out, const fx_number *in,
                                         fx_trig_function function, fx_angle_unit unit)
{
    static const fx_number quarter[3] = {
        {{0x09,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01,0x01}},
        {{0x01,0x57,0x07,0x96,0x32,0x67,0x94,0x90,0x00,0x01}},
        {{0x01,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x02,0x01}}
    };
    fx_number original, absolute, one, other, low, high, fraction, angle;
    fx_decimal value;
    fx_numeric_status status;
    int negative, reciprocal;
    if (!out || !in || function < FX_SINE || function > FX_TANGENT ||
        unit < FX_DEGREES || unit > FX_GRADIANS) return FX_NUMERIC_INVALID;
    if (fx_number_kind(in) == FX_NUMBER_ERROR || fx_number_kind(in) == FX_NUMBER_UNSUPPORTED) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    status = fx_number_to_decimal(&original, in);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_decimal_decode(&value, &original) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    negative = value.sign < 0; value.flags = 0;
    (void)fx_decimal_encode(&original, &value);
    value.sign = value.mantissa ? 1 : 0; (void)fx_decimal_encode(&absolute, &value);
    (void)fx_decimal_from_integer(&one, 1);
    other = one;
    if (function != FX_TANGENT) {
        /* Preserve the domain-reconstruction order: (1+x)*(1-x),
         * rather than computing1-x*x at a different precision boundary. */
        status = fx_decimal_binary(&low, &one, &original, FX_SUBTRACT);
        if (status == FX_NUMERIC_OK)
            status = fx_decimal_binary(&high, &one, &original, FX_ADD);
        if (status == FX_NUMERIC_OK)
            status = fx_decimal_binary(&other, &high, &low, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK) status = fx_decimal_sqrt(&other, &other);
        if (status != FX_NUMERIC_OK) return status;
        if (fx_number_kind(&other) == FX_NUMBER_ERROR) {
            *out = other; if (negative) out->bytes[9] = 5;
            return FX_NUMERIC_OK;
        }
    }
    reciprocal = !decimal_less(&absolute, &other);
    status = reciprocal ? fx_decimal_binary(&fraction, &other, &absolute, FX_DIVIDE)
                        : fx_decimal_binary(&fraction, &absolute, &other, FX_DIVIDE);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_atan_quarter_fraction(&fraction, &fraction);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_decimal_binary(&angle, &fraction, &quarter[unit], FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) return status;
    (void)fx_decimal_integer_cleanup(&angle);
    if (reciprocal) {
        if (function == FX_COSINE && !negative) { *out = angle; return FX_NUMERIC_OK; }
        status = fx_decimal_binary(&angle, &quarter[unit], &angle, FX_SUBTRACT);
        if (status != FX_NUMERIC_OK) return status;
    }
    if (negative) {
        status = fx_number_negate(&angle, &angle);
        if (status != FX_NUMERIC_OK) return status;
    }
    if (function == FX_COSINE) {
        status = fx_decimal_binary(&angle, &quarter[unit], &angle, FX_SUBTRACT);
        if (status != FX_NUMERIC_OK) return status;
    }
    *out = angle; return FX_NUMERIC_OK;
}
