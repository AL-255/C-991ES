/* Equation formulas in the original finite-scalar operation order.
 * GPL-3.0-or-later. No ROM execution or host floating point. */
#include "fx_solver.h"
#include "fx_solver_stage.h"
#include "../linalg/fx_linalg_stage.h"
#include "fx_root.h"
#include "../linalg/fx_linalg.h"
#include "../trig/fx_trig_inverse.h"
#include <string.h>

static uint8_t error(const fx_number *n)
{
    return n->bytes[0] >= 0xf0 ? n->bytes[0] & 15 : 0;
}
static int poll(fx_solver_result *r, const fx_solver_context *context)
{
    ++r->cancellation_checks;
    if (!context->cancel_at || context->cancel_at != r->cancellation_checks) return 0;
    r->firmware_status = 1;
    return 1;
}
static fx_numeric_status classify(uint8_t *out, const fx_number *n)
{
    return fx_scalar_numeric_classify(out, n);
}
static fx_numeric_status prepare(fx_number *out, const fx_number *in)
{
    fx_rational recognized;
    *out = *in;
    if ((out->bytes[0] & 0xf0) == 0x40) out->bytes[0] &= (uint8_t)~0x40;
    if (fx_number_recognize_rational(&recognized, out))
        return fx_rational_encode(out, &recognized);
    return FX_NUMERIC_OK;
}
/* 0x1876c selects fraction construction only for two plain decimals.
 * Other records retain generic scalar division's exact/metadata policy. */
static fx_numeric_status divide(fx_number *out, const fx_number *a,
                                const fx_number *b)
{
    int64_t numerator, denominator;
    if (a->bytes[0] >= 0xf0 || b->bytes[0] >= 0xf0) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    if (a->bytes[0] < 10 && b->bytes[0] < 10 &&
        fx_number_fractional_status(a) == 0 && fx_number_fractional_status(b) == 0 &&
        fx_decimal_to_integer(&numerator, a) == FX_NUMERIC_OK &&
        fx_decimal_to_integer(&denominator, b) == FX_NUMERIC_OK && denominator) {
        fx_rational ratio;
        if (denominator < 0) { numerator = -numerator; denominator = -denominator; }
        ratio.numerator = numerator; ratio.denominator = (uint64_t)denominator;
        ratio.flags = 0;
        return fx_rational_encode(out, &ratio);
    }
    return fx_number_binary(out, a, b, FX_DIVIDE);
}
static fx_numeric_status absolute(fx_number *out, const fx_number *in)
{
    uint8_t type;
    fx_numeric_status status = classify(&type, in);
    if (status != FX_NUMERIC_OK) return status;
    if (type == 0xf0) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
    *out = *in; out->bytes[0] &= (uint8_t)~0x40;
    return type == 2 ? fx_number_negate(out, out) : FX_NUMERIC_OK;
}
static fx_numeric_status square_root(fx_number *out, const fx_number *in,
                                     const fx_solver_context *context)
{
    /* Rational perfect squares survive the native Math-off gate. A
     * nonperfect square instead follows separate numerator/denominator
     * decimal roots, rather than converting the hypothetical exact surd. */
    if (!context->exact_math && fx_number_kind(in) == FX_NUMBER_RATIONAL) {
        fx_number exact;
        fx_numeric_status status = fx_number_sqrt(&exact, in, 1);
        if (status != FX_NUMERIC_OK) return status;
        if (fx_number_kind(&exact) != FX_NUMBER_SURD) { *out = exact; return status; }
    }
    return fx_number_sqrt(out, in, context->exact_math);
}
static fx_numeric_status arithmetic(fx_number *out, const fx_number *a,
                                    const fx_number *b, fx_binary_op op)
{
    if (a->bytes[0] >= 0xf0 || b->bytes[0] >= 0xf0) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    return fx_number_binary(out, a, b, op);
}
static fx_linalg_context following_context(const fx_solver_context *context,
                                            const fx_solver_result *r)
{
    fx_linalg_context next;
    fx_linalg_context_default(&next); next.exact_math = context->exact_math;
    next.cancel_at = context->cancel_at > r->cancellation_checks
        ? context->cancel_at - r->cancellation_checks : 0;
    return next;
}
typedef struct {
    fx_solver_result *result;
    fx_solver_stage_callback callback;
    void *userdata;
    fx_solver_linear_stage stage;
} linear_observer;
static int observe_matrix(const fx_linalg_result *matrix, void *userdata)
{
    linear_observer *observer = userdata;
    fx_solver_result snapshot = *observer->result;
    unsigned i;
    snapshot.cancellation_checks += matrix->cancellation_checks;
    snapshot.coefficient_rows = matrix->value.rows;
    snapshot.coefficient_columns = matrix->value.columns;
    for (i = 0; i < 9; ++i)
        snapshot.coefficient_work[i] = matrix->value.cells[i];
    return observer->callback
        ? observer->callback(&snapshot, observer->stage, observer->userdata) : 0;
}
static int observe_solver_poll(fx_solver_result *result,
                              const fx_solver_context *context,
                              linear_observer *observer,
                              fx_solver_linear_stage stage)
{
    int requested = 0;
    ++result->cancellation_checks;
    if (observer && observer->callback)
        requested = observer->callback(result, stage, observer->userdata);
    if (requested || (context->cancel_at &&
                      context->cancel_at == result->cancellation_checks)) {
        result->firmware_status = 1;
        return 1;
    }
    return 0;
}
static fx_numeric_status linear(fx_solver_result *r, const fx_number c[12],
                                unsigned dimension, const fx_solver_context *context,
                                linear_observer *observer)
{
    fx_linalg_value matrix, rhs;
    fx_linalg_result stage;
    fx_linalg_context next;
    fx_numeric_status status;
    unsigned row, column;
    memset(&matrix, 0, sizeof matrix); memset(&rhs, 0, sizeof rhs);
    matrix.reference.bytes[0] = 0x64; rhs.reference.bytes[0] = 0x65;
    matrix.rows = matrix.columns = rhs.rows = (uint8_t)dimension; rhs.columns = 1;
    r->coefficient_rows = r->coefficient_columns = r->root_rows = (uint8_t)dimension;
    r->root_columns = 1;
    for (row = 0; row < dimension; ++row) {
        for (column = 0; column < dimension; ++column)
            matrix.cells[row*3 + column] = c[row*3 + column];
        rhs.cells[row*3] = c[dimension == 2 ? row*3 + 2 : 9 + row];
    }
    memcpy(r->coefficient_work, matrix.cells, sizeof matrix.cells);
    next = following_context(context, r);
    status = fx_linalg_unary(&stage, &rhs, FX_LINALG_RATIONAL_PREPARE, &next);
    if (status != FX_NUMERIC_OK) return status;
    rhs = stage.value; memcpy(r->root_work, rhs.cells, sizeof rhs.cells);
    if (observe_solver_poll(r, context, observer, FX_SOLVER_RHS_PREPARED)) return FX_NUMERIC_OK;
    next = following_context(context, r);
    if (observer) observer->stage = FX_SOLVER_MATRIX_INVERTING;
    status = fx_linalg_inverse_observed(&stage, &matrix, &next,
        observer ? observe_matrix : NULL, observer);
    if (status != FX_NUMERIC_OK) return status;
    matrix = stage.value;
    r->cancellation_checks += stage.cancellation_checks;
    r->firmware_status = stage.firmware_status;
    memcpy(r->coefficient_work, matrix.cells, sizeof matrix.cells);
    if (r->firmware_status || observe_solver_poll(r, context, observer, FX_SOLVER_INVERSE_PREPARED)) return FX_NUMERIC_OK;
    next = following_context(context, r);
    if (observer) observer->stage = FX_SOLVER_MATRIX_MULTIPLYING;
    status = fx_linalg_multiply_observed(&stage, &matrix, &rhs, &next,
        observer ? observe_matrix : NULL, observer);
    if (status != FX_NUMERIC_OK) return status;
    r->cancellation_checks += stage.cancellation_checks;
    r->firmware_status = stage.firmware_status;
    memcpy(r->coefficient_work, stage.value.cells, sizeof stage.value.cells);
    r->coefficient_columns = stage.value.columns;
    if (!r->firmware_status) r->count = (uint8_t)dimension;
    return FX_NUMERIC_OK;
}

/* Native 0x150b2: the positive-discriminant branch computes the smaller
 * root using 2ac/(sqrt(D)+abs(b)), avoiding subtraction cancellation. */
static fx_numeric_status quadratic(fx_solver_result *r, unsigned degree,
                                   const fx_solver_context *context)
{
    fx_number *c = r->coefficient_work, *roots = r->root_work;
    uint8_t discriminant_type, b_type, c_type;
    fx_numeric_status status = classify(&c_type, &c[2]);
    if (status != FX_NUMERIC_OK) return status;
    if (c_type == 1) {
        roots[0] = c[1]; r->count = 1;
        status = classify(&b_type, &roots[0]);
        if (status != FX_NUMERIC_OK || b_type == 1) return status;
        status = fx_number_negate(&roots[0], &roots[0]);
        if (status == FX_NUMERIC_OK) status = divide(&roots[0], &roots[0], &c[0]);
        r->firmware_status = error(&roots[0]);
        if (!r->firmware_status) r->count = 2;
        return status;
    }
    c[4] = c[1];
    status = fx_number_integer_power(&c[4], &c[4], 2);
    fx_decimal_from_u8(&c[5], 4);
    if (status == FX_NUMERIC_OK) status = fx_number_binary(&c[5], &c[5], &c[0], FX_MULTIPLY);
    if (status == FX_NUMERIC_OK) status = fx_number_binary(&c[5], &c[5], &c[2], FX_MULTIPLY);
    if (status == FX_NUMERIC_OK) status = fx_number_binary(&c[4], &c[4], &c[5], FX_SUBTRACT);
    if (status != FX_NUMERIC_OK) return status;
    r->firmware_status = error(&c[4]);
    if (r->firmware_status) return FX_NUMERIC_OK;
    fx_decimal_from_u8(&c[5], 2); fx_decimal_from_u8(&c[6], 2);
    status = fx_number_binary(&c[6], &c[6], &c[0], FX_MULTIPLY);
    if (status != FX_NUMERIC_OK || poll(r, context)) return status;
    status = classify(&discriminant_type, &c[4]);
    if (status != FX_NUMERIC_OK) return status;
    if (discriminant_type != 4) {
        roots[0] = c[1];
        status = fx_number_negate(&roots[0], &roots[0]);
        if (status == FX_NUMERIC_OK) status = divide(&roots[0], &roots[0], &c[6]);
        if (status != FX_NUMERIC_OK) return status;
        r->firmware_status = error(&roots[0]);
        if (r->firmware_status) return FX_NUMERIC_OK;
        r->count = (uint8_t)(degree-1);
        if (discriminant_type != 2) return FX_NUMERIC_OK;
        if (context->real_only) {
            memset(roots, 0, 3*sizeof *roots); r->count = (uint8_t)(degree-2); return FX_NUMERIC_OK;
        }
        roots[3] = roots[0];
        status = fx_number_negate(&c[4], &c[4]);
        if (status == FX_NUMERIC_OK) status = square_root(&c[4], &c[4], context);
        if (status == FX_NUMERIC_OK) status = divide(&c[4], &c[4], &c[6]);
        if (status != FX_NUMERIC_OK) return status;
        r->firmware_status = error(&c[4]);
        if (r->firmware_status) return FX_NUMERIC_OK;
        roots[1] = c[4];
        status = fx_number_negate(&c[4], &c[4]); roots[4] = c[4];
        r->count = (uint8_t)degree; return status;
    }
    status = square_root(&c[4], &c[4], context);
    if (status == FX_NUMERIC_OK) status = classify(&b_type, &c[1]);
    if (status == FX_NUMERIC_OK) status = absolute(&c[1], &c[1]);
    if (status == FX_NUMERIC_OK) status = fx_number_binary(&c[4], &c[4], &c[1], FX_ADD);
    if (status == FX_NUMERIC_OK) status = fx_number_binary(&c[5], &c[5], &c[2], FX_MULTIPLY);
    if (status == FX_NUMERIC_OK) status = divide(&c[5], &c[5], &c[4]);
    if (status != FX_NUMERIC_OK) return status;
    r->firmware_status = error(&c[5]);
    if (r->firmware_status) return FX_NUMERIC_OK;
    status = divide(&c[4], &c[4], &c[6]);
    if (status != FX_NUMERIC_OK) return status;
    r->firmware_status = error(&c[4]);
    if (r->firmware_status) return FX_NUMERIC_OK;
    if (b_type == 2) { roots[0] = c[4]; roots[3] = c[5]; }
    else {
        status = fx_number_negate(&c[4], &c[4]);
        if (status == FX_NUMERIC_OK) status = fx_number_negate(&c[5], &c[5]);
        roots[0] = c[5]; roots[3] = c[4];
    }
    r->count = (uint8_t)degree; return status;
}

/* Each step stores fifteen external digits, as in the original formulas.
 * Native error tests occur only at the indicated formula boundaries. */
#define STEP(operation) do { status = (operation); if (status != FX_NUMERIC_OK) return status; } while (0)
#define CHECK(number) do { r->firmware_status = error(number); if ((number)->bytes[0] >= 0xf0) { r->firmware_status = 3; return FX_NUMERIC_OK; } } while (0)
static fx_numeric_status shifted_root(fx_number *out, const fx_number *b,
                                      const fx_number *three_a, int subtract)
{
    fx_numeric_status status = arithmetic(out, out, b, subtract ? FX_SUBTRACT : FX_ADD);
    return status == FX_NUMERIC_OK ? divide(out, out, three_a) : status;
}
static fx_numeric_status cubic(fx_solver_result *r, const fx_solver_context *context)
{
    static const fx_number pi = {{0x03,0x14,0x15,0x92,0x65,0x35,0x89,0x80,0x00,0x01}};
    fx_number *c = r->coefficient_work, *roots = r->root_work, two, three;
    fx_numeric_status status;
    uint8_t type, q_type;
    unsigned i, matched;
    STEP(classify(&type, &c[3]));
    if (type == 1) return quadratic(r, 3, context);
    /* P = 3ac-b². */
    fx_decimal_from_u8(&c[4], 3);
    STEP(arithmetic(&c[4], &c[4], &c[0], FX_MULTIPLY));
    STEP(arithmetic(&c[4], &c[4], &c[2], FX_MULTIPLY));
    c[8] = c[1]; STEP(fx_number_integer_power(&c[8], &c[8], 2));
    STEP(arithmetic(&c[4], &c[4], &c[8], FX_SUBTRACT)); CHECK(&c[4]);
    /* Q = 27a²d-9abc+2b³; retain a², abc and b³ in the root bank. */
    fx_decimal_from_u8(&c[5], 27);
    roots[0] = c[0]; STEP(fx_number_integer_power(&roots[0], &roots[0], 2));
    STEP(arithmetic(&c[5], &c[5], &roots[0], FX_MULTIPLY));
    STEP(arithmetic(&c[5], &c[5], &c[3], FX_MULTIPLY)); c[6] = c[5];
    fx_decimal_from_u8(&c[7], 9); roots[1] = c[0];
    STEP(arithmetic(&roots[1], &roots[1], &c[1], FX_MULTIPLY));
    STEP(arithmetic(&roots[1], &roots[1], &c[2], FX_MULTIPLY));
    STEP(arithmetic(&c[7], &c[7], &roots[1], FX_MULTIPLY));
    STEP(arithmetic(&c[5], &c[5], &c[7], FX_SUBTRACT));
    fx_decimal_from_u8(&c[7], 2); roots[2] = c[1];
    STEP(fx_number_integer_power(&roots[2], &roots[2], 3));
    STEP(arithmetic(&c[7], &c[7], &roots[2], FX_MULTIPLY));
    STEP(arithmetic(&c[5], &c[5], &c[7], FX_ADD)); CHECK(&c[5]);
    /* H = 27a²d²-18abcd+4b³d+4ac³-b²c². A positive H selects Cardano. */
    STEP(arithmetic(&c[6], &c[6], &c[3], FX_MULTIPLY));
    fx_decimal_from_u8(&c[7], 18);
    STEP(arithmetic(&c[7], &c[7], &c[3], FX_MULTIPLY));
    STEP(arithmetic(&c[7], &c[7], &roots[1], FX_MULTIPLY));
    STEP(arithmetic(&c[6], &c[6], &c[7], FX_SUBTRACT));
    fx_decimal_from_u8(&c[7], 4);
    STEP(arithmetic(&c[7], &c[7], &c[3], FX_MULTIPLY));
    STEP(arithmetic(&c[7], &c[7], &roots[2], FX_MULTIPLY));
    STEP(arithmetic(&c[6], &c[6], &c[7], FX_ADD));
    c[7] = c[2]; STEP(fx_number_integer_power(&c[7], &c[7], 3));
    fx_decimal_from_u8(&roots[2], 4);
    STEP(arithmetic(&c[7], &c[7], &roots[2], FX_MULTIPLY));
    STEP(arithmetic(&c[7], &c[7], &c[0], FX_MULTIPLY));
    STEP(arithmetic(&c[6], &c[6], &c[7], FX_ADD));
    c[7] = c[2]; STEP(fx_number_integer_power(&c[7], &c[7], 2));
    STEP(arithmetic(&c[7], &c[7], &c[8], FX_MULTIPLY));
    STEP(arithmetic(&c[6], &c[6], &c[7], FX_SUBTRACT)); CHECK(&c[6]);
    fx_decimal_from_u8(&c[3], 3);
    STEP(arithmetic(&c[3], &c[3], &c[0], FX_MULTIPLY));
    memset(roots, 0, 9*sizeof *roots);
    if (poll(r, context)) return FX_NUMERIC_OK;
    STEP(classify(&type, &c[6]));
    fx_decimal_from_u8(&two, 2); fx_decimal_from_u8(&three, 3);
    if (type == 1) {
        /* The simple root precedes the repeated root. Triple roots leave
         * the second scratch result present but only one result active. */
        roots[0] = c[5]; fx_decimal_from_u8(&two, 4);
        STEP(arithmetic(&roots[0], &roots[0], &two, FX_MULTIPLY));
        STEP(fx_number_cbrt(&roots[0], &roots[0]));
        STEP(shifted_root(&roots[0], &c[1], &c[3], 0));
        STEP(fx_number_negate(&roots[0], &roots[0])); CHECK(&roots[0]);
        roots[3] = c[5]; fx_decimal_from_u8(&two, 2);
        STEP(divide(&roots[3], &roots[3], &two));
        STEP(fx_number_cbrt(&roots[3], &roots[3]));
        STEP(shifted_root(&roots[3], &c[1], &c[3], 1)); CHECK(&roots[3]);
        STEP(classify(&type, &c[5])); r->count = type == 1 ? 1 : 2;
        return FX_NUMERIC_OK;
    }
    if (type != 2) {
        /* S = a*sqrt(27H); u and v use separate stored cube roots. */
        fx_decimal_from_u8(&c[7], 27);
        STEP(arithmetic(&c[6], &c[6], &c[7], FX_MULTIPLY));
        STEP(square_root(&c[6], &c[6], context));
        STEP(arithmetic(&c[6], &c[6], &c[0], FX_MULTIPLY)); c[4] = c[6];
        STEP(arithmetic(&c[6], &c[6], &c[5], FX_SUBTRACT));
        STEP(divide(&c[6], &c[6], &two)); STEP(fx_number_cbrt(&c[6], &c[6]));
        STEP(arithmetic(&c[4], &c[4], &c[5], FX_ADD));
        STEP(divide(&c[4], &c[4], &two)); STEP(fx_number_cbrt(&c[4], &c[4]));
        roots[0] = c[6]; STEP(arithmetic(&roots[0], &roots[0], &c[4], FX_SUBTRACT));
        roots[3] = roots[0];
        STEP(shifted_root(&roots[0], &c[1], &c[3], 1)); CHECK(&roots[0]);
        if (context->real_only) { r->count = 1; return FX_NUMERIC_OK; }
        STEP(divide(&roots[3], &roots[3], &two));
        STEP(shifted_root(&roots[3], &c[1], &c[3], 0));
        STEP(fx_number_negate(&roots[3], &roots[3])); CHECK(&roots[3]); roots[6] = roots[3];
        roots[4] = c[6]; STEP(arithmetic(&roots[4], &roots[4], &c[4], FX_ADD));
        STEP(divide(&roots[4], &roots[4], &c[3])); STEP(divide(&roots[4], &roots[4], &two));
        fx_decimal_from_u8(&c[4], 3); STEP(square_root(&c[4], &c[4], context));
        STEP(arithmetic(&roots[4], &roots[4], &c[4], FX_MULTIPLY)); CHECK(&roots[4]);
        STEP(fx_number_negate(&roots[7], &roots[4])); r->count = 3; return FX_NUMERIC_OK;
    }
    /* Three real roots: theta = atan(a*sqrt(-27H)/Q), stepped by 2pi. */
    c[2] = pi; STEP(arithmetic(&c[2], &c[2], &two, FX_MULTIPLY));
    fx_decimal_from_u8(&c[7], 27);
    STEP(arithmetic(&c[6], &c[6], &c[7], FX_MULTIPLY));
    STEP(fx_number_negate(&c[6], &c[6])); STEP(square_root(&c[6], &c[6], context));
    STEP(arithmetic(&c[6], &c[6], &c[0], FX_MULTIPLY));
    STEP(divide(&c[6], &c[6], &c[5]));
    fx_decimal_from_u8(&c[7], 1); STEP(classify(&q_type, &c[5]));
    if (q_type == 2) STEP(fx_number_negate(&c[7], &c[7]));
    STEP(fx_trig_inverse_decimal(&c[6], &c[6], FX_TANGENT, FX_RADIANS));
    if (c[6].bytes[0] >= 0xf0) {
        c[6] = pi; STEP(divide(&c[6], &c[6], &two));
        STEP(classify(&type, &c[0]));
        if (type == 1) fx_number_zero(&c[6]);
        else if (type == 2) STEP(fx_number_negate(&c[6], &c[6]));
        if (q_type == 2) STEP(fx_number_negate(&c[6], &c[6]));
    }
    STEP(fx_number_negate(&c[3], &c[3]));
    STEP(fx_number_negate(&c[4], &c[4])); STEP(square_root(&c[4], &c[4], context));
    STEP(arithmetic(&c[4], &c[4], &two, FX_MULTIPLY));
    STEP(arithmetic(&c[4], &c[4], &c[7], FX_MULTIPLY));
    for (i = 0; i < 3; ++i) {
        roots[i*3] = c[6];
        if (i) STEP(arithmetic(&roots[i*3], &roots[i*3], &c[2], FX_ADD));
        if (i == 2) STEP(arithmetic(&roots[i*3], &roots[i*3], &c[2], FX_ADD));
        STEP(divide(&roots[i*3], &roots[i*3], &three));
        STEP(fx_trig_evaluate(&roots[i*3], &roots[i*3], FX_COSINE, FX_RADIANS, context->exact_math, &matched));
        STEP(arithmetic(&roots[i*3], &roots[i*3], &c[4], FX_MULTIPLY));
        STEP(shifted_root(&roots[i*3], &c[1], &c[3], 0)); CHECK(&roots[i*3]);
    }
    r->count = 3; return FX_NUMERIC_OK;
}
#undef STEP
#undef CHECK

void fx_solver_context_default(fx_solver_context *context)
{
    if (!context) return;
    context->exact_math = 1; context->real_only = 0; context->cancel_at = 0;
}
fx_numeric_status fx_solver_solve(fx_solver_result *out,
                                 const fx_number coefficients[12],
                                 fx_solver_kind kind,
                                 const fx_solver_context *context)
{
    fx_solver_result result;
    fx_number input[12], leading;
    fx_numeric_status status;
    unsigned i;
    uint8_t before, after;
    if (!out || !coefficients || !context || context->exact_math > 1 ||
        context->real_only > 1 || kind < FX_SOLVER_LINEAR2 || kind > FX_SOLVER_CUBIC)
        return FX_NUMERIC_INVALID;
    memcpy(input, coefficients, sizeof input); memset(&result, 0, sizeof result);
    if (kind < FX_SOLVER_QUADRATIC) {
        status = linear(&result, input, (unsigned)kind+1, context, NULL);
        if (status != FX_NUMERIC_OK) return status;
    } else {
        result.coefficient_rows = result.coefficient_columns = result.root_rows = result.root_columns = 3;
        for (i = 0; i < (unsigned)kind; ++i) result.coefficient_work[i] = input[i];
        for (i = 0; i < 9; ++i) {
            status = prepare(&result.coefficient_work[i], &result.coefficient_work[i]);
            if (status != FX_NUMERIC_OK) return status;
        }
        if (poll(&result, context)) goto done;
        leading = result.coefficient_work[0]; result.coefficient_work[4] = leading;
        for (i = 0; i < 4; ++i) {
            status = classify(&before, &result.coefficient_work[i]);
            if (status == FX_NUMERIC_OK) status = divide(&result.coefficient_work[i], &result.coefficient_work[i], &leading);
            if (status != FX_NUMERIC_OK) return status;
            result.firmware_status = error(&result.coefficient_work[i]);
            if (result.firmware_status) goto done;
            status = classify(&after, &result.coefficient_work[i]);
            if (status != FX_NUMERIC_OK) return status;
            if (after == 1 && before != 1) { result.firmware_status = 3; goto done; }
            status = fx_decimal_integer_cleanup(&result.coefficient_work[i]);
            if (status != FX_NUMERIC_OK) return status;
            result.firmware_status = error(&result.coefficient_work[i]);
            if (result.firmware_status) goto done;
            /* 0x173fa converts only a compact surd; existing fractions
             * remain exact even when natural Math output is disabled. */
            if (!context->exact_math && fx_number_kind(&result.coefficient_work[i]) == FX_NUMBER_SURD) {
                status = fx_number_to_decimal(&result.coefficient_work[i], &result.coefficient_work[i]);
                if (status != FX_NUMERIC_OK) return status;
            }
        }
        if (poll(&result, context)) goto done;
        status = kind == FX_SOLVER_CUBIC ? cubic(&result, context) : quadratic(&result, 2, context);
        if (status != FX_NUMERIC_OK) return status;
    }
done:
    if (result.firmware_status) result.count = 0;
    for (i = 0; i < result.count; ++i) {
        const fx_number *values = kind < FX_SOLVER_QUADRATIC ? result.coefficient_work : result.root_work;
        result.roots[i].real = values[i*3]; result.roots[i].imaginary = values[i*3+1];
    }
    *out = result; return FX_NUMERIC_OK;
}
fx_numeric_status fx_solver_cleanup(fx_solver_result *out,
                                   const fx_solver_result *input)
{
    fx_solver_result result;
    fx_numeric_status status;
    uint8_t native;
    unsigned i;
    if (!out || !input || input->count > 3) return FX_NUMERIC_INVALID;
    result = *input;
    for (i = 0; i < result.count && !result.firmware_status; ++i) {
        fx_complex original = result.roots[i];
        status = fx_complex_cleanup(&result.roots[i], &original);
        if (status != FX_NUMERIC_OK) return status;
        status = fx_complex_firmware_status(&native, FX_COMPLEX_CLEANUP_RETURN, &original, &result.roots[i]);
        if (status != FX_NUMERIC_OK) return status;
        result.firmware_status = native;
    }
    *out = result; return FX_NUMERIC_OK;
}

fx_numeric_status fx_solver_solve_linear_observed(fx_solver_result *out,
    const fx_number coefficients[12], fx_solver_kind kind,
    const fx_solver_context *context, fx_solver_stage_callback callback,
    void *userdata)
{
    fx_solver_result result;
    fx_number input[12];
    fx_numeric_status status;
    unsigned i;
    linear_observer observer = {&result, callback, userdata, FX_SOLVER_RHS_PREPARED};
    if (!out || !coefficients || !context || context->exact_math > 1 ||
        context->real_only > 1 || kind < FX_SOLVER_LINEAR2 || kind > FX_SOLVER_LINEAR3)
        return FX_NUMERIC_INVALID;
    memcpy(input, coefficients, sizeof input);
    memset(&result, 0, sizeof result);
    status = linear(&result, input, (unsigned)kind + 1, context, &observer);
    if (status != FX_NUMERIC_OK) return status;
    if (result.firmware_status) result.count = 0;
    for (i = 0; i < result.count; ++i) {
        result.roots[i].real = result.coefficient_work[i*3];
        result.roots[i].imaginary = result.coefficient_work[i*3+1];
    }
    *out = result;
    return FX_NUMERIC_OK;
}
