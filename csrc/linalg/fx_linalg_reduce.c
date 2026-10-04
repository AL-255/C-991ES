/* Finite row elimination in the firmware's exact operation/commit order.
 * GPL-3.0-or-later. No firmware execution or host floating point. */
#include "fx_linalg_reduce.h"
#include "../complex/fx_complex.h"

typedef struct {
    fx_linalg_result *result;
    const fx_linalg_context *context;
    fx_numeric_status host;
} reduction;
static void fail(reduction *work, uint8_t code)
{
    work->result->firmware_status = code;
    fx_number_error(&work->result->value.reference, code);
}
static int stopped(const reduction *work)
{
    return work->host != FX_NUMERIC_OK || work->result->firmware_status;
}
static int poll(reduction *work)
{
    uint32_t count = ++work->result->cancellation_checks;
    if (work->context->cancel_at && count == work->context->cancel_at) {
        fail(work, 1); return 1;
    }
    return 0;
}
static int zero(reduction *work, const fx_number *number, int tiny)
{
    uint8_t classification;
    fx_number absolute;
    work->host = fx_scalar_numeric_classify(&classification, number);
    if (work->host != FX_NUMERIC_OK) return 0;
    if (classification == 1) return 1;
    if (!tiny) return 0;
    absolute = *number;
    if (classification == 0xf0) fx_number_error(&absolute, 3);
    else {
        absolute.bytes[0] &= (uint8_t)~0x40;
        if (classification == 2) work->host = fx_number_negate(&absolute, &absolute);
    }
    return work->host == FX_NUMERIC_OK && fx_number_exponent(&absolute) <= -11;
}
static void arithmetic(reduction *work, fx_number *out, const fx_number *a,
                       const fx_number *b, fx_binary_op operation)
{
    if (a->bytes[0] >= 0xf0 || b->bytes[0] >= 0xf0) {
        fx_number_error(out, 3); return;
    }
    work->host = fx_number_binary(out, a, b, operation);
}
static void check_number(reduction *work, const fx_number *number)
{
    if (number->bytes[0] >= 0xf0 && (number->bytes[0] & 15))
        fail(work, number->bytes[0] & 15);
}
static void divide(reduction *work, fx_number *out, const fx_number *a,
                   const fx_number *b)
{
    fx_number left = *a, right = *b;
    int64_t numerator, denominator;
    left.bytes[0] &= (uint8_t)~0x40; right.bytes[0] &= (uint8_t)~0x40;
    if (((left.bytes[0] & 0xf0) != 0 && (left.bytes[0] & 0xf0) != 0x20) ||
        ((right.bytes[0] & 0xf0) != 0 && (right.bytes[0] & 0xf0) != 0x20)) {
        fx_number_error(out, 3); return;
    }
    if (left.bytes[0] < 10 && right.bytes[0] < 10 &&
        fx_number_fractional_status(&left) == 0 &&
        fx_number_fractional_status(&right) == 0 &&
        fx_decimal_to_integer(&numerator, &left) == FX_NUMERIC_OK &&
        fx_decimal_to_integer(&denominator, &right) == FX_NUMERIC_OK && denominator) {
        fx_rational fraction;
        if (denominator < 0) { numerator = -numerator; denominator = -denominator; }
        fraction.numerator = numerator; fraction.denominator = (uint64_t)denominator;
        fraction.flags = 0;
        work->host = fx_rational_encode(out, &fraction);
    } else arithmetic(work, out, &left, &right, FX_DIVIDE);
}
static void swap_rows(fx_number cells[9], unsigned first, unsigned second,
                      unsigned columns)
{
    unsigned col;
    for (col = 0; col < columns; ++col) {
        fx_number temp = cells[first * 3 + col];
        cells[first * 3 + col] = cells[second * 3 + col];
        cells[second * 3 + col] = temp;
    }
}
static void lexical_order(reduction *work, fx_number cells[9], unsigned rows,
                          unsigned columns)
{
    unsigned target, col, candidate;
    for (target = 0; target + 1 < rows; ++target) {
        int found = 0;
        for (col = 0; col < columns && !found; ++col) {
            for (candidate = target; candidate + 1 < rows; ++candidate) {
                if (poll(work)) return;
                if (!zero(work, &cells[candidate * 3 + col], 0)) { found = 1; break; }
                if (stopped(work)) return;
                if (candidate + 2 == rows && !zero(work, &cells[(rows - 1) * 3 + col], 0)) {
                    candidate = rows - 1; found = 1; break;
                }
                if (stopped(work)) return;
            }
            if (found && candidate != target) swap_rows(cells, target, candidate, columns);
        }
    }
}
static void absolute(reduction *work, fx_number *out, const fx_number *input)
{
    uint8_t classification;
    work->host = fx_scalar_numeric_classify(&classification, input);
    if (work->host != FX_NUMERIC_OK) return;
    *out = *input;
    if (classification == 0xf0) fx_number_error(out, 3);
    else {
        out->bytes[0] &= (uint8_t)~0x40;
        if (classification == 2) work->host = fx_number_negate(out, out);
    }
}
/* The sole caller supplies C312 absolute records. This is the ordered
 * nonnegative comparison used for pivot selection; domain records do not
 * select a swap. It is not a general signed scalar comparison API. */
static int less(reduction *work, const fx_number *a, const fx_number *b)
{
    fx_number first, second;
    fx_decimal x, y;
    work->host = fx_number_to_decimal(&first, a);
    if (work->host == FX_NUMERIC_OK) work->host = fx_number_to_decimal(&second, b);
    if (work->host != FX_NUMERIC_OK) return 0;
    if (fx_decimal_decode(&x, &first) != FX_NUMERIC_OK ||
        fx_decimal_decode(&y, &second) != FX_NUMERIC_OK) return 0;
    if (!x.mantissa) return y.mantissa != 0;
    if (!y.mantissa) return 0;
    return x.exponent != y.exponent ? x.exponent < y.exponent : x.mantissa < y.mantissa;
}
static void magnitude_order(reduction *work, fx_number cells[9], unsigned rows,
                            unsigned columns)
{
    unsigned col, base, next;
    fx_number first, second;
    for (col = 0; col < columns; ++col) {
        if (!zero(work, &cells[col], 0)) break;
        if (stopped(work)) return;
    }
    if (col == columns) return;
    for (base = 0; base + 1 < rows; ++base) {
restart:
        absolute(work, &first, &cells[base * 3 + col]);
        if (stopped(work)) return;
        for (next = base + 1; ; ++next) {
            if (poll(work)) return;
            if (next >= rows) break;
            if (zero(work, &cells[next * 3 + col], 0)) return;
            absolute(work, &second, &cells[next * 3 + col]);
            if (stopped(work)) return;
            if (less(work, &first, &second)) {
                swap_rows(cells, base, next, columns); goto restart;
            }
            if (stopped(work)) return;
        }
    }
}
static void normalize(reduction *work, fx_number cells[9], unsigned rows,
                      unsigned columns, int tiny)
{
    unsigned row, col;
    fx_number pivot;
    for (row = 0; row < rows; ++row) {
        for (col = 0; ; ++col) {
            if (poll(work)) return;
            if (col >= columns) break;
            if (zero(work, &cells[row * 3 + col], tiny)) {
                fx_number_zero(&cells[row * 3 + col]);
                if (stopped(work)) return;
                continue;
            }
            pivot = cells[row * 3 + col];
            fx_decimal_from_u8(&cells[row * 3 + col], 1);
            for (++col; ; ++col) {
                if (poll(work)) return;
                if (col >= columns) break;
                divide(work, &cells[row * 3 + col], &cells[row * 3 + col], &pivot);
                check_number(work, &cells[row * 3 + col]);
                if (stopped(work)) return;
            }
            break;
        }
    }
}
static void forward(reduction *work, fx_number cells[9], unsigned rows,
                    unsigned columns);
static void shift_right(reduction *work, fx_number cells[9], unsigned rows,
                        unsigned width, unsigned offset)
{
    unsigned row, remaining, col;
    for (row = 0; row < rows; ++row) {
        for (remaining = width; remaining; --remaining) {
            if (poll(work)) return;
            col = remaining - 1;
            cells[row * 3 + col + offset] = cells[row * 3 + col];
        }
        for (col = 0; col < offset; ++col) fx_number_zero(&cells[row * 3 + col]);
    }
}
static void leading_columns(reduction *work, fx_number cells[9], unsigned rows,
                            unsigned columns)
{
    unsigned offset, row, col, width;
    if (columns == 1) return;
    for (offset = 1; offset + 1 < columns; ++offset) {
        if (!zero(work, &cells[offset], 0)) break;
        if (stopped(work)) return;
    }
    width = columns - offset;
    for (row = 0; row < rows; ++row) for (col = 0; ; ++col) {
        if (poll(work)) return;
        if (col >= width) break;
        cells[row * 3 + col] = cells[row * 3 + col + offset];
    }
    forward(work, cells, rows, width);
    if (stopped(work)) return;
    shift_right(work, cells, rows, width, offset);
}
static void forward(reduction *work, fx_number cells[9], unsigned rows,
                    unsigned columns)
{
    fx_number pending[9], scratch[9], first, second;
    unsigned pivot, row, col, index;
    if (columns == 1) {
        if (!zero(work, &cells[0], 0)) fx_decimal_from_u8(&cells[0], 1);
        for (row = 1; ; ++row) {
            if (poll(work)) return;
            if (row >= rows) return;
            fx_number_zero(&cells[row * 3]);
        }
    }
    if (zero(work, &cells[0], 0)) {
        leading_columns(work, cells, rows, columns); return;
    }
    if (stopped(work)) return;
    for (pivot = 0; ; ++pivot) {
        if (poll(work)) return;
        if (pivot + 1 >= rows || pivot >= columns) return;
        for (index = 0; index < 9; ++index) pending[index] = cells[index];
        if (pivot && zero(work, &cells[pivot * 3 + pivot], 0)) {
            /* Native extraction copies a lower-row prefix; the saved matrix
             * preserves the pivot row when reduced rows are merged back. */
            unsigned lower_rows = rows - pivot, lower_cols = columns - pivot;
            for (row = 0; ; ++row) {
                if (poll(work)) return;
                if (row >= lower_rows) break;
                for (col = 0; col < lower_cols; ++col)
                    cells[row * 3 + col] = cells[(row + pivot) * 3 + col];
            }
            leading_columns(work, cells, lower_rows, lower_cols);
            if (stopped(work)) return;
            shift_right(work, cells, lower_rows, lower_cols, pivot);
            if (stopped(work)) return;
            for (row = 1; ; ++row) {
                if (poll(work)) return;
                if (row >= lower_rows) break;
                for (col = 0; col < 3; ++col) pending[(row + pivot) * 3 + col] = cells[row * 3 + col];
            }
            for (index = 0; index < 9; ++index) cells[index] = pending[index];
            return;
        }
        if (stopped(work)) return;
        for (row = pivot + 1; row < rows; ++row) {
            for (index = 0; index < 9; ++index) fx_number_zero(&scratch[index]);
            for (col = pivot + 1; ; ++col) {
                if (poll(work)) return;
                if (col >= columns) break;
                arithmetic(work, &first, &cells[pivot * 3 + pivot], &cells[row * 3 + col], FX_MULTIPLY);
                if (stopped(work)) return;
                arithmetic(work, &second, &cells[pivot * 3 + col], &cells[row * 3 + pivot], FX_MULTIPLY);
                if (stopped(work)) return;
                arithmetic(work, &scratch[col], &first, &second, FX_SUBTRACT);
                check_number(work, &scratch[col]);
                if (stopped(work)) return;
            }
            normalize(work, scratch, 1, columns, 1);
            if (stopped(work)) return;
            for (col = 0; col < 3; ++col) pending[row * 3 + col] = scratch[col];
        }
        if (pivot + 2 < columns) {
            lexical_order(work, pending, rows, columns);
            if (stopped(work)) return;
        }
        for (index = 0; index < 9; ++index) cells[index] = pending[index];
    }
}
static void backward(reduction *work, fx_number cells[9], unsigned rows,
                     unsigned columns)
{
    unsigned row, col, above, next;
    fx_number factor, product;
    for (row = 1; row < rows; ++row) {
        for (col = row; col < columns; ++col) {
            if (!zero(work, &cells[row * 3 + col], 0)) break;
            if (stopped(work)) return;
        }
        if (col >= columns) continue;
        for (above = 0; above < row; ++above) {
            if (zero(work, &cells[above * 3 + col], 0)) continue;
            if (stopped(work)) return;
            factor = cells[above * 3 + col];
            for (next = col + 1; ; ++next) {
                if (poll(work)) return;
                if (next >= columns) break;
                arithmetic(work, &product, &factor, &cells[row * 3 + next], FX_MULTIPLY);
                if (stopped(work)) return;
                arithmetic(work, &cells[above * 3 + next], &cells[above * 3 + next], &product, FX_SUBTRACT);
                check_number(work, &cells[above * 3 + next]);
                if (stopped(work)) return;
            }
            fx_number_zero(&cells[above * 3 + col]);
        }
    }
}
fx_numeric_status fx_linalg_echelon(fx_linalg_result *out,
                                    const fx_linalg_value *input,
                                    int reduced,
                                    const fx_linalg_context *context)
{
    fx_linalg_result result;
    reduction work;
    fx_numeric_status status;
    if (!out || !input || !context || (reduced != 0 && reduced != 1))
        return FX_NUMERIC_INVALID;
    status = fx_linalg_unary(&result, input, FX_LINALG_RATIONAL_PREPARE, context);
    if (status != FX_NUMERIC_OK) return status;
    work.result = &result; work.context = context; work.host = FX_NUMERIC_OK;
    if (!result.firmware_status) lexical_order(&work, result.value.cells, input->rows, input->columns);
    if (!stopped(&work)) magnitude_order(&work, result.value.cells, input->rows, input->columns);
    if (!stopped(&work)) normalize(&work, result.value.cells, input->rows, input->columns, 0);
    if (!stopped(&work)) forward(&work, result.value.cells, input->rows, input->columns);
    if (!stopped(&work) && reduced) backward(&work, result.value.cells, input->rows, input->columns);
    if (work.host != FX_NUMERIC_OK) return work.host;
    *out = result; return FX_NUMERIC_OK;
}
