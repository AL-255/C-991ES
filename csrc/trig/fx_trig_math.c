/* Decimal digit rotations and forward trigonometry. GPL-3.0-or-later.
 *
 * The rotation workspace has eighteen decimal digits: the fifteen stored
 * mantissa digits, a leading normalization position, and two guard digits.
 * A uint64_t holds that bounded decimal coordinate without binary rounding.
 * No host floating point or firmware execution is used here.
 */
#include "fx_trig_math.h"

#define COORDINATE_MODULUS UINT64_C(1000000000000000000)
#define LEADING_POSITION UINT64_C(10000000000000000)

/* ROM data 1A2E..1A91: (2/pi)*atan(10^-k)*10^k, k=0..9,
 * represented in the eighteen-digit rotation coordinate scale. */
static const uint64_t angular_steps[10] = {
    UINT64_C(50000000000000000), UINT64_C(63451034861107139),
    UINT64_C(63659855298165103), UINT64_C(63661956016111788),
    UINT64_C(63661977024551545), UINT64_C(63661977234636068),
    UINT64_C(63661977236736914), UINT64_C(63661977236757922),
    UINT64_C(63661977236758132), UINT64_C(63661977236758134)
};

static uint64_t shift_right(uint64_t value, unsigned digits)
{
    if (digits >= 18) return 0;
    while (digits--) value /= 10;
    return value;
}

static unsigned rotation_position(unsigned index, int passed_zero)
{
    unsigned ones = index % 10;
    return index >= 90 && ones && !passed_zero ? 10 - ones : 0;
}

static fx_numeric_status encode_coordinate(fx_number *out, uint64_t mantissa,
                                          int exponent)
{
    fx_decimal value = {1, exponent, mantissa, 0};
    if (!mantissa) { fx_number_zero(out); return FX_NUMERIC_OK; }
    while (value.mantissa >= UINT64_C(1000000000000000)) {
        value.mantissa /= 10; ++value.exponent;
    }
    while (value.mantissa < UINT64_C(100000000000000)) {
        value.mantissa *= 10; --value.exponent;
    }
    if (value.exponent < -99) { fx_number_zero(out); return FX_NUMERIC_OK; }
    return fx_decimal_encode(out, &value);
}

fx_numeric_status fx_angle_convert(fx_number *out, const fx_number *angle,
                                  fx_angle_unit from, fx_angle_unit to)
{
    static const fx_number pi = {{0x03,0x14,0x15,0x92,0x65,0x35,0x89,0x80,0x00,0x01}};
    static const fx_number degree_to_grad = {{0x01,0x11,0x11,0x11,0x11,0x11,0x11,0x11,0x00,0x01}};
    static const fx_number grad_to_degree = {{0x09,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x99,0x00}};
    fx_number decimal, factor;
    fx_decimal value;
    fx_numeric_status status;
    if (!out || !angle || from < FX_DEGREES || from > FX_GRADIANS ||
        to < FX_DEGREES || to > FX_GRADIANS) return FX_NUMERIC_INVALID;
    if (fx_number_kind(angle) == FX_NUMBER_ERROR) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    if (from == to && fx_number_kind(angle) != FX_NUMBER_SURD) {
        *out = *angle; return FX_NUMERIC_OK;
    }
    status = fx_number_to_decimal(&decimal, angle);
    if (status != FX_NUMERIC_OK) return status;
    if (from == to) { *out = decimal; return FX_NUMERIC_OK; }
    if (fx_decimal_decode(&value, &decimal) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    value.flags = 0; (void)fx_decimal_encode(&decimal, &value);
    if (from != FX_RADIANS && to != FX_RADIANS) {
        factor = from == FX_DEGREES ? degree_to_grad : grad_to_degree;
        return fx_decimal_binary(out, &decimal, &factor, FX_MULTIPLY);
    }
    (void)fx_decimal_from_integer(&factor,
                                  from == FX_GRADIANS || to == FX_GRADIANS ? 200 : 180);
    if (to == FX_RADIANS) {
        status = fx_decimal_binary(&decimal, &decimal, &factor, FX_DIVIDE);
        if (status == FX_NUMERIC_OK)
            status = fx_decimal_binary(out, &decimal, &pi, FX_MULTIPLY);
    } else {
        status = fx_decimal_binary(&decimal, &decimal, &factor, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK)
            status = fx_decimal_binary(out, &decimal, &pi, FX_DIVIDE);
    }
    return status;
}

fx_numeric_status fx_trig_decimal_pair(fx_number *cosine_coordinate,
                                      fx_number *sine_coordinate,
                                      const fx_number *quarter_turn_fraction)
{
    fx_decimal argument;
    uint64_t residual, rotations = 0, horizontal;
    unsigned index, position, level;
    int passed_zero = 0, exponent;
    fx_number cosine, sine;
    fx_numeric_status status;
    if (!cosine_coordinate || !sine_coordinate || !quarter_turn_fraction ||
        fx_decimal_decode(&argument, quarter_turn_fraction) != FX_NUMERIC_OK ||
        argument.flags || argument.sign < 0 ||
        (argument.mantissa && argument.exponent > -1))
        return FX_NUMERIC_INVALID;
    residual = argument.mantissa * 100;
    index = (unsigned)((argument.exponent + 100) % 100);

    /* Eliminate angle digits, recording the number of rotations at each
     * decimal position. The stored table is reused below position nine. */
    if (residual) {
        do {
            uint64_t step, count;
            position = rotation_position(index, passed_zero);
            step = angular_steps[position ? position - 1 : 9];
            count = residual / step;
            residual %= step;
            rotations = (rotations + count) % COORDINATE_MODULUS;
            if (rotations >= LEADING_POSITION) break;
            residual = residual * 10 % COORDINATE_MODULUS;
            rotations = rotations * 10 % COORDINATE_MODULUS;
            if (!index) { index = 99; passed_zero = 1; }
            else --index;
        } while (1);
    }

    /* Reconstruct the coordinate pair, one saved count digit at a time.
     * x += y; y -= old_x * 10^(-2k). Coordinates remain bounded modulo
     * 10^18, reproducing the original decimal workspace carry behavior. */
    horizontal = UINT64_C(100000000000000000);
    for (level = 0; level < 17; ++level) {
        uint64_t previous = residual;
        unsigned count = (unsigned)(rotations % 10);
        unsigned displacement = 2 * rotation_position(index, passed_zero);
        while (count--) {
            residual = (residual + horizontal) % COORDINATE_MODULUS;
            if (displacement >= 2) {
                uint64_t correction = shift_right(previous, displacement - 2);
                horizontal = (horizontal + COORDINATE_MODULUS - correction)
                             % COORDINATE_MODULUS;
            }
            previous = residual;
        }
        rotations -= rotations % 10;
        if (level != 16) {
            residual /= 10; rotations /= 10;
            index = (index + 1) % 100;
        }
    }

    /* Normalize and round the vertical coordinate using its two guard
     * digits. The horizontal coordinate is stored by truncation. */
    exponent = (int)index - 100;
    if (residual) {
        while (residual < LEADING_POSITION) { residual *= 10; --exponent; }
        while (residual >= LEADING_POSITION * 10) { residual /= 10; ++exponent; }
        residual += 50;
    }
    status = encode_coordinate(&sine, residual / 100, exponent);
    if (status != FX_NUMERIC_OK) return status;
    status = encode_coordinate(&cosine, horizontal / 100, -1);
    if (status != FX_NUMERIC_OK) return status;
    *cosine_coordinate = cosine; *sine_coordinate = sine;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_trig_decimal(fx_number *out, const fx_number *angle,
                                 fx_trig_function function, fx_angle_unit unit)
{
    /* A694 constants before the two-position exponent adjustment. Keeping
     * that adjustment separate preserves the native multiplication order. */
    static const fx_number reciprocal[3] = {
        {{0x01,0x11,0x11,0x11,0x11,0x11,0x11,0x11,0x00,0x01}},
        {{0x06,0x36,0x61,0x97,0x72,0x36,0x75,0x79,0x01,0x01}},
        {{0x01,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01}}
    };
    static const fx_number quarter_angle[3] = {
        {{0x09,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01,0x01}},
        {{0x01,0x57,0x07,0x96,0x32,0x67,0x94,0x90,0x00,0x01}},
        {{0x01,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x02,0x01}}
    };
    fx_number original, scaled, factor, count, offset, fraction;
    fx_number horizontal, vertical, numerator, denominator, result, one;
    fx_decimal value;
    uint64_t rounded = 0, divisor = 1;
    unsigned quadrant, shift;
    int original_sign, residual_sign, result_sign, offset_exponent, original_exponent;
    int has_offset;
    fx_numeric_status status;
    if (!out || !angle || function < FX_SINE || function > FX_TANGENT ||
        unit < FX_DEGREES || unit > FX_GRADIANS) return FX_NUMERIC_INVALID;
    if (fx_number_kind(angle) == FX_NUMBER_ERROR ||
        fx_number_kind(angle) == FX_NUMBER_UNSUPPORTED) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    status = fx_number_to_decimal(&original, angle);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_decimal_decode(&value, &original) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    original_sign = value.sign < 0 ? -1 : 1;
    original_exponent = value.exponent;
    value.sign = value.mantissa ? 1 : 0; value.flags = 0;
    status = fx_decimal_encode(&original, &value);
    if (status != FX_NUMERIC_OK) return status;
    factor = reciprocal[unit];
    (void)fx_decimal_decode(&value, &factor); value.exponent -= 2;
    (void)fx_decimal_encode(&factor, &value);
    status = fx_decimal_binary(&scaled, &original, &factor, FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) return status;
    (void)fx_decimal_integer_cleanup(&scaled);
    if (fx_decimal_decode(&value, &scaled) != FX_NUMERIC_OK) {
        *out = scaled; return FX_NUMERIC_OK;
    }
    if (value.mantissa && value.exponent >= 8) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    if (value.mantissa && value.exponent >= -1) {
        shift = (unsigned)(14 - value.exponent);
        while (shift--) divisor *= 10;
        rounded = (value.mantissa + divisor / 2) / divisor;
    }
    quadrant = (unsigned)(rounded % 4);
    (void)fx_decimal_from_integer(&count, (int64_t)rounded);
    status = fx_decimal_binary(&offset, &count, &quarter_angle[unit], FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) return status;
    (void)fx_decimal_integer_cleanup(&offset);
    (void)fx_decimal_decode(&value, &offset);
    offset_exponent = value.exponent; has_offset = value.mantissa != 0;
    status = fx_decimal_binary(&fraction, &original, &offset, FX_SUBTRACT);
    if (status != FX_NUMERIC_OK) return status;
    /* Reverse subtraction BB3A enables its cancellation filter (3B=1).
     * A residue occupying only the last three aligned guard positions is
     * discarded, unlike the ordinary public subtraction entry. */
    if (has_offset && fx_decimal_decode(&value, &fraction) == FX_NUMERIC_OK && value.mantissa &&
        value.exponent < (original_exponent > offset_exponent ?
                          original_exponent : offset_exponent) - 12)
        fx_number_zero(&fraction);
    status = fx_decimal_binary(&fraction, &fraction, &reciprocal[unit], FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) return status;
    (void)fx_decimal_integer_cleanup(&fraction);
    if (fx_decimal_decode(&value, &fraction) != FX_NUMERIC_OK) {
        *out = fraction; return FX_NUMERIC_OK;
    }
    residual_sign = value.sign < 0 ? -1 : 1;
    value.sign = value.mantissa ? 1 : 0; value.exponent -= 2;
    if (value.mantissa && value.exponent < -99) fx_number_zero(&fraction);
    else if (fx_decimal_encode(&fraction, &value) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    status = fx_trig_decimal_pair(&horizontal, &vertical, &fraction);
    if (status != FX_NUMERIC_OK) return status;

    /* The quarter-turn parity selects which coordinate occupies the
     * numerator; signs are restored after the unsigned reconstruction. */
    if ((quadrant & 1) ^ (function == FX_COSINE)) {
        numerator = horizontal; denominator = vertical;
    } else { numerator = vertical; denominator = horizontal; }
    if (function == FX_SINE)
        result_sign = original_sign * ((quadrant == 0) ? residual_sign :
                       (quadrant == 1) ? 1 : (quadrant == 2) ? -residual_sign : -1);
    else if (function == FX_COSINE)
        result_sign = quadrant == 0 ? 1 : quadrant == 1 ? -residual_sign :
                      quadrant == 2 ? -1 : residual_sign;
    else result_sign = original_sign * residual_sign * ((quadrant & 1) ? -1 : 1);

    (void)fx_decimal_decode(&value, &numerator);
    if (function == FX_TANGENT || !value.mantissa || value.exponent < -10) {
        status = fx_decimal_binary(&result, &numerator, &denominator, FX_DIVIDE);
    } else {
        /* Native sine/cosine reconstruction: reciprocal of
         * sqrt((other/selected)^2+1). Each decimal operation truncates at
         * the same boundary as the original arithmetic routine. */
        status = fx_decimal_binary(&result, &denominator, &numerator, FX_DIVIDE);
        if (status == FX_NUMERIC_OK)
            status = fx_decimal_binary(&result, &result, &result, FX_MULTIPLY);
        (void)fx_decimal_from_integer(&one, 1);
        if (status == FX_NUMERIC_OK)
            status = fx_decimal_binary(&result, &result, &one, FX_ADD);
        if (status == FX_NUMERIC_OK)
            status = fx_decimal_binary(&result, &one, &result, FX_DIVIDE);
        if (status == FX_NUMERIC_OK) status = fx_decimal_sqrt(&result, &result);
    }
    if (status != FX_NUMERIC_OK) return status;
    if (result_sign < 0) {
        if (fx_number_kind(&result) == FX_NUMBER_ERROR) result.bytes[9] = 5;
        else status = fx_number_negate(&result, &result);
    }
    if (status == FX_NUMERIC_OK) *out = result;
    return status;
}

fx_numeric_status fx_trig_evaluate(fx_number *out, const fx_number *angle,
                                  fx_trig_function function, fx_angle_unit unit,
                                  int exact_math, unsigned *matched)
{
    fx_number decimal;
    fx_numeric_status status = fx_trig_decimal(&decimal, angle, function, unit);
    if (matched) *matched = 0;
    if (status != FX_NUMERIC_OK) return status;
    if (fx_number_kind(&decimal) == FX_NUMBER_ERROR) {
        *out = decimal; return FX_NUMERIC_OK;
    }
    return fx_trig_special_result(out, &decimal, function, exact_math, matched);
}
