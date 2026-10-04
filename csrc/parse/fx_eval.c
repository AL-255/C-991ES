/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_eval.h"
#include "fx_tokens.h"
#include "../trig/fx_trig_math.h"
#include "../trig/fx_trig_inverse.h"
#include "../trig/fx_trig_hyperbolic.h"
#include "../numeric/fx_transcend.h"
#include "../numeric/fx_root.h"
#include "../numeric/fx_combinatorics.h"
#include "../numeric/fx_logbase.h"
#include "../numeric/fx_integral.h"
#include "../numeric/fx_derivative.h"
#include "../complex/fx_complex_dispatch.h"
#include "../complex/fx_complex_angle.h"
#include <string.h>

typedef struct {
    const uint8_t *input;
    size_t length, position;
    unsigned depth;
    fx_eval_options options;
    fx_eval_variables *variables;
    fx_linalg_bank *linear_algebra;
    const fx_calculus_control *control;
    uint8_t calculus_mode, calculus_token, scan_only;
    fx_eval_status status;
    uint8_t unsupported;
} parser;

static uint8_t peek(const parser *p)
{
    return p->position < p->length ? p->input[p->position] : 0;
}

static void unsupported(parser *p, uint8_t token)
{
    p->status = FX_EVAL_UNIMPLEMENTED;
    p->unsupported = token;
}

static void accept_operation(parser *p, fx_number *value, fx_numeric_status status)
{
    if (status == FX_NUMERIC_UNIMPLEMENTED || status == FX_NUMERIC_UNREPRESENTABLE) {
        unsupported(p, 0); return;
    }
    if (status != FX_NUMERIC_OK || fx_number_kind(value) == FX_NUMBER_ERROR) {
        p->status = FX_EVAL_MATH; return;
    }
    /* The expression dispatcher (16562..16588), unlike the arithmetic leaf,
     * removes tiny trailing residues after each successful operation. */
    if (fx_decimal_integer_cleanup(value) != FX_NUMERIC_OK) {
        p->status = FX_EVAL_MATH; return;
    }
}

static fx_complex_dispatch_context complex_context(const parser *p)
{
    fx_complex_dispatch_context context = fx_complex_dispatch_default_context();
    context.calculation_context = p->options.calculation_context;
    context.exact_math = p->options.math_output;
    context.angle_unit = p->options.angle_unit;
    return context;
}

static void accept_complex_operation(parser *p, fx_complex *destination,
                                     const fx_complex *output,
                                     fx_numeric_status status, uint8_t firmware_status)
{
    if (status == FX_NUMERIC_UNIMPLEMENTED || status == FX_NUMERIC_UNREPRESENTABLE) {
        unsupported(p, 0); return;
    }
    if (status != FX_NUMERIC_OK) { p->status = FX_EVAL_MATH; return; }
    *destination = *output;
    p->status = (fx_eval_status)firmware_status;
}

static void binary(parser *p, fx_complex *left, const fx_complex *right, fx_binary_op op)
{
    fx_complex output = *left;
    if (p->scan_only) { fx_complex_zero(left); return; }
    if (p->options.calculation_context == 0xc4) {
        static const uint8_t tokens[] = {'+', '-', 0x4e, 0x4f};
        fx_complex_dispatch_context context = complex_context(p);
        uint8_t firmware_status = 0;
        fx_numeric_status status = fx_complex_dispatch_binary(&output, left, right,
                                                               tokens[op], &context, &firmware_status);
        accept_complex_operation(p, left, &output, status, firmware_status);
    } else {
        fx_numeric_status status = fx_number_binary(&output.real, &left->real, &right->real, op);
        accept_operation(p, &output.real, status);
        if (p->status == FX_EVAL_OK) *left = output;
    }
}

static void expression(parser *p, fx_complex *out, unsigned minimum);

static int store_token(const parser *p)
{
    fx_evaluator_token decoded = fx_decode_evaluator_token(peek(p), p->options.calculation_context);
    return decoded.kind == 8 && decoded.value <= 11;
}

static int omitted_closing(parser *p)
{
    if (!peek(p) || (p->calculus_mode && peek(p) == ',')) return 1;
    if (store_token(p)) {
        if (p->position+1 >= p->length || !p->input[p->position+1]) return 1;
        /*170A0 consumes the store before rejecting a following token. */
        ++p->position;
    }
    return 0;
}

static void calculus(parser *p, fx_complex *out, uint8_t token);

static int function_prefix(uint8_t token)
{
    return token == 0x5d || (token >= 0x69 && token <= 0x6b) || token == 0x63 || token == 0x88 || token == 0xc3 || token == 0x98 || token == 0xa8 || token == 0x68 || (token >= 0x70 && token <= 0x73) ||
           (token >= 0x90 && token <= 0x93) || (token >= 0xa0 && token <= 0xa3) ||
           (token >= 0xb0 && token <= 0xb2);
}

static void literal(parser *p, fx_complex *out)
{
    char text[256];
    size_t used = 0;
    unsigned point = 0, digits = 0;
    uint8_t token;
    while ((token = peek(p)) != 0) {
        if (token >= '0' && token <= '9') ++digits;
        else if (token == '.') {
            if (point++) { p->status = FX_EVAL_SYNTAX; return; }
        } else break;
        if (used + 1 >= sizeof(text)) { p->status = FX_EVAL_RESOURCE_LIMIT; return; }
        text[used++] = (char)token;
        ++p->position;
    }
    /* The calculator accepts a lone decimal point as zero. */
    if (!digits && point && peek(p) != 0x74) { fx_number_zero(&out->real); return; }
    if (!digits) { p->status = FX_EVAL_SYNTAX; return; }
    if (peek(p) == 0x74) {
        unsigned exponent_digits = 0;
        if (used + 1 >= sizeof(text)) { p->status = FX_EVAL_RESOURCE_LIMIT; return; }
        ++p->position;
        text[used++] = 'e';
        if (peek(p) == 0x60 || peek(p) == '-' || peek(p) == '+') {
            if (used + 1 >= sizeof(text)) { p->status = FX_EVAL_RESOURCE_LIMIT; return; }
            text[used++] = peek(p) == '+' ? '+' : '-';
            ++p->position;
        }
        while (peek(p) >= '0' && peek(p) <= '9') {
            if (exponent_digits == 2) { p->status = FX_EVAL_SYNTAX; return; }
            if (used + 1 >= sizeof(text)) { p->status = FX_EVAL_RESOURCE_LIMIT; return; }
            text[used++] = (char)peek(p); ++p->position; ++exponent_digits;
        }
        if (!exponent_digits) { p->status = FX_EVAL_SYNTAX; return; }
    }
    text[used] = 0;
    if (fx_decimal_parse(&out->real, text) != FX_NUMERIC_OK) p->status = FX_EVAL_SYNTAX;
    else if (fx_number_kind(&out->real) == FX_NUMBER_ERROR) p->status = FX_EVAL_MATH;
}

static int variable_slot(uint8_t token, uint8_t context)
{
    fx_evaluator_token decoded = fx_decode_evaluator_token(token, context);
    return decoded.kind == 5 && decoded.value < FX_VARIABLE_COUNT ? decoded.value : -1;
}

static void load_variable(parser *p, fx_complex *out, unsigned slot)
{
    out->real = p->variables->values[slot][0];
    if (p->options.calculation_context == 0xc4)
        out->imaginary = p->variables->values[slot][1];
    fx_number *components[] = {&out->real, &out->imaginary};
    for (unsigned index = 0; index < 2; ++index) {
        unsigned header = components[index]->bytes[0] >> 4;
        fx_number_type kind = fx_number_kind(components[index]);
        /* A direct error-valued load can succeed as an expression; the
         * continuous driver then detects it at its original arithmetic site.
         * This differs from a failed operation that produces the same F3. */
        if ((header == 6 || header == 9 || header == 15) &&
            (p->calculus_token == 0x6a || p->calculus_token == 0x6b)) {
            if (p->scan_only) fx_complex_zero(out);
            continue;
        }
        if ((header != 0 && header != 2 && header != 4 && header != 8) ||
            (kind != FX_NUMBER_DECIMAL && kind != FX_NUMBER_RATIONAL && kind != FX_NUMBER_SURD)) {
            if (p->scan_only) {
                /* The prepared ordinary screen (80FC=1) admits rich/error
                 * body values during17258 preflight. Their real evaluation
                 * fails after the first loop poll, rather than at syntax scan. */
                fx_complex_zero(out);
                return;
            }
            if (p->calculus_mode == 1 && p->calculus_token != 0x6a && p->calculus_token != 0x6b) {
                p->status = FX_EVAL_MATH; return;
            }
            unsupported(p, peek(p)); return;
        }
        /* 51CA invokes173FA when18212 denies natural output. This path
         * converts compact radicals, preserving other scalar headers. */
        if (!p->options.math_output && kind == FX_NUMBER_SURD &&
            fx_number_to_decimal(components[index], components[index]) != FX_NUMERIC_OK) {
            unsupported(p, peek(p)); return;
        }
    }
}

static void primary(parser *p, fx_complex *out)
{
    uint8_t token = peek(p);
    fx_complex_zero(out);
    if (++p->depth > 256) { p->status = FX_EVAL_RESOURCE_LIMIT; --p->depth; return; }
    if ((token >= '0' && token <= '9') || token == '.') literal(p, out);
    else if (token == '(') {
        ++p->position;
        expression(p, out, 0);
        if (p->status == FX_EVAL_OK) {
            if (peek(p) == ')') ++p->position;
            else if (!omitted_closing(p)) p->status = FX_EVAL_SYNTAX;
            /* Original input evaluation allows closing parentheses omitted at end. */
        }
    } else if (variable_slot(token, p->options.calculation_context) >= 0) {
        load_variable(p, out, (unsigned)variable_slot(token, p->options.calculation_context));
        if (p->status == FX_EVAL_OK) ++p->position;
    } else if (token == 0x80) {
        if (p->options.calculation_context == 0xc4) fx_decimal_from_u8(&out->imaginary, 1);
        ++p->position;
    } else if (token == 0x81 || token == 0x82) {
        static const uint8_t e[10] = {0x02,0x71,0x82,0x81,0x82,0x84,0x59,0x04,0x00,0x01};
        static const uint8_t pi[10] = {0x03,0x14,0x15,0x92,0x65,0x35,0x89,0x80,0x00,0x01};
        memcpy(out->real.bytes, token == 0x81 ? e : pi, 10);
        ++p->position;
    } else if (token == 0x5d || (token >= 0x69 && token <= 0x6b)) {
        calculus(p, out, token);
    } else if (function_prefix(token)) {
        fx_complex output = *out, second_argument;
        int closed = 0;
        int has_base = 0;
        ++p->position;
        /* Function tokens include the opening parenthesis implicitly. */
        expression(p, out, 0);
        if (p->status == FX_EVAL_OK && token == 0x68 && peek(p) == ',') {
            ++p->position;
            expression(p, &second_argument, 0);
            has_base = 1;
        }
        if (p->status == FX_EVAL_OK) {
            if (peek(p) == ')') { ++p->position; closed = 1; }
            else if (!omitted_closing(p)) p->status = FX_EVAL_SYNTAX;
        }
        if (p->status == FX_EVAL_OK) {
            if (p->scan_only) { fx_complex_zero(out); }
            else if (p->options.calculation_context == 0xc4) {
                fx_complex_dispatch_context context = complex_context(p);
                uint8_t firmware_status = 0;
                fx_numeric_status status = has_base ?
                    fx_complex_dispatch_binary(&output, out, &second_argument, token, &context, &firmware_status) :
                    fx_complex_dispatch_unary(&output, out, token, &context, &firmware_status);
                accept_complex_operation(p, out, &output, status, firmware_status);
            } else {
                fx_numeric_status status;
                if (token == 0x63) {
                    /* COMP selects scalar1C312, avoiding the CMPLX norm.
                     * Classification precedes clearing the decimal marker. */
                    uint8_t classification;
                    status = fx_scalar_numeric_classify(&classification, &out->real);
                    output = *out;
                    if (status == FX_NUMERIC_OK && classification == 0xf0)
                        fx_number_error(&output.real, 3);
                    else if (status == FX_NUMERIC_OK) {
                        output.real.bytes[0] &= (uint8_t)~0x40;
                        if (classification == 2)
                            status = fx_number_negate(&output.real, &output.real);
                    }
                }
                else if (token == 0x88) status = fx_complex_conjugate(&output, out);
                else if (token == 0xc3 && p->options.angle_unit >= 4 && p->options.angle_unit <= 6)
                    status = fx_complex_argument(&output, out, (fx_angle_unit)(p->options.angle_unit-4));
                else if (token == 0x98) status = fx_number_sqrt(&output.real, &out->real, p->options.math_output);
                else if (token == 0xa8) status = fx_number_cbrt(&output.real, &out->real);
                else if (token == 0x68) status = has_base ? fx_number_log_base(&output.real, &out->real, &second_argument.real) :
                                                         fx_number_log10(&output.real, &out->real);
                else if (token == 0xa3) status = fx_number_ln(&output.real, &out->real);
                else if (token == 0x73) status = fx_number_exp(&output.real, &out->real);
                else if (token == 0x93) status = fx_number_exp10(&output.real, &out->real);
                else if (token >= 0x70 && token <= 0x72)
                    status = fx_hyperbolic_decimal(&output.real, &out->real, (fx_trig_function)(token - 0x70), 0);
                else if (token >= 0x90 && token <= 0x92)
                    status = fx_hyperbolic_decimal(&output.real, &out->real, (fx_trig_function)(token - 0x90), 1);
                else if (p->options.angle_unit >= 4 && p->options.angle_unit <= 6) {
                    if (token >= 0xb0)
                        status = fx_trig_inverse_decimal(&output.real, &out->real, (fx_trig_function)(token - 0xb0),
                                                         (fx_angle_unit)(p->options.angle_unit - 4));
                    else status = fx_trig_evaluate(&output.real, &out->real, (fx_trig_function)(token - 0xa0),
                                             (fx_angle_unit)(p->options.angle_unit - 4),
                                             p->options.math_output, NULL);
                }
                else { unsupported(p, token); --p->depth; return; }
                accept_operation(p, &output.real, status);
                if (p->status == FX_EVAL_OK) *out = output;
            }
            if (p->status == FX_EVAL_MATH && closed) --p->position;
        }
    } else if (token == '-' || token == '+' || token == 0x60) {
        fx_complex output = *out;
        ++p->position;
        expression(p, out, 40); /* powers bind more tightly than unary negation */
        if (p->status == FX_EVAL_OK && token != '+') {
            if (p->scan_only) { fx_complex_zero(out); }
            else if (p->options.calculation_context == 0xc4) {
                fx_complex_dispatch_context context = complex_context(p);
                uint8_t firmware_status = 0;
                fx_numeric_status status = fx_complex_dispatch_unary(&output, out, 0x60, &context, &firmware_status);
                accept_complex_operation(p, out, &output, status, firmware_status);
            } else {
                fx_numeric_status status = fx_number_negate(&output.real, &out->real);
                accept_operation(p, &output.real, status);
                if (p->status == FX_EVAL_OK) *out = output;
            }
        }
    } else if (token == 0 || token == ')' || token == ',') p->status = FX_EVAL_SYNTAX;
    else unsupported(p, token);
    --p->depth;
}

static int implicit_start(uint8_t token, uint8_t context)
{
    return variable_slot(token, context) >= 0 || token == '(' || token == 0x80 || token == 0x81 || token == 0x82 || function_prefix(token);
}

static void fraction(parser *p, fx_complex *out, const fx_complex *denominator)
{
    int64_t n, d;
    if (p->scan_only) { fx_complex_zero(out); return; }
    if (p->options.calculation_context == 0xc4) {
        uint8_t left_class, right_class;
        if (fx_scalar_numeric_classify(&left_class, &out->imaginary) != FX_NUMERIC_OK ||
            fx_scalar_numeric_classify(&right_class, &denominator->imaginary) != FX_NUMERIC_OK) {
            unsupported(p, 0xae); return;
        }
        if (left_class != 1 || right_class != 1) {
            binary(p, out, denominator, FX_DIVIDE); return;
        }
    }
    if (fx_number_fractional_status(&out->real) || fx_number_fractional_status(&denominator->real) ||
        fx_decimal_to_integer(&n, &out->real) != FX_NUMERIC_OK ||
        fx_decimal_to_integer(&d, &denominator->real) != FX_NUMERIC_OK) {
        binary(p, out, denominator, FX_DIVIDE); return;
    }
    if (!d) { p->status = FX_EVAL_MATH; return; }
    if (d < 0) { n = -n; d = -d; }
    fx_rational rational = {n, (uint64_t)d, 0};
    fx_number value;
    fx_numeric_status status = fx_rational_encode(&value, &rational);
    accept_operation(p, &value, status);
    if (p->status == FX_EVAL_OK) out->real = value;
}

static void power_or_root(parser *p, fx_complex *out, const fx_complex *argument, uint8_t token)
{
    fx_complex output = *out;
    if (p->scan_only) { fx_complex_zero(out); return; }
    if (p->options.calculation_context == 0xc4) {
        fx_complex_dispatch_context context = complex_context(p);
        uint8_t firmware_status = 0;
        fx_numeric_status status = fx_complex_dispatch_binary(&output, out, argument, token, &context, &firmware_status);
        accept_complex_operation(p, out, &output, status, firmware_status);
    } else {
        fx_numeric_status status = token == 0x5e ? fx_number_power(&output.real, &out->real, &argument->real) :
                                                 fx_number_nthroot(&output.real, &argument->real, &out->real);
        accept_operation(p, &output.real, status);
        if (p->status == FX_EVAL_OK) *out = output;
    }
}

static void expression(parser *p, fx_complex *out, unsigned minimum)
{
    primary(p, out);
    while (p->status == FX_EVAL_OK) {
        uint8_t token = peek(p);
        unsigned precedence;
        fx_binary_op op;
        fx_complex right;
        int implicit = 0;
        if (token == 0x57 || token == 0x25 || (token >= 0x75 && token <= 0x77) ||
            (token >= 0x85 && token <= 0x87)) {
            if (70 < minimum) return;
            fx_complex output = *out;
            fx_numeric_status status;
            ++p->position;
            if (p->scan_only) { fx_complex_zero(out); continue; }
            if (p->options.calculation_context == 0xc4) {
                fx_complex_dispatch_context context = complex_context(p);
                uint8_t firmware_status = 0;
                status = fx_complex_dispatch_unary(&output, out, token, &context, &firmware_status);
                accept_complex_operation(p, out, &output, status, firmware_status);
            } else {
                if (token == 0x57) status = fx_number_factorial(&output.real, &out->real);
                else if (token == 0x25) status = fx_number_percent(&output.real, &out->real);
                else if (token >= 0x75 && token <= 0x77)
                    status = fx_number_integer_power(&output.real, &out->real, token == 0x75 ? 2 : token == 0x76 ? 3 : -1);
                else if (p->options.angle_unit >= 4 && p->options.angle_unit <= 6)
                    status = fx_angle_convert(&output.real, &out->real, (fx_angle_unit)(token - 0x85),
                                              (fx_angle_unit)(p->options.angle_unit - 4));
                else { unsupported(p, token); return; }
                accept_operation(p, &output.real, status);
                if (p->status == FX_EVAL_OK) *out = output;
            }
            if (p->status == FX_EVAL_MATH) --p->position;
            continue;
        }
        if (token == '+' || token == '-') {
            precedence = 10; op = token == '+' ? FX_ADD : FX_SUBTRACT;
        } else if (token == 0x4e || token == 0x4f) {
            precedence = 20; op = token == 0x4e ? FX_MULTIPLY : FX_DIVIDE;
        } else if (token == 0xbe || token == 0xbf) {
            precedence = 25; op = FX_MULTIPLY;
        } else if (implicit_start(token, p->options.calculation_context)) {
            precedence = 30; op = FX_MULTIPLY; implicit = 1;
        } else if (token == 0xae) {
            precedence = 60; op = FX_DIVIDE;
        } else if (token == 0x5e || token == 0x9f) {
            precedence = 65; op = FX_MULTIPLY;
        } else if (token == 0x97) {
            unsupported(p, token); return;
        } else return;
        if (precedence < minimum) return;
        if (!implicit) ++p->position;
        if (token == 0x5e || token == 0x9f) {
            /* Power and nth-root include an implicit opening parenthesis.
             * The right argument is a full expression. Nth-root takes its
             * degree on the left and radicand on the right. A closing token
             * may be omitted at end of input. */
            int closed = 0;
            expression(p, &right, 0);
            if (p->status == FX_EVAL_OK) {
                if (peek(p) == ')') { ++p->position; closed = 1; }
                else if (!omitted_closing(p)) p->status = FX_EVAL_SYNTAX;
            }
            if (p->status == FX_EVAL_OK) {
                power_or_root(p, out, &right, token);
                if (p->status == FX_EVAL_MATH && closed) --p->position;
            }
            continue;
        }
        expression(p, &right, precedence + 1);
        if (p->status == FX_EVAL_OK && token == 0xae) {
            if (peek(p) == 0xae) {
                fx_complex denominator;
                ++p->position;
                expression(p, &denominator, precedence + 1);
                if (p->status == FX_EVAL_OK) fraction(p, &right, &denominator);
                if (p->status == FX_EVAL_OK) binary(p, out, &right, FX_ADD);
            } else fraction(p, out, &right);
        } else if (p->status == FX_EVAL_OK && (token == 0xbe || token == 0xbf)) {
            if (p->scan_only) { fx_complex_zero(out); continue; }
            fx_complex output = *out;
            if (p->options.calculation_context == 0xc4) {
                fx_complex_dispatch_context context = complex_context(p);
                uint8_t firmware_status = 0;
                fx_numeric_status status = fx_complex_dispatch_binary(&output, out, &right, token, &context, &firmware_status);
                accept_complex_operation(p, out, &output, status, firmware_status);
            } else {
                fx_numeric_status status = token == 0xbe ? fx_number_permutation(&output.real, &out->real, &right.real) :
                                                           fx_number_combination(&output.real, &out->real, &right.real);
                accept_operation(p, &output.real, status);
                if (p->status == FX_EVAL_OK) *out = output;
            }
        } else if (p->status == FX_EVAL_OK) binary(p, out, &right, op);
    }
}

typedef struct {
    parser *parent;
    size_t body_start, body_end, callback_position;
    int64_t next_x;
    fx_eval_status host_failure;
    uint8_t unsupported_token, finite_series, sampled;
} calculus_call;

static int calculus_cancelled(void *userdata)
{
    calculus_call *call = userdata;
    parser *p = call->parent;
    /* Series04330/04426 installs the next X before5550 polls cancellation.
     * Quadrature/Richardson polls retain the most recently sampled X. */
    if (call->finite_series)
        (void)fx_decimal_from_integer(&p->variables->values[FX_VARIABLE_X][0], call->next_x++);
    return p->control && p->control->cancelled && p->control->cancelled(p->control->userdata);
}

static void continuous_finish(parser *p, fx_number *value)
{
    unsigned header = value->bytes[0] >> 4;
    if (header == 15) {
        /*17274 ignores1415A's status, retaining successful evaluation EQ.
         * The leaf rejects a non-matrix/vector rich kind with F3. */
        fx_number_error(value, 3);
    } else if (header == 6 || header == 9) {
        unsigned identity = value->bytes[0] & 15;
        fx_linalg_value input;
        fx_linalg_result result;
        fx_linalg_context context;
        fx_linalg_context_default(&context);
        context.exact_math = p->options.math_output;
        if (fx_linalg_bank_value(&input, p->linear_algebra, value) != FX_NUMERIC_OK ||
            fx_linalg_unary(&result, &input, FX_LINALG_INTEGER_CLEANUP, &context) != FX_NUMERIC_OK ||
            fx_linalg_bank_store_value(p->linear_algebra, identity, &result.value) != FX_NUMERIC_OK) {
            unsupported(p, 0);
            return;
        }
        *value = result.value.reference;
    }
}

static fx_numeric_status calculus_evaluate(fx_number *out, const fx_number *x, void *userdata)
{
    calculus_call *call = userdata;
    parser callback = *call->parent;
    fx_complex value;
    callback.position = call->body_start;
    callback.length = call->body_end;
    callback.status = FX_EVAL_OK;
    callback.unsupported = 0;
    callback.calculus_mode = 1;
    callback.scan_only = 0;
    callback.variables->values[FX_VARIABLE_X][0] = *x;
    expression(&callback, &value, 0);
    call->callback_position = callback.position;
    call->sampled = 1;
    if (callback.status == FX_EVAL_OK && peek(&callback)) callback.status = FX_EVAL_SYNTAX;
    if (callback.status == FX_EVAL_OK &&
        (callback.calculus_token == 0x6a || callback.calculus_token == 0x6b))
        continuous_finish(&callback, &value.real);
    if (callback.status < 0) {
        call->host_failure = callback.status;
        call->unsupported_token = callback.unsupported;
        return FX_NUMERIC_UNIMPLEMENTED;
    }
    if (callback.status) fx_number_error(out, (unsigned)callback.status);
    else *out = value.real;
    if (callback.calculus_token == 0x6a || callback.calculus_token == 0x6b)
        return (fx_numeric_status)(callback.status ? FX_CALCULUS_EVALUATION_ERROR : FX_CALCULUS_EVALUATION_OK);
    return FX_NUMERIC_OK;
}

static void calculus(parser *p, fx_complex *out, uint8_t token)
{
    fx_complex saved_x, lower, upper, tolerance, ignored;
    fx_number result, decimal_lower;
    uint8_t exact = p->options.math_output;
    calculus_call call = {.parent = p, .finite_series = token == 0x69 || token == 0x5d};
    fx_calculus_control control = {calculus_cancelled, &call};
    int has_tolerance = 0;
    if (p->calculus_mode) { p->status = FX_EVAL_SYNTAX; return; }
    if (p->options.calculation_context != 0xc1) { unsupported(p, token); return; }
    fx_complex_zero(&saved_x);
    load_variable(p, &saved_x, FX_VARIABLE_X);
    if (p->status != FX_EVAL_OK) return;
    ++p->position;
    p->calculus_token = token;
    call.body_start = p->position;
    p->calculus_mode = 255;
    p->scan_only = 1;
    p->options.math_output = 0;
    /* Native171EA first validates syntax/type without running arithmetic. */
    expression(p, &ignored, 0);
    if (p->status != FX_EVAL_OK) goto restore;
    if (peek(p) != ',') { p->status = FX_EVAL_SYNTAX; goto restore; }
    call.body_end = p->position++;
    p->calculus_mode = 2;
    p->scan_only = 0;
    expression(p, &lower, 0);
    if (p->status != FX_EVAL_OK) goto restore;
    if (token != 0x6b) {
        if (peek(p) != ',') { p->status = FX_EVAL_SYNTAX; goto restore; }
        ++p->position;
        expression(p, &upper, 0);
        if (p->status != FX_EVAL_OK) goto restore;
    }
    if ((token == 0x6a || token == 0x6b) && peek(p) == ',') {
        ++p->position;
        expression(p, &tolerance, 0);
        if (p->status != FX_EVAL_OK) goto restore;
        has_tolerance = 1;
    }
    if (fx_number_to_decimal(&decimal_lower, &lower.real) == FX_NUMERIC_OK)
        (void)fx_decimal_to_integer(&call.next_x, &decimal_lower);
    p->calculus_mode = 1;
    fx_numeric_status status;
    if (token == 0x69)
        status = fx_number_sum(&result, &lower.real, &upper.real, calculus_evaluate, &call, &control);
    else if (token == 0x5d)
        status = fx_number_product(&result, &lower.real, &upper.real, calculus_evaluate, &call, &control);
    else if (token == 0x6a)
        status = fx_number_integral(&result, &lower.real, &upper.real,
                                    has_tolerance ? &tolerance.real : NULL,
                                    calculus_evaluate, &call, &control);
    else
        status = fx_number_derivative(&result, &lower.real,
                                      has_tolerance ? &tolerance.real : NULL,
                                      calculus_evaluate, &call, &control);
    if (status != FX_NUMERIC_OK) {
        if (call.host_failure) {
            p->status = call.host_failure;
            p->unsupported = call.unsupported_token;
        } else unsupported(p, token);
        goto restore;
    }
    fx_complex_zero(out);
    out->real = result;
    if (fx_number_kind(&result) == FX_NUMBER_ERROR) {
        p->status = (fx_eval_status)(result.bytes[0] & 15);
        /* Integral4A4C preserves the last body evaluation cursor for F3/FB;
         * cancellation4A52 restores the saved post-argument position.
         * Derivative4DBC restores it for every driver outcome. */
        if (token == 0x6a && p->status != FX_EVAL_CANCELLED && call.sampled)
            p->position = call.callback_position;
        if (p->status == FX_EVAL_CANCELLED && peek(p) == ')') ++p->position;
        goto restore;
    }
    /* Extra arguments are rejected after the native callbacks have run. */
    p->calculus_mode = 0;
    if (peek(p) == ')') ++p->position;
    else if (!omitted_closing(p)) p->status = FX_EVAL_SYNTAX;
restore:
    p->variables->values[FX_VARIABLE_X][0] = saved_x.real;
    p->options.math_output = exact;
    p->calculus_mode = 0;
    p->calculus_token = 0;
    p->scan_only = 0;
}

fx_eval_options fx_eval_default_options(void)
{
    fx_eval_options options = {0xc1, 1, 4};
    return options;
}

void fx_eval_variables_clear(fx_eval_variables *variables)
{
    if (variables) memset(variables, 0, sizeof *variables);
}

static void store_result(parser *p, fx_complex *value)
{
    uint8_t token = peek(p);
    fx_evaluator_token decoded = fx_decode_evaluator_token(token, p->options.calculation_context);
    if (decoded.kind != 8 || decoded.value > 11) return;
    size_t position = p->position++;
    /*170A0 requires the store token to be followed by the input terminator.
     * No variable write occurs until syntax and scalar admission succeed. */
    if (peek(p)) { p->status = FX_EVAL_SYNTAX; return; }
    if (fx_number_kind(&value->real) == FX_NUMBER_ERROR ||
        fx_number_kind(&value->real) == FX_NUMBER_UNSUPPORTED) {
        p->position = position; p->status = FX_EVAL_SYNTAX; return;
    }
    unsigned slot = decoded.value;
    fx_complex stored = *value;
    if (slot >= FX_VARIABLE_COUNT) {
        fx_complex original = stored;
        fx_complex_zero(&stored);
        load_variable(p, &stored, FX_VARIABLE_M);
        if (p->status != FX_EVAL_OK) { p->position = position; return; }
        binary(p, &stored, &original, slot == 10 ? FX_ADD : FX_SUBTRACT);
        if (p->status != FX_EVAL_OK) { p->position = position; return; }
        slot = FX_VARIABLE_M;
    }
    p->variables->values[slot][0] = stored.real;
    if (p->options.calculation_context == 0xc4)
        p->variables->values[slot][1] = stored.imaginary;
}

fx_eval_status fx_evaluate_with_state(const uint8_t *input, size_t length,
                           const fx_eval_options *options, const fx_eval_state *state,
                           const fx_calculus_control *control, fx_eval_result *result)
{
    parser p;
    fx_complex value;
    fx_eval_variables local_variables;
    fx_linalg_bank local_linear_algebra = {0};
    fx_eval_variables *variables = state ? state->variables : NULL;
    fx_complex_zero(&value);
    if (!result) return FX_EVAL_SYNTAX;
    memset(result, 0, sizeof *result);
    if (!input || !length) { fx_number_error(&result->value[0], 2); return FX_EVAL_SYNTAX; }
    memset(&p, 0, sizeof p);
    p.input = input; p.length = length;
    if (!variables) { fx_eval_variables_clear(&local_variables); variables = &local_variables; }
    p.variables = variables;
    p.linear_algebra = state && state->linear_algebra ? state->linear_algebra : &local_linear_algebra;
    p.control = control;
    p.options = options ? *options : fx_eval_default_options();
    if (p.options.calculation_context != 0xc1 && p.options.calculation_context != 0xc4)
        p.status = FX_EVAL_UNIMPLEMENTED;
    else expression(&p, &value, 0);
    if (p.status == FX_EVAL_OK) store_result(&p, &value);
    result->value[0] = value.real;
    result->value[1] = value.imaginary;
    if (p.status == FX_EVAL_OK && peek(&p) != 0) {
        fx_evaluator_token token = fx_decode_evaluator_token(peek(&p), p.options.calculation_context);
        if (token.kind == 10 || peek(&p) == ')' || peek(&p) == ',' || peek(&p) == '.' ||
            (peek(&p) >= '0' && peek(&p) <= '9')) p.status = FX_EVAL_SYNTAX;
        else unsupported(&p, peek(&p));
    }
    result->consumed = p.position;
    if (p.status == FX_EVAL_OK && p.position < p.length) ++result->consumed;
    if (p.status > FX_EVAL_OK && p.status <= 15) {
        fx_number_error(&result->value[0], (unsigned)p.status);
        fx_number_zero(&result->value[1]);
    }
    result->unsupported_token = p.unsupported;
    return p.status;
}

fx_eval_status fx_evaluate_controlled(const uint8_t *input, size_t length,
                           const fx_eval_options *options, fx_eval_variables *variables,
                           const fx_calculus_control *control, fx_eval_result *result)
{
    fx_eval_state state = {variables, NULL};
    return fx_evaluate_with_state(input, length, options, &state, control, result);
}

fx_eval_status fx_evaluate_with_variables(const uint8_t *input, size_t length,
                           const fx_eval_options *options, fx_eval_variables *variables,
                           fx_eval_result *result)
{
    return fx_evaluate_controlled(input, length, options, variables, NULL, result);
}

fx_eval_status fx_evaluate(const uint8_t *input, size_t length,
                           const fx_eval_options *options, fx_eval_result *result)
{
    return fx_evaluate_with_variables(input, length, options, NULL, result);
}
