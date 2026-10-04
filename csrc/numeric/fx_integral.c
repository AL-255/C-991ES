/* Adaptive 7/15-point Gauss-Kronrod integration. GPL-3.0-or-later.
 * Handwritten C; no firmware execution or host floating-point arithmetic. */
#include "fx_integral.h"

/* Original fifteen-digit nodes/weights, ROM2b08..2bbc. Keeping the stored
 * constants and their evaluation order is necessary for numeric parity. */
static const fx_number gauss_center = {{0x04,0x17,0x95,0x91,0x83,0x67,0x34,0x69,0x99,0x00}};
static const fx_number kronrod_center = {{0x02,0x09,0x48,0x21,0x41,0x08,0x47,0x28,0x99,0x00}};
typedef struct { fx_number node, kronrod, gauss; } common_node;
static const common_node common_nodes[3] = {
    {{{0x09,0x49,0x10,0x79,0x12,0x34,0x27,0x59,0x99,0x00}},
     {{0x06,0x30,0x92,0x09,0x26,0x29,0x97,0x86,0x98,0x00}},
     {{0x01,0x29,0x48,0x49,0x66,0x16,0x88,0x70,0x99,0x00}}},
    {{{0x07,0x41,0x53,0x11,0x85,0x59,0x93,0x94,0x99,0x00}},
     {{0x01,0x40,0x65,0x32,0x59,0x71,0x55,0x26,0x99,0x00}},
     {{0x02,0x79,0x70,0x53,0x91,0x48,0x92,0x77,0x99,0x00}}},
    {{{0x04,0x05,0x84,0x51,0x51,0x37,0x73,0x97,0x99,0x00}},
     {{0x01,0x90,0x35,0x05,0x78,0x06,0x47,0x85,0x99,0x00}},
     {{0x03,0x81,0x83,0x00,0x50,0x50,0x51,0x19,0x99,0x00}}}
};
typedef struct { fx_number node, weight; } extra_node;
static const extra_node extra_nodes[4] = {
    {{{0x09,0x91,0x45,0x53,0x71,0x12,0x08,0x13,0x99,0x00}},
     {{0x02,0x29,0x35,0x32,0x20,0x10,0x52,0x92,0x98,0x00}}},
    {{{0x08,0x64,0x86,0x44,0x23,0x35,0x97,0x69,0x99,0x00}},
     {{0x01,0x04,0x79,0x00,0x10,0x32,0x22,0x50,0x99,0x00}}},
    {{{0x05,0x86,0x08,0x72,0x35,0x46,0x76,0x91,0x99,0x00}},
     {{0x01,0x69,0x00,0x47,0x26,0x63,0x92,0x68,0x99,0x00}}},
    {{{0x02,0x07,0x78,0x49,0x55,0x00,0x78,0x99,0x99,0x00}},
     {{0x02,0x04,0x43,0x29,0x40,0x07,0x52,0x99,0x99,0x00}}}
};

typedef struct {
    fx_calculus_function function;
    void *userdata;
    const fx_calculus_control *control;
    fx_numeric_status host_status;
    unsigned native_error;
} integral_context;

static int numeric_result(integral_context *context, fx_number *value,
                           fx_numeric_status status) {
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    if (fx_number_kind(value) == FX_NUMBER_ERROR) {
        context->native_error = 3; return 0;
    }
    return 1;
}

static fx_numeric_status binary_record(fx_number *out, const fx_number *a,
                                        const fx_number *b, fx_binary_op op) {
    fx_number first, second;
    fx_numeric_status status;
    /* AB64 clears bit40 on every non-F header before scalar dispatch.
     * Consequently a surviving61 reference uses its raw rational payload;
     * this is distinct from15C82, which rejects the unmasked header. */
    if ((fx_number_kind(a) != FX_NUMBER_DECIMAL && fx_number_kind(a) != FX_NUMBER_RATIONAL) ||
        (fx_number_kind(b) != FX_NUMBER_DECIMAL && fx_number_kind(b) != FX_NUMBER_RATIONAL)) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    /* Ordinary scalar wrappers load rational components as decimals before
     * operating; they do not use the exact rational arithmetic dispatcher. */
    if (fx_number_kind(a) == FX_NUMBER_RATIONAL) {
        status = fx_number_to_decimal(&first, a);
        if (status != FX_NUMERIC_OK) return status;
        first.bytes[0] |= a->bytes[0] & 0x40; a = &first;
    }
    if (fx_number_kind(b) == FX_NUMBER_RATIONAL) {
        status = fx_number_to_decimal(&second, b);
        if (status != FX_NUMERIC_OK) return status;
        second.bytes[0] |= b->bytes[0] & 0x40; b = &second;
    }
    if (fx_number_kind(a) == FX_NUMBER_ERROR || fx_number_kind(b) == FX_NUMBER_ERROR) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    return op == FX_SUBTRACT ? fx_decimal_subtract_cancel(out, a, b) :
                             fx_decimal_binary(out, a, b, op);
}

static int binary(integral_context *context, fx_number *out,
                   const fx_number *a, const fx_number *b, fx_binary_op op) {
    return numeric_result(context, out, binary_record(out, a, b, op));
}

/* Midpoint weights at045c6/045da are computed without a native status gate.
 * Preserve an arithmetic F3 until a checked pair operation detects it. */
static int binary_unchecked(integral_context *context, fx_number *out,
                             const fx_number *a, const fx_number *b,
                             fx_binary_op op) {
    fx_numeric_status status = binary_record(out, a, b, op);
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    return 1;
}

static int cleanup(integral_context *context, fx_number *value) {
    return numeric_result(context, value, fx_decimal_integer_cleanup(value));
}

static int decimal(integral_context *context, fx_number *out,
                    const fx_number *in) {
    fx_number value = *in;
    if (fx_number_kind(&value) == FX_NUMBER_SURD &&
        !numeric_result(context, &value, fx_number_to_decimal(&value, &value))) return 0;
    if (value.bytes[0] > 0x4f) { context->native_error = 3; return 0; }
    /*15c82 clears the scalar metadata after radical/rational conversion. */
    value.bytes[0] &= (uint8_t)~0x40;
    return numeric_result(context, out, fx_number_to_decimal(out, &value));
}

static int absolute(integral_context *context, fx_number *value) {
    fx_decimal decoded;
    value->bytes[0] &= (uint8_t)~0x40;
    if (fx_decimal_decode(&decoded, value) != FX_NUMERIC_OK) {
        context->host_status = FX_NUMERIC_INVALID; return 0;
    }
    if (decoded.sign < 0)
        return numeric_result(context, value, fx_number_negate(value, value));
    return 1;
}

/*1cd94 uses the thirteen-digit cancellation-suppressing subtraction. */
static int compare(const fx_number *a, const fx_number *b) {
    fx_decimal x, y, difference;
    fx_number residue;
    (void)fx_decimal_decode(&x, a); (void)fx_decimal_decode(&y, b);
    if (x.sign != y.sign) return x.sign < y.sign ? -1 : 1;
    if (!x.sign) return 0;
    (void)fx_decimal_subtract_cancel(&residue, a, b);
    (void)fx_decimal_decode(&difference, &residue);
    return difference.sign;
}

static int evaluate(integral_context *context, fx_number *value,
                     const fx_number *x) {
    fx_numeric_status status = context->function(value, x, context->userdata);
    if ((int)status == FX_CALCULUS_EVALUATION_ERROR) {
        context->native_error = 3; return 0;
    }
    if ((int)status == FX_CALCULUS_EVALUATION_OK) {
        if (fx_number_kind(value) == FX_NUMBER_ERROR) return 1;
        status = FX_NUMERIC_OK;
    }
    if (!numeric_result(context, value, status)) return 0;
    if (fx_number_kind(value) == FX_NUMBER_SURD)
        return numeric_result(context, value, fx_number_to_decimal(value, value));
    return 1;
}

static int poll(integral_context *context) {
    if (context->control && context->control->cancelled &&
        context->control->cancelled(context->control->userdata)) {
        context->native_error = 1; return 0;
    }
    return 1;
}

static int weighted_add(integral_context *context, fx_number *sum,
                         const fx_number *value, const fx_number *weight) {
    fx_number term;
    return binary(context, &term, value, weight, FX_MULTIPLY) &&
           binary(context, sum, sum, &term, FX_ADD);
}

/*044b8 samples center-node*halfwidth first, then center+node*halfwidth.
 * Its subtraction/negation order differs from swapping the two operands. */
static int pair(integral_context *context, fx_number *value,
                 const fx_number *center, const fx_number *halfwidth,
                 const fx_number *node) {
    fx_number offset, x, left, right;
    return binary(context, &offset, node, halfwidth, FX_MULTIPLY) &&
           binary(context, &x, &offset, center, FX_SUBTRACT) &&
           numeric_result(context, &x, fx_number_negate(&x, &x)) &&
           evaluate(context, &left, &x) &&
           binary(context, &x, &offset, center, FX_ADD) &&
           evaluate(context, &right, &x) &&
           binary(context, value, &left, &right, FX_ADD) && cleanup(context, value);
}

/*04544 embeds the seven-point Gauss sum in the fifteen-point Kronrod sum.
 * Each node pair has one cancellation poll, after the midpoint evaluation. */
static int quadrature(integral_context *context, fx_number *result,
                       fx_number *error, const fx_number *lower,
                       const fx_number *upper) {
    fx_number two, halfwidth, center, value, gauss, kronrod;
    fx_decimal width;
    unsigned index;
    (void)fx_decimal_from_integer(&two, 2);
    if (!binary(context, &halfwidth, upper, lower, FX_SUBTRACT) ||
        !binary(context, &halfwidth, &halfwidth, &two, FX_DIVIDE)) return 0;
    if (fx_decimal_decode(&width, &halfwidth) != FX_NUMERIC_OK || !width.sign) {
        context->native_error = 3; return 0;
    }
    if (!binary(context, &center, upper, lower, FX_ADD) ||
        !binary(context, &center, &center, &two, FX_DIVIDE) ||
        !evaluate(context, &value, &center) ||
        !binary_unchecked(context, &gauss, &gauss_center, &value, FX_MULTIPLY) ||
        !binary_unchecked(context, &kronrod, &kronrod_center, &value, FX_MULTIPLY)) return 0;
    for (index = 0; index < 3; ++index) {
        if (!poll(context) || !pair(context, &value, &center, &halfwidth, &common_nodes[index].node) ||
            !weighted_add(context, &kronrod, &value, &common_nodes[index].kronrod) ||
            !weighted_add(context, &gauss, &value, &common_nodes[index].gauss)) return 0;
    }
    for (index = 0; index < 4; ++index) {
        if (!poll(context) || !pair(context, &value, &center, &halfwidth, &extra_nodes[index].node) ||
            !weighted_add(context, &kronrod, &value, &extra_nodes[index].weight)) return 0;
    }
    if (!cleanup(context, &gauss) || !decimal(context, &gauss, &gauss) ||
        !binary(context, &gauss, &gauss, &halfwidth, FX_MULTIPLY) ||
        !cleanup(context, &kronrod) || !decimal(context, &kronrod, &kronrod) ||
        !binary(context, &kronrod, &kronrod, &halfwidth, FX_MULTIPLY) ||
        !binary(context, error, &gauss, &kronrod, FX_SUBTRACT) ||
        !absolute(context, error) || !cleanup(context, error)) return 0;
    *result = kronrod;
    return 1;
}

/*04696 accepts when max(|tolerance*integral|,1e-10) exceeds the Gauss/Kronrod
 * difference. A native overflow of the scale also selects acceptance. */
static int converged(integral_context *context, const fx_number *result,
                      const fx_number *error, const fx_number *tolerance) {
    fx_number threshold, minimum;
    fx_numeric_status status = fx_decimal_binary(&threshold, tolerance, result, FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    if (fx_number_kind(&threshold) == FX_NUMBER_ERROR) return 1;
    if (!absolute(context, &threshold)) return 0;
    (void)fx_decimal_parse(&minimum, "1e-10");
    if (compare(&threshold, &minimum) < 0) threshold = minimum;
    return compare(&threshold, error);
}

/* Reconstruct a dyadic endpoint using the original finite-decimal sequence:
 * (index+1-denominator)/denominator * span + original_lower. In particular,
 * keep the subtraction's cancellation suppression at very deep levels. */
static int endpoint(integral_context *context, fx_number *out, uint64_t index,
                      uint64_t denominator, int next,
                      const fx_number *span, const fx_number *lower) {
    fx_number position, divisor, one;
    (void)fx_decimal_from_integer(&position, (int64_t)index);
    (void)fx_decimal_from_integer(&divisor, (int64_t)denominator);
    if (next) {
        (void)fx_decimal_from_integer(&one, 1);
        if (!binary(context, &position, &position, &one, FX_ADD)) return 0;
    }
    return binary(context, &position, &position, &divisor, FX_SUBTRACT) &&
           binary(context, &position, &position, &divisor, FX_DIVIDE) &&
           binary(context, &position, &position, span, FX_MULTIPLY) &&
           binary(context, out, &position, lower, FX_ADD);
}

fx_numeric_status fx_number_integral(fx_number *out, const fx_number *lower,
                                     const fx_number *upper,
                                     const fx_number *tolerance,
                                     fx_calculus_function function,
                                     void *userdata,
                                     const fx_calculus_control *control) {
    integral_context context = {function, userdata, control, FX_NUMERIC_OK, 0};
    fx_number a, b, precision, span, left, right, result, error, total, value, difference;
    fx_decimal decoded;
    uint64_t index = 1, denominator = 1;
    unsigned budget = 324, depth = 47;
    int decision;
    if (!out || !lower || !upper || !function) return FX_NUMERIC_INVALID;
    if (!decimal(&context, &a, lower) || !decimal(&context, &b, upper)) goto done;
    if (tolerance) {
        if (!decimal(&context, &precision, tolerance)) goto done;
        if (fx_decimal_decode(&decoded, &precision) != FX_NUMERIC_OK) {
            context.host_status = FX_NUMERIC_INVALID; goto done;
        }
        if (decoded.sign < 0) { context.native_error = 8; goto done; }
    } else (void)fx_decimal_parse(&precision, "1e-5");
    /*04796/047d6 validates both endpoint callbacks before returning a zero
     * interval or constructing the quadrature's center and width. */
    if (compare(&a, &b) == 0) {
        if (!evaluate(&context, &value, &b) || !evaluate(&context, &value, &a)) goto done;
        fx_number_zero(&total); goto success;
    }
    if (!evaluate(&context, &value, &a) || !evaluate(&context, &value, &b)) goto done;
    left = a; right = b; fx_number_zero(&total);
    if (!binary(&context, &span, &b, &a, FX_SUBTRACT) ||
        !quadrature(&context, &result, &error, &left, &right)) goto done;
    decision = converged(&context, &result, &error, &precision);
    if (context.host_status != FX_NUMERIC_OK) goto done;
    if (decision > 0) { total = result; goto success; }
    /* The native driver repeats the initial failed interval, then follows
     * the binary subdivision tree in depth-first, left-to-right order. */
    for (;;) {
        if (!--budget) { context.native_error = 11; goto done; }
        if (!quadrature(&context, &result, &error, &left, &right)) goto done;
        decision = converged(&context, &result, &error, &precision);
        if (context.host_status != FX_NUMERIC_OK) goto done;
        if (decision < 0) {
            denominator *= 2;
            if (!--depth) {
                if (!binary(&context, &value, &total, &result, FX_ADD) ||
                    !numeric_result(&context, &difference,
                        fx_decimal_binary(&difference, &value, &total, FX_SUBTRACT))) goto done;
                if (difference.bytes[0]) { context.native_error = 11; goto done; }
                ++depth; denominator /= 2;
            } else {
                index *= 2;
                if (!endpoint(&context, &right, index, denominator, 1, &span, &a)) goto done;
                continue;
            }
        }
        if (!binary(&context, &total, &total, &result, FX_ADD)) goto done;
        for (;;) {
            if (index == 1) goto success;
            if (!(index & 1)) break;
            ++depth; denominator /= 2; index = (index-1)/2;
            if (!endpoint(&context, &left, index, denominator, 0, &span, &a)) goto done;
        }
        ++index; left = right;
        if (!endpoint(&context, &right, index, denominator, 1, &span, &a)) goto done;
    }
success:
    if (!cleanup(&context, &total)) goto done;
    *out = total;
    return FX_NUMERIC_OK;
done:
    if (context.host_status != FX_NUMERIC_OK) return context.host_status;
    fx_number_error(out, context.native_error ? context.native_error : 3);
    return FX_NUMERIC_OK;
}
