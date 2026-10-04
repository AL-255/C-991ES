/* Complex formulas with the original scalar operation order.
 * GPL-3.0-or-later. No host floating point or firmware execution. */
#include "fx_complex.h"

unsigned fx_complex_error_status(const fx_complex *value)
{
    if (!value) return 0;
    if (value->real.bytes[0] >= 0xf0) return value->real.bytes[0] & 15;
    return value->imaginary.bytes[0] >= 0xf0 ? value->imaginary.bytes[0] & 15 : 0;
}

fx_numeric_status fx_scalar_numeric_classify(uint8_t *classification,
                                             const fx_number *input)
{
    unsigned header, sign;
    uint8_t result;
    fx_number decimal;
    fx_numeric_status status;
    if (!classification || !input) return FX_NUMERIC_INVALID;
    header = input->bytes[0] & 0xf0;
    if (!input->bytes[0]) result = 1;
    else if (header == 0x80) {
        sign = input->bytes[9] ? input->bytes[8] + input->bytes[9] : input->bytes[8];
        if (input->bytes[9] && sign == 7) {
            status = fx_number_to_decimal(&decimal, input);
            if (status != FX_NUMERIC_OK) return status;
            sign = decimal.bytes[9];
        }
        /* The surd branch deliberately bypasses the ordinary zero test. */
        result = sign >= 4 ? 2 : 4;
    } else if (header >= 0x50) result = 0xf0;
    else if (!input->bytes[8] && !input->bytes[9]) result = 1;
    else result = input->bytes[9] >= 4 ? 2 : 4;
    *classification = result;
    return FX_NUMERIC_OK;
}

static unsigned scalar_error_status(const fx_number *number)
{
    return number->bytes[0] >= 0xf0 ? number->bytes[0] & 15 : 0;
}

static int canonical_component_zero(const fx_number *number)
{
    fx_decimal value;
    return fx_decimal_decode(&value, number) == FX_NUMERIC_OK && !value.mantissa;
}

fx_numeric_status fx_complex_firmware_status(uint8_t *firmware_status,
                                             fx_complex_return_kind kind,
                                             const fx_complex *input,
                                             const fx_complex *result)
{
    unsigned real, imaginary, numerical;
    fx_number prepared;
    uint8_t classification;
    fx_numeric_status status;
    if (!firmware_status || !input || !result ||
        kind < FX_COMPLEX_ARITHMETIC_RETURN || kind > FX_COMPLEX_FROM_POLAR_RETURN)
        return FX_NUMERIC_INVALID;
    real = scalar_error_status(&input->real);
    imaginary = scalar_error_status(&input->imaginary);
    switch (kind) {
    case FX_COMPLEX_CONJUGATE_RETURN:
        numerical = input->real.bytes[0] >= 0xf0 ? 3 : 0; break;
    case FX_COMPLEX_NEGATE_RETURN:
        numerical = imaginary ? imaginary : real; break;
    case FX_COMPLEX_CLEANUP_RETURN:
        /* 18724 returns the original real error directly. Otherwise either
         * component cleanup can overflow; its nonzero return takes18762,
         * which constructs a full Math error and clears the imaginary part. */
        numerical = input->real.bytes[0] >= 0xf0 ? real :
            imaginary || scalar_error_status(&result->real) ||
            scalar_error_status(&result->imaginary) ? 3 : 0;
        break;
    case FX_COMPLEX_MAGNITUDE_RETURN:
        numerical = input->real.bytes[0] >= 0xf0 || input->imaginary.bytes[0] >= 0xf0 ||
                    canonical_component_zero(&input->real) ||
                    canonical_component_zero(&input->imaginary)
                    ? 0 : scalar_error_status(&result->real); break;
    case FX_COMPLEX_SQRT_RETURN:
        /* 1CBFC checks admission, then forces native success after rooting,
         * independently of any root result header. */
        numerical = 3;
        status = fx_scalar_numeric_classify(&classification, &input->imaginary);
        if (status != FX_NUMERIC_OK) return status;
        if (classification != 1) break;
        prepared = input->real;
        if (fx_number_kind(&prepared) == FX_NUMBER_SURD) {
            status = fx_number_to_decimal(&prepared, &prepared);
            if (status != FX_NUMERIC_OK) return status;
        }
        status = fx_scalar_numeric_classify(&classification, &prepared);
        if (status != FX_NUMERIC_OK) return status;
        if (classification != 0xf0) numerical = 0;
        break;
    case FX_COMPLEX_TO_POLAR_RETURN:
        numerical = result->imaginary.bytes[0] >= 0xf0 ? 3 : 0; break;
    default:
        numerical = scalar_error_status(&result->real); break;
    }
    *firmware_status = (uint8_t)numerical;
    return FX_NUMERIC_OK;
}

void fx_complex_zero(fx_complex *out)
{
    fx_number_zero(&out->real); fx_number_zero(&out->imaginary);
}

static void complex_error(fx_complex *out)
{
    fx_number_error(&out->real, 3); fx_number_zero(&out->imaginary);
}

/* 1876C selects the rational division entry when both operands are ordinary
 * decimal records. Exact integer ratios retain a fraction when it fits. */
static fx_numeric_status component_divide(fx_number *out, const fx_number *a,
                                          const fx_number *b)
{
    int64_t numerator, denominator;
    if (a->bytes[0] < 10 && b->bytes[0] < 10 &&
        fx_decimal_to_integer(&numerator, a) == FX_NUMERIC_OK &&
        fx_decimal_to_integer(&denominator, b) == FX_NUMERIC_OK && denominator) {
        fx_rational ratio;
        if (denominator < 0) { numerator = -numerator; denominator = -denominator; }
        ratio.numerator = numerator; ratio.denominator = (uint64_t)denominator; ratio.flags = 0;
        return fx_rational_encode(out, &ratio);
    }
    return fx_number_binary(out, a, b, FX_DIVIDE);
}

fx_numeric_status fx_complex_binary(fx_complex *out, const fx_complex *a,
                                    const fx_complex *b, fx_binary_op operation)
{
    fx_complex left, right, result;
    fx_number first, second, denominator;
    fx_numeric_status status;
    if (!out || !a || !b || operation < FX_ADD || operation > FX_DIVIDE)
        return FX_NUMERIC_INVALID;
    left = *a; right = *b;
    if (left.real.bytes[0] >= 0xf0 || right.real.bytes[0] >= 0xf0) {
        complex_error(out); return FX_NUMERIC_OK;
    }
    /* 18574 clears the metadata marker on the real component only. */
    left.real.bytes[0] &= (uint8_t)~0x40;
    right.real.bytes[0] &= (uint8_t)~0x40;
    if (operation == FX_ADD || operation == FX_SUBTRACT) {
        if (operation == FX_SUBTRACT) {
            status = fx_number_negate(&right.real, &right.real);
            if (status == FX_NUMERIC_OK)
                status = fx_number_negate(&right.imaginary, &right.imaginary);
            if (status != FX_NUMERIC_OK) return status;
        }
        status = fx_number_binary(&result.real, &left.real, &right.real, FX_ADD);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&result.imaginary, &left.imaginary, &right.imaginary, FX_ADD);
    } else if (operation == FX_MULTIPLY) {
        /* The imaginary component is completed before the real component. */
        status = fx_number_binary(&first, &left.real, &right.imaginary, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&second, &left.imaginary, &right.real, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&result.imaginary, &first, &second, FX_ADD);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&first, &left.real, &right.real, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&second, &left.imaginary, &right.imaginary, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&result.real, &first, &second, FX_SUBTRACT);
    } else if (!left.real.bytes[0] && !right.real.bytes[0]) {
        status = component_divide(&result.real, &left.imaginary, &right.imaginary);
        fx_number_zero(&result.imaginary);
    } else if (!left.real.bytes[0] && !right.imaginary.bytes[0]) {
        fx_number_zero(&result.real);
        status = component_divide(&result.imaginary, &left.imaginary, &right.real);
    } else if (!left.imaginary.bytes[0] && !right.real.bytes[0]) {
        fx_number_zero(&result.real);
        status = component_divide(&result.imaginary, &left.real, &right.imaginary);
        if (status == FX_NUMERIC_OK)
            status = fx_number_negate(&result.imaginary, &result.imaginary);
    } else {
        status = fx_number_binary(&first, &right.real, &right.real, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&second, &right.imaginary, &right.imaginary, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&denominator, &second, &first, FX_ADD);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&first, &left.real, &right.imaginary, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&second, &left.imaginary, &right.real, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&first, &second, &first, FX_SUBTRACT);
        if (status == FX_NUMERIC_OK)
            status = component_divide(&result.imaginary, &first, &denominator);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&first, &left.real, &right.real, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&second, &left.imaginary, &right.imaginary, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK)
            status = fx_number_binary(&first, &first, &second, FX_ADD);
        if (status == FX_NUMERIC_OK)
            status = component_divide(&result.real, &first, &denominator);
    }
    if (status != FX_NUMERIC_OK) return status;
    if (result.real.bytes[0] >= 0xf0 || result.imaginary.bytes[0] >= 0xf0)
        complex_error(&result);
    *out = result; return FX_NUMERIC_OK;
}

fx_numeric_status fx_complex_conjugate(fx_complex *out, const fx_complex *in)
{
    fx_complex result;
    fx_numeric_status status;
    if (!out || !in) return FX_NUMERIC_INVALID;
    result = *in;
    if (result.real.bytes[0] >= 0xf0) {
        fx_number_error(&result.real, 3); *out = result; return FX_NUMERIC_OK;
    }
    status = fx_number_negate(&result.imaginary, &result.imaginary);
    if (status == FX_NUMERIC_OK) *out = result;
    return status;
}

fx_numeric_status fx_complex_negate(fx_complex *out, const fx_complex *in)
{
    fx_complex result;
    fx_numeric_status status;
    if (!out || !in) return FX_NUMERIC_INVALID;
    result = *in;
    /* 15D4E stops after a nonzero imaginary scalar status. */
    if (result.imaginary.bytes[0] >= 0xf0 && (result.imaginary.bytes[0] & 15)) {
        *out = result; return FX_NUMERIC_OK;
    }
    status = fx_number_negate(&result.imaginary, &result.imaginary);
    if (status == FX_NUMERIC_OK) status = fx_number_negate(&result.real, &result.real);
    if (status == FX_NUMERIC_OK) *out = result;
    return status;
}

fx_numeric_status fx_complex_integer_power(fx_complex *out, const fx_complex *in,
                                           int exponent)
{
    fx_complex one, square;
    fx_numeric_status status;
    if (!out || !in) return FX_NUMERIC_INVALID;
    if (exponent == -1) {
        fx_complex_zero(&one); (void)fx_decimal_from_integer(&one.real, 1);
        return fx_complex_binary(out, &one, in, FX_DIVIDE);
    }
    if (exponent != 2 && exponent != 3) return FX_NUMERIC_UNIMPLEMENTED;
    status = fx_complex_binary(&square, in, in, FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) return status;
    if (exponent == 2) { *out = square; return FX_NUMERIC_OK; }
    /* 18672 restores the original value as the left operand and multiplies
     * it by the already stored square. */
    return fx_complex_binary(out, in, &square, FX_MULTIPLY);
}

fx_numeric_status fx_complex_power(fx_complex *out, const fx_complex *base,
                                   const fx_complex *exponent)
{
    int64_t integer;
    if (!out || !base || !exponent) return FX_NUMERIC_INVALID;
    if (exponent->imaginary.bytes[0] ||
        fx_decimal_to_integer(&integer, &exponent->real) != FX_NUMERIC_OK ||
        (integer != -1 && integer != 2 && integer != 3)) {
        complex_error(out); return FX_NUMERIC_OK;
    }
    return fx_complex_integer_power(out, base, (int)integer);
}

fx_numeric_status fx_complex_cleanup(fx_complex *out, const fx_complex *in)
{
    fx_complex result;
    fx_numeric_status status;
    if (!out || !in) return FX_NUMERIC_INVALID;
    result = *in;
    if (result.real.bytes[0] >= 0xf0) { *out = result; return FX_NUMERIC_OK; }
    status = fx_decimal_integer_cleanup(&result.real);
    if (status == FX_NUMERIC_OK &&
        (scalar_error_status(&result.real) || scalar_error_status(&result.imaginary))) {
        complex_error(out); return FX_NUMERIC_OK;
    }
    if (status == FX_NUMERIC_OK) status = fx_decimal_integer_cleanup(&result.imaginary);
    if (status == FX_NUMERIC_OK && scalar_error_status(&result.imaginary)) {
        complex_error(out); return FX_NUMERIC_OK;
    }
    if (status == FX_NUMERIC_OK) *out = result;
    return status;
}

static fx_numeric_status absolute_component(fx_number *out, const fx_number *in,
    const fx_complex_preparation *preparation)
{
    fx_number number = *in;
    uint8_t classification;
    fx_numeric_status status;
    /* CCF6 classifies before C312 clears bit40. In particular the marked
     * rational header6x is a domain error rather than an ordinary fraction. */
    status = preparation && preparation->classify ?
        preparation->classify(&classification, &number, preparation->userdata) :
        fx_scalar_numeric_classify(&classification, &number);
    if (status != FX_NUMERIC_OK) return status;
    if (classification == 0xf0) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    number.bytes[0] &= (uint8_t)~0x40;
    if (classification == 2) status = fx_number_negate(&number, &number);
    if (status == FX_NUMERIC_OK) *out = number;
    return status;
}

fx_numeric_status fx_complex_magnitude_with_preparation(fx_complex *out,
    const fx_complex *in, int exact_math,
    const fx_complex_preparation *preparation)
{
    fx_complex result;
    fx_number real, imaginary, x, y, square_x, square_y, sum, ratio, one;
    fx_decimal decoded_x, decoded_y;
    fx_numeric_status status;
    int large;
    if (!out || !in || (exact_math != 0 && exact_math != 1)) return FX_NUMERIC_INVALID;
    result = *in;
    if (result.real.bytes[0] >= 0xf0 || result.imaginary.bytes[0] >= 0xf0) {
        fx_number_error(&result.real, 3); *out = result; return FX_NUMERIC_OK;
    }
    status = absolute_component(&real, &result.real, preparation);
    if (status == FX_NUMERIC_OK) status = absolute_component(&imaginary, &result.imaginary, preparation);
    if (status != FX_NUMERIC_OK) return status;
    fx_number_zero(&result.imaginary);
    if (!imaginary.bytes[0]) { result.real = real; *out = result; return FX_NUMERIC_OK; }
    if (!real.bytes[0]) { result.real = imaginary; *out = result; return FX_NUMERIC_OK; }
    if (real.bytes[0] >= 0xf0 || imaginary.bytes[0] >= 0xf0) {
        complex_error(out); return FX_NUMERIC_OK;
    }
    status = preparation && preparation->decimal ?
        preparation->decimal(&x, &real, preparation->userdata) :
        fx_number_to_decimal(&x, &real);
    if (status == FX_NUMERIC_OK) status = preparation && preparation->decimal ?
        preparation->decimal(&y, &imaginary, preparation->userdata) :
        fx_number_to_decimal(&y, &imaginary);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_decimal_decode(&decoded_x, &x) != FX_NUMERIC_OK ||
        fx_decimal_decode(&decoded_y, &y) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    /* A compact cancellation can convert to canonical decimal zero while
     * retaining a nonzero original header. Its raw exponent/sign word is
     * zero, outside the native safe-square interval, rather than exponent0. */
    if (decoded_x.mantissa && decoded_y.mantissa &&
        decoded_x.exponent > -50 && decoded_x.exponent < 49 &&
        decoded_y.exponent > -50 && decoded_y.exponent < 49) {
        /* Ordinary magnitudes square the decimal-prepared components and
         * add before invoking the exact-output square-root recognizer. */
        status = fx_number_integer_power(&square_x, &x, 2);
        if (status == FX_NUMERIC_OK) status = fx_number_integer_power(&square_y, &y, 2);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&sum, &square_x, &square_y, FX_ADD);
        if (status == FX_NUMERIC_OK)
            status = preparation && preparation->root ?
                preparation->root(&result.real, &sum, exact_math, preparation->userdata) :
                            fx_number_sqrt(&result.real, &sum, exact_math);
    } else {
        /* Outside the safe square range, divide the smaller component by
         * the larger first; its stored square cannot overflow. */
        large = decoded_x.mantissa && (!decoded_y.mantissa ||
                decoded_x.exponent > decoded_y.exponent ||
                (decoded_x.exponent == decoded_y.exponent && decoded_x.mantissa >= decoded_y.mantissa));
        status = large ? fx_decimal_binary(&ratio, &y, &x, FX_DIVIDE)
                       : fx_decimal_binary(&ratio, &x, &y, FX_DIVIDE);
        if (status == FX_NUMERIC_OK) status = fx_number_integer_power(&ratio, &ratio, 2);
        (void)fx_decimal_from_integer(&one, 1);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&ratio, &ratio, &one, FX_ADD);
        if (status == FX_NUMERIC_OK)
            status = preparation && preparation->root ?
                preparation->root(&ratio, &ratio, 0, preparation->userdata) :
                            fx_number_sqrt(&ratio, &ratio, 0);
        if (status == FX_NUMERIC_OK)
            status = preparation && preparation->binary ?
                preparation->binary(&result.real, &ratio,
                    large ? &real : &imaginary, FX_MULTIPLY, preparation->userdata) :
                fx_number_binary(&result.real, &ratio,
                    large ? &real : &imaginary, FX_MULTIPLY);
    }
    if (status == FX_NUMERIC_OK) *out = result;
    return status;
}

fx_numeric_status fx_complex_magnitude_prepared(fx_complex *out,
    const fx_complex *in, int exact_math, fx_complex_square_root root,
    void *userdata)
{
    const fx_complex_preparation preparation = {root, NULL, NULL, NULL, userdata};
    return fx_complex_magnitude_with_preparation(out, in, exact_math, &preparation);
}

fx_numeric_status fx_complex_magnitude(fx_complex *out, const fx_complex *in,
                                       int exact_math)
{
    return fx_complex_magnitude_prepared(out, in, exact_math, NULL, NULL);
}

fx_numeric_status fx_complex_sqrt_with_preparation(fx_complex *out,
    const fx_complex *in, int exact_math,
    const fx_complex_preparation *preparation)
{
    fx_complex result;
    fx_number root;
    uint8_t classification;
    fx_numeric_status status;
    int negative;
    if (!out || !in || (exact_math != 0 && exact_math != 1)) return FX_NUMERIC_INVALID;
    result = *in;
    status = preparation && preparation->classify ?
        preparation->classify(&classification, &result.imaginary, preparation->userdata) :
        fx_scalar_numeric_classify(&classification, &result.imaginary);
    if (status != FX_NUMERIC_OK) return status;
    if (classification != 1) {
        fx_number_error(&result.real, 3); *out = result; return FX_NUMERIC_OK;
    }
    if (fx_number_kind(&result.real) == FX_NUMBER_SURD) {
        status = preparation && preparation->decimal ?
            preparation->decimal(&result.real, &result.real, preparation->userdata) :
            fx_number_to_decimal(&result.real, &result.real);
        if (status != FX_NUMERIC_OK) return status;
    }
    status = preparation && preparation->classify ?
        preparation->classify(&classification, &result.real, preparation->userdata) :
        fx_scalar_numeric_classify(&classification, &result.real);
    if (status != FX_NUMERIC_OK) return status;
    if (classification == 0xf0) {
        fx_number_error(&result.real, 3); *out = result; return FX_NUMERIC_OK;
    }
    negative = classification == 2;
    if (negative) status = fx_number_negate(&result.real, &result.real);
    if (status == FX_NUMERIC_OK) status = preparation && preparation->root ?
        preparation->root(&root, &result.real, exact_math, preparation->userdata) :
        fx_number_sqrt(&root, &result.real, exact_math);
    if (status != FX_NUMERIC_OK) return status;
    if (negative) { result.imaginary = root; fx_number_zero(&result.real); }
    else result.real = root;
    *out = result; return FX_NUMERIC_OK;
}

fx_numeric_status fx_complex_sqrt(fx_complex *out, const fx_complex *in,
                                  int exact_math)
{
    return fx_complex_sqrt_with_preparation(out, in, exact_math, NULL);
}
