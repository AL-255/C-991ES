/* Decimal quadrant reduction and coordinate formulas. GPL-3.0-or-later. */
#include "fx_complex_angle.h"
#include "../trig/fx_trig_inverse.h"

static void coordinate_error(fx_complex *out)
{
    fx_number_error(&out->real, 3); fx_number_error(&out->imaginary, 3);
}

static int coordinate_zero(const fx_number *value)
{
    fx_decimal decimal;
    return fx_decimal_decode(&decimal, value) == FX_NUMERIC_OK && !decimal.mantissa;
}

static fx_numeric_status argument_scalar(fx_number *out, const fx_number *x,
                                          const fx_number *y, fx_angle_unit unit,
                                          const fx_complex_preparation *preparation)
{
    static const fx_number quarter[3] = {
        {{0x09,0,0,0,0,0,0,0,0x01,0x01}},
        {{0x01,0x57,0x07,0x96,0x32,0x67,0x94,0x90,0,0x01}},
        {{0x01,0,0,0,0,0,0,0,0x02,0x01}}
    };
    fx_number real, imaginary, ratio, angle, half;
    fx_decimal a, b;
    fx_numeric_status status;
    int x_negative, y_negative;
    if (x->bytes[0] >= 0xf0 || y->bytes[0] >= 0xf0) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    /*17442 prepares the right coordinate before falling through17470 to
     * prepare the left coordinate. Both records are copied mathematical
     * inputs; the callback commits only each actual conversion stage. */
    status = preparation && preparation->decimal ?
        preparation->decimal(&imaginary, y, preparation->userdata) :
        fx_number_to_decimal(&imaginary, y);
    if (status == FX_NUMERIC_OK) status = preparation && preparation->decimal ?
        preparation->decimal(&real, x, preparation->userdata) :
        fx_number_to_decimal(&real, x);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_decimal_decode(&a, &real) != FX_NUMERIC_OK ||
        fx_decimal_decode(&b, &imaginary) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    if (!a.mantissa && !b.mantissa) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
    x_negative = a.sign < 0; y_negative = b.sign < 0;
    a.sign = a.mantissa ? 1 : 0; a.flags = 0;
    b.sign = b.mantissa ? 1 : 0; b.flags = 0;
    (void)fx_decimal_encode(&real, &a); (void)fx_decimal_encode(&imaginary, &b);
    /* Native18D78 always stores y/x first. The inverse tangent may then
     * store1/(y/x); computing x/y directly crosses a different truncation
     * boundary and changes the final low digits. */
    if (!a.mantissa) { angle = quarter[unit]; status = FX_NUMERIC_OK; }
    else {
        status = fx_decimal_binary(&ratio, &imaginary, &real, FX_DIVIDE);
        if (status == FX_NUMERIC_OK && ratio.bytes[0] >= 0xf0) angle = quarter[unit];
        else if (status == FX_NUMERIC_OK)
            status = fx_trig_inverse_decimal(&angle, &ratio, FX_TANGENT, unit);
    }
    if (status == FX_NUMERIC_OK && x_negative) {
        status = fx_decimal_binary(&half, &quarter[unit], &quarter[unit], FX_ADD);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&angle, &half, &angle, FX_SUBTRACT);
    }
    if (status == FX_NUMERIC_OK && y_negative) status = fx_number_negate(&angle, &angle);
    if (status == FX_NUMERIC_OK) *out = angle;
    return status;
}

fx_numeric_status fx_complex_argument_with_preparation(fx_complex *out,
    const fx_complex *in, fx_angle_unit unit,
    const fx_complex_preparation *preparation)
{
    fx_complex result;
    fx_number real, imaginary;
    fx_numeric_status status;
    if (!out || !in || unit < FX_DEGREES || unit > FX_GRADIANS) return FX_NUMERIC_INVALID;
    real = in->real; imaginary = in->imaginary;
    /* 18708 checks the real component's 15C82 preparation status, whose
     * header guard runs before clearing bit40. The imaginary preparation
     * status is not checked before entering the two-coordinate kernel. */
    if (fx_number_kind(&real) == FX_NUMBER_SURD) {
        status = preparation && preparation->decimal ?
            preparation->decimal(&real, &real, preparation->userdata) :
            fx_number_to_decimal(&real, &real);
        if (status != FX_NUMERIC_OK) return status;
    }
    if (real.bytes[0] > 0x4f) {
        fx_number_error(&result.real, 3); fx_number_zero(&result.imaginary);
        *out = result; return FX_NUMERIC_OK;
    }
    /*18708 performs both15C82 preparations in real/imaginary order. The
     * real guard above is decisive; the imaginary guard's status is ignored.
     * Its compact conversion still commits before the two-coordinate stage. */
    if (preparation && preparation->decimal &&
        fx_number_kind(&imaginary) == FX_NUMBER_SURD) {
        status = preparation->decimal(&imaginary, &imaginary, preparation->userdata);
        if (status != FX_NUMERIC_OK) return status;
    }
    status = argument_scalar(&result.real, &real, &imaginary, unit, preparation);
    fx_number_zero(&result.imaginary);
    if (status == FX_NUMERIC_OK) *out = result;
    return status;
}

fx_numeric_status fx_complex_to_polar_with_preparation(fx_complex *out,
    const fx_complex *in, fx_angle_unit unit, int exact_math,
    const fx_complex_preparation *preparation)
{
    fx_complex radius, result;
    fx_numeric_status status;
    if (!out || !in || unit < FX_DEGREES || unit > FX_GRADIANS ||
        (exact_math != 0 && exact_math != 1)) return FX_NUMERIC_INVALID;
    status = fx_complex_magnitude_with_preparation(&radius, in, exact_math, preparation);
    if (status == FX_NUMERIC_OK)
        status = argument_scalar(&result.imaginary, &in->real, &in->imaginary, unit, preparation);
    if (status != FX_NUMERIC_OK) return status;
    result.real = radius.real;
    /* 1CADE returns success on either zero-axis branch even if C312
     * produced an F3 radius. 18366 preserves that radius and the successful
     * argument; a non-axis magnitude error normalizes both coordinates. */
    if (result.imaginary.bytes[0] >= 0xf0 ||
        (result.real.bytes[0] >= 0xf0 && !coordinate_zero(&in->real) &&
         !coordinate_zero(&in->imaginary)) ||
        in->real.bytes[0] >= 0xf0 || in->imaginary.bytes[0] >= 0xf0)
        coordinate_error(&result);
    *out = result; return FX_NUMERIC_OK;
}

fx_numeric_status fx_complex_argument(fx_complex *out, const fx_complex *in,
    fx_angle_unit unit)
{
    return fx_complex_argument_with_preparation(out, in, unit, NULL);
}

fx_numeric_status fx_complex_to_polar_prepared(fx_complex *out,
    const fx_complex *in, fx_angle_unit unit, int exact_math,
    fx_complex_square_root root, void *userdata)
{
    const fx_complex_preparation preparation = {root, NULL, NULL, NULL, userdata};
    return fx_complex_to_polar_with_preparation(out, in, unit, exact_math, &preparation);
}

fx_numeric_status fx_complex_to_polar(fx_complex *out, const fx_complex *in,
                                      fx_angle_unit unit, int exact_math)
{
    return fx_complex_to_polar_prepared(out, in, unit, exact_math, NULL, NULL);
}

fx_numeric_status fx_complex_from_polar(fx_complex *out, const fx_complex *in,
                                        fx_angle_unit unit, int exact_math)
{
    fx_complex source, result;
    fx_number sine, cosine, decimal;
    fx_decimal radius;
    fx_numeric_status status;
    if (!out || !in || unit < FX_DEGREES || unit > FX_GRADIANS ||
        (exact_math != 0 && exact_math != 1)) return FX_NUMERIC_INVALID;
    source = *in;
    if (source.real.bytes[0] >= 0xf0 || source.imaginary.bytes[0] >= 0xf0) {
        coordinate_error(out); return FX_NUMERIC_OK;
    }
    source.real.bytes[0] &= (uint8_t)~0x40;
    status = fx_number_to_decimal(&decimal, &source.real);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_decimal_decode(&radius, &decimal) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    if (radius.sign < 0) { coordinate_error(out); return FX_NUMERIC_OK; }
    status = fx_trig_evaluate(&sine, &source.imaginary, FX_SINE, unit, exact_math, 0);
    if (status == FX_NUMERIC_OK)
        status = fx_number_binary(&result.imaginary, &source.real, &sine, FX_MULTIPLY);
    if (status == FX_NUMERIC_OK)
        status = fx_trig_evaluate(&cosine, &source.imaginary, FX_COSINE, unit, exact_math, 0);
    if (status == FX_NUMERIC_OK)
        status = fx_number_binary(&result.real, &source.real, &cosine, FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) return status;
    if (result.real.bytes[0] >= 0xf0 || result.imaginary.bytes[0] >= 0xf0)
        coordinate_error(&result);
    *out = result; return FX_NUMERIC_OK;
}
