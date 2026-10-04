/* Readable normal-distribution approximation and statistics standardization.
 * GPL-3.0-or-later. Integer decimal arithmetic; no ROM or CPU execution. */
#include "fx_stats_normal.h"
#include "../../numeric/fx_transcend.h"

static int error_status(const fx_number *value)
{
    return value->bytes[0] >= 0xf0 ? value->bytes[0] & 15 : 0;
}

/* The real arithmetic entries collapse operand errors and stored surds to
 * Math error; they convert rationals before the decimal operation. */
static int real_binary(fx_number *out, const fx_number *a, const fx_number *b,
                       fx_binary_op operation)
{
    fx_number x, y;
    int status;
    if (a->bytes[0] >= 0xf0 || b->bytes[0] >= 0xf0 ||
        fx_number_kind(a) == FX_NUMBER_SURD || fx_number_kind(b) == FX_NUMBER_SURD) {
        fx_number_error(out, 3); return 0;
    }
    status = fx_number_to_decimal(&x, a);
    if (!status) status = fx_number_to_decimal(&y, b);
    if (status) return status;
    if ((a->bytes[0] & 0xf0) == 0x60) x.bytes[0] |= 0x40;
    if ((b->bytes[0] & 0xf0) == 0x60) y.bytes[0] |= 0x40;
    if (operation == FX_ADD) return fx_decimal_add_plain(out, &x, &y);
    return fx_decimal_binary(out, &x, &y, operation);
}

/* Horner evaluation preserves the original fifteen-digit intermediate order.
 * The coefficient records and pi are constants used by the original kernel. */
static int positive_tail(fx_number *out, const fx_number *input)
{
    static const fx_number coefficients[6] = {
        {{0x02,0x31,0x64,0x19,0,0,0,0,0x99,0}},
        {{0x03,0x19,0x38,0x15,0x03,0,0,0,0x99,0}},
        {{0x03,0x56,0x56,0x37,0x82,0,0,0,0x99,5}},
        {{0x01,0x78,0x14,0x79,0x37,0,0,0,0,1}},
        {{0x01,0x82,0x12,0x55,0x97,0x80,0,0,0,6}},
        {{0x01,0x33,0x02,0x74,0x42,0x90,0,0,0,1}}
    };
    static const fx_number pi = {{0x03,0x14,0x15,0x92,0x65,0x35,0x89,0x80,0,1}};
    fx_number x = *input, t, polynomial, density, one, two, divisor;
    fx_decimal decimal;
    int status, i;
    if ((x.bytes[0] & 0xf0) == 0x40) x.bytes[0] &= 0xbf;
    if (x.bytes[0] >= 0xf0 || fx_number_kind(&x) == FX_NUMBER_SURD ||
        (x.bytes[0] & 0xf0) == 0x60) {
        fx_number_error(out, 3); return 0;
    }
    status = fx_number_to_decimal(&x, &x);
    if (!status) status = fx_decimal_decode(&decimal, &x);
    if (status) return status;
    if (!decimal.mantissa) return fx_decimal_parse(out, "0.5");
    if (decimal.exponent >= 3) { fx_number_zero(out); return 0; }
    decimal.sign = 1; decimal.flags = 0;
    status = fx_decimal_encode(&x, &decimal);
    fx_decimal_from_u8(&one, 1);
    fx_decimal_from_u8(&two, 2);
    if (!status) status = real_binary(&t, &x, &coefficients[0], FX_MULTIPLY);
    if (!status) status = real_binary(&t, &t, &one, FX_ADD);
    if (!status) status = real_binary(&t, &one, &t, FX_DIVIDE);
    if (!status) status = real_binary(&polynomial, &t, &coefficients[5], FX_MULTIPLY);
    if (!status) status = real_binary(&polynomial, &polynomial, &coefficients[4], FX_ADD);
    for (i = 3; !status && i >= 1; --i) {
        status = real_binary(&polynomial, &polynomial, &t, FX_MULTIPLY);
        if (!status) status = real_binary(&polynomial, &polynomial, &coefficients[i], FX_ADD);
    }
    if (!status) status = real_binary(&polynomial, &t, &polynomial, FX_MULTIPLY);
    if (!status) status = real_binary(&density, input, input, FX_MULTIPLY);
    if (!status) status = real_binary(&density, &density, &two, FX_DIVIDE);
    if (!status) status = fx_number_negate(&density, &density);
    if (!status) status = fx_number_exp(&density, &density);
    if (!status) status = real_binary(&density, &density, &polynomial, FX_MULTIPLY);
    if (!status) status = real_binary(&divisor, &pi, &two, FX_MULTIPLY);
    if (!status) status = fx_decimal_sqrt(&divisor, &divisor);
    if (!status) status = real_binary(out, &density, &divisor, FX_DIVIDE);
    return status;
}

/* CC90's leading workspace guard digit means its parameter6 retains five
 * significant digits. Normal functions only round magnitudes below one. */
static int probability_round(fx_number *value)
{
    fx_decimal decimal;
    int status;
    const uint64_t unit = UINT64_C(10000000000);
    if (value->bytes[0] >= 0xf0) return 0;
    status = fx_decimal_decode(&decimal, value);
    if (status) return status;
    if (decimal.mantissa) {
        decimal.mantissa = ((decimal.mantissa + unit / 2) / unit) * unit;
        if (decimal.mantissa >= UINT64_C(1000000000000000)) {
            decimal.mantissa /= 10; ++decimal.exponent;
        }
    }
    if (decimal.sign < 0) { fx_number_zero(value); return 0; }
    return fx_decimal_encode(value, &decimal);
}

int fx_stats_normal_probability(fx_number *out, const fx_number *input,
                                fx_stats_normal_function function)
{
    fx_number tail, probability, boundary;
    fx_decimal decimal;
    int negative = 0, status;
    if (!out || !input || function < FX_STATS_NORMAL_P || function > FX_STATS_NORMAL_R)
        return -1;
    if (input->bytes[0] >= 0xf0) { *out = *input; return error_status(input); }
    status = positive_tail(&tail, input);
    if (!status && fx_number_to_decimal(&probability, input) == 0 &&
        fx_decimal_decode(&decimal, &probability) == 0) negative = decimal.sign < 0;
    if (!status && function == FX_STATS_NORMAL_Q) {
        status = fx_decimal_parse(&boundary, "0.5");
        if (!status) status = real_binary(&probability, &boundary, &tail, FX_SUBTRACT);
    } else if (!status && ((function == FX_STATS_NORMAL_P && !negative) ||
                           (function == FX_STATS_NORMAL_R && negative))) {
        fx_decimal_from_u8(&boundary, 1);
        status = real_binary(&probability, &boundary, &tail, FX_SUBTRACT);
    } else if (!status) probability = tail;
    if (!status) status = probability_round(&probability);
    if (status) return status;
    *out = probability; return error_status(out);
}

int fx_stats_standardize(fx_number *out, const fx_stats_table *table,
                         const fx_number *input)
{
    fx_number mean, population, sample, result;
    int status;
    if (!out || !input || !table || table->variables < 1 || table->variables > 2 ||
        table->frequency > 1 || (table->rows && !table->cells)) return -1;
    if (input->bytes[0] >= 0xf0) { *out = *input; return error_status(input); }
    status = fx_stats_mean(&mean, table, 0);
    if (status < 0) return status;
    status = fx_stats_deviations(&population, &sample, table, 0);
    if (status < 0) return status;
    status = real_binary(&result, input, &mean, FX_SUBTRACT);
    if (!status) status = real_binary(&result, &result, &population, FX_DIVIDE);
    if (!status) status = fx_decimal_integer_cleanup(&result);
    if (status) return status;
    *out = result; return error_status(out);
}
