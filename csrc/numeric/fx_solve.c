/* Handwritten Newton iteration with native finite-decimal recovery policies.
 * GPL-3.0-or-later. No CPU, firmware execution or host floating point. */
#include "fx_solve.h"
#include "../complex/fx_complex.h"
#include <string.h>

typedef struct {
    fx_solve_equation equation;
    void *userdata;
    const fx_calculus_control *control;
    fx_numeric_status host_status;
    fx_solve_result result;
    fx_number sides[2];
    fx_number point, previous_point, residual, previous_residual;
    fx_number rounded_point;
} solve_work;

static unsigned error(const fx_number *value)
{
    return value->bytes[0] >= 0xf0 ? value->bytes[0] & 15 : 0;
}

static int checked(solve_work *work, fx_numeric_status status)
{
    if (status != FX_NUMERIC_OK) { work->host_status = status; return 0; }
    return 1;
}

static unsigned classification(solve_work *work, const fx_number *value)
{
    uint8_t result = 0xf0;
    (void)checked(work, fx_scalar_numeric_classify(&result, value));
    return result;
}

/* The inner1BFxx routines admit ordinary decimals and rational payloads,
 * preserve bit40 arithmetic, and turn other formats into a Math error. */
static void binary(solve_work *work, fx_number *out, const fx_number *a,
                    const fx_number *b, fx_binary_op operation, int plain)
{
    fx_number first = *a, second = *b;
    unsigned i;
    fx_number *values[2] = { &first, &second };
    for (i = 0; i < 2; ++i) {
        fx_number_type kind = fx_number_kind(values[i]);
        if (kind != FX_NUMBER_DECIMAL && kind != FX_NUMBER_RATIONAL) {
            fx_number_error(out, 3); return;
        }
        if (kind == FX_NUMBER_RATIONAL) {
            uint8_t marker = values[i]->bytes[0] & 0x40;
            values[i]->bytes[0] &= (uint8_t)~0x40;
            if (!checked(work, fx_number_to_decimal(values[i], values[i]))) {
                fx_number_error(out,3); return;
            }
            values[i]->bytes[0] |= marker;
        }
    }
    if (operation == FX_ADD && plain)
        { if (!checked(work, fx_decimal_add_plain(out, &first, &second))) fx_number_error(out,3); }
    else if (operation == FX_SUBTRACT && !plain)
        { if (!checked(work, fx_decimal_subtract_cancel(out, &first, &second))) fx_number_error(out,3); }
    else if (!checked(work, fx_decimal_binary(out, &first, &second, operation))) fx_number_error(out,3);
}

static void absolute(solve_work *work, fx_number *value)
{
    unsigned sign = classification(work, value);
    if (sign == 0xf0) { fx_number_error(value,3); return; }
    value->bytes[0] &= (uint8_t)~0x40;
    if (sign == 2) (void)checked(work, fx_number_negate(value, value));
}

/* CD60 is ordinary finite comparison, with no near-cancellation cutoff. */
static unsigned compare(solve_work *work, const fx_number *a, const fx_number *b)
{
    fx_number difference;
    /* AB3E/AB36 are stricter than the arithmetic loader: comparison rejects
     * tagged/rational/surd headers before invoking decimal subtraction. */
    if (a->bytes[0] >= 10 || b->bytes[0] >= 10) return 0xf0;
    binary(work, &difference, a, b, FX_SUBTRACT, 1);
    return error(&difference) ? 0xf0 : classification(work, &difference);
}

static void constant(fx_number *out, const char *text)
{
    (void)fx_decimal_parse(out, text);
}

static void rounded(solve_work *work, fx_number *out, const fx_number *in,
                     unsigned significant)
{
    fx_decimal value;
    uint64_t unit = 1, original;
    unsigned i;
    *out = *in;
    if (in->bytes[0] >= 10) { fx_number_error(out,3); return; }
    if (!checked(work, fx_decimal_decode(&value, in))) return;
    if (!value.sign) return;
    for (i = significant; i < 15; ++i) unit *= 10;
    original = value.mantissa;
    value.mantissa = ((value.mantissa + unit / 2) / unit) * unit;
    if (value.mantissa >= UINT64_C(1000000000000000)) {
        if (value.exponent == 99) value.mantissa = original / unit * unit;
        else { value.mantissa /= 10; ++value.exponent; }
    }
    (void)checked(work, fx_decimal_encode(out, &value));
}

/* 1074C publishes a cleaned copy while retaining the uncleaned iteration
 * point. The callback writes both equation sides, even on a native error. */
static unsigned evaluate(solve_work *work, const fx_number *point)
{
    fx_number published = *point;
    fx_numeric_status status;
    unsigned code = error(&published);
    if (work->host_status != FX_NUMERIC_OK) return 3;
    if (!code) {
        if (!checked(work, fx_decimal_integer_cleanup(&published))) return 3;
        ++work->result.evaluations;
        status = work->equation(work->sides, &published, work->userdata);
        if (status < 0) { work->host_status = status; return 3; }
        code = (unsigned)status;
    }
    if (code) {
        unsigned record_code = code < 16 ? code : 3;
        fx_number_error(&work->sides[0], record_code);
        fx_number_error(&work->sides[1], record_code);
    }
    return code;
}

static unsigned update_residual(solve_work *work)
{
    binary(work, &work->residual, &work->sides[0], &work->sides[1], FX_SUBTRACT, 1);
    return classification(work, &work->residual);
}

static unsigned poll(solve_work *work)
{
    if (work->host_status != FX_NUMERIC_OK) return 3;
    ++work->result.cancellation_checks;
    return work->control && work->control->cancelled &&
        work->control->cancelled(work->control->userdata) ? 1u : 0u;
}

/* 107AA: central difference, retaining one-sided recovery when either nearby
 * expression fails. The relative step is1e-7 with a1e-93 absolute floor. */
static unsigned derivative(solve_work *work, fx_number *out)
{
    fx_number step = work->point, floor, relative, plus, minus, plus_difference;
    absolute(work, &step);
    constant(&floor, "1e-93"); constant(&relative, "1e-7");
    if (classification(work, &step) == 1) step = relative;
    else if (compare(work, &step, &floor) == 2) step = floor;
    else binary(work, &step, &step, &relative, FX_MULTIPLY, 0);
    binary(work, &plus, &step, &work->point, FX_ADD, 1);
    if (!evaluate(work, &plus)) {
        binary(work, &plus_difference, &work->sides[0], &work->sides[1], FX_SUBTRACT, 1);
        binary(work, &minus, &work->point, &step, FX_SUBTRACT, 1);
        if (!evaluate(work, &minus)) {
            binary(work, out, &work->sides[0], &work->sides[1], FX_SUBTRACT, 1);
            binary(work, &plus_difference, &plus_difference, out, FX_SUBTRACT, 1);
            binary(work, &step, &step, &step, FX_ADD, 1);
        }
        binary(work, out, &plus_difference, &step, FX_DIVIDE, 0);
    } else {
        binary(work, &minus, &work->point, &step, FX_SUBTRACT, 1);
        unsigned code = evaluate(work, &minus);
        if (code) return code;
        binary(work, out, &work->sides[0], &work->sides[1], FX_SUBTRACT, 1);
        (void)checked(work, fx_number_negate(out, out));
        binary(work, out, out, &step, FX_DIVIDE, 0);
    }
    return error(out);
}

/* Zero is tested only below the specified absolute threshold and is accepted
 * only when its newly evaluated two equation sides agree exactly. */
static int accepts_zero(solve_work *work, const char *threshold)
{
    fx_number magnitude = work->point, limit, zero;
    absolute(work, &magnitude); constant(&limit, threshold);
    if (compare(work, &magnitude, &limit) != 2) return 0;
    fx_number_zero(&zero); work->rounded_point = zero;
    if (evaluate(work, &zero)) return 0;
    return compare(work, &work->sides[1], &work->sides[0]) == 1;
}

/*105FE checks five, then ten significant digits. Return2 for evaluator
 * failure,0 for a rounded root and1 if both finite rounding probes fail. */
static unsigned accepts_rounding(solve_work *work)
{
    unsigned digits;
    for (digits = 5; digits <= 10; digits += 5) {
        rounded(work, &work->rounded_point, &work->point, digits);
        if (error(&work->rounded_point)) return 1;
        if (evaluate(work, &work->rounded_point)) return 2;
        if (compare(work, &work->sides[1], &work->sides[0]) == 1) return 0;
    }
    return 1;
}

static void failure(solve_work *work, unsigned status, const fx_number *original)
{
    work->result.firmware_status = (uint8_t)status;
    fx_number_error(&work->result.root, status > 0 && status < 16 ? status : 3);
    fx_number_zero(&work->result.residual);
    work->result.variable = *original;
}

fx_numeric_status fx_solve_root(fx_solve_result *out,
                                const fx_number *initial_variable,
                                fx_solve_equation equation, void *userdata,
                                const fx_calculus_control *control)
{
    static const char *const starts[] = { "0", "1e-5", "-1e-5", "1e-50", "-1e-50", "1e7", "-1e7" };
    solve_work work;
    fx_number original, candidate, scale, derivative_value, previous_derivative, step, temp, temp2, saved[2];
    unsigned code, iteration, midpoint_iterations, improvements, attempts, rounding_status;
    int limited;
    if (!out || !initial_variable || !equation) return FX_NUMERIC_INVALID;
    memset(&work, 0, sizeof work);
    work.equation = equation; work.userdata = userdata; work.control = control;
    original = *initial_variable;
    /* SOLVE forces18212 permission off. Its51CA variable read converts a
     * stored surd before saving the record that error cleanup restores. */
    if (fx_number_kind(&original) == FX_NUMBER_SURD)
        (void)checked(&work, fx_number_to_decimal(&original, &original));
    candidate = original;
    if (fx_number_kind(&candidate) == FX_NUMBER_DECIMAL) candidate.bytes[0] &= (uint8_t)~0x40;
    else if (candidate.bytes[0] >> 4 == 2)
        (void)checked(&work, fx_number_to_decimal(&candidate, &candidate));
    else fx_number_error(&candidate, 3);
    improvements = 0;

restart:
    iteration = midpoint_iterations = 0;
    fx_number_zero(&work.previous_point);
    work.point = candidate;
    code = evaluate(&work, &candidate);
    if (code == 2 || code == 7) goto failed;
    if (code) goto midpoint_recovery;

newton:
    if (update_residual(&work) == 1) goto converged;
    work.previous_residual = work.residual;
    temp = work.point;
    scale = work.point;
    if (classification(&work, &scale) == 1) constant(&scale, "1e-15");
    code = derivative(&work, &derivative_value);
    if (code || classification(&work, &derivative_value) == 1) goto midpoint_recovery;
    previous_derivative = derivative_value;
    binary(&work, &step, &work.residual, &derivative_value, FX_DIVIDE, 0);
    work.previous_point = work.point;
    binary(&work, &work.point, &work.point, &step, FX_SUBTRACT, 1);
    candidate = work.point;
    if (evaluate(&work, &candidate)) goto midpoint_recovery;
    if (update_residual(&work) == 1) goto converged;
    binary(&work, &temp2, &work.point, &temp, FX_SUBTRACT, 1);
    absolute(&work, &temp2); absolute(&work, &scale);
    binary(&work, &temp2, &temp2, &scale, FX_DIVIDE, 0); absolute(&work, &temp2);
    constant(&scale, "1e-13");
    if (compare(&work, &temp2, &scale) == 2) goto converged;
    temp = work.previous_residual; temp2 = work.residual;
    absolute(&work, &temp); absolute(&work, &temp2);
    binary(&work, &temp, &temp, &temp2, FX_SUBTRACT, 1);
    if (classification(&work, &temp) >= 4) {
        if ((code = poll(&work)) != 0) goto failed;
        if (++iteration < 40) goto newton;
        if (midpoint_iterations) goto alternate_start;
        goto limited_convergence;
    }

    /* A non-improving Newton step is damped toward the preceding point. */
    code = derivative(&work, &derivative_value);
    if (code) goto midpoint_recovery;
    if ((classification(&work, &previous_derivative) == 2 && classification(&work, &derivative_value) == 4) ||
        (classification(&work, &previous_derivative) == 4 && classification(&work, &derivative_value) == 2))
        goto alternate_start;
    if (improvements >= 50) goto limited_convergence;
    attempts = 0;
damping_retry:
    {
        if ((code = poll(&work)) != 0) goto failed;
        if (++attempts >= 30) goto alternate_start;
        binary(&work, &step, &work.previous_point, &work.point, FX_SUBTRACT, 1);
        constant(&temp, ".666666666666666");
        binary(&work, &step, &step, &temp, FX_MULTIPLY, 0);
        binary(&work, &work.point, &work.point, &step, FX_ADD, 1);
        candidate = work.point;
        /* A failed damping sample shares its current retry budget with the
         * midpoint fallback, rather than resetting the midpoint entry. */
        if (evaluate(&work, &candidate)) goto midpoint_retry;
        temp = work.sides[0];
        binary(&work, &temp, &temp, &work.sides[1], FX_SUBTRACT, 1); absolute(&work, &temp);
        temp2 = work.previous_residual; absolute(&work, &temp2);
        unsigned comparison = compare(&work, &temp, &temp2);
        if (comparison == 2 || comparison == 0xf0) {
            ++improvements;
            saved[0] = work.sides[0]; saved[1] = work.sides[1];
            if (accepts_zero(&work, "1e-50")) { work.point = work.rounded_point; goto export_result; }
            work.sides[0] = saved[0]; work.sides[1] = saved[1];
            goto newton;
        }
    }
    goto damping_retry;

midpoint_recovery:
    if (work.host_status != FX_NUMERIC_OK) return work.host_status;
    if (midpoint_iterations >= 13 ||
        (classification(&work, &work.point) == 1 && classification(&work, &work.previous_point) == 1))
        goto alternate_start;
    attempts = 0;
midpoint_retry:
    {
        if ((code = poll(&work)) != 0) goto failed;
        code = error(&work.sides[0]);
        if (code && code != 3) goto failed;
        if (++attempts >= 15) goto alternate_start;
        temp = work.point; temp2 = work.previous_point;
        absolute(&work, &temp); absolute(&work, &temp2);
        if (compare(&work, &temp, &temp2) < 4)
            binary(&work, &step, &work.previous_point, &work.point, FX_SUBTRACT, 1);
        else binary(&work, &step, &work.point, &work.previous_point, FX_SUBTRACT, 1);
        constant(&temp, "2");
        binary(&work, &step, &step, &temp, FX_DIVIDE, 0);
        temp = compare(&work, &work.point, &work.previous_point) < 4 ? work.point : work.previous_point;
        absolute(&work, &step);
        binary(&work, &work.point, &step, &temp, FX_ADD, 1);
        candidate = work.point;
        if (evaluate(&work, &candidate)) goto midpoint_retry;
        ++midpoint_iterations;
        if (update_residual(&work) == 1) goto export_result;
        saved[0] = work.sides[0]; saved[1] = work.sides[1];
        rounded(&work, &candidate, &work.point, 3);
        if (!evaluate(&work, &candidate) && update_residual(&work) == 1) {
            work.point = candidate; goto converged;
        }
        work.sides[0] = saved[0]; work.sides[1] = saved[1];
        goto newton;
    }

alternate_start:
    if (++work.result.alternate_starts >= 8) { code = 10; goto failed; }
    constant(&candidate, starts[work.result.alternate_starts - 1]);
    goto restart;

converged:
    limited = 0;
    goto final_checks;
limited_convergence:
    limited = 1;
final_checks:
    if (accepts_zero(&work, "1e-12")) work.point = work.rounded_point;
    else {
        rounding_status = accepts_rounding(&work);
        if (rounding_status == 2) { code = 10; goto failed; }
        if (!rounding_status) work.point = work.rounded_point;
        else if (limited) work.result.firmware_status = 36;
    }
export_result:
    candidate = work.point;
    if (evaluate(&work, &candidate)) { code = 10; goto failed; }
    work.result.root = work.point;
    binary(&work, &work.result.residual, &work.sides[0], &work.sides[1], FX_SUBTRACT,
            work.result.firmware_status == 36);
    work.result.variable = work.point;
    goto finished;
failed:
    failure(&work, code, &original);
finished:
    if (work.host_status != FX_NUMERIC_OK) return work.host_status;
    *out = work.result;
    return FX_NUMERIC_OK;
}
