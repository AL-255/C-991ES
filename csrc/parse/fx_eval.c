/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_eval.h"
#include "fx_eval_transport.h"
#include "fx_eval_surd_workspace.h"
#include "fx_eval_rich.h"
#include "../platform/fx_platform.h"
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
#include "../numeric/fx_integral_storage.h"
#include "../numeric/fx_c4_integral_storage.h"
#include "../numeric/fx_derivative.h"
#include "../numeric/fx_derivative_storage.h"
#include "../numeric/fx_c4_derivative_storage.h"
#include "../numeric/fx_surd_components.h"
#include "../numeric/fx_sexagesimal.h"
#include "../numeric/fx_quotient_remainder.h"
#include "../numeric/fx_random.h"
#include "../numeric/fx_base_word.h"
#include "../numeric/fx_raw_fraction_convert.h"
#include "../complex/fx_complex_dispatch.h"
#include "../complex/fx_complex_angle.h"
#include "../complex/fx_complex_round.h"
#include "../stats/fx_stats_value.h"
#include "../stats/fx_stats.h"
#include <string.h>

typedef struct {
    const uint8_t *input;
    size_t length, position;
    size_t lookahead_position;
    uint8_t lookahead_token, lookahead_valid;
    unsigned depth;
    unsigned operator_depth, value_depth, group_depth;
    uint8_t equation_used;
    size_t equation_position;
    fx_eval_options options;
    fx_eval_environment environment;
    fx_eval_variables *variables;
    fx_linalg_bank *linear_algebra;
    fx_eval_storage *storage;
    const fx_eval_transport *transport;
    fx_number *random_seed;
    const fx_calculus_control *control;
    uint8_t base_radix;
    uint8_t calculus_mode, calculus_token, preflight_mode;
    uint8_t preflight_constant_error;
    uint8_t terminal_operator, table_continuation;
    fx_number secondary, prior_answer;
    fx_eval_status status;
    uint8_t unsupported;
} parser;

static void retain_workspace_source(parser *p)
{
    if (p->transport) {
        size_t begin = p->transport->input_address, end = begin + p->length;
        /* A component stage can replace the source's original terminator.
         * Future token reads remain live within the actual RAM capacity. */
        if (begin < 0x8780 && end > 0x8640) p->length = 65536u - begin;
    }
}

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
    if (p->lookahead_valid && p->position == p->lookahead_position)
        return p->lookahead_token;
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
        if (p->preflight_mode == 2 && status == FX_NUMERIC_OK &&
            ((value->bytes[0] & 15) == 3 || (value->bytes[0] & 15) == 8)) {
            fx_number_zero(value);
            return;
        }
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

static void preflight_failure(parser *p, fx_complex *value)
{
    if (p->preflight_mode == 2 && !p->preflight_constant_error &&
        (p->status == FX_EVAL_MATH || p->status == FX_EVAL_ARGUMENT)) {
        fx_complex_zero(value);
        p->status = FX_EVAL_OK;
    }
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

/* Native cancellation samples see every prior physical bank/variable write. */
static int rich_cancelled(void *userdata)
{
    parser *p = userdata;
    variables_from_storage(p);
    bank_from_storage(p);
    p->equation_used = p->storage->ram[0x8125] & 1;
    return p->control && p->control->cancelled &&
        p->control->cancelled(p->control->userdata);
}

/* Storage allocation/release is already complete. Execute the selected rich
 * numerical leaf once, retaining even partial mutations on errors. */
static void dispatch_staged_rich(parser *p, fx_complex *current,
                                const fx_complex *other, uint8_t selector,
                                uint8_t operation)
{
    fx_eval_rich_context context;
    fx_eval_rich_result result;
    uint8_t *ram = p->storage->ram;
    fx_numeric_status status;
    fx_eval_rich_context_default(&context, ram[0x80f9]);
    context.numeric.exact_math = (ram[0x80f9] & 0x40) && ram[0x8106] &&
        ram[0x810c] != 1 && !(ram[0x80fc] & 0x40) &&
        ram[0x80f5] != 0xed && !(ram[0x8124] & 1);
    context.numeric.display_mode = ram[0x8102];
    context.numeric.digits = ram[0x8103];
    context.cancelled = rich_cancelled;
    context.userdata = p;
    status = fx_eval_rich_dispatch(&result, p->storage, current, other,
                                   selector, &context);
    variables_from_storage(p);
    bank_from_storage(p);
    p->equation_used = ram[0x8125] & 1;
    if (status != FX_NUMERIC_OK) { unsupported(p, operation); return; }
    *current = result.value;
    p->status = (fx_eval_status)result.firmware_status;
    preflight_failure(p, current);
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
        preflight_failure(p, left);
        return 1;
    }
    if (staged.route == FX_EVAL_STORAGE_RICH) {
        dispatch_staged_rich(p, left, &other, staged.operation, native_operation);
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
        p->status = (fx_eval_status)staged.native_status;
        preflight_failure(p, current); return 1;
    }
    if (staged.route == FX_EVAL_STORAGE_RICH) {
        dispatch_staged_rich(p, current, &other, staged.operation, operation);
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

static fx_complex_preparation coordinate_preparation(parser *p);

static void binary(parser *p, fx_complex *left, const fx_complex *right, fx_binary_op op)
{
    fx_complex output = *left;
    if (p->preflight_mode == 1) { fx_complex_zero(left); return; }
    if (p->transport) {
        /*16336 drains this binary reduction after159D0 already decoded
         * the following token. Preserve that token across live pool writes. */
        p->lookahead_token = peek(p);
        p->lookahead_position = p->position;
        p->lookahead_valid = 1;
    }
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
        fx_numeric_status status;
        if (p->storage && !left->imaginary.bytes[0] && !right->imaginary.bytes[0]) {
            /*15FCE selects the scalar arithmetic leaf when both imaginary
             * classifiers return zero, retaining the live SURD workspace. */
            retain_workspace_source(p);
            status = fx_eval_surd_workspace_binary(&output.real, p->storage->ram,
                &left->real, &right->real, 0, 0, op);
            if (status == FX_NUMERIC_OK) {
                uint8_t leaf = output.real.bytes[0] >= 0xf0 ?
                    output.real.bytes[0] & 15u : 0;
                status = fx_complex_dispatch_cleanup(&output, &output, leaf,
                    &context, &firmware_status);
            }
        } else if (p->storage) {
            fx_complex_preparation preparation = coordinate_preparation(p);
            status = fx_complex_dispatch_binary_with_preparation(&output, left,
                right, tokens[op], &context, &firmware_status, &preparation);
        } else status = fx_complex_dispatch_binary(&output, left, right,
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
        fx_numeric_status status = p->storage && exact_math(p) ?
            fx_eval_surd_workspace_binary(&output.real, p->storage->ram,
                &left->real, &right->real, 0, 0, op) :
            fx_number_binary(&output.real, &left->real, &right->real, op);
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
    /*171A0 repeatedly reduces pending groups/functions at a comma until
     * reaching an argument checkpoint or the outer comma syntax guard. */
    if (!peek(p) || peek(p) == ':' ||
        ((p->environment.screen & 0x40) && peek(p) == '=') ||
        peek(p) == ',') return 1;
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
static fx_complex_preparation coordinate_preparation(parser *p);
static fx_numeric_status coordinate_unary_storage(parser *p, fx_complex *out,
    const fx_complex *in, uint8_t token, const fx_complex_dispatch_context *context,
    uint8_t *firmware_status);

static int function_prefix(uint8_t token)
{
    return token == 0x3f || token == 0x5a || token == 0x5b || token == 0x61 || token == 0x62 || token == 0x5d || (token >= 0x69 && token <= 0x6d) || token == 0x63 || token == 0x88 || token == 0xc3 || token == 0x98 || token == 0xa8 || token == 0x68 || (token >= 0x70 && token <= 0x73) ||
           (token >= 0x90 && token <= 0x93) || (token >= 0xa0 && token <= 0xa3) ||
           (token >= 0xb0 && token <= 0xb3) || token == 0xc0 || token == 0xc1 || token == 0xc2;
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
        /*51CA/173FA copies foreign records unchanged. The physical paired
         * derivative lets17258 classify them at the expression boundary. */
        if (p->storage && p->options.calculation_context == 0xc4 &&
            p->calculus_token == 0x6b && header >= 10 && header <= 14) continue;
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
            if (p->preflight_mode == 1) {
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
        if (!exact_math(p) && kind == FX_NUMBER_SURD) {
            if (p->storage) retain_workspace_source(p);
            fx_numeric_status status = p->storage ?
                fx_surd_components_convert_copy(p->storage->ram,
                    components[index], components[index]) :
                fx_number_to_decimal(components[index], components[index]);
            if (status != FX_NUMERIC_OK) {
                unsupported(p, peek(p)); return;
            }
        }
    }
}

/* 1C76C keeps an already rational operand when18212 denies compact-surd
 * recognition. The scalar root operates on numerator and denominator and
 * ordinary rational division retains a perfect rational square root. */
static fx_numeric_status scalar_square_root(parser *p, fx_number *out,
                                            const fx_number *input)
{
    if (p->storage &&
        (exact_math(p) || fx_number_kind(input) != FX_NUMBER_RATIONAL)) {
        retain_workspace_source(p);
        return fx_eval_surd_workspace_sqrt(out, p->storage->ram, input, exact_math(p));
    }
    return fx_eval_scalar_square_root(out, input, exact_math(p));
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

/* Dynamic constant64 dispatches13620: population deviation of physical Y.
 * TABLE keeps this statistical constant available even outside STAT mode. */
static void table_population_y(parser *p, fx_complex *out)
{
    fx_number cells[255*3],sample;
    if(!p->storage){unsupported(p,peek(p));return;}
    const uint8_t *ram=p->storage->ram;
    unsigned columns=ram[0x810e] && !(ram[0x8138]&128) ? 3u : 2u;
    unsigned frequency=ram[0x8109]!=0,width=2u+frequency;
    fx_stats_table table={cells,ram[0x80de],2,(uint8_t)frequency};
    for(unsigned row=0;row<table.rows;row++){
        fx_number_zero(&cells[width*row]);
        memcpy(cells[width*row+1].bytes,ram+0x82ee + 10*(columns*row+1),10);
        if(frequency)memcpy(cells[width*row+2].bytes,
            ram+0x82ee + 10*(columns*row+(ram[0x80fa]==1 ? 1u : 2u)),10);
        /*1CEC0/real arithmetic classify foreign A..E table headers as
         * Math3. They do not become a ROM-addressable rich reference. */
        unsigned header=cells[width*row+1].bytes[0]>>4;
        if(header>=10 && header<=14){fx_number_error(&out->real,3);p->status=FX_EVAL_MATH;return;}
        if(frequency){
            header=cells[width*row+2].bytes[0]>>4;
            if(header>=10 && header<=14){fx_number_error(&out->real,3);p->status=FX_EVAL_MATH;return;}
        }
    }
    int status=fx_stats_deviations(&out->real,&sample,&table,1);
    if(status<0){unsupported(p,peek(p));return;}
    if(out->real.bytes[0]>=0xf0)p->status=FX_EVAL_MATH;
}

static void primary(parser *p, fx_complex *out)
{
    uint8_t token = peek(p);
    /* Native TABLE continuation rejects calculus and coordinate prefixes
     * before argument admission (16B44/16B54). */
    if (p->table_continuation && (token == 0x5d ||
        (token >= 0x69 && token <= 0x6d))) {
        p->status = FX_EVAL_SYNTAX; return;
    }
    /*16BA8 rejects a restricted RanInt prefix before its operator push. */
    if (token == 0xc2 && (p->environment.screen & 0x40)) {
        p->status = FX_EVAL_SYNTAX;
        return;
    }
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
    preflight_failure(p, out);
    p->operator_depth = saved_depth;
    p->group_depth = saved_group_depth;
}

/* The caller owns the full seed. Storage callbacks share the physical seed
 * cell, and typed callbacks share one pointer for the complete evaluation.
 * Publication happens at the leaf, before later reductions or errors. */
static void random_value(parser *p, fx_complex *out,
                         const fx_complex *lower, const fx_complex *upper)
{
    fx_number seed;
    if (p->storage) memcpy(seed.bytes, p->storage->ram + 0x821c, 10);
    else seed = *p->random_seed;
    fx_random_result result;
    fx_numeric_status status = lower ?
        fx_random_integer(&result, &seed, &lower->real, &upper->real) :
        fx_random_next(&result, &seed);
    if (status != FX_NUMERIC_OK) { unsupported(p, lower ? 0xc2 : 0x8c); return; }
    if (p->storage) memcpy(p->storage->ram + 0x821c, result.seed.bytes, 10);
    else *p->random_seed = result.seed;
    p->status = (fx_eval_status)result.firmware_status;
    if (p->preflight_mode == 2 &&
        (p->status == FX_EVAL_MATH || p->status == FX_EVAL_ARGUMENT)) {
        fx_complex_zero(out);
        p->status = FX_EVAL_OK;
    } else if (p->status == FX_EVAL_OK) {
        out->real = result.value;
        fx_number_zero(&out->imaginary);
        accept_operation(p, &out->real, FX_NUMERIC_OK);
    }
}

static void random_integer(parser *p, fx_complex *out)
{
    fx_complex lower, upper;
    ++p->position; /* The prefix includes its opening parenthesis. */
    expression(p, &lower, 0);
    if (p->status != FX_EVAL_OK) return;
    if (peek(p) != ',') { p->status = FX_EVAL_SYNTAX; return; }
    /*1718C retains the first argument at the comma. Stack failure occurs
     * after evaluating that argument, before consuming or evaluating upper. */
    if (p->value_depth >= 10) { p->status = FX_EVAL_STACK; return; }
    unsigned width = p->options.calculation_context == 0xc4 ? 2u : 1u;
    p->value_depth += width;
    ++p->position;
    expression(p, &upper, 0);
    p->value_depth -= width;
    if (p->status != FX_EVAL_OK) return;
    uint8_t delimiter = peek(p);
    if (store_token(p) && (p->environment.screen & 0x80)) {
        p->status = FX_EVAL_SYNTAX;
        return;
    }
    /*1708E store-follow validation precedes reduction while a function is
     * unfinished. A completed ')' has already dispatched its leaf. */
    if (delimiter != ')' && delimiter != ',' && !omitted_closing(p)) {
        p->status = FX_EVAL_SYNTAX;
        return;
    }
    /*16336/16A14 tests the second argument first, before native13EBE. */
    if (p->preflight_mode != 1 && (!operand_admitted(p, &upper, 7) ||
                         !operand_admitted(p, &lower, 7))) {
        if (p->preflight_mode == 2) {
            fx_complex_zero(out);
            if (delimiter == ')') ++p->position;
        } else p->status = FX_EVAL_MATH;
        return;
    }
    random_value(p, out, &lower, &upper);
    if (p->status != FX_EVAL_OK) return;
    if (delimiter == ')') ++p->position;
    /* A remaining comma belongs to the enclosing operator context. Its
     * pending reduction can consume this result as that context's argument.
     * At top level the ordinary final delimiter check reports Syntax2. */
}

static void stored_y_mean(parser *p, fx_complex *out)
{
    int status;
    if (p->storage)
        status = fx_stats_mean_y_prepared(&out->real,
            p->storage->ram, p->storage->ram_size);
    else {
        fx_number_error(&out->real, 3);
        status = 3;
    }
    if (status < 0) unsupported(p, 0x8a);
    else {
        p->status = (fx_eval_status)status;
        /*16FF6 returns a dynamic constant's error directly. It never passes
         * through the16A64 arithmetic error-to-zero preflight policy. Keep
         * this failure while unwinding any enclosing function/group. */
        if (status && p->preflight_mode == 2) p->preflight_constant_error = 1;
    }
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
    } else if (token == 0xac && p->options.calculation_context == 0x88) {
        table_population_y(p,out);
        if(p->status==FX_EVAL_OK)++p->position;
    } else if (fx_decode_evaluator_token(token, p->options.calculation_context).kind == 6 &&
               (fx_decode_evaluator_token(token, p->options.calculation_context).value == 48 ||
                fx_decode_evaluator_token(token, p->options.calculation_context).value == 43 ||
                fx_decode_evaluator_token(token, p->options.calculation_context).value == 46) &&
               p->storage && !p->storage->ram[0x80de]) {
        /* Dynamic X population deviation13418 and moments135A4/13544 admit an
         * empty table as Math3 before persistent cache publication. */
        fx_number_error(&out->real, 3);
        p->status = FX_EVAL_MATH;
        if (p->preflight_mode == 2) p->preflight_constant_error = 1;
    } else if (fx_decode_evaluator_token(token, p->options.calculation_context).kind == 6 &&
               (fx_decode_evaluator_token(token, p->options.calculation_context).value == 50 ||
                fx_decode_evaluator_token(token, p->options.calculation_context).value == 51)) {
        /*133E2/133B2 compute X cubes/fourths without persistent cache writes.
         * Dynamic constant errors bypass preflight's arithmetic normalization. */
        fx_evaluator_token decoded = fx_decode_evaluator_token(token, p->options.calculation_context);
        int status = p->storage ?
            fx_stats_higher_x_prepared(&out->real, p->storage->ram,
                p->storage->ram_size, decoded.value == 50 ? 3u : 4u) :
            FX_NUMERIC_UNIMPLEMENTED;
        if (status < 0) unsupported(p, token);
        else {
            p->status = (fx_eval_status)status;
            if (p->preflight_mode == 2 && status) p->preflight_constant_error = 1;
            if (!status) ++p->position;
        }
    } else if (token == 0x8a) {
        stored_y_mean(p, out);
        if (p->status == FX_EVAL_OK) ++p->position;
    } else if (token == 0x8c) {
        /*17006 guards the dynamic constant before sampling it. */
        if (p->environment.screen & 0x40) p->status = FX_EVAL_SYNTAX;
        else { ++p->position; random_value(p, out, NULL, NULL); }
    } else if (token == 0xc2) {
        random_integer(p, out);
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
        if (p->status == FX_EVAL_OK && p->preflight_mode != 1) {
            unsigned mask = token == 0xc0 || token == 0xc1 || token == 0x5a || token == 0x5b ? 0 :
                token == 0x61 || token == 0x62 || token == 0x63 ||
                token == 0x88 || token == 0xc3 || token == 0xb3 ? 255 : 7;
            /*16336 admits an argument at its delimiter, before the close
             * is consumed. Logbase checks the second argument first. */
            if ((has_base && !operand_admitted(p, &second_argument, 7)) ||
                !operand_admitted(p, out, mask)) {
                if (p->preflight_mode == 2) {
                    fx_complex_zero(out);
                    if (peek(p) == ')') ++p->position;
                } else p->status = FX_EVAL_MATH;
                --p->depth;
                return;
            }
        }
        if (p->status == FX_EVAL_OK) {
            if (peek(p) == ')') { ++p->position; closed = 1; }
            else if (!omitted_closing(p)) p->status = FX_EVAL_SYNTAX;
        }
        if (p->status == FX_EVAL_OK) {
            if (p->preflight_mode == 1) { fx_complex_zero(out); }
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
                    (p->storage && (token == 0x63 || token == 0xc3 || token == 0x98) ?
                        coordinate_unary_storage(p, &output, out, token, &context, &firmware_status) :
                        fx_complex_dispatch_unary(&output, out, token, &context, &firmware_status));
                accept_complex_operation(p, out, &output, status, firmware_status);
            } else {
                fx_numeric_status status;
                if (token == 0x61 || token == 0x62) {
                    unsigned native_status = 0;
                    fx_base_word_context context = {p->base_radix,
                        p->options.calculation_context, p->options.calculation_context};
                    status = fx_base_word_unary(&output.real, &out->real, &context,
                        token == 0x61 ? FX_BASE_NOT : FX_BASE_NEGATE, &native_status);
                    if (status == FX_NUMERIC_OK && native_status) {
                        p->status = (fx_eval_status)native_status;
                        if (closed) --p->position;
                        --p->depth;
                        return;
                    }
                }
                else if (token == 0x63) {
                    /* COMP selects scalar1C312, avoiding the CMPLX norm.
                     * Classification precedes clearing the decimal marker. */
                    uint8_t classification;
                    fx_complex_preparation preparation = coordinate_preparation(p);
                    status = p->storage ? preparation.classify(&classification,
                        &out->real, preparation.userdata) :
                        fx_scalar_numeric_classify(&classification, &out->real);
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
                    {
                    fx_complex_preparation preparation = coordinate_preparation(p);
                    status = p->storage ? fx_complex_argument_with_preparation(&output, out,
                        (fx_angle_unit)(p->options.angle_unit-4), &preparation) :
                        fx_complex_argument(&output, out, (fx_angle_unit)(p->options.angle_unit-4));
                }
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
            if ((p->status == FX_EVAL_MATH || p->status == (fx_eval_status)9) && closed) --p->position;
        }
    } else if (token == '-' || token == '+' || token == 0x60) {
        fx_complex output = *out;
        ++p->position;
        expression(p, out, 40); /* powers bind more tightly than unary negation */
        if (p->status == FX_EVAL_OK && token != '+') {
            if (p->preflight_mode == 1) { fx_complex_zero(out); }
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
        if (decoded.kind == 2 || decoded.kind == 3 || decoded.kind == 8 || decoded.kind == 15 ||
            decoded.kind == 10)
            p->status = FX_EVAL_SYNTAX;
        else unsupported(p, token);
    }
    --p->depth;
}

static int implicit_start(uint8_t token, uint8_t context)
{
    fx_evaluator_token decoded = fx_decode_evaluator_token(token, context);
    return token == 0x8a || token == 0x8c || variable_slot(token, context) >= 0 || token == '(' || token == 0x80 || token == 0x81 || token == 0x82 || function_prefix(token) ||
           (decoded.kind == 6 && (decoded.value < 40 || decoded.value == 48 || decoded.value == 43 || decoded.value == 46 || decoded.value == 50 || decoded.value == 51)) || decoded.kind == 7 ||
           (context == 2 && token >= 0x50 && token <= 0x53);
}

static void sexagesimal(parser *p, fx_complex *out)
{
    fx_number components[3];
    size_t count = 1;
    fx_complex output = *out;
    if (p->preflight_mode != 1 && !real_only_admitted(p, out)) {
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
    if (p->preflight_mode == 1) { fx_complex_zero(out); return; }
    fx_numeric_status status = fx_number_sexagesimal(&output.real, components, count);
    accept_real_result(p, out, &output, status);
}

static void conversion(parser *p, fx_complex *out, fx_evaluator_token decoded)
{
    uint8_t token = peek(p);
    if (p->preflight_mode != 1 && !real_only_admitted(p, out)) {
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
    if (p->preflight_mode == 1) { fx_complex_zero(out); return; }
    fx_complex output = *out;
    fx_numeric_status status = fx_number_unit_convert(&output.real, &out->real, decoded.value - 55);
    accept_real_result(p, out, &output, status);
    if (p->status == FX_EVAL_MATH) --p->position;
}

static fx_numeric_status coordinate_square_root(fx_number *out,
    const fx_number *input, int exact, void *userdata)
{
    parser *p = userdata;
    fx_eval_storage *storage = p->storage;
    retain_workspace_source(p);
    return fx_eval_surd_workspace_sqrt(out, storage->ram, input, exact);
}

static fx_numeric_status coordinate_decimal_prepare(fx_number *out,
    const fx_number *input, void *userdata)
{
    parser *p = userdata;
    fx_eval_storage *storage = p->storage;
    retain_workspace_source(p);
    return fx_number_kind(input) == FX_NUMBER_SURD ?
        fx_surd_components_convert_copy(storage->ram, out, input) :
        fx_number_to_decimal(out, input);
}

static fx_numeric_status coordinate_classify(uint8_t *classification,
    const fx_number *input, void *userdata)
{
    fx_number decimal;
    fx_numeric_status status;
    parser *p = userdata;
    fx_eval_storage *storage = p->storage;
    retain_workspace_source(p);
    if ((input->bytes[0] & 0xf0) == 0x80 && input->bytes[9] &&
        input->bytes[8] + input->bytes[9] == 7) {
        status = fx_surd_components_convert_copy(storage->ram, &decimal, input);
        if (status != FX_NUMERIC_OK) return status;
        /*1CD56 gives17576 the actual numerical destination poolslot0. */
        memcpy(storage->ram + 0x8640, decimal.bytes, 10);
        *classification = decimal.bytes[9] >= 4 ? 2 : 4;
        return FX_NUMERIC_OK;
    }
    return fx_scalar_numeric_classify(classification, input);
}

static fx_numeric_status coordinate_binary_prepare(fx_number *out,
    const fx_number *left, const fx_number *right,
    fx_binary_op operation, void *userdata)
{
    parser *p = userdata;
    fx_eval_storage *storage = p->storage;
    retain_workspace_source(p);
    return fx_eval_surd_workspace_binary(out, storage->ram,
        left, right, 0, 0, operation);
}

static fx_complex_preparation coordinate_preparation(parser *p)
{
    const fx_complex_preparation preparation = {coordinate_square_root,
        coordinate_decimal_prepare, coordinate_classify,
        coordinate_binary_prepare, p};
    return preparation;
}

static fx_numeric_status coordinate_unary_storage(parser *p, fx_complex *out,
    const fx_complex *in, uint8_t token, const fx_complex_dispatch_context *context,
    uint8_t *firmware_status)
{
    fx_complex result;
    fx_complex_preparation preparation = coordinate_preparation(p);
    fx_numeric_status status = token == 0x63 ?
        fx_complex_magnitude_with_preparation(&result, in, context->exact_math, &preparation) :
        token == 0x98 ? fx_complex_sqrt_with_preparation(&result, in,
            context->exact_math, &preparation) :
        fx_complex_argument_with_preparation(&result, in,
            (fx_angle_unit)(context->angle_unit-4), &preparation);
    uint8_t leaf = 0;
    if (status == FX_NUMERIC_OK)
        status = fx_complex_firmware_status(&leaf, token == 0x63 ?
            FX_COMPLEX_MAGNITUDE_RETURN : token == 0x98 ? FX_COMPLEX_SQRT_RETURN :
            FX_COMPLEX_ARGUMENT_RETURN, in, &result);
    return status == FX_NUMERIC_OK ?
        fx_complex_dispatch_cleanup(out, &result, leaf, context, firmware_status) : status;
}

/* Physical Rec preserves each exact multiplication's live SURD workspace.
 * These writes occur while each coordinate is computed, before the next
 * trigonometric value and multiplication are evaluated. */
static fx_numeric_status coordinates_from_polar_storage(parser *p,
    fx_complex *out, const fx_complex *in, fx_angle_unit unit)
{
    fx_complex source = *in, result;
    fx_number sine, cosine, decimal;
    uint8_t classification;
    fx_numeric_status status;
    if (source.real.bytes[0] >= 0xf0 || source.imaginary.bytes[0] >= 0xf0) {
        fx_number_error(&out->real, 3); fx_number_error(&out->imaginary, 3);
        return FX_NUMERIC_OK;
    }
    source.real.bytes[0] &= (uint8_t)~0x40;
    /*182EC clears the marker, then CCF6 classifies the original radius.
     * Opposing-sign SURD classification owns its slot0 conversion commit. */
    status = coordinate_classify(&classification, &source.real, p);
    if (status != FX_NUMERIC_OK) return status;
    if (classification == 2) {
        fx_number_error(&out->real, 3); fx_number_error(&out->imaginary, 3);
        return FX_NUMERIC_OK;
    }
    /*6268/6272 each prepare their own copied angle through17470 before
     * evaluating sine/cosine. Preserve the original angle for the second. */
    status = coordinate_decimal_prepare(&decimal, &source.imaginary, p);
    if (status == FX_NUMERIC_OK)
        status = fx_trig_evaluate(&sine, &decimal, FX_SINE, unit, exact_math(p), 0);
    if (status == FX_NUMERIC_OK)
        status = fx_eval_surd_workspace_binary(&result.imaginary, p->storage->ram,
            &sine, &source.real, 0, 0, FX_MULTIPLY);
    if (status == FX_NUMERIC_OK)
        status = coordinate_decimal_prepare(&decimal, &source.imaginary, p);
    if (status == FX_NUMERIC_OK)
        status = fx_trig_evaluate(&cosine, &decimal, FX_COSINE, unit, exact_math(p), 0);
    if (status == FX_NUMERIC_OK)
        status = fx_eval_surd_workspace_binary(&result.real, p->storage->ram,
            &source.real, &cosine, 0, 0, FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) return status;
    if (result.real.bytes[0] >= 0xf0 || result.imaginary.bytes[0] >= 0xf0) {
        fx_number_error(&result.real, 3); fx_number_error(&result.imaginary, 3);
    }
    *out = result;
    return FX_NUMERIC_OK;
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
    /* The closing token was read by the delimiter reduction before16168
     * publishes X/Y. Its byte may belong to those physical destinations. */
    int closed = peek(p) == ')';
    if (p->preflight_mode == 1) fx_complex_zero(out);
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
        fx_complex_preparation preparation = coordinate_preparation(p);
        fx_numeric_status status = token == 0x6c ?
            (p->storage ? fx_complex_to_polar_with_preparation(&converted, &operands,
                unit, exact_math(p), &preparation) :
                fx_complex_to_polar(&converted, &operands, unit, exact_math(p))) :
            (p->storage ?
                coordinates_from_polar_storage(p, &converted, &operands, unit) :
                          fx_complex_from_polar(&converted, &operands, unit, exact_math(p)));
        if (status != FX_NUMERIC_OK) { unsupported(p, token); return; }
        uint8_t native_status = 0;
        status = fx_complex_firmware_status(&native_status,
            token == 0x6c ? FX_COMPLEX_TO_POLAR_RETURN : FX_COMPLEX_FROM_POLAR_RETURN,
            &operands, &converted);
        if (status != FX_NUMERIC_OK) { unsupported(p, token); return; }
        if (native_status) { p->status = (fx_eval_status)native_status; return; }
        /*16168 stores raw coordinates before16562 cleanup or later syntax
         * validation. COMP leaves the imaginary bank records untouched. */
        const fx_number *coordinates[] = {&converted.real, &converted.imaginary};
        for (unsigned index = 0; index < 2; ++index) {
            unsigned slot = FX_VARIABLE_X + index;
            p->variables->values[slot][0] = *coordinates[index];
            if (p->storage)
                memcpy(p->storage->ram + 0x8226 + 10 * slot,
                       coordinates[index]->bytes, 10);
            if (p->options.calculation_context == 0xc4) {
                fx_number_zero(&p->variables->values[slot][1]);
                if (p->storage)
                    memcpy(p->storage->ram + 0x8408 + 10 * slot,
                           p->variables->values[slot][1].bytes, 10);
            }
        }
        /* A physical source is zero-terminated live RAM. Publication can
         * replace its former terminator; retain the bounded RAM capacity
         * when the supplied source interval overlaps the written banks. */
        if (p->transport) {
            size_t begin = p->transport->input_address, end = begin + p->length;
            if ((begin < 0x828a && end > 0x8276) ||
                (p->options.calculation_context == 0xc4 &&
                 begin < 0x846c && end > 0x8458))
                p->length = 65536u - begin;
        }
        p->secondary = converted.imaginary;
        fx_complex_zero(&active);
        active.real = converted.real;
        accept_real_result(p, out, &active, FX_NUMERIC_OK);
        if (p->status != FX_EVAL_OK) return;
    }
    if (closed) ++p->position;
    else if (!omitted_closing(p)) p->status = FX_EVAL_SYNTAX;
}

static void polar_operator(parser *p, fx_complex *out, const fx_complex *right)
{
    fx_complex operands, converted;
    if (p->preflight_mode == 1) { fx_complex_zero(out); return; }
    if (!real_only_admitted(p, right) || !real_only_admitted(p, out)) {
        p->status = FX_EVAL_MATH; return;
    }
    if (p->options.angle_unit < 4 || p->options.angle_unit > 6) {
        unsupported(p, 0xaf); return;
    }
    operands.real = out->real;
    operands.imaginary = right->real;
    fx_numeric_status status = p->storage ?
        coordinates_from_polar_storage(p, &converted, &operands,
            (fx_angle_unit)(p->options.angle_unit - 4)) :
        fx_complex_from_polar(&converted, &operands,
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
    if (p->preflight_mode == 1) { fx_complex_zero(out); return; }
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
    if (p->preflight_mode == 1) { fx_complex_zero(out); return; }
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
    if (p->preflight_mode == 1) { fx_complex_zero(out); return; }
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
    for (;;) {
        preflight_failure(p, out);
        if (p->status != FX_EVAL_OK) return;
        uint8_t token = peek(p);
        fx_evaluator_token decoded = fx_decode_evaluator_token(token, p->options.calculation_context);
        /*1708E validates the terminal store and its following delimiter
         * before reducing pending numerical operators. The read consumes
         * an invalid following token position, but never commits a store. */
        if (decoded.kind == 8 && decoded.value <= 11) {
            if (p->environment.screen & 0x80) {
                p->status = FX_EVAL_SYNTAX;
                return;
            }
            uint8_t next = p->position + 1 < p->length ? p->input[p->position + 1] : 0;
            if (next && next != ':') {
                ++p->position;
                p->status = FX_EVAL_SYNTAX;
                return;
            }
        }
        /* A digit cannot begin implicit multiplication after an existing
         * value; an unmatched ')' is rejected before a pending reduction. */
        if ((token >= '0' && token <= '9') || token == '.' ||
            (token == ')' && !p->group_depth)) {
            p->status = FX_EVAL_SYNTAX;
            return;
        }
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
        if (decoded.kind == 3 && decoded.value == 54 && p->storage &&
            !p->storage->ram[0x80de] && p->preflight_mode != 1) {
            /*131FC's second quadratic inverse prediction queries its empty
             * dataset before any persistent cache commit. Keep its token as
             * the error cursor, matching ordinary16336 postfix admission. */
            if (70 < minimum) return;
            p->status = FX_EVAL_MATH;
            return;
        }
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
            if (p->preflight_mode != 1 && !operand_admitted(p, out,
                    token >= 0x75 && token <= 0x77 ? 1 : 7)) {
                p->status = FX_EVAL_MATH; return;
            }
            fx_complex output = *out;
            fx_numeric_status status;
            ++p->position;
            if (p->preflight_mode != 1 && stage_unary(p, out, decoded.value)) {
                if (p->status > FX_EVAL_CANCELLED && p->status < 32) --p->position;
                continue;
            }
            if (p->preflight_mode == 1) { fx_complex_zero(out); continue; }
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
        } else if ((p->options.calculation_context == 0x88 || p->options.calculation_context == 2) && token == 0x2f) {
            precedence = 30; op = FX_MULTIPLY;
        } else if (token == 0x9e) {
            /*1673E..16754 gives operation47 rank6, above rank5 product. */
            precedence = 22; op = FX_MULTIPLY;
        } else if (token == 0xbe || token == 0xbf || token == 0xaf) {
            precedence = 25; op = FX_MULTIPLY;
        } else if (implicit_start(token, p->options.calculation_context)) {
            precedence = 30; op = FX_MULTIPLY; implicit = 1;
        } else if (token == 0xae) {
            precedence = 60; op = FX_DIVIDE;
        } else if (token == 0x5e || token == 0x9f) {
            precedence = 65; op = FX_MULTIPLY;
        } else if (token == 0x97) {
            if ((p->options.calculation_context == 6 || p->options.calculation_context == 7) &&
                !p->operator_depth) p->status = FX_EVAL_SYNTAX;
            else unsupported(p, token);
            return;
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
        if (token == 0xae && p->preflight_mode != 1 && !operand_admitted(p, out, 3)) {
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
        int reduction_ran = p->status == FX_EVAL_OK;
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
        } else if (p->status == FX_EVAL_OK && token == 0x9e) {
            /*16336 admits both rich arguments before staging operation47. */
            if (!operand_admitted(p, &right, 0) || !operand_admitted(p, out, 0))
                p->status = FX_EVAL_MATH;
            else if (!stage_binary(p, out, &right, 47)) unsupported(p, token);
        } else if (p->status == FX_EVAL_OK && token == 0xaf) {
            polar_operator(p, out, &right);
        } else if (p->status == FX_EVAL_OK && token == 0x5f) {
            quotient_remainder(p, out, &right);
        } else if (p->status == FX_EVAL_OK && token == 0xae) {
            if (peek(p) == 0xae) {
                fx_complex denominator;
                if (p->preflight_mode != 1 && !operand_admitted(p, &right, 3)) {
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
                if (p->status == FX_EVAL_OK && p->preflight_mode != 1 &&
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
            if (p->preflight_mode == 1) {
                fx_complex_zero(out); p->operator_depth = saved_operator_depth;
                p->value_depth -= p->options.calculation_context == 0xc4 ? 2 : 1; continue;
            }
            if (!operand_admitted(p, &right, 7) || !operand_admitted(p, out, 7)) {
                p->status = FX_EVAL_MATH;
            } else {
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
            }
        } else if (p->status == FX_EVAL_OK) binary(p, out, &right, op);
        /*159D0 consumes the following token before16682 reduces a pending
         * binary operator.1723E retains that read for cancellation1 when
         * the consumed byte is nonzero; an input terminator is rolled back.
         * A propagated child cancellation has already retained its read. */
        if (reduction_ran && p->status == FX_EVAL_CANCELLED && peek(p)) ++p->position;
        p->operator_depth = saved_operator_depth;
        p->value_depth -= p->options.calculation_context == 0xc4 ? 2 : 1;
    }
}

typedef struct {
    parser *parent;
    size_t body_start, body_end, callback_position;
    int64_t next_x;
    fx_eval_status host_failure;
    uint8_t unsupported_token, finite_series, sampled, device_started;
    uint32_t cancellation_checks;
    uint16_t *physical_cursor;
    uint16_t error_sink;
    uint8_t physical_integral, paired_derivative;
    fx_number sample_imaginary;
} calculus_call;

static int calculus_cancelled(void *userdata)
{
    calculus_call *call = userdata;
    parser *p = call->parent;
    /* Series04330/04426 installs the next X before5550 polls cancellation.
     * Quadrature/Richardson polls retain the most recently sampled X. */
    if (call->finite_series)
        (void)fx_decimal_from_integer(&p->variables->values[FX_VARIABLE_X][0], call->next_x++);
    if (p->storage) {
        fx_platform platform = {p->storage->rom, p->storage->rom_size,
                                p->storage->ram, 0, FX_MEMORY_OK};
        fx_eval_rich_context context;
        if (call->finite_series && !call->device_started) {
            /* Series04316/0440A enter054E6 directly. The public UI helper
             * has the054E0 bit4 guard; satisfy the unconditional entry first. */
            if (p->storage->ram[0x80fc] & 16u) p->storage->ram[0xf031] = 6;
            fx_display_port_sleep(&platform);
            call->device_started = 1;
        }
        variables_to_storage(p);
        fx_eval_rich_context_default(&context, p->options.calculation_context);
        context.cancelled = rich_cancelled;
        context.userdata = p;
        return fx_eval_rich_poll(p->storage, &call->cancellation_checks, &context);
    }
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

static void calculus_expression_finish(parser *p, fx_complex *value)
{
    if (p->status == FX_EVAL_OK &&
        (value->real.bytes[0] >= 0x90 ||
         (value->real.bytes[0] >= 0x60 && value->real.bytes[0] < 0x80))) {
        /*17258 also completes preflight and argument171EA entries. */
        if (p->environment.screen != 1) p->status = FX_EVAL_SYNTAX;
        else continuous_finish(p, &value->real);
    }
    if (p->storage && p->calculus_token == 0x6b &&
        p->calculus_mode != 1 && p->status > FX_EVAL_OK) {
        /*04AFA establishes85B4 before preflight/argument171EA calls.
         *17250 publishes actual expression errors here, before point/run
         * staging. Later driver-level comma/tolerance guards do not. */
        fx_number error;
        fx_number_error(&error, (unsigned)p->status);
        memcpy(p->storage->ram + 0x85b4, error.bytes, 10);
    }
}

/*169C0 and CDE4 retain EA+ word alignment. The first eight-byte store
 * uses the requested address; its final word starts at the next even EA. */
static void physical_record_store(fx_eval_storage *storage, uint16_t address,
                                  const fx_number *value)
{
    memcpy(storage->ram + address, value->bytes, 8);
    memcpy(storage->ram + address + 8u - (address & 1u), value->bytes + 8, 2);
}

/*D142 publishes the secondary field in the opposite physical order:
 * its first word uses the supplied address, followed by an aligned eight
 * byte tail. The immutable record keeps overlapping stores deterministic. */
static void physical_secondary_store(fx_eval_storage *storage, uint16_t address,
                                      const fx_number *value)
{
    memcpy(storage->ram + address, value->bytes, 2);
    memcpy(storage->ram + address + 2u - (address & 1u), value->bytes + 2, 8);
}

static void integral_publish_x(const fx_number *x, void *userdata)
{
    calculus_call *call = userdata;
    parser *p = call->parent;
    /*522A scalar publication retains the imaginary record in these modes. */
    memcpy(p->storage->ram + 0x8276, x->bytes, 10);
    variables_from_storage(p);
    bank_from_storage(p);
}

static void integral_publish_x_c4(const fx_complex *x, void *userdata)
{
    calculus_call *call = userdata;
    parser *p = call->parent;
    memcpy(p->storage->ram + 0x8276, &x->real, 10);
    memcpy(p->storage->ram + 0x8458, &x->imaginary, 10);
    variables_from_storage(p);
    bank_from_storage(p);
}

/* The paired derivative leaf has already published physical X according
 * to live80F9. This hook refreshes views without repeating its transfer. */
static void derivative_refresh_x_c4(const fx_complex *x, void *userdata)
{
    calculus_call *call = userdata;
    (void)x;
    variables_from_storage(call->parent);
    bank_from_storage(call->parent);
}

static void integral_callback_context(uint16_t sink, uint16_t *cursor, void *userdata)
{
    calculus_call *call = userdata;
    call->error_sink = sink;
    call->physical_cursor = cursor;
}

static fx_numeric_status calculus_evaluate(fx_number *out, const fx_number *x, void *userdata)
{
    calculus_call *call = userdata;
    parser callback = *call->parent;
    fx_complex value;
    if ((call->physical_integral || call->paired_derivative) && callback.transport &&
        callback.transport->before_sample)
        callback.transport->before_sample(callback.storage,
            (uint16_t)(callback.transport->input_address + call->body_start),
            call->error_sink, callback.transport->userdata);
    if (call->paired_derivative)
        callback.options.calculation_context = callback.storage->ram[0x80f9];
    callback.position = call->body_start;
    callback.length = call->body_end;
    /*171EA starts a fresh decoder stream for every sample. A token cached
     * by the outer argument scan belongs to that scan, not this body view. */
    callback.lookahead_valid = 0;
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
    callback.preflight_mode = 0;
    if (callback.storage) {
        /* Fixed calculus stores overlap Mat/Vct slots7/8. Refresh before
         * body evaluation, so the typed view observes current physical RAM. */
        variables_from_storage(&callback);
        bank_from_storage(&callback);
    }
    if (!call->physical_integral && !call->paired_derivative) {
        callback.variables->values[FX_VARIABLE_X][0] = *x;
        variables_to_storage(&callback); /*522A publishes local scalar X. */
    }
    expression(&callback, &value, 0);
    call->callback_position = callback.position;
    call->sampled = 1;
    if (call->physical_cursor)
        *call->physical_cursor = (uint16_t)(callback.transport->input_address +
                                           callback.position + 1u);
    if (callback.status == FX_EVAL_OK && peek(&callback)) callback.status = FX_EVAL_SYNTAX;
    calculus_expression_finish(&callback, &value);
    if (callback.status == FX_EVAL_OK && call->finite_series && callback.storage &&
        (value.real.bytes[0] & 0xf0u) == 0x60) {
        fx_rational fraction;
        if (fx_rational_decode(&fraction, &value.real) != FX_NUMERIC_OK) {
            fx_number converted;
            fx_numeric_status status = fx_raw_fraction_convert(&converted, &value.real);
            /* SUM04448 and PRODUCT04354 send the reference to scalar
             * rational arithmetic, whose zero denominator publishes F3.
             * This error-only recovery is equivalent for the proven finite
             * witnesses; it does not replay native arithmetic order.
             * A finite non-error conversion still requires an ordered proof. */
            if (status == FX_NUMERIC_OK && converted.bytes[0] >= 0xf0)
                fx_number_error(&value.real, 3);
            else unsupported(&callback, callback.calculus_token);
        }
    }
    call->sample_imaginary = value.imaginary;
    if (callback.status < 0) {
        call->host_failure = callback.status;
        call->unsupported_token = callback.unsupported;
        return FX_NUMERIC_UNIMPLEMENTED;
    }
    if (callback.status) {
        fx_number_error(out, (unsigned)callback.status);
        /*17250 writes actual evaluator errors at inherited ER8. The
         * quadrature pair's ROM node sink is immutable and rejects writes. */
        if ((call->physical_integral || call->paired_derivative) && callback.storage && call->error_sink >= 0x8000 &&
            call->error_sink <= 65526u)
            physical_record_store(callback.storage, call->error_sink, out);
    }
    else *out = value.real;
    if (callback.calculus_token == 0x6a || callback.calculus_token == 0x6b)
        return (fx_numeric_status)(callback.status ? FX_CALCULUS_EVALUATION_ERROR : FX_CALCULUS_EVALUATION_OK);
    return FX_NUMERIC_OK;
}

static fx_numeric_status calculus_evaluate_c4(fx_complex *out, const fx_complex *x, void *userdata)
{
    calculus_call *call = userdata;
    fx_numeric_status status = calculus_evaluate(&out->real, &x->real, userdata);
    out->imaginary = call->sample_imaginary;
    return status;
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
    int closing_consumed = 0;
    int lower_comma_consumed = 0;
    int upper_comma_consumed = 0;
    int physical_derivative = p->storage && token == 0x6b;
    int physical_integral = p->storage && p->transport && token == 0x6a;
    int paired_integral = physical_integral && p->options.calculation_context == 0xc4;
    int paired_derivative = physical_derivative && p->options.calculation_context == 0xc4;
    int paired_series_preflight = p->storage && p->options.calculation_context == 0xc4 &&
        (token == 0x69 || token == 0x5d);
    fx_complex paired_result;
    fx_complex_zero(&paired_result);
    call.physical_integral = (uint8_t)physical_integral;
    call.paired_derivative = (uint8_t)paired_derivative;
    call.error_sink = paired_derivative ? 0x85b4u :
        p->transport ? p->transport->output_address : 0;
    fx_integral_storage integral_storage = {
        p->storage ? p->storage->ram : NULL,
        p->storage ? p->storage->ram_size : 0
    };
    unsigned integral_native_status = 0;
    uint16_t integral_cursor = 0;
    fx_derivative_storage derivative_storage = {
        p->storage ? p->storage->ram : NULL,
        p->storage ? p->storage->ram_size : 0
    };
    fx_numeric_status derivative_preparation = FX_NUMERIC_OK;
    unsigned derivative_native_status = 0;
    if (p->calculus_mode) { p->status = FX_EVAL_SYNTAX; return; }
    if (p->options.calculation_context != 0xc1 &&
        !(p->storage && (p->options.calculation_context == 6 || p->options.calculation_context == 7 ||
            (p->options.calculation_context == 0x88 && !p->table_continuation))) &&
        !paired_integral && !paired_derivative && !paired_series_preflight) {
        unsupported(p, token); return;
    }
    fx_complex_zero(&saved_x);
    if (paired_derivative) p->calculus_token = token;
    load_variable(p, &saved_x, FX_VARIABLE_X);
    if (p->status != FX_EVAL_OK) return;
    ++p->position;
    p->calculus_token = token;
    call.body_start = p->position;
    p->calculus_mode = 255;
    p->preflight_mode = 2;
    p->options.math_output = 0;
    /* Native R6=FF evaluates the preflight expression, including dynamic
     * constants.16A64 turns numerical3/8 into zero and continues syntax
     * validation; seed writes already made by13DB8 remain committed. */
    expression(p, &ignored, 0);
    calculus_expression_finish(p, &ignored);
    if (p->status != FX_EVAL_OK) goto restore;
    if (peek(p) != ',') {
        /* The FF entry can finish a nested function at input-end. The
         * enclosing1723E Syntax return retracts that consumed final byte. */
        if (paired_derivative && !peek(p) && p->position) --p->position;
        p->status = FX_EVAL_SYNTAX; goto restore;
    }
    /* C4 finite-series syntax preflight and saved-X effects precede the
     * still-unimplemented numerical paired loop. Never replace an invalid
     * body with a host backend limitation. */
    if (paired_series_preflight) { unsupported(p, token); goto restore; }
    call.body_end = p->position++;
    p->calculus_mode = 2;
    p->preflight_mode = 0;
    expression(p, &lower, 0);
    calculus_expression_finish(p, &lower);
    if (p->status != FX_EVAL_OK) goto restore;
    if (physical_derivative) {
        /*04B20..04B2A stores the point BEFORE parsing explicit tolerance. */
        variables_to_storage(p);
        derivative_preparation = paired_derivative ?
            fx_c4_derivative_point(&derivative_storage, &lower) :
            fx_derivative_storage_point(&derivative_storage, &lower.real);
        variables_from_storage(p);
        bank_from_storage(p);
        if (derivative_preparation != FX_NUMERIC_OK) { unsupported(p, token); goto restore; }
    }
    if (physical_integral) {
        /*04718 requires the lower argument's comma before850A staging. */
        if (peek(p) != ',') { p->status = FX_EVAL_SYNTAX; goto restore; }
        ++p->position;
        lower_comma_consumed = 1;
        variables_to_storage(p);
        fx_numeric_status prepared = paired_integral ?
            fx_c4_integral_lower(&integral_storage, &lower) :
            fx_integral_storage_lower(&integral_storage, &lower.real);
        variables_from_storage(p);
        bank_from_storage(p);
        if (prepared != FX_NUMERIC_OK) { unsupported(p, token); goto restore; }
    }
    if (token != 0x6b) {
        if (!lower_comma_consumed) {
            if (peek(p) != ',') { p->status = FX_EVAL_SYNTAX; goto restore; }
            ++p->position;
        }
        expression(p, &upper, 0);
        calculus_expression_finish(p, &upper);
        if (p->status != FX_EVAL_OK) goto restore;
    }
    if (physical_integral) {
        /*171EA has consumed the upper delimiter before04738's bound store.
         * Cache its meaning before a physical input alias can overwrite it. */
        if (peek(p) == ')') { ++p->position; closing_consumed = 1; }
        else if (peek(p) == ',') { ++p->position; upper_comma_consumed = 1; }
        variables_to_storage(p);
        fx_numeric_status prepared = paired_integral ?
            fx_c4_integral_upper(&integral_storage, &upper) :
            fx_integral_storage_upper(&integral_storage, &upper.real);
        variables_from_storage(p);
        bank_from_storage(p);
        if (prepared != FX_NUMERIC_OK) { unsupported(p, token); goto restore; }
    }
    if ((token == 0x6a || token == 0x6b) &&
        (upper_comma_consumed || (!closing_consumed && peek(p) == ','))) {
        if (!upper_comma_consumed) ++p->position;
        expression(p, &tolerance, 0);
        calculus_expression_finish(p, &tolerance);
        if (p->status != FX_EVAL_OK) goto restore;
        has_tolerance = 1;
    }
    if (fx_number_to_decimal(&decimal_lower, &lower.real) == FX_NUMERIC_OK)
        (void)fx_decimal_to_integer(&call.next_x, &decimal_lower);
    p->calculus_mode = 1;
    fx_numeric_status status;
    if (physical_derivative) {
        derivative_preparation = paired_derivative ?
            fx_c4_derivative_tolerance(&derivative_storage,
                has_tolerance ? &tolerance : NULL, &derivative_native_status) :
            fx_derivative_storage_tolerance(&derivative_storage,
                has_tolerance ? &tolerance.real : NULL, &derivative_native_status);
        variables_from_storage(p);
        bank_from_storage(p);
        if (derivative_preparation != FX_NUMERIC_OK) { unsupported(p, token); goto restore; }
    }
    if (physical_integral) {
        /* Default upper171EA consumes its closing token before0476C.
         * Explicit tolerance04756 backs that token up before04758. */
        if (!has_tolerance && !closing_consumed && peek(p) == ')') {
            ++p->position;
            closing_consumed = 1;
        }
        if (has_tolerance && peek(p) == ')') closing_consumed = 1;
        integral_cursor = (uint16_t)(p->transport->input_address + p->position +
            (has_tolerance && peek(p) == ')' ? 1u : 0u));
        fx_numeric_status prepared = paired_integral ?
            fx_c4_integral_tolerance(&integral_storage, has_tolerance ? &tolerance : NULL,
                integral_cursor, &integral_native_status) :
            fx_integral_storage_tolerance(&integral_storage,
                has_tolerance ? &tolerance.real : NULL, integral_cursor, &integral_native_status);
        variables_from_storage(p);
        bank_from_storage(p);
        if (prepared != FX_NUMERIC_OK) { unsupported(p, token); goto restore; }
        if (integral_native_status) {
            fx_number_error(&result, integral_native_status);
            status = FX_NUMERIC_OK;
        } else {
            if (paired_integral) {
                status = fx_c4_integral_run(&paired_result, &integral_storage,
                    calculus_evaluate_c4, &call, integral_publish_x_c4,
                    p->transport->output_address, integral_callback_context,
                    &control, &integral_native_status, &integral_cursor);
                result = paired_result.real;
            } else status = fx_number_integral_storage(&result, &integral_storage,
                calculus_evaluate, &call, integral_publish_x,
                p->transport->output_address, integral_callback_context,
                &control, &integral_native_status, &integral_cursor);
            if (status == FX_NUMERIC_OK) {
                if (integral_native_status) fx_number_error(&result, integral_native_status);
                if (integral_native_status == 0 || integral_native_status == 1)
                    p->position = (uint16_t)(integral_cursor - p->transport->input_address);
            }
        }
        variables_from_storage(p);
        bank_from_storage(p);
    } else if (token == 0x69)
        status = fx_number_sum(&result, &lower.real, &upper.real, calculus_evaluate, &call, &control);
    else if (token == 0x5d)
        status = fx_number_product(&result, &lower.real, &upper.real, calculus_evaluate, &call, &control);
    else if (token == 0x6a)
        status = fx_number_integral(&result, &lower.real, &upper.real,
                                    has_tolerance ? &tolerance.real : NULL,
                                    calculus_evaluate, &call, &control);
    else if (physical_derivative) {
        if (derivative_native_status) {
            /* R6=2 comma leaves the source on that separator.1723E
             * retracts its preceding byte when tolerance admission fails. */
            if (paired_derivative && peek(p) == ',' && p->position) --p->position;
            fx_number_error(&result, derivative_native_status);
            status = FX_NUMERIC_OK;
        } else {
            /*171EA evaluator-error85B4 publication is driver-owned; do not
             * rewrite a successful F-valued callback's separate EQ result. */
            if (paired_derivative) {
                status = fx_c4_derivative_run(&paired_result, &derivative_storage,
                    calculus_evaluate_c4, &call, derivative_refresh_x_c4,
                    &control, &derivative_native_status);
                result = paired_result.real;
                if (status == FX_NUMERIC_OK && derivative_native_status)
                    fx_number_error(&result, derivative_native_status);
            } else status = fx_number_derivative_storage(&result, &derivative_storage,
                calculus_evaluate, &call, &control);
        }
        variables_from_storage(p);
        bank_from_storage(p);
    } else
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
    if (paired_integral || paired_derivative) *out = paired_result;
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
    if (!closing_consumed) {
        if (peek(p) == ')') ++p->position;
        else if (!omitted_closing(p)) p->status = FX_EVAL_SYNTAX;
    }
restore:
    p->variables->values[FX_VARIABLE_X][0] = saved_x.real;
    if (paired_integral || ((paired_derivative || paired_series_preflight) &&
        p->storage->ram[0x80f9] == 0xc4))
        p->variables->values[FX_VARIABLE_X][1] = saved_x.imaginary;
    p->options.math_output = exact;
    p->calculus_mode = 0;
    p->calculus_token = 0;
    p->preflight_mode = 0;
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
    /*170B8..170C0 validates a continued store terminator, then returns
     * at its token without committing the ordinary variable transaction. */
    if (p->table_continuation) { p->position = position; return; }
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

static fx_eval_status evaluate_transported(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment, const fx_eval_state *state,
                           const fx_calculus_control *control, uint8_t selected_base,
                           const fx_number *initial_secondary,
                           const fx_number *prior_answer, fx_eval_storage *storage,
                           fx_number *random_seed, fx_eval_effects *effects, fx_eval_result *result,
                           const fx_eval_transport *transport, uint16_t *named_cursor, uint8_t table_continuation)
{
    parser p;
    fx_complex value;
    fx_eval_variables local_variables;
    fx_number local_seed = {{0}};
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
    p.table_continuation = table_continuation == 1;
    p.input = input; p.length = length;
    if (!variables) { fx_eval_variables_clear(&local_variables); variables = &local_variables; }
    p.variables = variables;
    p.storage = storage;
    p.transport = transport;
    p.random_seed = random_seed ? random_seed : &local_seed;
    p.linear_algebra = state && state->linear_algebra ? state->linear_algebra : &local_linear_algebra;
    p.control = control;
    p.base_radix = selected_base;
    p.options = options ? *options : fx_eval_default_options();
    p.environment = environment ? *environment : fx_eval_default_environment();
    if (p.table_continuation) {
        p.environment.restricted_state |= 1;
        if (storage) storage->ram[0x8124] |= 1;
    }
    if (prior_answer) p.prior_answer = *prior_answer;
    else if (storage) memcpy(p.prior_answer.bytes, storage->ram + 0x828a, 10);
    if (storage) {
        if (state && state->variables) variables_to_storage(&p);
        else variables_from_storage(&p);
        if (!p.table_continuation)
            storage->ram[0x8125] = p.options.calculation_context == 6 ? 0x18 : 0;
        bank_from_storage(&p);
    }
    if (p.options.calculation_context != 0xc1 && p.options.calculation_context != 0xc4 &&
        p.options.calculation_context != 2 &&
        !(storage && (p.options.calculation_context == 6 || p.options.calculation_context == 7 ||
          (p.options.calculation_context == 0x45 && p.environment.screen == 21 &&
           storage->ram[0x80fa]>=1 && storage->ram[0x80fa]<=4))) &&
        !(table_continuation && p.options.calculation_context == 0x88))
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
    if (p.status == FX_EVAL_OK && !suffix &&
        !(p.table_continuation && store_token(&p)) && peek(&p) != 0 &&
        (peek(&p) != ':' || (p.environment.screen & 0x40))) {
        fx_evaluator_token token = fx_decode_evaluator_token(peek(&p), p.options.calculation_context);
        if (token.kind == 1 && token.value >= 99 && token.value <= 102 &&
            p.options.calculation_context != 2) {
            /* BASE literal prefixes are rejected by the ordinary grammar's
             * post-read admission; they do not require a numerical leaf. */
            ++p.position;
            p.status = FX_EVAL_SYNTAX;
        } else if (token.kind == 1 && token.value == 95 &&
                   p.options.calculation_context != 2) {
            /*16B54 rejects a late unary-minus prefix after an operand. */
            p.status = FX_EVAL_SYNTAX;
        } else if (token.kind == 10 || peek(&p) == ')' || peek(&p) == ',' || peek(&p) == '.' ||
            (peek(&p) >= '0' && peek(&p) <= '9')) p.status = FX_EVAL_SYNTAX;
        else unsupported(&p, peek(&p));
    }
    int finish_rejected = 0;
    if (p.status == FX_EVAL_OK &&
        (value.real.bytes[0] >= 0x90 ||
         (value.real.bytes[0] >= 0x60 && value.real.bytes[0] < 0x80))) {
        /*17258 tests the full header byte. Rich/error results require the
         * ordinary screen and retain the evaluator's success channel while
         *1415A independently cleans or rejects the reference. */
        if (p.environment.screen != 1) { p.status = FX_EVAL_SYNTAX; finish_rejected = 1; }
        else continuous_finish(&p, &value.real);
    }
    result->value[0] = value.real;
    result->value[1] = value.imaginary;
    result->consumed = p.position;
    /*171E0 leaves a successful continuation on its delimiter; error
     * dispatch instead returns the post-read offending-token position. */
    if (p.table_continuation) {
        if (!finish_rejected && p.status != FX_EVAL_OK && p.status > 0 && p.position < p.length)
            ++result->consumed;
    } else if (p.status == FX_EVAL_OK && p.position < p.length) ++result->consumed;
    if (p.status == FX_EVAL_OK && !p.table_continuation) {
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
    if (transport && p.status >= 0) {
        physical_record_store(storage, transport->output_address, &result->value[0]);
        if ((storage->ram[0x80f9] == 0xc4 && p.status == FX_EVAL_OK) ||
            (p.status == FX_EVAL_OK && (p.environment.screen & 0x40)) ||
            p.status == FX_EVAL_POLAR_PAIR || p.status == FX_EVAL_RECTANGULAR_PAIR ||
            p.status == FX_EVAL_QUOTIENT_PAIR)
        {
            /*17284 ordinary C4 copies both records through169C0 (8+2).
             * Paired/C0 publication uses the separate69AE/D142 (2+8). */
            if (storage->ram[0x80f9] == 0xc4 && p.status == FX_EVAL_OK &&
                !(p.environment.screen & 0x40))
                physical_record_store(storage, (uint16_t)(transport->output_address + 10),
                                      &result->value[1]);
            else physical_secondary_store(storage, (uint16_t)(transport->output_address + 10),
                                          &result->value[1]);
        }
        else memcpy(result->value[1].bytes,
                    storage->ram + transport->output_address + 10, 10);
        uint16_t cursor = (uint16_t)(transport->input_address + result->consumed);
        if (named_cursor) *named_cursor = cursor;
        else {
            storage->ram[transport->cursor_address] = (uint8_t)cursor;
            storage->ram[transport->cursor_address + 1u] = (uint8_t)(cursor >> 8);
        }
    }
    return p.status;
}

static fx_eval_status evaluate(const uint8_t *input, size_t length,
    const fx_eval_options *options, const fx_eval_environment *environment,
    const fx_eval_state *state, const fx_calculus_control *control, uint8_t selected_base,
    const fx_number *initial_secondary, const fx_number *prior_answer,
    fx_eval_storage *storage, fx_number *random_seed, fx_eval_effects *effects,
    fx_eval_result *result)
{
    return evaluate_transported(input, length, options, environment, state, control,
        selected_base, initial_secondary, prior_answer, storage, random_seed,
        effects, result, NULL, NULL, 0);
}

/* Draft primary-only TABLE callback. Raw255 is its success channel. Values
 * on Syntax/Argument errors are outside TABLE's consumed-output contract. */
int fx_evaluate_table_expression(const uint8_t *input, size_t length,
    fx_eval_storage *storage, fx_eval_effects *effects, fx_eval_result *result)
{
    if (!storage || !storage->ram || storage->ram_size != 65536u ||
        storage->ram[0x80f9] != 0x88) return FX_EVAL_UNIMPLEMENTED;
    fx_eval_options options = {storage->ram[0x80f9],storage->ram[0x8106],storage->ram[0x8105]};
    fx_eval_environment globals = {storage->ram[0x80fc],storage->ram[0x80f5],
        storage->ram[0x810c],storage->ram[0x8124],storage->ram[0x8102],
        storage->ram[0x8103],storage->ram[0x80fa]};
    fx_eval_status status = evaluate_transported(input,length,&options,&globals,
        NULL,NULL,globals.selected_base,NULL,NULL,storage,NULL,effects,result,NULL,NULL,1);
    return status == FX_EVAL_OK ? 255 : status;
}

/* Actual88 ordinary parameter entry; continued completion is deliberately
 * absent. The caller supplies its retained secondary and raw PreAns source. */
int fx_evaluate_table_parameter(const uint8_t *input, size_t length,
    fx_eval_storage *storage, const fx_number *retained_secondary,
    const fx_number *prior_answer, fx_eval_result *result)
{
    if (!storage || !storage->ram || storage->ram_size != 65536u ||
        storage->ram[0x80f9] != 0x88) return FX_EVAL_UNIMPLEMENTED;
    fx_eval_options options = {storage->ram[0x80f9],storage->ram[0x8106],storage->ram[0x8105]};
    fx_eval_environment globals = {storage->ram[0x80fc],storage->ram[0x80f5],
        storage->ram[0x810c],storage->ram[0x8124],storage->ram[0x8102],
        storage->ram[0x8103],storage->ram[0x80fa]};
    return evaluate_transported(input,length,&options,&globals,NULL,NULL,
        globals.selected_base,retained_secondary,prior_answer,storage,NULL,NULL,result,NULL,NULL,2);
}

fx_eval_status fx_evaluate_with_state(const uint8_t *input, size_t length,
                           const fx_eval_options *options, const fx_eval_state *state,
                           const fx_calculus_control *control, fx_eval_result *result)
{
    return evaluate(input, length, options, NULL, state, control, FX_BASE_DEC, NULL, NULL, NULL, NULL, NULL, result);
}

fx_eval_status fx_evaluate_prepared(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment,
                           const fx_eval_state *state, const fx_calculus_control *control,
                           const fx_number *initial_secondary, fx_eval_result *result)
{
    uint8_t selected_base = environment ? environment->selected_base : FX_BASE_DEC;
    return evaluate(input, length, options, environment, state, control,
                    selected_base, initial_secondary, NULL, NULL, NULL, NULL, result);
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
                    selected_base, initial_secondary, prior_answer, NULL, NULL, NULL, result);
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
                    selected_base, initial_secondary, NULL, NULL, NULL, NULL, result);
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
                    selected_base, initial_secondary, prior_answer, NULL, NULL, effects, result);
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
        globals.selected_base, initial_secondary, prior_answer, storage, NULL, effects, result);
}

/* Additive session-seed entry: old public records and entry ABIs remain
 * unchanged. Seed, input, state, observations and output use separate storage. */
fx_eval_status fx_evaluate_prepared_random(const uint8_t *input, size_t length,
                           const fx_eval_options *options,
                           const fx_eval_environment *environment,
                           const fx_eval_state *state, const fx_calculus_control *control,
                           const fx_number *initial_secondary,
                           const fx_number *prior_answer, fx_number *seed,
                           fx_eval_effects *effects, fx_eval_result *result)
{
    uint8_t selected_base = environment ? environment->selected_base : FX_BASE_DEC;
    return evaluate(input, length, options, environment, state, control,
                    selected_base, initial_secondary, prior_answer, NULL, seed, effects, result);
}

static fx_eval_status evaluate_from_physical_source(size_t input_length,
    const fx_eval_options *options, const fx_eval_environment *environment,
    const fx_eval_state *state, const fx_calculus_control *control,
    const fx_number *prior_answer, fx_eval_storage *storage,
    const fx_eval_transport *transport, uint16_t *named_cursor, uint8_t table_mode,
    fx_eval_effects *effects, fx_eval_result *result)
{
    if (!storage || !storage->ram || storage->ram_size != 65536u || !transport ||
        !result || !input_length || transport->input_address < 0x8000u ||
        input_length > 65536u - transport->input_address ||
        (!named_cursor && (transport->cursor_address < 0x8000u ||
                           transport->cursor_address > 65534u)) ||
        transport->output_address < 0x8000u || transport->output_address > 65516u)
        return FX_EVAL_UNIMPLEMENTED;
    fx_eval_options prepared = options ? *options : fx_eval_default_options();
    if (!options) {
        prepared.calculation_context = storage->ram[0x80f9];
        prepared.math_output = storage->ram[0x8106];
        prepared.angle_unit = storage->ram[0x8105];
    }
    if (prepared.calculation_context != storage->ram[0x80f9]) return FX_EVAL_UNIMPLEMENTED;
    fx_eval_environment globals = environment ? *environment : fx_eval_default_environment();
    if (!environment) {
        globals.screen = storage->ram[0x80fc]; globals.prior_operation = storage->ram[0x80f5];
        globals.complex_format = storage->ram[0x810c]; globals.restricted_state = storage->ram[0x8124];
        globals.display_mode = storage->ram[0x8102]; globals.digits = storage->ram[0x8103];
        globals.selected_base = storage->ram[0x80fa];
    }
    fx_number secondary;
    memcpy(secondary.bytes, storage->ram + transport->output_address + 10, 10);
    return evaluate_transported(storage->ram + transport->input_address, input_length,
        &prepared, &globals, state, control, globals.selected_base, &secondary,
        prior_answer, storage, NULL, effects, result, transport, named_cursor, table_mode);
}

fx_eval_status fx_evaluate_prepared_physical(size_t input_length,
    const fx_eval_options *options, const fx_eval_environment *environment,
    const fx_eval_state *state, const fx_calculus_control *control,
    const fx_number *prior_answer, fx_eval_storage *storage,
    const fx_eval_transport *transport, fx_eval_effects *effects, fx_eval_result *result)
{
    return evaluate_from_physical_source(input_length, options, environment,
        state, control, prior_answer, storage, transport, NULL, 0, effects, result);
}

fx_eval_status fx_evaluate_prepared_source(size_t input_length,
    const fx_eval_options *options, const fx_eval_environment *environment,
    const fx_eval_state *state, const fx_calculus_control *control,
    const fx_number *prior_answer, fx_eval_storage *storage,
    const fx_eval_source *source, uint16_t *returned_source,
    fx_eval_effects *effects, fx_eval_result *result)
{
    if (!source || !returned_source) return FX_EVAL_UNIMPLEMENTED;
    fx_eval_transport transport = {source->input_address, 0,
        source->output_address, source->before_sample, source->userdata};
    return evaluate_from_physical_source(input_length, options, environment,
        state, control, prior_answer, storage, &transport, returned_source, 0,
        effects, result);
}

/* Ordinary171F4 in actual TABLE mode88, with a named caller-owned source.
 * Physical output and integral sample sinks use the common source transport. */
int fx_evaluate_table_parameter_source(size_t input_length,
    fx_eval_storage *storage, const fx_eval_source *source,
    uint16_t *returned_source, const fx_number *prior_answer,
    fx_eval_result *result)
{
    if (!storage || !storage->ram || storage->ram_size != 65536u ||
        storage->ram[0x80f9] != 0x88 || !source || !returned_source)
        return FX_EVAL_UNIMPLEMENTED;
    fx_eval_transport transport = {source->input_address, 0,
        source->output_address, source->before_sample, source->userdata};
    return evaluate_from_physical_source(input_length,NULL,NULL,NULL,NULL,
        prior_answer,storage,&transport,returned_source,2,NULL,result);
}
