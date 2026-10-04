/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_eval_rich.h"
#include "fx_eval_rich_unary.h"
#include "fx_eval_rich_reduce.h"
#include "fx_eval_surd_workspace.h"
#include "../complex/fx_complex_dispatch.h"
#include "../platform/fx_platform.h"
#include "../numeric/fx_raw_fraction_convert.h"
#include <string.h>

static int valid(const fx_eval_storage *s, const fx_eval_rich_context *c)
{
    return s && s->ram && s->ram_size == 65536u && c &&
        c->numeric.exact_math <= 1 && c->numeric.digits <= 9 &&
        (c->numeric.display_mode == 0 || c->numeric.display_mode == 4 ||
         c->numeric.display_mode == 8 || c->numeric.display_mode == 9);
}

void fx_eval_rich_context_default(fx_eval_rich_context *c, uint8_t context)
{
    if (!c) return;
    c->calculation_context = context;
    fx_linalg_context_default(&c->numeric);
    c->numeric.exact_math = (context & 0x40u) != 0;
    c->cancelled = NULL;
    c->userdata = NULL;
}

static unsigned dimension_address(uint8_t header)
{
    return 0x80e0u + 2u * (header & 15u);
}
static unsigned payload_address(uint8_t header)
{
    return 0x829eu + 90u * (header & 15u);
}
static unsigned cell_address(unsigned payload, unsigned row, unsigned column)
{
    /* The native cell-coordinate sum is byte sized before multiplying by10. */
    return payload + 10u * ((3u * row + column) & 255u);
}
static int overlaps(unsigned a, unsigned an, unsigned b, unsigned bn)
{
    return a < b + bn && b < a + an;
}
static int work_alias(uint16_t pair, uint8_t a, uint8_t b, int right_rich)
{
    if (!pair) return 0;
    return overlaps(pair, 40, payload_address(a), 90) ||
        overlaps(pair, 40, dimension_address(a), 2) ||
        (right_rich && (overlaps(pair, 40, payload_address(b), 90) ||
                        overlaps(pair, 40, dimension_address(b), 2)));
}

static void update_current(fx_eval_storage *s, uint16_t pair,
                            const fx_complex *value)
{
    if (pair) memcpy(s->ram + pair, value, sizeof *value);
}
static void refresh_current(fx_complex *value, const fx_eval_storage *s,
                             uint16_t pair)
{
    if (pair) memcpy(value, s->ram + pair, sizeof *value);
}
static void reject(fx_eval_rich_result *out, fx_eval_storage *s,
                    uint16_t pair, uint8_t status)
{
    refresh_current(&out->value, s, pair);
    if (pair) memcpy(&out->other, s->ram + pair + 20u, sizeof out->other);
    fx_number_error(&out->value.real, status);
    update_current(s, pair, &out->value);
    out->firmware_status = status;
}
static fx_numeric_status cleanup(fx_eval_rich_result *out,
                                  fx_eval_storage *s, uint16_t pair,
                                  const fx_eval_rich_context *context)
{
    fx_complex_dispatch_context c = fx_complex_dispatch_default_context();
    fx_complex input;
    fx_numeric_status status;
    refresh_current(&out->value, s, pair);
    input = out->value;
    c.calculation_context = context->calculation_context;
    c.exact_math = context->numeric.exact_math;
    c.display_mode = context->numeric.display_mode;
    c.digits = context->numeric.digits;
    status = fx_complex_dispatch_cleanup(&out->value, &input,
        out->firmware_status, &c, &out->firmware_status);
    if (status == FX_NUMERIC_OK) update_current(s, pair, &out->value);
    if (pair) memcpy(&out->other, s->ram + pair + 20u, sizeof out->other);
    return status;
}

static fx_numeric_status arithmetic(fx_number *out, fx_eval_storage *s,
    const fx_number *a, const fx_number *b, fx_binary_op operation,
    uint16_t physical_a, uint16_t physical_b)
{
    fx_numeric_status status;
    /* Surd admission precedes the scalar error predicate in1C6E0. Its
     * saved-operand and component writes must occur during the operation,
     * before a later cell is read from an overlapping physical slot. */
    if ((a->bytes[0] & 0xf0u) == 0x80 || (b->bytes[0] & 0xf0u) == 0x80)
        return fx_eval_surd_workspace_binary(out, s->ram, a, b,
            physical_a, physical_b, operation);
    if (a->bytes[0] >= 0xf0 || b->bytes[0] >= 0xf0) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    status = fx_number_binary(out, a, b, operation);
    if (status == FX_NUMERIC_INVALID) {
        const fx_number *operand[2] = {a,b};
        unsigned i;
        for (i = 0; i < 2; ++i) if ((operand[i]->bytes[0] & 0xf0u) == 0x60) {
            fx_rational checked;
            fx_number converted;
            if (fx_rational_decode(&checked, operand[i]) == FX_NUMERIC_OK) continue;
            /* Native scalar admission masks the rich marker on6x before
             * its unchecked fraction conversion. A zero-denominator work
             * reference reaches finite F3, rather than a host input error.
             * Other malformed finite conversions require their own ordered
             * arithmetic proof and remain an explicit host gap. */
            status = fx_raw_fraction_convert(&converted, operand[i]);
            if (status != FX_NUMERIC_OK) return status;
            if (converted.bytes[0] >= 0xf0) {
                fx_number_error(out, 3); return FX_NUMERIC_OK;
            }
            return FX_NUMERIC_UNIMPLEMENTED;
        }
    }
    return status;
}
static uint8_t error(const fx_number *value)
{
    return value->bytes[0] >= 0xf0 ? value->bytes[0] & 15u : 0;
}
int fx_eval_rich_poll(fx_eval_storage *s, uint32_t *checks,
                      const fx_eval_rich_context *context)
{
    fx_platform platform = {s->rom, s->rom_size, s->ram, 0, FX_MEMORY_OK};
    int requested;
    ++*checks;
    s->ram[0x8e00] = 2;
    fx_timer_start(&platform, 0x129a);
    requested = context->cancelled && context->cancelled(context->userdata);
    if (context->numeric.cancel_at && *checks == context->numeric.cancel_at)
        requested = 1;
    if (requested) { s->ram[0x80f2] = 4; s->ram[0x80f3] = 16; }
    s->ram[0x8e00] = 0;
    return requested;
}
static int cancelled(fx_eval_rich_result *r, fx_eval_storage *s,
                      const fx_eval_rich_context *c)
{
    return fx_eval_rich_poll(s, &r->cancellation_checks, c);
}

/* Live storage loops are needed when work records alias cells or when byte
 * dimensions exceed the bounded nine-cell value-kernel representation. */
static fx_numeric_status elementwise(fx_eval_rich_result *out,
    fx_eval_storage *s, uint16_t pair, const fx_complex *other,
    unsigned rows, unsigned columns, unsigned left, unsigned right,
    uint8_t selector, const fx_eval_rich_context *context)
{
    unsigned row, col;
    fx_number a, b, value;
    fx_numeric_status status;
    int scalar = selector == FX_EVAL_RICH_SCALE || selector == FX_EVAL_RICH_DIVIDE;
    fx_binary_op op = selector == FX_EVAL_RICH_ADD ? FX_ADD :
        selector == FX_EVAL_RICH_SUBTRACT ? FX_SUBTRACT :
        selector == FX_EVAL_RICH_SCALE ? FX_MULTIPLY : FX_DIVIDE;
    for (row = 0; row < rows; ++row) for (col = 0; col < columns; ++col) {
        unsigned destination = cell_address(left, row, col);
        memcpy(&a, s->ram + destination, sizeof a);
        if (scalar) {
            if (pair) memcpy(&b, s->ram + pair + 20u, sizeof b);
            else b = other->real;
        } else memcpy(&b, s->ram + cell_address(right, row, col), sizeof b);
        status = arithmetic(&value, s, &a, &b, op, (uint16_t)destination,
            scalar ? pair ? (uint16_t)(pair + 20u) : 0 :
            (uint16_t)cell_address(right, row, col));
        if (status != FX_NUMERIC_OK) return status;
        memcpy(s->ram + destination, &value, sizeof value);
        if (error(&value)) { reject(out, s, pair, error(&value)); return FX_NUMERIC_OK; }
        if (scalar && cancelled(out, s, context)) {
            reject(out, s, pair, 1); return FX_NUMERIC_OK;
        }
    }
    refresh_current(&out->value, s, pair);
    return FX_NUMERIC_OK;
}

static fx_numeric_status dot(fx_eval_rich_result *out, fx_eval_storage *s,
    uint16_t pair, unsigned columns, unsigned left, unsigned right)
{
    unsigned col;
    fx_number a, b, product, sum;
    fx_numeric_status status;
    fx_number_zero(&out->value.real); update_current(s, pair, &out->value);
    for (col = 0; col < columns; ++col) {
        memcpy(&a, s->ram + left + 10u * col, sizeof a);
        memcpy(&b, s->ram + right + 10u * col, sizeof b);
        status = arithmetic(&product, s, &a, &b, FX_MULTIPLY,
            0, (uint16_t)(right + 10u * col));
        refresh_current(&out->value, s, pair);
        if (status == FX_NUMERIC_OK)
            status = arithmetic(&sum, s, &out->value.real, &product, FX_ADD, pair, 0);
        if (status != FX_NUMERIC_OK) return status;
        out->value.real = sum; update_current(s, pair, &out->value);
        if (error(&sum)) { reject(out, s, pair, error(&sum)); break; }
    }
    return FX_NUMERIC_OK;
}

static fx_numeric_status matrix_multiply(fx_eval_rich_result *out,
    fx_eval_storage *s, uint16_t pair, unsigned rows, unsigned inner_count,
    unsigned columns, unsigned left, unsigned right,
    const fx_eval_rich_context *context)
{
    /* The native90-byte accumulator borders a ten-byte numeric term.
     * Output coordinate9 aliases that term; coordinate10 enters CPU-local
     * descriptor pointers and loop state, a separate explicit boundary. */
    fx_number temporary[10], b, sum;
    fx_numeric_status status;
    unsigned row, col, inner, index;
    for (index = 0; index < 9; ++index) fx_number_zero(&temporary[index]);
    for (row = 0; row < rows; ++row) for (col = 0; col < columns; ++col) {
        index = (3u * row + col) & 255u;
        if (index >= 10) return FX_NUMERIC_UNIMPLEMENTED;
        for (inner = 0; inner < inner_count; ++inner) {
            memcpy(&temporary[9], s->ram + cell_address(left, row, inner), sizeof temporary[9]);
            memcpy(&b, s->ram + cell_address(right, inner, col), sizeof b);
            status = arithmetic(&temporary[9], s, &temporary[9], &b,
                FX_MULTIPLY, 0, (uint16_t)cell_address(right, inner, col));
            if (status == FX_NUMERIC_OK)
                status = arithmetic(&sum, s, &temporary[index], &temporary[9], FX_ADD, 0, 0);
            if (status != FX_NUMERIC_OK) return status;
            temporary[index] = sum;
            if (error(&sum)) { reject(out, s, pair, error(&sum)); return FX_NUMERIC_OK; }
            if (cancelled(out, s, context)) {
                reject(out, s, pair, 1); return FX_NUMERIC_OK;
            }
        }
    }
    memcpy(s->ram + left, temporary, 9u * sizeof temporary[0]);
    refresh_current(&out->value, s, pair);
    return FX_NUMERIC_OK;
}

static fx_numeric_status cross(fx_eval_rich_result *out, fx_eval_storage *s,
    uint16_t pair, unsigned columns, unsigned left, unsigned right)
{
    static const unsigned components[3][2] = {{1,2},{2,0},{0,1}};
    fx_number result[3], first, second, a, b;
    fx_numeric_status status;
    unsigned component;
    fx_number_zero(&result[0]); fx_number_zero(&result[1]);
    for (component = columns == 3 ? 0u : 2u; component < 3; ++component) {
        unsigned j = components[component][0], k = components[component][1];
        memcpy(&a, s->ram + left + 10u*j, sizeof a);
        memcpy(&b, s->ram + right + 10u*k, sizeof b);
        status = arithmetic(&first, s, &a, &b, FX_MULTIPLY,
            0, (uint16_t)(right + 10u*k));
        /* Each source is reread after the preceding product's pool writes. */
        if (status == FX_NUMERIC_OK) {
            memcpy(&a, s->ram + left + 10u*k, sizeof a);
            memcpy(&b, s->ram + right + 10u*j, sizeof b);
            status = arithmetic(&second, s, &a, &b, FX_MULTIPLY,
                0, (uint16_t)(right + 10u*j));
        }
        if (status == FX_NUMERIC_OK)
            status = arithmetic(&result[component], s, &first, &second, FX_SUBTRACT, 0, 0);
        if (status != FX_NUMERIC_OK) return status;
        if (error(&result[component])) {
            reject(out, s, pair, error(&result[component])); return FX_NUMERIC_OK;
        }
    }
    memcpy(s->ram + left, result, sizeof result);
    refresh_current(&out->value, s, pair);
    return FX_NUMERIC_OK;
}

static fx_numeric_status dispatch(fx_eval_rich_result *out,
    fx_eval_storage *s, const fx_complex *current, const fx_complex *other,
    uint16_t pair, uint8_t selector, const fx_eval_rich_context *context)
{
    fx_eval_rich_result result;
    fx_numeric_status status;
    unsigned ka, kb, dimensions, rows, columns, right_rows = 0, right_columns = 0;
    uint8_t header;
    int scalar;
    if (!out || !current || !other || !valid(s, context)) return FX_NUMERIC_INVALID;
    if (selector == FX_EVAL_RICH_REF || selector == FX_EVAL_RICH_RREF ||
        selector == FX_EVAL_RICH_VECTOR_NORMAL_R || selector == FX_EVAL_RICH_VECTOR_NOT) {
        status = fx_eval_rich_reduce_after_storage(&result, s, current, other,
            selector, context, pair);
        if (status != FX_NUMERIC_OK) return status;
        status = cleanup(&result, s, pair, context);
        if (status == FX_NUMERIC_OK) *out = result;
        return status;
    }
    if (selector <= 8 || selector == 162 || selector == 163 || selector == 164) {
        fx_eval_rich_unary_result unary;
        unsigned kind = current->real.bytes[0] >> 4;
        /* The pointer API has independent host work records. The address
         * adapter currently stops when unary work-record copies overlap the
         * bank; their live constant-copy alias is a separate bus boundary. */
        if (pair && (kind == 6 || kind == 9) &&
            work_alias(pair, current->real.bytes[0], other->real.bytes[0],
                       (other->real.bytes[0] >> 4) == 6))
            return FX_NUMERIC_UNIMPLEMENTED;
        status = fx_eval_rich_unary_after_storage(&unary, s, current, other,
            selector, context, pair);
        if (status != FX_NUMERIC_OK) return status;
        result.value = unary.value; result.other = unary.other;
        result.firmware_status = unary.native_status;
        result.cancellation_checks = unary.cancellation_checks;
        if (pair) {
            memcpy(s->ram + pair, &result.value, sizeof result.value);
            memcpy(s->ram + pair + 20u, &result.other, sizeof result.other);
        }
        *out = result;
        return FX_NUMERIC_OK;
    }
    if (selector < FX_EVAL_RICH_ADD || selector > FX_EVAL_RICH_MATRIX_MULTIPLY)
        return FX_NUMERIC_UNIMPLEMENTED;
    result.value = *current; result.other = *other;
    result.firmware_status = 0; result.cancellation_checks = 0;
    header = current->real.bytes[0]; ka = header >> 4; kb = other->real.bytes[0] >> 4;
    scalar = selector == FX_EVAL_RICH_SCALE || selector == FX_EVAL_RICH_DIVIDE;
    if ((scalar ? kb >= 6 || (ka != 6 && ka != 9) : ka != kb ||
         (selector == FX_EVAL_RICH_MATRIX_MULTIPLY ? ka != 6 :
          selector >= FX_EVAL_RICH_DOT ? ka != 9 : ka != 6 && ka != 9))) {
        reject(&result, s, pair, 3); *out = result; return FX_NUMERIC_OK;
    }
    dimensions = dimension_address(header);
    rows = s->ram[dimensions]; columns = s->ram[dimensions + 1u];
    if (!scalar) {
        dimensions = dimension_address(other->real.bytes[0]);
        right_rows = s->ram[dimensions]; right_columns = s->ram[dimensions + 1u];
    }
    if (selector == FX_EVAL_RICH_MATRIX_MULTIPLY) {
        if (columns != right_rows || !columns) {
            reject(&result, s, pair, 9); *out = result; return FX_NUMERIC_OK;
        }
        s->ram[dimension_address(header) + 1u] = (uint8_t)right_columns;
        if (!rows || !right_columns) {
            reject(&result, s, pair, 9); *out = result; return FX_NUMERIC_OK;
        }
    } else if (!rows || !columns || (!scalar &&
              (rows != right_rows || columns != right_columns))) {
        reject(&result, s, pair, 9); *out = result; return FX_NUMERIC_OK;
    }
    if (selector == FX_EVAL_RICH_CROSS) {
        /* Cross accepts equal nonzero dimensions, then uses only three
         * components. The exact3-column case selects all three minors. */
        dimensions = dimension_address(header);
        s->ram[dimensions] = 1; s->ram[dimensions + 1u] = 3;
        status = cross(&result, s, pair, columns, payload_address(header),
            payload_address(other->real.bytes[0]));
    } else {
        status = selector == FX_EVAL_RICH_MATRIX_MULTIPLY ?
            matrix_multiply(&result, s, pair, rows, columns, right_columns,
                payload_address(header), payload_address(other->real.bytes[0]), context) :
            selector == FX_EVAL_RICH_DOT ?
            dot(&result, s, pair, columns, payload_address(header),
                payload_address(other->real.bytes[0])) :
            elementwise(&result, s, pair, other, rows, columns,
                payload_address(header), payload_address(other->real.bytes[0]),
                selector, context);
    }
    if (status == FX_NUMERIC_OK) status = cleanup(&result, s, pair, context);
    if (status == FX_NUMERIC_OK) *out = result;
    return status;
}

fx_numeric_status fx_eval_rich_dispatch(fx_eval_rich_result *out,
    fx_eval_storage *s, const fx_complex *current, const fx_complex *other,
    uint8_t selector, const fx_eval_rich_context *context)
{
    return dispatch(out, s, current, other, 0, selector, context);
}

fx_numeric_status fx_eval_rich_dispatch_address(fx_eval_rich_result *out,
    fx_eval_storage *s, uint16_t pair, uint8_t selector,
    const fx_eval_rich_context *context)
{
    fx_complex current, other;
    if (!valid(s, context) || !out) return FX_NUMERIC_INVALID;
    if (pair < 0x8000u || pair > 65496u || (pair & 1u))
        return FX_NUMERIC_UNIMPLEMENTED;
    memcpy(&current, s->ram + pair, sizeof current);
    memcpy(&other, s->ram + pair + 20u, sizeof other);
    return dispatch(out, s, &current, &other, pair, selector, context);
}
