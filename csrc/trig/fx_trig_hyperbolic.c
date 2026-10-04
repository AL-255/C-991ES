/* Decimal hyperbolic formulas with the original precision boundaries.
 * GPL-3.0-or-later. No host floating point or firmware execution. */
#include "fx_trig_hyperbolic.h"
#include "../numeric/fx_transcend.h"

static int less_magnitude(const fx_number *a, const fx_number *b)
{
    fx_decimal x, y;
    (void)fx_decimal_decode(&x, a); (void)fx_decimal_decode(&y, b);
    if (!x.mantissa) return y.mantissa != 0;
    if (!y.mantissa) return 0;
    return x.exponent < y.exponent || (x.exponent == y.exponent && x.mantissa < y.mantissa);
}

/* For |x| < .013 the original avoids cancellation in exponentials/logs.
 * Its fourth-order correction is constructed before the quadratic term;
 * each arithmetic operation stores a15-digit decimal record. */
static fx_numeric_status small_argument(fx_number *out, const fx_number *x,
                                        fx_trig_function function, int inverse)
{
    fx_number square, fourth, second_term, fourth_term, divisor, one, sum;
    fx_numeric_status status = fx_decimal_binary(&square, x, x, FX_MULTIPLY);
    if (status == FX_NUMERIC_OK)
        status = fx_decimal_binary(&fourth, &square, &square, FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) return status;
    if (function == FX_SINE && inverse) {
        (void)fx_decimal_parse(&divisor, ".075");
        status = fx_decimal_binary(&fourth_term, &fourth, &divisor, FX_MULTIPLY);
    } else {
        (void)fx_decimal_parse(&divisor, function == FX_SINE ? "120" : inverse ? "5" : "7.5");
        status = fx_decimal_binary(&fourth_term, &fourth, &divisor, FX_DIVIDE);
    }
    if (status != FX_NUMERIC_OK) return status;
    (void)fx_decimal_from_integer(&divisor, function == FX_SINE ? (inverse ? -6 : 6)
                                                            : (inverse ? 3 : -3));
    status = fx_decimal_binary(&second_term, &square, &divisor, FX_DIVIDE);
    (void)fx_decimal_from_integer(&one, 1);
    if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&sum, &second_term, &one, FX_ADD);
    if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&sum, &sum, &fourth_term, FX_ADD);
    if (status == FX_NUMERIC_OK) status = fx_decimal_binary(out, &sum, x, FX_MULTIPLY);
    return status;
}

/* Reconstruct sqrt(x*x +/-1) without squaring a large x. The reciprocal
 * branch retains the original order and precision, including near |x|=1. */
static fx_numeric_status inverse_root(fx_number *root, const fx_number *x,
                                      fx_trig_function function)
{
    fx_number one, ratio, square, low, high;
    fx_numeric_status status;
    int reciprocal;
    (void)fx_decimal_from_integer(&one, 1);
    reciprocal = !less_magnitude(x, &one);
    status = reciprocal ? fx_decimal_binary(&ratio, &one, x, FX_DIVIDE)
                        : fx_decimal_binary(&ratio, x, &one, FX_DIVIDE);
    if (status != FX_NUMERIC_OK) return status;
    if (function == FX_COSINE) {
        status = fx_decimal_binary(&low, &ratio, &one, FX_SUBTRACT);
        if (status == FX_NUMERIC_OK && reciprocal) status = fx_number_negate(&low, &low);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&high, &ratio, &one, FX_ADD);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(root, &high, &low, FX_MULTIPLY);
    } else {
        status = fx_decimal_binary(&square, &ratio, &ratio, FX_MULTIPLY);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(root, &square, &one, FX_ADD);
    }
    if (status == FX_NUMERIC_OK) status = fx_decimal_sqrt(root, root);
    if (status == FX_NUMERIC_OK && reciprocal)
        status = fx_decimal_binary(root, root, x, FX_MULTIPLY);
    if (status == FX_NUMERIC_OK && fx_number_kind(root) == FX_NUMBER_DECIMAL) {
        fx_decimal value;
        (void)fx_decimal_decode(&value, root); value.sign = value.mantissa ? 1 : 0;
        (void)fx_decimal_encode(root, &value);
    }
    return status;
}

fx_numeric_status fx_hyperbolic_decimal(fx_number *out, const fx_number *in,
                                       fx_trig_function function, int inverse)
{
    static const fx_number small_limit = {{0x01,0x30,0,0,0,0,0,0,0x98,0}};
    fx_number original, absolute, one, two, positive_exp, reciprocal, low, high, value;
    fx_decimal decoded;
    fx_numeric_status status;
    int negative;
    if (!out || !in || function < FX_SINE || function > FX_TANGENT ||
        (inverse != 0 && inverse != 1)) return FX_NUMERIC_INVALID;
    if (fx_number_kind(in) == FX_NUMBER_ERROR || fx_number_kind(in) == FX_NUMBER_UNSUPPORTED) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    status = fx_number_to_decimal(&original, in);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_decimal_decode(&decoded, &original) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    negative = decoded.sign < 0; decoded.flags = 0;
    (void)fx_decimal_encode(&original, &decoded);
    decoded.sign = decoded.mantissa ? 1 : 0;
    (void)fx_decimal_encode(&absolute, &decoded);
    if (function != FX_COSINE && less_magnitude(&absolute, &small_limit))
        return small_argument(out, &original, function, inverse);
    (void)fx_decimal_from_integer(&one, 1); (void)fx_decimal_from_integer(&two, 2);
    if (inverse) {
        if (function == FX_TANGENT) {
            status = fx_decimal_binary(&low, &one, &original, FX_SUBTRACT);
            if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&high, &original, &one, FX_ADD);
            if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&value, &high, &low, FX_DIVIDE);
            if (status == FX_NUMERIC_OK) status = fx_decimal_sqrt(&value, &value);
        } else {
            const fx_number *argument = function == FX_SINE ? &absolute : &original;
            status = inverse_root(&value, argument, function);
            if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&value, &value, argument, FX_ADD);
        }
        if (status == FX_NUMERIC_OK) status = fx_number_ln(out, &value);
        if (status == FX_NUMERIC_OK && function == FX_SINE && negative)
            status = fx_number_negate(out, out);
        return status;
    }
    status = fx_number_exp(&positive_exp, &absolute);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_number_kind(&positive_exp) == FX_NUMBER_ERROR) {
        if (function == FX_TANGENT) {
            *out = one; if (negative) out->bytes[9] = 6;
        } else {
            *out = positive_exp;
            out->bytes[9] = function == FX_SINE && !negative ? 5 : 0;
        }
        return FX_NUMERIC_OK;
    }
    status = fx_decimal_binary(&reciprocal, &one, &positive_exp, FX_DIVIDE);
    if (status != FX_NUMERIC_OK) return status;
    if (function == FX_TANGENT) {
        status = fx_decimal_binary(&low, &positive_exp, &reciprocal, FX_SUBTRACT);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&high, &positive_exp, &reciprocal, FX_ADD);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(out, &low, &high, FX_DIVIDE);
    } else {
        status = fx_decimal_binary(&value, &positive_exp, &reciprocal,
                                   function == FX_SINE ? FX_SUBTRACT : FX_ADD);
        if (status == FX_NUMERIC_OK) status = fx_decimal_binary(out, &value, &two, FX_DIVIDE);
    }
    if (status == FX_NUMERIC_OK && negative && function != FX_COSINE)
        status = fx_number_negate(out, out);
    return status;
}
