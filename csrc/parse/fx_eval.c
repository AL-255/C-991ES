/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_eval.h"
#include "fx_tokens.h"
#include "../trig/fx_trig_math.h"
#include "../trig/fx_trig_inverse.h"
#include "../trig/fx_trig_hyperbolic.h"
#include "../numeric/fx_transcend.h"
#include <string.h>

typedef struct {
    const uint8_t *input;
    size_t length, position;
    unsigned depth;
    fx_eval_options options;
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

static void binary(parser *p, fx_number *left, const fx_number *right, fx_binary_op op)
{
    fx_number output;
    fx_numeric_status status = fx_number_binary(&output, left, right, op);
    accept_operation(p, &output, status);
    if (p->status == FX_EVAL_OK) *left = output;
}

static void expression(parser *p, fx_number *out, unsigned minimum);

static int function_prefix(uint8_t token)
{
    return token == 0x98 || token == 0x68 || (token >= 0x70 && token <= 0x73) ||
           (token >= 0x90 && token <= 0x93) || (token >= 0xa0 && token <= 0xa3) ||
           (token >= 0xb0 && token <= 0xb2);
}

static void literal(parser *p, fx_number *out)
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
    if (!digits && point && peek(p) != 0x74) { fx_number_zero(out); return; }
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
    if (fx_decimal_parse(out, text) != FX_NUMERIC_OK) p->status = FX_EVAL_SYNTAX;
    else if (fx_number_kind(out) == FX_NUMBER_ERROR) p->status = FX_EVAL_MATH;
}

static void primary(parser *p, fx_number *out)
{
    uint8_t token = peek(p);
    if (++p->depth > 256) { p->status = FX_EVAL_RESOURCE_LIMIT; --p->depth; return; }
    if ((token >= '0' && token <= '9') || token == '.') literal(p, out);
    else if (token == '(') {
        ++p->position;
        expression(p, out, 0);
        if (p->status == FX_EVAL_OK) {
            if (peek(p) == ')') ++p->position;
            else if (peek(p) != 0) p->status = FX_EVAL_SYNTAX;
            /* Original input evaluation allows closing parentheses omitted at end. */
        }
    } else if (token == 0x81 || token == 0x82) {
        static const uint8_t e[10] = {0x02,0x71,0x82,0x81,0x82,0x84,0x59,0x04,0x00,0x01};
        static const uint8_t pi[10] = {0x03,0x14,0x15,0x92,0x65,0x35,0x89,0x80,0x00,0x01};
        memcpy(out->bytes, token == 0x81 ? e : pi, 10);
        ++p->position;
    } else if (function_prefix(token)) {
        fx_number output;
        int closed = 0;
        ++p->position;
        /* Function tokens include the opening parenthesis implicitly. */
        expression(p, out, 0);
        if (p->status == FX_EVAL_OK) {
            if (peek(p) == ')') { ++p->position; closed = 1; }
            else if (token == 0x68 && peek(p) == ',') unsupported(p, ',');
            else if (peek(p) != 0) p->status = FX_EVAL_SYNTAX;
        }
        if (p->status == FX_EVAL_OK) {
            fx_numeric_status status;
            if (token == 0x98) status = fx_number_sqrt(&output, out, p->options.math_output);
            else if (token == 0x68) status = fx_number_log10(&output, out);
            else if (token == 0xa3) status = fx_number_ln(&output, out);
            else if (token == 0x73) status = fx_number_exp(&output, out);
            else if (token == 0x93) status = fx_number_exp10(&output, out);
            else if (token >= 0x70 && token <= 0x72)
                status = fx_hyperbolic_decimal(&output, out, (fx_trig_function)(token - 0x70), 0);
            else if (token >= 0x90 && token <= 0x92)
                status = fx_hyperbolic_decimal(&output, out, (fx_trig_function)(token - 0x90), 1);
            else if (p->options.angle_unit >= 4 && p->options.angle_unit <= 6) {
                if (token >= 0xb0)
                    status = fx_trig_inverse_decimal(&output, out, (fx_trig_function)(token - 0xb0),
                                                     (fx_angle_unit)(p->options.angle_unit - 4));
                else status = fx_trig_evaluate(&output, out, (fx_trig_function)(token - 0xa0),
                                         (fx_angle_unit)(p->options.angle_unit - 4),
                                         p->options.math_output, NULL);
            }
            else { unsupported(p, token); --p->depth; return; }
            accept_operation(p, &output, status);
            if (p->status == FX_EVAL_OK) *out = output;
            else if (p->status == FX_EVAL_MATH && closed) --p->position;
        }
    } else if (token == '-' || token == '+' || token == 0x60) {
        fx_number output;
        ++p->position;
        expression(p, out, 40); /* powers bind more tightly than unary negation */
        if (p->status == FX_EVAL_OK && token != '+') {
            fx_numeric_status status = fx_number_negate(&output, out);
            accept_operation(p, &output, status);
            if (p->status == FX_EVAL_OK) *out = output;
        }
    } else if (token == 0 || token == ')') p->status = FX_EVAL_SYNTAX;
    else unsupported(p, token);
    --p->depth;
}

static int implicit_start(uint8_t token)
{
    return token == '(' || token == 0x81 || token == 0x82 || function_prefix(token);
}

static void fraction(parser *p, fx_number *out, const fx_number *denominator)
{
    int64_t n, d;
    if (fx_number_fractional_status(out) || fx_number_fractional_status(denominator) ||
        fx_decimal_to_integer(&n, out) != FX_NUMERIC_OK ||
        fx_decimal_to_integer(&d, denominator) != FX_NUMERIC_OK) {
        binary(p, out, denominator, FX_DIVIDE); return;
    }
    if (!d) { p->status = FX_EVAL_MATH; return; }
    if (d < 0) { n = -n; d = -d; }
    fx_rational rational = {n, (uint64_t)d, 0};
    fx_number value;
    fx_numeric_status status = fx_rational_encode(&value, &rational);
    accept_operation(p, &value, status);
    if (p->status == FX_EVAL_OK) *out = value;
}

static void real_power(parser *p, fx_number *out, const fx_number *exponent)
{
    fx_number output;
    fx_numeric_status status = fx_number_power(&output, out, exponent);
    accept_operation(p, &output, status);
    if (p->status == FX_EVAL_OK) *out = output;
}

static void expression(parser *p, fx_number *out, unsigned minimum)
{
    primary(p, out);
    while (p->status == FX_EVAL_OK) {
        uint8_t token = peek(p);
        unsigned precedence;
        fx_binary_op op;
        fx_number right;
        int implicit = 0;
        if ((token >= 0x75 && token <= 0x77) || (token >= 0x85 && token <= 0x87)) {
            if (70 < minimum) return;
            fx_number output;
            fx_numeric_status status;
            ++p->position;
            if (token <= 0x77)
                status = fx_number_integer_power(&output, out, token == 0x75 ? 2 : token == 0x76 ? 3 : -1);
            else if (p->options.angle_unit >= 4 && p->options.angle_unit <= 6)
                status = fx_angle_convert(&output, out, (fx_angle_unit)(token - 0x85),
                                          (fx_angle_unit)(p->options.angle_unit - 4));
            else { unsupported(p, token); return; }
            accept_operation(p, &output, status);
            if (p->status == FX_EVAL_OK) *out = output;
            else if (p->status == FX_EVAL_MATH) --p->position;
            continue;
        }
        if (token == '+' || token == '-') {
            precedence = 10; op = token == '+' ? FX_ADD : FX_SUBTRACT;
        } else if (token == 0x4e || token == 0x4f) {
            precedence = 20; op = token == 0x4e ? FX_MULTIPLY : FX_DIVIDE;
        } else if (implicit_start(token)) {
            precedence = 30; op = FX_MULTIPLY; implicit = 1;
        } else if (token == 0xae) {
            precedence = 60; op = FX_DIVIDE;
        } else if (token == 0x5e) {
            precedence = 65; op = FX_MULTIPLY;
        } else if (token == 0x25 || token == 0x97) {
            unsupported(p, token); return;
        } else return;
        if (precedence < minimum) return;
        if (!implicit) ++p->position;
        if (token == 0x5e) {
            /* The input power token includes an implicit opening parenthesis.
             * Its exponent is a full argument expression, as for a function;
             * the closing parenthesis may be omitted at end of input. */
            int closed = 0;
            expression(p, &right, 0);
            if (p->status == FX_EVAL_OK) {
                if (peek(p) == ')') { ++p->position; closed = 1; }
                else if (peek(p) != 0) p->status = FX_EVAL_SYNTAX;
            }
            if (p->status == FX_EVAL_OK) {
                real_power(p, out, &right);
                if (p->status == FX_EVAL_MATH && closed) --p->position;
            }
            continue;
        }
        expression(p, &right, precedence + 1);
        if (p->status == FX_EVAL_OK && token == 0xae) {
            if (peek(p) == 0xae) {
                fx_number denominator;
                ++p->position;
                expression(p, &denominator, precedence + 1);
                if (p->status == FX_EVAL_OK) fraction(p, &right, &denominator);
                if (p->status == FX_EVAL_OK) binary(p, out, &right, FX_ADD);
            } else fraction(p, out, &right);
        } else if (p->status == FX_EVAL_OK) binary(p, out, &right, op);
    }
}

fx_eval_options fx_eval_default_options(void)
{
    fx_eval_options options = {0xc1, 1, 4};
    return options;
}

fx_eval_status fx_evaluate(const uint8_t *input, size_t length,
                           const fx_eval_options *options, fx_eval_result *result)
{
    parser p;
    if (!result) return FX_EVAL_SYNTAX;
    memset(result, 0, sizeof *result);
    if (!input || !length) { fx_number_error(&result->value[0], 2); return FX_EVAL_SYNTAX; }
    memset(&p, 0, sizeof p);
    p.input = input; p.length = length;
    p.options = options ? *options : fx_eval_default_options();
    if (p.options.calculation_context != 0xc1) p.status = FX_EVAL_UNIMPLEMENTED;
    else expression(&p, &result->value[0], 0);
    if (p.status == FX_EVAL_OK && peek(&p) != 0) {
        fx_evaluator_token token = fx_decode_evaluator_token(peek(&p), p.options.calculation_context);
        if (token.kind == 10 || peek(&p) == ')') p.status = FX_EVAL_SYNTAX;
        else unsupported(&p, peek(&p));
    }
    result->consumed = p.position;
    if (p.status == FX_EVAL_OK && p.position < p.length) ++result->consumed;
    if (p.status == FX_EVAL_SYNTAX || p.status == FX_EVAL_MATH)
        fx_number_error(&result->value[0], (unsigned)p.status);
    result->unsupported_token = p.unsupported;
    return p.status;
}
