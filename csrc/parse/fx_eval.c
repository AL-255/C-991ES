/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_eval.h"
#include "fx_tokens.h"
#include "fx_eval_finish.h"
#include "../trig/fx_trig_math.h"
#include "../trig/fx_trig_inverse.h"
#include "../trig/fx_trig_hyperbolic.h"
#include "../numeric/fx_transcend.h"
#include "../numeric/fx_root.h"
#include "../numeric/fx_combinatorics.h"
#include "../numeric/fx_logbase.h"
#include "../numeric/fx_integral.h"
#include "../numeric/fx_derivative.h"
#include "../numeric/fx_sexagesimal.h"
#include "../numeric/fx_quotient_remainder.h"
#include "../complex/fx_complex_dispatch.h"
#include "../complex/fx_complex_angle.h"
#include "../complex/fx_complex_round.h"
#include <string.h>

typedef struct {
    const uint8_t *input;
    size_t length, position;
    unsigned depth;
    unsigned operator_depth, value_depth, group_depth;
    uint8_t equation_used;
    size_t equation_position;
    fx_eval_options options;
    fx_eval_environment environment;
    fx_eval_variables *variables;
    fx_linalg_bank *linear_algebra;
    fx_eval_storage *storage;
    const fx_calculus_control *control;
    uint8_t base_radix;
    uint8_t calculus_mode, calculus_token, scan_only;
    uint8_t terminal_operator;
    fx_number secondary, prior_answer;
    fx_eval_status status;
    uint8_t unsupported;
} parser;

static void variables_from_storage(parser *p)
{
    if (!p->storage) return;
    for (unsigned slot = 0; slot < FX_VARIABLE_COUNT; ++slot) {
        memcpy(p->variables->values[slot][0].bytes,
               p->storage->ram + 0x8226 + 10 * slot, 10);
        memcpy(p->variables->values[slot][1].bytes,
               p->storage->ram + 0x8408 + 10 * slot, 10);
    }
}

static void variables_to_storage(parser *p)
{
    if (!p->storage) return;
    for (unsigned slot = 0; slot < FX_VARIABLE_COUNT; ++slot) {
        memcpy(p->storage->ram + 0x8226 + 10 * slot,
               p->variables->values[slot][0].bytes, 10);
        memcpy(p->storage->ram + 0x8408 + 10 * slot,
               p->variables->values[slot][1].bytes, 10);
    }
}

static void bank_from_storage(parser *p)
{
    if (!p->storage) return;
    for (unsigned slot = 0; slot < 9; ++slot) {
        p->linear_algebra->slots[slot].rows = p->storage->ram[0x80e0 + 2 * slot];
        p->linear_algebra->slots[slot].columns = p->storage->ram[0x80e1 + 2 * slot];
        memcpy(p->linear_algebra->slots[slot].cells,
               p->storage->ram + 0x829e + 90 * slot, 90);
    }
    p->linear_algebra->temporary_mask = p->storage->ram[0x8125];
}

static uint8_t exact_math(const parser *p)
{
    /*18212: global Math and natural-result permission are distinct. SOLVE
     * screenC0, ED operations and polar complex output deny exact results. */
    return p->environment.prior_operation != 0xed &&
           !(p->environment.screen & 0x40) && p->options.math_output != 0 &&
           p->environment.complex_format != 1 &&
           (p->options.calculation_context & 0x40) != 0 &&
           !(p->environment.restricted_state & 1);
}

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
    /*1CEF0 can itself overflow when near-integer cleanup carries a finite
     * exponent99 record to10^100. The native dispatcher forwards that3. */
    if (fx_number_kind(value) == FX_NUMBER_ERROR) p->status = FX_EVAL_MATH;
}

static fx_complex_dispatch_context complex_context(const parser *p)
{
    fx_complex_dispatch_context context = fx_complex_dispatch_default_context();
    context.calculation_context = p->options.calculation_context;
    context.exact_math = exact_math(p);
    context.angle_unit = p->options.angle_unit;
    context.display_mode = p->environment.display_mode;
    context.digits = p->environment.digits;
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

static int real_only_admitted(const parser *p, const fx_complex *value)
{
    unsigned header = value->real.bytes[0] & 0xf0;
    if (header == 0xf0 || header == 0x60 || header == 0x90) return 0;
    if (p->options.calculation_context == 0xc4 &&
        (header == 0 || header == 0x20 || header == 0x80))
        return !value->imaginary.bytes[8] && !value->imaginary.bytes[9];
    return 1;
}

/*16A14 applies the raw header mask before any scalar marker cleanup or
 * rich allocation. Mask3 admits scalar complex values, while mask7 also
 * requires their stored imaginary exponent to be zero in CMPLX. */
static int operand_admitted(const parser *p, const fx_complex *value,
                            unsigned mask)
{
    unsigned kind = value->real.bytes[0] >> 4;
    if (kind == 15) return 0;
    if (mask == 255) return 1;
    if (!mask) return kind >= 6 && kind != 8;
    if ((mask & 1) && kind == 9) return 0;
    if ((mask & 2) && kind == 6) return 0;
    if ((mask & 4) && p->options.calculation_context == 0xc4 &&
        (kind == 0 || kind == 2 || kind == 8))
        return !value->imaginary.bytes[8] && !value->imaginary.bytes[9];
    return 1;
}

static int scalar_header_admitted(const fx_complex *value)
{
    unsigned kind = value->real.bytes[0] >> 4;
    return kind != 6 && kind != 9 && kind != 15;
}

static int rich_reference(const fx_complex *value)
{
    unsigned kind = value->real.bytes[0] >> 4;
    return kind == 6 || kind == 7 || (kind >= 9 && kind < 15);
}

/*16336 restores the left operand before163F0. Its remaining numerical stack
 * counts ten-byte records, after popping that saved left operand. Temporary
 * payload copies and right-reference releases precede the numerical leaf. */
static int stage_binary(parser *p, fx_complex *left, const fx_complex *right,
                        uint8_t native_operation)
{
    if (!p->storage) {
        /* The typed equation admission below already handles rejected
         * headers. Ordinary rich arithmetic needs its separate bank route;
         * a6x reference must never become a marked scalar rational here. */
        if (!(p->environment.screen & 0x40) &&
            (rich_reference(left) || rich_reference(right))) {
            unsupported(p, native_operation); return 1;
        }
        return 0;
    }
    unsigned width = p->options.calculation_context == 0xc4 ? 2u : 1u;
    unsigned remaining = p->value_depth >= width ? p->value_depth - width : 0;
    fx_complex other = *right;
    fx_eval_storage_result staged;
    uint8_t mask = p->storage->ram[0x8125];
    variables_to_storage(p);
    fx_numeric_status host_status = fx_eval_storage_stage(p->storage,
        (fx_number *)left, (fx_number *)&other, native_operation, 0xff,
        (uint8_t)remaining, &mask, &staged);
    variables_from_storage(p);
    bank_from_storage(p);
    /* Wrapped release identities can clear8125.bit0. It is a shared mask,
     * not an equation flag that can be reasserted after every operation. */
    p->equation_used = p->storage->ram[0x8125] & 1;
    if (host_status != FX_NUMERIC_OK) {
        unsupported(p, native_operation);
        return 1;
    }
    if (staged.native_status) {
        p->status = (fx_eval_status)staged.native_status;
        return 1;
    }
    if (staged.route == FX_EVAL_STORAGE_RICH) {
        if ((left->real.bytes[0] >> 4) == 15) p->status = FX_EVAL_MATH;
        else unsupported(p, native_operation);
        return 1;
    }
    return 0;
}

static int stage_unary(parser *p, fx_complex *current, uint8_t operation)
{
    if (!p->storage) {
        if (rich_reference(current)) { unsupported(p, operation); return 1; }
        return 0;
    }
    uint8_t header = current->real.bytes[0];
    /* Scalar count1 dispatch exits163F0 without touching RAM or the data
     * stack. A legal CMPLX scalar may already have all ten saved records. */
    if (header < 0x90 && (header < 0x60 || header >= 0x80)) return 0;
    fx_complex other;
    fx_complex_zero(&other);
    fx_eval_storage_result staged;
    uint8_t mask = p->storage->ram[0x8125];
    variables_to_storage(p);
    fx_numeric_status status = fx_eval_storage_stage(p->storage,
        (fx_number *)current, (fx_number *)&other, operation, 1,
        (uint8_t)p->value_depth, &mask, &staged);
    variables_from_storage(p);
    bank_from_storage(p);
    p->equation_used = p->storage->ram[0x8125] & 1;
    if (status != FX_NUMERIC_OK) {
        unsupported(p, operation); return 1;
    }
    if (staged.native_status) {
        p->status = (fx_eval_status)staged.native_status; return 1;
    }
    if (staged.route == FX_EVAL_STORAGE_RICH) {
        if ((current->real.bytes[0] >> 4) == 15) p->status = FX_EVAL_MATH;
        else unsupported(p, operation);
        return 1;
    }
    return 0;
}

static void accept_real_result(parser *p, fx_complex *destination,
                                const fx_complex *output, fx_numeric_status status)
{
    if (p->options.calculation_context == 0xc4 && status == FX_NUMERIC_OK &&
        fx_number_kind(&output->real) != FX_NUMBER_ERROR) {
        fx_complex cleaned;
        uint8_t native_status = 0;
        fx_complex_dispatch_context context = complex_context(p);
        status = fx_complex_dispatch_cleanup(&cleaned, output, 0, &context, &native_status);
        accept_complex_operation(p, destination, &cleaned, status, native_status);
    } else {
        fx_complex cleaned = *output;
        accept_operation(p, &cleaned.real, status);
        if (p->status == FX_EVAL_OK) *destination = cleaned;
    }
}

static void binary(parser *p, fx_complex *left, const fx_complex *right, fx_binary_op op)
{
    fx_complex output = *left;
    if (p->scan_only) { fx_complex_zero(left); return; }
    if (stage_binary(p, left, right, (uint8_t)(43 + op))) return;
    if ((p->environment.screen & 0x40) &&
        (!scalar_header_admitted(right) || !scalar_header_admitted(left))) {
        p->status = FX_EVAL_MATH;
        return;
    }
    if (p->options.calculation_context == 0xc4) {
        static const uint8_t tokens[] = {'+', '-', 0x4e, 0x4f};
        fx_complex_dispatch_context context = complex_context(p);
        uint8_t firmware_status = 0;
        fx_numeric_status status = fx_complex_dispatch_binary(&output, left, right,
                                                               tokens[op], &context, &firmware_status);
        accept_complex_operation(p, left, &output, status, firmware_status);
    } else if (p->options.calculation_context == 2) {
        unsigned native_status = 0;
        fx_numeric_status status = fx_base_binary(&output.real, &left->real, &right->real,
                                                  p->base_radix, (fx_base_binary_op)op,
                                                  &native_status);
        if (status == FX_NUMERIC_OK && native_status) p->status = (fx_eval_status)native_status;
        else accept_operation(p, &output.real, status);
        if (p->status == FX_EVAL_OK) *left = output;
    } else {
        fx_numeric_status status = fx_number_binary(&output.real, &left->real, &right->real, op);
        accept_operation(p, &output.real, status);
        if (p->status == FX_EVAL_OK) *left = output;
    }
}

static void expression(parser *p, fx_complex *out, unsigned minimum);

/*166FC retains the first operator slot after its active stack is popped.
 * Group/function arguments and binary right operands have an outer operator;
 * only a new operation at depth zero replaces the terminal selector. */
static void note_operator(parser *p, uint8_t operation)
{
    if (!p->operator_depth) p->terminal_operator = operation;
}

static int store_token(const parser *p)
{
    fx_evaluator_token decoded = fx_decode_evaluator_token(peek(p), p->options.calculation_context);
    return decoded.kind == 8 && decoded.value <= 11;
}

static int omitted_closing(parser *p)
{
    if (!peek(p) || peek(p) == ':' ||
        ((p->environment.screen & 0x40) && peek(p) == '=') ||
        ((p->calculus_mode || (p->environment.screen & 0x40)) && peek(p) == ',')) return 1;
    if (store_token(p)) {
        if (p->position+1 >= p->length || !p->input[p->position+1] ||
            p->input[p->position+1] == ':') return 1;
        /*170A0 consumes the store before rejecting a following token. */
        ++p->position;
    }
    return 0;
}

static void calculus(parser *p, fx_complex *out, uint8_t token);
static void coordinates(parser *p, fx_complex *out, uint8_t token);

static int function_prefix(uint8_t token)
{
    return token == 0x3f || token == 0x61 || token == 0x62 || token == 0x5d || (token >= 0x69 && token <= 0x6d) || token == 0x63 || token == 0x88 || token == 0xc3 || token == 0x98 || token == 0xa8 || token == 0x68 || (token >= 0x70 && token <= 0x73) ||
           (token >= 0x90 && token <= 0x93) || (token >= 0xa0 && token <= 0xa3) ||
           (token >= 0xb0 && token <= 0xb3) || token == 0xc0 || token == 0xc1;
}

static void base_literal(parser *p, fx_complex *out, uint8_t input_base)
{
    fx_base_literal_result result;
    fx_numeric_status status;
    size_t start = p->position;
    status = fx_base_parse_literal(&out->real, p->input + start, p->length - start,
                                   input_base, p->base_radix, &result);
    if (status == FX_NUMERIC_INVALID) {
        /* The value API also accepts a bounded input with a virtual NUL.
         * A missing delimiter can occur only after admitted digits; discard
         * leading zeroes to append that NUL in a fixed bounded scratch array. */
        uint8_t scratch[18];
        size_t significant = start;
        while (significant < p->length && p->input[significant] == '0') ++significant;
        size_t count = p->length - significant;
        if (count >= sizeof scratch) { p->status = FX_EVAL_RESOURCE_LIMIT; return; }
        memcpy(scratch, p->input + significant, count);
        if (!count && significant > start) scratch[count++] = '0';
        scratch[count] = 0;
        status = fx_base_parse_literal(&out->real, scratch, count + 1,
                                       input_base, p->base_radix, &result);
        if (status == FX_NUMERIC_OK) {
            p->position = p->length;
            p->status = (fx_eval_status)result.native_status;
            return;
        }
    }
    if (status != FX_NUMERIC_OK) { unsupported(p, peek(p)); return; }
    /* Handler16DCA/16BFC reports the scanner's rejected token, not its
     * post-read cursor. Successful literals retain the delimiter position. */
    p->position += result.consumed - (result.native_status && result.consumed ? 1 : 0);
    p->status = (fx_eval_status)result.native_status;
}

static void literal(parser *p, fx_complex *out)
{
    char text[256];
    size_t used = 0;
    unsigned point = 0, digits = 0;
    uint8_t token;
    if (p->options.calculation_context == 2) {
        base_literal(p, out, p->base_radix);
        return;
    }
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
    return decoded.kind == 5 && decoded.value <= FX_VARIABLE_COUNT ? decoded.value : -1;
}

static void load_variable(parser *p, fx_complex *out, unsigned slot)
{
    out->real = slot == FX_VARIABLE_COUNT ? p->prior_answer : p->variables->values[slot][0];
    if (p->options.calculation_context == 2) {
        unsigned native_status = 0;
        fx_number_zero(&out->imaginary);
        fx_numeric_status status = fx_base_prepare_scalar(&out->real, &out->real,
                                                          p->base_radix, &native_status);
        if (status != FX_NUMERIC_OK) unsupported(p, peek(p));
        else p->status = (fx_eval_status)native_status;
        return;
    }
    if (p->options.calculation_context == 0xc4)
        out->imaginary = p->variables->values[slot][1];
    fx_number *components[] = {&out->real, &out->imaginary};
    for (unsigned index = 0; index < 2; ++index) {
        unsigned header = components[index]->bytes[0] >> 4;
        fx_number_type kind = fx_number_kind(components[index]);
        /*51CA copies an error-valued scalar without turning the load into
         * an evaluator failure. Its later arithmetic or17258 finish gate
         * decides whether this is Math3, Syntax2 or a successful F3 value. */
        if (header == 15) continue;
        if (header == 6 || header == 9) {
            /* Direct loads retain the rich reference for the later operation
             * or17258 finish guard. Finite-series callbacks separately reject
             * a rich body after their first poll, rather than reading its
             * payload as a marked scalar fraction. */
            if (p->calculus_mode == 1 && p->calculus_token != 0x6a && p->calculus_token != 0x6b) {
                p->status = FX_EVAL_MATH;
                return;
            }
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
        if (!exact_math(p) && kind == FX_NUMBER_SURD &&
            fx_number_to_decimal(components[index], components[index]) != FX_NUMERIC_OK) {
            unsupported(p, peek(p)); return;
        }
    }
}

/* 1C76C keeps an already rational operand when18212 denies compact-surd
 * recognition. The scalar root operates on numerator and denominator and
 * ordinary rational division retains a perfect rational square root. */
static fx_numeric_status scalar_square_root(parser *p, fx_number *out,
                                            const fx_number *input)
{
    if (exact_math(p) || fx_number_kind(input) != FX_NUMBER_RATIONAL)
        return fx_number_sqrt(out, input, exact_math(p));
    fx_rational rational;
    fx_number numerator, denominator;
    fx_numeric_status status = fx_rational_decode(&rational, input);
    if (status != FX_NUMERIC_OK) return status;
    if (rational.numerator < 0) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
    if (rational.denominator > (uint64_t)INT64_MAX) return FX_NUMERIC_UNREPRESENTABLE;
    status = fx_decimal_from_integer(&numerator, rational.numerator);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_decimal_from_integer(&denominator, (int64_t)rational.denominator);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_decimal_sqrt(&numerator, &numerator);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_decimal_integer_cleanup(&numerator);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_decimal_sqrt(&denominator, &denominator);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_decimal_integer_cleanup(&denominator);
    if (status != FX_NUMERIC_OK) return status;
    int64_t n, d;
    if (!fx_number_fractional_status(&numerator) && !fx_number_fractional_status(&denominator) &&
        fx_decimal_to_integer(&n, &numerator) == FX_NUMERIC_OK &&
        fx_decimal_to_integer(&d, &denominator) == FX_NUMERIC_OK && d > 0) {
        fx_rational root = {n, (uint64_t)d, 0};
        return fx_rational_encode(out, &root);
    }
    return fx_decimal_binary(out, &numerator, &denominator, FX_DIVIDE);
}

static int solve_suffix_admitted(const parser *p)
{
    if (peek(p) != ',') return 0;
    fx_evaluator_token variable = fx_decode_evaluator_token(
        p->position + 1 < p->length ? p->input[p->position + 1] : 0,
        p->options.calculation_context);
    fx_evaluator_token end = fx_decode_evaluator_token(
        p->position + 2 < p->length ? p->input[p->position + 2] : 0,
        p->options.calculation_context);
    return variable.kind == 5 && variable.value != 1 && variable.value != 10 &&
           end.kind == 10;
}

static void primary_value(parser *p, fx_complex *out);

static void primary(parser *p, fx_complex *out)
{
    uint8_t token = peek(p);
    unsigned saved_depth = p->operator_depth;
    unsigned saved_group_depth = p->group_depth;
    if (token == '(' || function_prefix(token) || token == '-' || token == 0x60) {
        uint8_t operation = token == '(' ? 3 :
            (token == '-' || token == '+' || token == 0x60) ? 95 :
            fx_decode_evaluator_token(token, p->options.calculation_context).value;
        note_operator(p, operation);
        ++p->operator_depth;
        if (token == '(' || function_prefix(token)) ++p->group_depth;
    }
    if (p->operator_depth > 24) {
        p->status = FX_EVAL_STACK;
        p->operator_depth = saved_depth;
        p->group_depth = saved_group_depth;
        return;
    }
    primary_value(p, out);
    p->operator_depth = saved_depth;
    p->group_depth = saved_group_depth;
}

static void primary_value(parser *p, fx_complex *out)
{
    uint8_t token = peek(p);
    fx_complex_zero(out);
    if (++p->depth > 256) { p->status = FX_EVAL_RESOURCE_LIMIT; --p->depth; return; }
    if ((token >= '0' && token <= '9') || token == '.' ||
        (p->options.calculation_context == 2 && token >= 0xb8 && token <= 0xbd)) literal(p, out);
    else if (p->options.calculation_context == 2 && token >= 0x50 && token <= 0x53) {
        static const uint8_t bases[] = {FX_BASE_HEX, FX_BASE_DEC, FX_BASE_OCT, FX_BASE_BIN};
        ++p->position;
        base_literal(p, out, bases[token - 0x50]);
    }
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
    } else if (fx_decode_evaluator_token(token, p->options.calculation_context).kind == 7) {
        /*1705C observes the referenced dimension word before any rich leaf.
         * A partial word is admitted; an empty one returns native9. */
        fx_evaluator_token reference = fx_decode_evaluator_token(token, p->options.calculation_context);
        uint8_t native_status = 0;
        fx_numeric_status status = fx_linalg_bank_reference(&out->real, p->linear_algebra,
            reference.value & 0xf0, reference.value & 15, &native_status);
        if (status != FX_NUMERIC_OK) unsupported(p, token);
        else p->status = (fx_eval_status)native_status;
        if (p->status == FX_EVAL_OK) ++p->position;
    } else if (token == 0x80) {
        if (p->options.calculation_context == 0xc4) fx_decimal_from_u8(&out->imaginary, 1);
        ++p->position;
    } else if (token == 0x81 || token == 0x82) {
        static const uint8_t e[10] = {0x02,0x71,0x82,0x81,0x82,0x84,0x59,0x04,0x00,0x01};
        static const uint8_t pi[10] = {0x03,0x14,0x15,0x92,0x65,0x35,0x89,0x80,0x00,0x01};
        memcpy(out->real.bytes, token == 0x81 ? e : pi, 10);
        ++p->position;
    } else if (fx_decode_evaluator_token(token, p->options.calculation_context).kind == 6 &&
               fx_decode_evaluator_token(token, p->options.calculation_context).value < 40) {
        fx_evaluator_token decoded = fx_decode_evaluator_token(token, p->options.calculation_context);
        if (fx_number_scientific_constant(&out->real, decoded.value) != FX_NUMERIC_OK)
            unsupported(p, token);
        else ++p->position;
    } else if (token == 0x6c || token == 0x6d) {
        coordinates(p, out, token);
    } else if (token == 0x5d || (token >= 0x69 && token <= 0x6b)) {
        calculus(p, out, token);
    } else if (function_prefix(token)) {
        fx_complex output = *out, second_argument;
        int closed = 0;
        int has_base = 0;
        ++p->position;
        /* Function tokens include the opening parenthesis implicitly. */
        expression(p, out, 0);
        if (p->status == FX_EVAL_OK && token == 0x3f) {
            p->status = FX_EVAL_SYNTAX;
            --p->depth;
            return;
        }
        if (p->status == FX_EVAL_OK && token == 0x68 && peek(p) == ',') {
            /*1718C retains the base as a numeric stack operand while the
             * second argument is parsed. CMPLX retains both records. */
            if (p->value_depth >= 10) {
                p->status = FX_EVAL_STACK;
                --p->depth;
                return;
            }
            unsigned width = p->options.calculation_context == 0xc4 ? 2 : 1;
            p->value_depth += width;
            ++p->position;
            expression(p, &second_argument, 0);
            p->value_depth -= width;
            has_base = 1;
        }
        if (p->status == FX_EVAL_OK && !p->scan_only) {
            unsigned mask = token == 0xc0 || token == 0xc1 ? 0 :
                token == 0x61 || token == 0x62 || token == 0x63 ||
                token == 0x88 || token == 0xc3 || token == 0xb3 ? 255 : 7;
            /*16336 admits an argument at its delimiter, before the close
             * is consumed. Logbase checks the second argument first. */
            if ((has_base && !operand_admitted(p, &second_argument, 7)) ||
                !operand_admitted(p, out, mask)) {
                p->status = FX_EVAL_MATH;
                --p->depth;
                return;
            }
        }
        if (p->status == FX_EVAL_OK) {
            if (peek(p) == ')') { ++p->position; closed = 1; }
            else if (!omitted_closing(p)) p->status = FX_EVAL_SYNTAX;
        }
        if (p->status == FX_EVAL_OK) {
            if (p->scan_only) { fx_complex_zero(out); }
            else if (!has_base && stage_unary(p, out,
                    fx_decode_evaluator_token(token, p->options.calculation_context).value)) {
                /* The rich route has already copied/reserved its physical
                 * slot; it must not fall through to a scalar function. */
            }
            else if (p->options.calculation_context == 0xc4) {
                fx_complex_dispatch_context context = complex_context(p);
                uint8_t firmware_status = 0;
                fx_numeric_status status = has_base ?
                    fx_complex_dispatch_binary(&output, out, &second_argument, token, &context, &firmware_status) :
                    fx_complex_dispatch_unary(&output, out, token, &context, &firmware_status);
                accept_complex_operation(p, out, &output, status, firmware_status);
            } else {
                fx_numeric_status status;
                if ((token == 0x61 || token == 0x62) && p->options.calculation_context == 2) {
                    unsigned native_status = 0;
                    status = fx_base_unary(&output.real, &out->real, p->base_radix,
                                           token == 0x61 ? FX_BASE_NOT : FX_BASE_NEGATE,
                                           &native_status);
                    if (status == FX_NUMERIC_OK && native_status) {
                        p->status = (fx_eval_status)native_status;
                        if (closed) --p->position;
                        --p->depth;
                        return;
                    }
                }
                else if (token == 0x61 || token == 0x62) {
                    unsupported(p, token); --p->depth; return;
                }
                else if (token == 0x63) {
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
                else if (token == 0xb3) {
                    uint8_t native_status = 0;
                    status = fx_scalar_display_round(&output.real, &out->real,
                        p->environment.display_mode, p->environment.digits, &native_status);
                    if (status == FX_NUMERIC_OK && native_status) p->status = (fx_eval_status)native_status;
                }
                else if (token == 0xc3 && p->options.angle_unit >= 4 && p->options.angle_unit <= 6)
                    status = fx_complex_argument(&output, out, (fx_angle_unit)(p->options.angle_unit-4));
                else if (token == 0x98) status = scalar_square_root(p, &output.real, &out->real);
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
                                             exact_math(p), NULL);
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
            else if (stage_unary(p, out, 95)) { }
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
    else {
        fx_evaluator_token decoded = fx_decode_evaluator_token(token, p->options.calculation_context);
        if (decoded.kind == 2 || decoded.kind == 3 || decoded.kind == 8 || decoded.kind == 15)
            p->status = FX_EVAL_SYNTAX;
        else unsupported(p, token);
    }
    --p->depth;
}

static int implicit_start(uint8_t token, uint8_t context)
{
    fx_evaluator_token decoded = fx_decode_evaluator_token(token, context);
    return variable_slot(token, context) >= 0 || token == '(' || token == 0x80 || token == 0x81 || token == 0x82 || function_prefix(token) ||
           (decoded.kind == 6 && decoded.value < 40) || decoded.kind == 7 ||
           (context == 2 && token >= 0x50 && token <= 0x53);
}

static void sexagesimal(parser *p, fx_complex *out)
{
    fx_number components[3];
    size_t count = 1;
    fx_complex output = *out;
    if (!p->scan_only && !real_only_admitted(p, out)) {
        p->status = FX_EVAL_MATH;
        return;
    }
    components[0] = out->real;
    for (;;) {
        ++p->position; /* the required5C after this component */
        uint8_t next = peek(p);
        fx_evaluator_token decoded = fx_decode_evaluator_token(next, p->options.calculation_context);
        if (next == 0x60 || next == 0x5c) { p->status = FX_EVAL_SYNTAX; return; }
        if (decoded.kind != 4) break;
        if (count == 3) { p->status = FX_EVAL_SYNTAX; return; }
        fx_complex component;
        fx_complex_zero(&component);
        literal(p, &component);
        if (p->status != FX_EVAL_OK) return;
        if (peek(p) != 0x5c) { p->status = FX_EVAL_SYNTAX; return; }
        components[count++] = component.real;
    }
    if (p->scan_only) { fx_complex_zero(out); return; }
    fx_numeric_status status = fx_number_sexagesimal(&output.real, components, count);
    accept_real_result(p, out, &output, status);
}

static void conversion(parser *p, fx_complex *out, fx_evaluator_token decoded)
{
    uint8_t token = peek(p);
    if (!p->scan_only && !real_only_admitted(p, out)) {
        p->status = FX_EVAL_MATH;
        return;
    }
    ++p->position;
    if (token == 0xa5) {
        for (unsigned index = 0; index < 3; ++index) {
            fx_evaluator_token digit = fx_decode_evaluator_token(peek(p), p->options.calculation_context);
            if (digit.kind != 4 || digit.value > 9) { p->status = FX_EVAL_SYNTAX; return; }
            ++p->position;
        }
        /* This pinned model has feature byte1FFE3=0. The dynamic selector
         * handler rejects a complete three-digit code at its last digit. */
        --p->position;
        p->status = FX_EVAL_SYNTAX;
        return;
    }
    if (p->scan_only) { fx_complex_zero(out); return; }
    fx_complex output = *out;
    fx_numeric_status status = fx_number_unit_convert(&output.real, &out->real, decoded.value - 55);
    accept_real_result(p, out, &output, status);
    if (p->status == FX_EVAL_MATH) --p->position;
}

static void coordinates(parser *p, fx_complex *out, uint8_t token)
{
    fx_complex second, operands, converted, active;
    /*16B54 rejects coordinate prefixes in equation screens before reading
     * an argument, independently of Math or calculation mode. */
    if (p->environment.screen & 0x40) { p->status = FX_EVAL_SYNTAX; return; }
    ++p->position;
    expression(p, out, 0);
    if (p->status != FX_EVAL_OK) return;
    if (peek(p) != ',') {
        if (store_token(p) && p->position + 1 < p->length &&
            p->input[p->position + 1] && p->input[p->position + 1] != ':') ++p->position;
        p->status = FX_EVAL_SYNTAX; return;
    }
    if (p->value_depth >= 10) { p->status = FX_EVAL_STACK; return; }
    unsigned width = p->options.calculation_context == 0xc4 ? 2 : 1;
    p->value_depth += width;
    ++p->position;
    /*1718C replaces the root prefix selector when accepting its comma. */
    if (p->operator_depth == 1) p->terminal_operator = token == 0x6c ? 0x24 : 0x25;
    expression(p, &second, 0);
    p->value_depth -= width;
    if (p->status != FX_EVAL_OK) return;
    /*1708E validates a following scalar-store delimiter before draining
     * the pending coordinate operation. An extra comma instead reaches the
     * ordinary reduction first, so successful X/Y writes survive that error. */
    if (store_token(p) && p->position + 1 < p->length &&
        p->input[p->position + 1] && p->input[p->position + 1] != ':') {
        ++p->position;
        p->status = FX_EVAL_SYNTAX;
        return;
    }
    if (p->scan_only) fx_complex_zero(out);
    else {
        if (!real_only_admitted(p, &second) || !real_only_admitted(p, out)) {
            p->status = FX_EVAL_MATH; return;
        }
        if (p->options.angle_unit < 4 || p->options.angle_unit > 6) {
            unsupported(p, token); return;
        }
        operands.real = out->real;
        operands.imaginary = second.real;
        fx_angle_unit unit = (fx_angle_unit)(p->options.angle_unit - 4);
        fx_numeric_status status = token == 0x6c ?
            fx_complex_to_polar(&converted, &operands, unit, exact_math(p)) :
            fx_complex_from_polar(&converted, &operands, unit, exact_math(p));
        if (status != FX_NUMERIC_OK) { unsupported(p, token); return; }
        uint8_t native_status = 0;
        status = fx_complex_firmware_status(&native_status,
            token == 0x6c ? FX_COMPLEX_TO_POLAR_RETURN : FX_COMPLEX_FROM_POLAR_RETURN,
            &operands, &converted);
        if (status != FX_NUMERIC_OK) { unsupported(p, token); return; }
        if (native_status) { p->status = (fx_eval_status)native_status; return; }
        /*16168 stores raw coordinates before16562 cleanup or later syntax
         * validation. COMP leaves the imaginary bank records untouched. */
        p->variables->values[FX_VARIABLE_X][0] = converted.real;
        p->variables->values[FX_VARIABLE_Y][0] = converted.imaginary;
        if (p->options.calculation_context == 0xc4) {
            fx_number_zero(&p->variables->values[FX_VARIABLE_X][1]);
            fx_number_zero(&p->variables->values[FX_VARIABLE_Y][1]);
        }
        p->secondary = converted.imaginary;
        fx_complex_zero(&active);
        active.real = converted.real;
        accept_real_result(p, out, &active, FX_NUMERIC_OK);
        if (p->status != FX_EVAL_OK) return;
    }
    if (peek(p) == ')') ++p->position;
    else if (!omitted_closing(p)) p->status = FX_EVAL_SYNTAX;
}

static void polar_operator(parser *p, fx_complex *out, const fx_complex *right)
{
    fx_complex operands, converted;
    if (p->scan_only) { fx_complex_zero(out); return; }
    if (!real_only_admitted(p, right) || !real_only_admitted(p, out)) {
        p->status = FX_EVAL_MATH; return;
    }
    if (p->options.angle_unit < 4 || p->options.angle_unit > 6) {
        unsupported(p, 0xaf); return;
    }
    operands.real = out->real;
    operands.imaginary = right->real;
    fx_numeric_status status = fx_complex_from_polar(&converted, &operands,
        (fx_angle_unit)(p->options.angle_unit - 4), exact_math(p));
    if (status != FX_NUMERIC_OK) { unsupported(p, 0xaf); return; }
    uint8_t native_status = 0;
    status = fx_complex_firmware_status(&native_status, FX_COMPLEX_FROM_POLAR_RETURN,
                                        &operands, &converted);
    if (status != FX_NUMERIC_OK) { unsupported(p, 0xaf); return; }
    fx_complex_dispatch_context context = complex_context(p);
    fx_complex cleaned;
    status = fx_complex_dispatch_cleanup(&cleaned, &converted, native_status, &context, &native_status);
    accept_complex_operation(p, out, &cleaned, status, native_status);
    if (p->options.calculation_context != 0xc4) fx_number_zero(&out->imaginary);
}

static void quotient_remainder(parser *p, fx_complex *out, const fx_complex *right)
{
    if (p->scan_only) { fx_complex_zero(out); return; }
    if (!real_only_admitted(p, right) || !real_only_admitted(p, out)) {
        p->status = FX_EVAL_MATH; return;
    }
    fx_quotient_remainder_result result;
    fx_numeric_status status = fx_number_quotient_remainder(&result, &out->real, &right->real);
    if (status != FX_NUMERIC_OK) { unsupported(p, 0x5f); return; }
    fx_complex active;
    fx_complex_zero(&active);
    active.real = result.quotient;
    p->secondary = result.remainder;
    fx_complex_dispatch_context context = complex_context(p);
    fx_complex cleaned;
    uint8_t native_status = result.firmware_status;
    status = fx_complex_dispatch_cleanup(&cleaned, &active, native_status, &context, &native_status);
    accept_complex_operation(p, out, &cleaned, status, native_status);
}

static void fraction(parser *p, fx_complex *out, const fx_complex *denominator,
                     int mixed)
{
    int64_t n, d;
    fx_complex unmarked_denominator;
    if (p->scan_only) { fx_complex_zero(out); return; }
    if (!operand_admitted(p, denominator, 3) || !operand_admitted(p, out, 3)) {
        p->status = FX_EVAL_MATH; return;
    }
    /*16058 clears the sexagesimal marker from both real operands before
     * complex admission or integrality tests. In1 AE2 degrees, DMS binds to
     * the denominator; the constructor returns an ordinary rational record. */
    out->real.bytes[0] &= (uint8_t)~0x40;
    unmarked_denominator = *denominator;
    unmarked_denominator.real.bytes[0] &= (uint8_t)~0x40;
    denominator = &unmarked_denominator;
    if (p->options.calculation_context == 0xc4) {
        uint8_t left_class, right_class;
        if (fx_scalar_numeric_classify(&left_class, &out->imaginary) != FX_NUMERIC_OK ||
            fx_scalar_numeric_classify(&right_class, &denominator->imaginary) != FX_NUMERIC_OK) {
            unsupported(p, 0xae); return;
        }
        if (left_class != 1 || right_class != 1) {
            /*1607A sees the pending mixed-fraction selector100 and rejects
             * an imaginary numerator/denominator instead of dividing. */
            if (mixed) { p->status = FX_EVAL_MATH; return; }
            binary(p, out, denominator, FX_DIVIDE); return;
        }
    }
    if (fx_number_fractional_status(&out->real) || fx_number_fractional_status(&denominator->real) ||
        fx_decimal_to_integer(&n, &out->real) != FX_NUMERIC_OK ||
        fx_decimal_to_integer(&d, &denominator->real) != FX_NUMERIC_OK) {
        if (p->options.calculation_context == 2) {
            /*160E2 dispatches ordinary scalar division, independently of
             * the BASE-N pending-operator range/truncation policy15F34. */
            fx_complex output = *out;
            fx_numeric_status status = fx_number_binary(&output.real, &out->real,
                                                         &denominator->real, FX_DIVIDE);
            accept_operation(p, &output.real, status);
            if (p->status == FX_EVAL_OK) *out = output;
        } else binary(p, out, denominator, FX_DIVIDE);
        return;
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
    if (!operand_admitted(p, argument, token == 0x5e ? 3 : 7)) {
        p->status = FX_EVAL_MATH; return;
    }
    /*16394 distinguishes general matrix power from its square/cube
     * shortcut. The right operand has already passed its own admission. */
    if (token == 0x5e && (out->real.bytes[0] >> 4) == 6) {
        p->status = FX_EVAL_SYNTAX; return;
    }
    if (!operand_admitted(p, out, token == 0x5e ? 1 : 7)) {
        p->status = FX_EVAL_MATH; return;
    }
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
        fx_evaluator_token decoded = fx_decode_evaluator_token(token, p->options.calculation_context);
        if ((p->environment.screen & 0x40) &&
            (token == ':' || (token == ')' && !p->group_depth))) {
            /* The SOLVE terminator and unmatched closing guard run before
             * reduction of pending arithmetic. Comma suffixes instead reduce
             * first when their variable/terminator admission fails. */
            p->status = FX_EVAL_SYNTAX;
            return;
        }
        if (token == '=') {
            if (!(p->environment.screen & 0x40) ||
                (p->equation_used && p->equation_position != p->position)) {
                p->status = FX_EVAL_SYNTAX;
                return;
            }
            p->equation_used = 1;
            if (p->storage) p->storage->ram[0x8125] |= 1;
            p->equation_position = p->position;
            if (minimum || p->group_depth) return;
            if (p->value_depth >= 10 || p->operator_depth >= 24) {
                p->status = FX_EVAL_STACK;
                return;
            }
            unsigned outer = p->operator_depth++;
            p->value_depth += p->options.calculation_context == 0xc4 ? 2 : 1;
            ++p->position;
            fx_complex right;
            expression(p, &right, 0);
            p->value_depth -= p->options.calculation_context == 0xc4 ? 2 : 1;
            p->operator_depth = outer;
            if (p->status == FX_EVAL_OK) {
                if (!scalar_header_admitted(&right) || !scalar_header_admitted(out)) {
                    p->status = FX_EVAL_MATH;
                    return;
                }
                p->secondary = right.real;
                p->terminal_operator = 42;

            }
            return;
        }
        unsigned precedence;
        fx_binary_op op;
        fx_complex right;
        int implicit = 0;
        int logical = 0;
        if (token == 0x5c || token == 0xa5 ||
            (decoded.kind == 3 && decoded.value >= 55 && decoded.value <= 94)) {
            /* Unit postfixes have native rank9: above implicit product8,
             * below unary negation10. DMS has the ordinary postfix rank12. */
            unsigned postfix_precedence = token == 0x5c ? 70 : 35;
            if (postfix_precedence < minimum) return;
            note_operator(p, decoded.value);
            if (token == 0x5c) sexagesimal(p, out);
            else conversion(p, out, decoded);
            continue;
        }
        if (token == 0x57 || token == 0x25 || (token >= 0x75 && token <= 0x77) ||
            (token >= 0x85 && token <= 0x87)) {
            if (70 < minimum) return;
            note_operator(p, decoded.value);
            if (!p->scan_only && !operand_admitted(p, out,
                    token >= 0x75 && token <= 0x77 ? 1 : 7)) {
                p->status = FX_EVAL_MATH; return;
            }
            fx_complex output = *out;
            fx_numeric_status status;
            ++p->position;
            if (!p->scan_only && stage_unary(p, out, decoded.value)) return;
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
        if (p->options.calculation_context == 2 &&
            (token == 0x6e || token == 0x6f || token == 0x7e || token == 0x7f)) {
            precedence = token == 0x6e ? 6 : 5; op = FX_ADD; logical = 1;
        } else if (token == '+' || token == '-') {
            precedence = 10; op = token == '+' ? FX_ADD : FX_SUBTRACT;
        } else if (token == 0x4e || token == 0x4f || token == 0x5f) {
            precedence = 20; op = token == 0x4e ? FX_MULTIPLY : FX_DIVIDE;
        } else if (p->options.calculation_context == 2 && token == 0x2f) {
            precedence = 30; op = FX_MULTIPLY;
        } else if (token == 0xbe || token == 0xbf || token == 0xaf) {
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
        /*Equation screens reject quotient/remainder before
         * consuming its operator or evaluating the right operand. */
        if (token == 0x5f && (p->environment.screen & 0x40)) {
            p->status = FX_EVAL_SYNTAX; return;
        }
        /*16C78 checks the current operand for AE before stacking it or
         * consuming the separator. In particular, F3 stays an error tag;
         *16058 must never clear its marker bit into the unrelated B3 tag. */
        if (token == 0xae && !p->scan_only && !operand_admitted(p, out, 3)) {
            p->status = FX_EVAL_MATH; return;
        }
        note_operator(p, implicit ? 117 : decoded.value);
        if (p->value_depth >= 10 || p->operator_depth >= 24) {
            p->status = FX_EVAL_STACK;
            return;
        }
        p->value_depth += p->options.calculation_context == 0xc4 ? 2 : 1;
        unsigned saved_operator_depth = p->operator_depth++;
        if (!implicit) ++p->position;
        if (token == 0x5e || token == 0x9f) {
            /* Power and nth-root include an implicit opening parenthesis.
             * The right argument is a full expression. Nth-root takes its
             * degree on the left and radicand on the right. A closing token
             * may be omitted at end of input. */
            int closed = 0;
            ++p->group_depth;
            expression(p, &right, 0);
            if (p->status == FX_EVAL_OK) {
                if (peek(p) == ')') { ++p->position; closed = 1; }
                else if (!omitted_closing(p)) p->status = FX_EVAL_SYNTAX;
            }
            if (p->status == FX_EVAL_OK) {
                power_or_root(p, out, &right, token);
                if ((p->status == FX_EVAL_MATH || p->status == FX_EVAL_SYNTAX) && closed)
                    --p->position;
            }
            p->operator_depth = saved_operator_depth;
            p->value_depth -= p->options.calculation_context == 0xc4 ? 2 : 1;
            --p->group_depth;
            continue;
        }
        expression(p, &right, precedence + 1);
        if (p->status == FX_EVAL_OK && logical) {
            fx_complex output = *out;
            fx_base_binary_op operation = token == 0x6e ? FX_BASE_AND : token == 0x6f ? FX_BASE_OR :
                                           token == 0x7e ? FX_BASE_XOR : FX_BASE_XNOR;
            unsigned native_status = 0;
            fx_numeric_status status = fx_base_binary(&output.real, &out->real, &right.real,
                                                       p->base_radix, operation, &native_status);
            if (status == FX_NUMERIC_OK && native_status) p->status = (fx_eval_status)native_status;
            else accept_operation(p, &output.real, status);
            if (p->status == FX_EVAL_OK) *out = output;
        } else if (p->status == FX_EVAL_OK && token == 0xaf) {
            polar_operator(p, out, &right);
        } else if (p->status == FX_EVAL_OK && token == 0x5f) {
            quotient_remainder(p, out, &right);
        } else if (p->status == FX_EVAL_OK && token == 0xae) {
            if (peek(p) == 0xae) {
                fx_complex denominator;
                if (!p->scan_only && !operand_admitted(p, &right, 3)) {
                    p->status = FX_EVAL_MATH;
                    p->operator_depth = saved_operator_depth;
                    p->value_depth -= p->options.calculation_context == 0xc4 ? 2 : 1;
                    return;
                }
                /* The second separator keeps both the whole part and the
                 * numerator until16058 restores them for construction. */
                if (p->value_depth >= 10 || p->operator_depth >= 24) {
                    p->status = FX_EVAL_STACK;
                    p->operator_depth = saved_operator_depth;
                    p->value_depth -= p->options.calculation_context == 0xc4 ? 2 : 1;
                    return;
                }
                unsigned width = p->options.calculation_context == 0xc4 ? 2 : 1;
                p->value_depth += width;
                ++p->operator_depth;
                ++p->position;
                expression(p, &denominator, precedence + 1);
                --p->operator_depth;
                p->value_depth -= width;
                if (p->status == FX_EVAL_OK && peek(p) == 0xae)
                    p->status = FX_EVAL_SYNTAX;
                if (p->status == FX_EVAL_OK) fraction(p, &right, &denominator, 1);
                /*1610E checks the restored whole part's imaginary value
                 * before its marker or mixed-fraction signs are changed. */
                if (p->status == FX_EVAL_OK && !p->scan_only &&
                    p->options.calculation_context == 0xc4 &&
                    (out->imaginary.bytes[8] || out->imaginary.bytes[9]))
                    p->status = FX_EVAL_MATH;
                /*16118 also clears the restored whole-number marker before
                 * the mixed-fraction addition. */
                out->real.bytes[0] &= (uint8_t)~0x40;
                if (p->status == FX_EVAL_OK) {
                    uint8_t whole_sign, fraction_sign;
                    fx_numeric_status first = fx_scalar_numeric_classify(&whole_sign, &out->real);
                    fx_numeric_status second = fx_scalar_numeric_classify(&fraction_sign, &right.real);
                    if (first != FX_NUMERIC_OK || second != FX_NUMERIC_OK) unsupported(p, 0xae);
                    else if (whole_sign != 1 && fraction_sign != 1) {
                        if (whole_sign != 4) (void)fx_number_negate(&right.real, &right.real);
                        if (fraction_sign != 4) (void)fx_number_negate(&out->real, &out->real);
                    }
                }
                if (p->status == FX_EVAL_OK && p->options.calculation_context == 2) {
                    /* The mixed-fraction constructor is not a pending plus
                     * operator. Its scalar arithmetic bypasses15F34/E82. */
                    fx_complex output = *out;
                    fx_numeric_status status = fx_number_binary(&output.real, &out->real, &right.real, FX_ADD);
                    accept_operation(p, &output.real, status);
                    if (p->status == FX_EVAL_OK) *out = output;
                } else if (p->status == FX_EVAL_OK) binary(p, out, &right, FX_ADD);
            } else fraction(p, out, &right, 0);
        } else if (p->status == FX_EVAL_OK && (token == 0xbe || token == 0xbf)) {
            if (p->scan_only) {
                fx_complex_zero(out); p->operator_depth = saved_operator_depth;
                p->value_depth -= p->options.calculation_context == 0xc4 ? 2 : 1; continue;
            }
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
        p->operator_depth = saved_operator_depth;
        p->value_depth -= p->options.calculation_context == 0xc4 ? 2 : 1;
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
    if (p->storage && (header == 6 || header == 9 || header == 15)) {
        uint8_t leaf_status;
        variables_to_storage(p);
        fx_numeric_status status = fx_eval_finish_cleanup(p->storage, value, &leaf_status);
        variables_from_storage(p);
        bank_from_storage(p);
        /*17274 restores the enclosing success channel even when1415A
         * publishes an error reference after partial physical cell cleanup. */
        if (status != FX_NUMERIC_OK) unsupported(p, 0);
        return;
    }
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
        context.exact_math = exact_math(p);
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
    callback.operator_depth = 0;
    callback.group_depth = 0;
    callback.value_depth = 0;
    callback.equation_used = 0;
    callback.equation_position = 0;
    callback.terminal_operator = 0xff;
    fx_number_zero(&callback.secondary);
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
    /*16B44/16BA8 reject every calculus prefix in equation screens before
     * loading X, preflighting the body, or polling cancellation. */
    if (p->environment.screen & 0x40) { p->status = FX_EVAL_SYNTAX; return; }
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

fx_eval_environment fx_eval_default_environment(void)
{
    fx_eval_environment environment = {1, 0, 0, 0, 0, 0, FX_BASE_DEC};
    return environment;
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
    if (p->environment.screen & 0x80) { p->status = FX_EVAL_SYNTAX; return; }
    size_t position = p->position++;
    /*170A0 requires the store token to be followed by the input terminator.
     * No variable write occurs until syntax and scalar admission succeed. */
    if (peek(p) && peek(p) != ':') { p->status = FX_EVAL_SYNTAX; return; }
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
    p->terminal_operator = 0xff;
}

static fx_eval_status evaluate(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment, const fx_eval_state *state,
                           const fx_calculus_control *control, uint8_t selected_base,
                           const fx_number *initial_secondary,
                           const fx_number *prior_answer, fx_eval_storage *storage,
                           fx_eval_effects *effects, fx_eval_result *result)
{
    parser p;
    fx_complex value;
    fx_eval_variables local_variables;
    fx_linalg_bank local_linear_algebra = {0};
    fx_eval_variables *variables = state ? state->variables : NULL;
    fx_complex_zero(&value);
    if (effects) {
        effects->equation_used = 0;
        effects->restricted_state = (environment ? environment->restricted_state : 0) & (uint8_t)~1;
    }
    if (!result) return FX_EVAL_SYNTAX;
    memset(result, 0, sizeof *result);
    if (initial_secondary) result->value[1] = *initial_secondary;
    if (!input || !length) { fx_number_error(&result->value[0], 2); return FX_EVAL_SYNTAX; }
    memset(&p, 0, sizeof p);
    p.terminal_operator = 0xff;
    p.input = input; p.length = length;
    if (!variables) { fx_eval_variables_clear(&local_variables); variables = &local_variables; }
    p.variables = variables;
    p.storage = storage;
    p.linear_algebra = state && state->linear_algebra ? state->linear_algebra : &local_linear_algebra;
    p.control = control;
    p.base_radix = selected_base;
    p.options = options ? *options : fx_eval_default_options();
    p.environment = environment ? *environment : fx_eval_default_environment();
    if (prior_answer) p.prior_answer = *prior_answer;
    else if (storage) memcpy(p.prior_answer.bytes, storage->ram + 0x828a, 10);
    if (storage) {
        if (state && state->variables) variables_to_storage(&p);
        else variables_from_storage(&p);
        storage->ram[0x8125] = p.options.calculation_context == 6 ? 0x18 : 0;
        bank_from_storage(&p);
    }
    if (p.options.calculation_context != 0xc1 && p.options.calculation_context != 0xc4 &&
        p.options.calculation_context != 2)
        p.status = FX_EVAL_UNIMPLEMENTED;
    else if (p.options.calculation_context == 2 && selected_base != FX_BASE_BIN &&
             selected_base != FX_BASE_OCT && selected_base != FX_BASE_DEC && selected_base != FX_BASE_HEX)
        p.status = FX_EVAL_UNIMPLEMENTED;
    else expression(&p, &value, 0);
    int suffix = 0;
    if (p.status == FX_EVAL_OK && (p.environment.screen & 0x40) && peek(&p) == ',') {
        if (!solve_suffix_admitted(&p)) p.status = FX_EVAL_SYNTAX;
        else suffix = 1;
    }
    if (p.status == FX_EVAL_OK && !suffix) store_result(&p, &value);
    if (p.status == FX_EVAL_OK && !suffix && peek(&p) != 0 &&
        (peek(&p) != ':' || (p.environment.screen & 0x40))) {
        fx_evaluator_token token = fx_decode_evaluator_token(peek(&p), p.options.calculation_context);
        if (token.kind == 10 || peek(&p) == ')' || peek(&p) == ',' || peek(&p) == '.' ||
            (peek(&p) >= '0' && peek(&p) <= '9')) p.status = FX_EVAL_SYNTAX;
        else unsupported(&p, peek(&p));
    }
    if (p.status == FX_EVAL_OK &&
        (value.real.bytes[0] >= 0x90 ||
         (value.real.bytes[0] >= 0x60 && value.real.bytes[0] < 0x80))) {
        /*17258 tests the full header byte. Rich/error results require the
         * ordinary screen and retain the evaluator's success channel while
         *1415A independently cleans or rejects the reference. */
        if (p.environment.screen != 1) p.status = FX_EVAL_SYNTAX;
        else continuous_finish(&p, &value.real);
    }
    result->value[0] = value.real;
    result->value[1] = value.imaginary;
    result->consumed = p.position;
    if (p.status == FX_EVAL_OK && p.position < p.length) ++result->consumed;
    if (p.status == FX_EVAL_OK) {
        if (p.terminal_operator == 0x24) p.status = FX_EVAL_POLAR_PAIR;
        else if (p.terminal_operator == 0x25) p.status = FX_EVAL_RECTANGULAR_PAIR;
        else if (p.terminal_operator == 0x74) p.status = FX_EVAL_QUOTIENT_PAIR;
        if (p.status != FX_EVAL_OK) result->value[1] = p.secondary;
        else if (p.environment.screen & 0x40) {
            if (p.terminal_operator == 42) result->value[1] = p.secondary;
            else fx_number_zero(&result->value[1]);
        }
        else if (p.options.calculation_context != 0xc4 && initial_secondary)
            result->value[1] = *initial_secondary;
    }
    if (p.status > FX_EVAL_OK && p.status <= 15) {
        fx_number_error(&result->value[0], (unsigned)p.status);
        fx_number_zero(&result->value[1]);
        if (initial_secondary) result->value[1] = *initial_secondary;
    }
    result->unsupported_token = p.unsupported;
    if (storage) {
        variables_to_storage(&p);
        storage->ram[0x8124] &= (uint8_t)~1;
    }
    if (effects) effects->equation_used = storage ? storage->ram[0x8125] & 1 : p.equation_used;
    if (p.options.calculation_context == 2 && initial_secondary &&
        (p.status != FX_EVAL_OK || !(p.environment.screen & 0x40)) &&
        p.status != FX_EVAL_POLAR_PAIR && p.status != FX_EVAL_RECTANGULAR_PAIR && p.status != FX_EVAL_QUOTIENT_PAIR)
        result->value[1] = *initial_secondary;
    return p.status;
}

fx_eval_status fx_evaluate_with_state(const uint8_t *input, size_t length,
                           const fx_eval_options *options, const fx_eval_state *state,
                           const fx_calculus_control *control, fx_eval_result *result)
{
    return evaluate(input, length, options, NULL, state, control, FX_BASE_DEC, NULL, NULL, NULL, NULL, result);
}

fx_eval_status fx_evaluate_prepared(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment,
                           const fx_eval_state *state, const fx_calculus_control *control,
                           const fx_number *initial_secondary, fx_eval_result *result)
{
    uint8_t selected_base = environment ? environment->selected_base : FX_BASE_DEC;
    return evaluate(input, length, options, environment, state, control,
                    selected_base, initial_secondary, NULL, NULL, NULL, result);
}

fx_eval_status fx_evaluate_prepared_with_prior_answer(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment,
                           const fx_eval_state *state, const fx_calculus_control *control,
                           const fx_number *initial_secondary,
                           const fx_number *prior_answer, fx_eval_result *result)
{
    uint8_t selected_base = environment ? environment->selected_base : FX_BASE_DEC;
    return evaluate(input, length, options, environment, state, control,
                    selected_base, initial_secondary, prior_answer, NULL, NULL, result);
}

fx_eval_status fx_evaluate_base_n(const uint8_t *input, size_t length,
                           uint8_t selected_base, const fx_eval_options *options,
                           fx_eval_variables *variables,
                           const fx_number *initial_secondary, fx_eval_result *result)
{
    fx_eval_options prepared = options ? *options : fx_eval_default_options();
    fx_eval_state state = {variables, NULL};
    prepared.calculation_context = 2;
    return evaluate(input, length, &prepared, NULL, &state, NULL,
                    selected_base, initial_secondary, NULL, NULL, NULL, result);
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

fx_eval_status fx_evaluate_prepared_observed(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment,
                           const fx_eval_state *state, const fx_calculus_control *control,
                           const fx_number *initial_secondary,
                           const fx_number *prior_answer,
                           fx_eval_effects *effects, fx_eval_result *result)
{
    uint8_t selected_base = environment ? environment->selected_base : FX_BASE_DEC;
    return evaluate(input, length, options, environment, state, control,
                    selected_base, initial_secondary, prior_answer, NULL, effects, result);
}

fx_eval_status fx_evaluate_prepared_with_storage(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment,
                           const fx_eval_state *state, const fx_calculus_control *control,
                           const fx_number *initial_secondary,
                           const fx_number *prior_answer, fx_eval_storage *storage,
                           fx_eval_effects *effects, fx_eval_result *result)
{
    if (!storage || !storage->ram || storage->ram_size != 65536u) {
        if (result) memset(result, 0, sizeof *result);
        if (effects) memset(effects, 0, sizeof *effects);
        return FX_EVAL_UNIMPLEMENTED;
    }
    fx_eval_options prepared = options ? *options : fx_eval_default_options();
    if (!options) {
        prepared.calculation_context = storage->ram[0x80f9];
        prepared.math_output = storage->ram[0x8106];
        prepared.angle_unit = storage->ram[0x8105];
    }
    if (prepared.calculation_context != storage->ram[0x80f9]) {
        if (result) memset(result, 0, sizeof *result);
        if (effects) memset(effects, 0, sizeof *effects);
        return FX_EVAL_UNIMPLEMENTED;
    }
    fx_eval_environment globals = environment ? *environment : fx_eval_default_environment();
    if (!environment) {
        globals.screen = storage->ram[0x80fc];
        globals.prior_operation = storage->ram[0x80f5];
        globals.complex_format = storage->ram[0x810c];
        globals.restricted_state = storage->ram[0x8124];
        globals.display_mode = storage->ram[0x8102];
        globals.digits = storage->ram[0x8103];
        globals.selected_base = storage->ram[0x80fa];
    }
    return evaluate(input, length, &prepared, &globals, state, control,
        globals.selected_base, initial_secondary, prior_answer, storage, effects, result);
}
