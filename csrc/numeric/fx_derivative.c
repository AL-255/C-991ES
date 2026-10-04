/* Handwritten real finite-decimal Richardson differentiation.
 * GPL-3.0-or-later. No CPU, ROM execution or host floating-point arithmetic. */
#include "fx_derivative.h"

typedef struct {
    fx_calculus_function function;
    void *userdata;
    const fx_calculus_control *control;
    fx_numeric_status host_status;
    unsigned native_error;
} derivative_context;

static int result(derivative_context *context, fx_number *value,
                   fx_numeric_status status) {
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    if (fx_number_kind(value) == FX_NUMBER_ERROR) {
        context->native_error = 3; return 0;
    }
    return 1;
}

static int decimal(derivative_context *context, fx_number *out,
                    const fx_number *in) {
    fx_number value = *in;
    if (fx_number_kind(&value) == FX_NUMBER_SURD &&
        !result(context, &value, fx_number_to_decimal(&value, &value))) return 0;
    if (value.bytes[0] > 0x4f) { context->native_error = 3; return 0; }
    value.bytes[0] &= (uint8_t)~0x40;
    return result(context, out, fx_number_to_decimal(out, &value));
}

/*15c82 leaves an F-valued record intact. The initial base value and the
 * central divided difference have no status gate at their normalization. */
static int decimal_unchecked(derivative_context *context, fx_number *out,
                              const fx_number *in) {
    fx_number value = *in;
    fx_numeric_status status;
    if (fx_number_kind(&value) == FX_NUMBER_SURD) {
        status = fx_number_to_decimal(&value, &value);
        if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    }
    if (value.bytes[0] > 0x4f) { *out = value; return 1; }
    value.bytes[0] &= (uint8_t)~0x40;
    status = fx_number_to_decimal(out, &value);
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    if (fx_number_kind(out) != FX_NUMBER_ERROR) out->bytes[0] &= (uint8_t)~0x40;
    return 1;
}

static fx_numeric_status binary_record(fx_number *out, const fx_number *a,
                                        const fx_number *b,
                                        fx_binary_op operation) {
    fx_number first, second;
    fx_numeric_status status;
    /* AB64 masks bit40 before ordinary scalar arithmetic. Unlike15C82,
     * it therefore admits a surviving61 reference's rational payload. */
    if ((fx_number_kind(a) != FX_NUMBER_DECIMAL && fx_number_kind(a) != FX_NUMBER_RATIONAL) ||
        (fx_number_kind(b) != FX_NUMBER_DECIMAL && fx_number_kind(b) != FX_NUMBER_RATIONAL)) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
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
    return operation == FX_SUBTRACT ? fx_decimal_subtract_cancel(out, a, b) :
                                     fx_decimal_binary(out, a, b, operation);
}

static int binary(derivative_context *context, fx_number *out,
                   const fx_number *a, const fx_number *b,
                   fx_binary_op operation) {
    return result(context, out, binary_record(out, a, b, operation));
}

static int binary_unchecked(derivative_context *context, fx_number *out,
                             const fx_number *a, const fx_number *b,
                             fx_binary_op operation) {
    fx_numeric_status status = binary_record(out, a, b, operation);
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    return 1;
}

static int absolute(derivative_context *context, fx_number *value) {
    fx_decimal decoded;
    if (!decimal(context, value, value)) return 0;
    if (fx_decimal_decode(&decoded, value) != FX_NUMERIC_OK) {
        context->host_status = FX_NUMERIC_INVALID; return 0;
    }
    return decoded.sign >= 0 || result(context, value, fx_number_negate(value, value));
}

/* CD94 suppresses thirteen-digit cancellation; CD60 retains its residue. */
static int compare(const fx_number *a, const fx_number *b, int cancel) {
    fx_decimal first, second, decoded;
    fx_number difference;
    (void)fx_decimal_decode(&first, a); (void)fx_decimal_decode(&second, b);
    if (first.sign != second.sign) return first.sign < second.sign ? -1 : 1;
    if (!first.sign) return 0;
    if (cancel) (void)fx_decimal_subtract_cancel(&difference, a, b);
    else (void)fx_decimal_binary(&difference, a, b, FX_SUBTRACT);
    (void)fx_decimal_decode(&decoded, &difference);
    return decoded.sign;
}

static int evaluate(derivative_context *context, fx_number *value,
                     const fx_number *x, int allow_error) {
    fx_numeric_status status = context->function(value, x, context->userdata);
    if ((int)status == FX_CALCULUS_EVALUATION_ERROR) {
        if (allow_error) status = FX_NUMERIC_OK;
        else { context->native_error = 3; return 0; }
    }
    if ((int)status == FX_CALCULUS_EVALUATION_OK) {
        if (fx_number_kind(value) == FX_NUMBER_ERROR) return 1;
        status = FX_NUMERIC_OK;
    }
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    if (allow_error && fx_number_kind(value) == FX_NUMBER_ERROR) return 1;
    if (!result(context, value, FX_NUMERIC_OK)) return 0;
    if (fx_number_kind(value) == FX_NUMBER_SURD)
        return result(context, value, fx_number_to_decimal(value, value));
    return 1;
}

static int poll(derivative_context *context) {
    if (context->control && context->control->cancelled &&
        context->control->cancelled(context->control->userdata)) {
        context->native_error = 1; return 0;
    }
    return 1;
}

/* CC80 R2=1 retains zero significant digits after its workspace guard.
 * Its away-from-zero ceiling chooses the next signed decimal power. */
static int starting_step(derivative_context *context, fx_number *step,
                          const fx_number *point) {
    fx_decimal decoded;
    fx_number scale;
    (void)fx_decimal_decode(&decoded, point);
    if (!decoded.sign) return result(context, step, fx_decimal_parse(step, ".01"));
    (void)fx_decimal_parse(&scale, "1e-3");
    if (!binary(context, step, point, &scale, FX_MULTIPLY)) return 0;
    (void)fx_decimal_decode(&decoded, step);
    if (!decoded.sign || decoded.exponent+1 < -93)
        return result(context, step, fx_decimal_parse(step, "1e-93"));
    ++decoded.exponent; decoded.mantissa = UINT64_C(100000000000000);
    return result(context, step, fx_decimal_encode(step, &decoded));
}

/* 04dcc probes f(point+step), shrinking step/10 at most seven times.
 * The ordinary relative ratio must be nonnegative and in [0.9,1.1].
 * A domain error is retried only while the changed point remains distinct. */
static int select_step(derivative_context *context, fx_number *step,
                        const fx_number *point) {
    fx_number base_value, value, x, ratio, lower, width, ten;
    fx_decimal decoded;
    unsigned attempt, previous_error = 0;
    (void)fx_decimal_parse(&lower, ".9");
    (void)fx_decimal_parse(&width, ".2");
    (void)fx_decimal_from_integer(&ten, 10);
    if (!evaluate(context, &base_value, point, 0) ||
        !decimal_unchecked(context, &base_value, &base_value)) return 0;
    for (attempt = 0; attempt < 7; ++attempt) {
        if (!binary(context, &x, point, step, FX_ADD)) return 0;
        if (previous_error && compare(&x, point, 1) == 0) {
            context->native_error = 3; return 0;
        }
        if (!evaluate(context, &value, &x, 1)) return 0;
        previous_error = fx_number_kind(&value) == FX_NUMBER_ERROR ? value.bytes[0] & 15 : 0;
        if (previous_error && previous_error != 3) {
            context->native_error = 3; return 0;
        }
        if (!previous_error) {
            if (!decimal_unchecked(context, &value, &value)) return 0;
            if (base_value.bytes[0] <= 0x4f) {
                (void)fx_decimal_decode(&decoded, &base_value);
                if (!decoded.sign) break;
            }
            if (value.bytes[0] <= 0x4f) {
                (void)fx_decimal_decode(&decoded, &value);
                if (!decoded.sign) break;
            }
            fx_numeric_status status = binary_record(&ratio, &value, &base_value, FX_DIVIDE);
            if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
            if (fx_number_kind(&ratio) != FX_NUMBER_ERROR) {
                (void)fx_decimal_decode(&decoded, &ratio);
            } else decoded.sign = -1;
            if (decoded.sign >= 0) {
                if (!absolute(context, &ratio) ||
                    !result(context, &ratio, fx_decimal_binary(&ratio, &ratio, &lower, FX_SUBTRACT))) return 0;
                (void)fx_decimal_decode(&decoded, &ratio);
                if (decoded.sign >= 0 && compare(&ratio, &width, 0) <= 0) break;
            }
        }
        if (!binary(context, step, step, &ten, FX_DIVIDE)) return 0;
    }
    return 1;
}

/* 04a62: plus callback first, then minus; normalize the divided difference
 * before integer cleanup. Keep its distinct add/subtract order. */
static int central_sample(derivative_context *context, fx_number *out,
                           const fx_number *point, const fx_number *step) {
    fx_number x, plus, minus, denominator;
    return binary(context, &x, point, step, FX_ADD) &&
        evaluate(context, &plus, &x, 0) &&
        binary(context, &x, point, step, FX_SUBTRACT) &&
        evaluate(context, &minus, &x, 0) &&
        binary_unchecked(context, out, &plus, &minus, FX_SUBTRACT) &&
        binary(context, &denominator, step, step, FX_ADD) &&
        binary_unchecked(context, out, out, &denominator, FX_DIVIDE) &&
        decimal_unchecked(context, out, out) && result(context, out, fx_decimal_integer_cleanup(out));
}

/* Overflow in the relative convergence error requests another table row;
 * it is not a sampling-domain error. */
static int relative_error(derivative_context *context, fx_number *out,
                           const fx_number *previous, const fx_number *current) {
    fx_numeric_status status = fx_decimal_subtract_cancel(out, previous, current);
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    if (fx_number_kind(out) == FX_NUMBER_ERROR) return 0;
    status = fx_decimal_binary(out, out, current, FX_DIVIDE);
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    if (fx_number_kind(out) == FX_NUMBER_ERROR) return 0;
    return absolute(context, out);
}

fx_numeric_status fx_number_derivative(fx_number *out, const fx_number *point,
                                       const fx_number *tolerance,
                                       fx_calculus_function function,
                                       void *userdata,
                                       const fx_calculus_control *control) {
    derivative_context context = {function, userdata, control, FX_NUMERIC_OK, 0};
    fx_number x, precision, step, table[16], previous, error, prior_error, best;
    fx_number value, two, factor, four, three;
    fx_decimal decoded;
    unsigned iteration, column, maximum = tolerance ? 15 : 10;
    int best_valid = 0, prior_error_valid = !tolerance;
    if (!out || !point || !function) return FX_NUMERIC_INVALID;
    if (!decimal(&context, &x, point)) goto done;
    if (tolerance) {
        if (!decimal(&context, &precision, tolerance)) goto done;
        (void)fx_decimal_decode(&decoded, &precision);
        if (decoded.sign <= 0) { context.native_error = 8; goto done; }
    } else {
        (void)fx_decimal_parse(&precision, "1e-10");
        (void)fx_decimal_parse(&prior_error, "1e-7");
    }
    (void)fx_decimal_from_integer(&two, 2);
    (void)fx_decimal_from_integer(&three, 3);
    (void)fx_decimal_from_integer(&four, 4);
    if (!evaluate(&context, &value, &x, 0) || !starting_step(&context, &step, &x) ||
        !select_step(&context, &step, &x) || !absolute(&context, &step) ||
        !central_sample(&context, &table[0], &x, &step)) goto done;
    for (iteration = 1; iteration <= maximum; ++iteration) {
        if (!poll(&context) || !binary(&context, &step, &step, &two, FX_DIVIDE)) goto done;
        previous = table[0];
        if (!central_sample(&context, &table[iteration], &x, &step) ||
            !result(&context, &factor, fx_number_negate(&factor, &three))) goto done;
        for (column = iteration; column > 0; --column) {
            if (!binary(&context, &value, &table[column-1], &table[column], FX_SUBTRACT) ||
                !binary(&context, &value, &value, &factor, FX_DIVIDE) ||
                !binary(&context, &table[column-1], &value, &table[column], FX_ADD)) goto done;
            if (column > 1 &&
                (!binary(&context, &factor, &factor, &four, FX_MULTIPLY) ||
                 !binary(&context, &factor, &factor, &three, FX_SUBTRACT))) goto done;
        }
        (void)fx_decimal_decode(&decoded, &table[0]);
        if (!decoded.sign) goto success;
        if (!relative_error(&context, &error, &previous, &table[0])) {
            if (context.host_status != FX_NUMERIC_OK) goto done;
            continue;
        }
        if (compare(&error, &precision, 1) <= 0) goto success;
        if (prior_error_valid) {
            (void)fx_decimal_decode(&decoded, &prior_error);
            while (decoded.sign && compare(&error, &prior_error, 1) <= 0) {
                best = table[0]; best_valid = 1;
                if (decoded.exponent == -9) fx_number_zero(&prior_error);
                else { --decoded.exponent; (void)fx_decimal_encode(&prior_error, &decoded); }
                (void)fx_decimal_decode(&decoded, &prior_error);
            }
        }
        (void)fx_decimal_decode(&decoded, &table[0]);
        if (decoded.exponent < -10) { fx_number_zero(&table[0]); goto success; }
    }
    if (best_valid) { table[0] = best; goto success; }
    context.native_error = 11;
    goto done;
success:
    *out = table[0]; return FX_NUMERIC_OK;
done:
    if (context.host_status != FX_NUMERIC_OK) return context.host_status;
    fx_number_error(out, context.native_error ? context.native_error : 3);
    return FX_NUMERIC_OK;
}
