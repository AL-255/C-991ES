/* Original finite-scalar operation order, expressed as matrix formulas.
 * GPL-3.0-or-later. No ROM execution or host floating point. */
#include "fx_linalg.h"
#include "../complex/fx_complex.h"
#include "../complex/fx_complex_round.h"

static unsigned kind(const fx_linalg_value *v) { return v->reference.bytes[0] >> 4; }
static uint8_t error(const fx_number *n) { return n->bytes[0] >= 0xf0 ? n->bytes[0] & 15 : 0; }
static void reject(fx_linalg_result *r, uint8_t status)
{
    fx_number_error(&r->value.reference, status); r->firmware_status = status;
}
static int interrupted(fx_linalg_result *r, const fx_linalg_context *context)
{
    ++r->cancellation_checks;
    return context->cancel_at && r->cancellation_checks == context->cancel_at;
}
static int valid(const fx_linalg_value *v, const fx_linalg_context *context)
{
    return v && context && v->rows <= 3 && v->columns <= 3 &&
        context->exact_math <= 1 && context->digits <= 9 &&
        (context->display_mode == 0 || context->display_mode == 4 ||
         context->display_mode == 8 || context->display_mode == 9);
}
static void begin(fx_linalg_result *r, const fx_linalg_value *v)
{
    r->value = *v; r->firmware_status = 0; r->cancellation_checks = 0;
}
void fx_linalg_context_default(fx_linalg_context *context)
{
    if (!context) return;
    context->exact_math = 1; context->display_mode = 0;
    context->digits = 0; context->cancel_at = 0;
}
static fx_numeric_status arithmetic(fx_number *out, const fx_number *a,
                                    const fx_number *b, fx_binary_op op)
{
    if (a->bytes[0] >= 0xf0 || b->bytes[0] >= 0xf0) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    return fx_number_binary(out, a, b, op);
}
static fx_numeric_status fraction_divide(fx_number *out, const fx_number *a,
                                         const fx_number *b)
{
    int64_t numerator, denominator;
    fx_number left = *a, right = *b;
    left.bytes[0] &= (uint8_t)~0x40; right.bytes[0] &= (uint8_t)~0x40;
    a = &left; b = &right;
    if ((a->bytes[0] & 0xf0) != 0 && (a->bytes[0] & 0xf0) != 0x20) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    if ((b->bytes[0] & 0xf0) != 0 && (b->bytes[0] & 0xf0) != 0x20) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    /* Native94EC admits only bounded integer operands to fraction packing.
     * Larger integers retain ordinary division's guard digits; eligible
     * inputs still receive the fraction encoder's decimal cleanup. */
    if (a->bytes[0] < 10 && b->bytes[0] < 10 &&
        fx_number_fractional_status(a) == 0 &&
        fx_number_fractional_status(b) == 0 &&
        fx_decimal_to_integer(&numerator, a) == FX_NUMERIC_OK &&
        fx_decimal_to_integer(&denominator, b) == FX_NUMERIC_OK && denominator) {
        fx_rational ratio;
        if (denominator < 0) { numerator = -numerator; denominator = -denominator; }
        ratio.numerator = numerator; ratio.denominator = (uint64_t)denominator;
        ratio.flags = 0;
        return fx_rational_encode(out, &ratio);
    }
    return arithmetic(out, a, b, FX_DIVIDE);
}
static fx_numeric_status absolute(fx_number *out, const fx_number *in)
{
    uint8_t classification;
    fx_numeric_status status = fx_scalar_numeric_classify(&classification, in);
    if (status != FX_NUMERIC_OK) return status;
    if (classification == 0xf0) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
    *out = *in; out->bytes[0] &= (uint8_t)~0x40;
    return classification == 2 ? fx_number_negate(out, out) : FX_NUMERIC_OK;
}
static fx_numeric_status prepare(fx_number *out, const fx_number *in)
{
    fx_rational rational;
    *out = *in;
    /* CEC0 clears only a marked decimal header; it does not convert surds. */
    if ((out->bytes[0] & 0xf0) == 0x40) out->bytes[0] &= (uint8_t)~0x40;
    if (fx_number_recognize_rational(&rational, out))
        return fx_rational_encode(out, &rational);
    return FX_NUMERIC_OK;
}
/* a*b-c*d. Both products are completed before the checked subtraction. */
static fx_numeric_status minor(fx_number *out, const fx_number cells[9],
                               unsigned a, unsigned b, unsigned c, unsigned d)
{
    fx_number first, second;
    fx_numeric_status status = arithmetic(&first, &cells[a], &cells[b], FX_MULTIPLY);
    if (status == FX_NUMERIC_OK) status = arithmetic(&second, &cells[c], &cells[d], FX_MULTIPLY);
    if (status == FX_NUMERIC_OK) status = arithmetic(out, &first, &second, FX_SUBTRACT);
    return status;
}
static fx_numeric_status triple(fx_number *out, const fx_number cells[9],
                                unsigned a, unsigned b, unsigned c)
{
    fx_numeric_status status = arithmetic(out, &cells[a], &cells[b], FX_MULTIPLY);
    return status == FX_NUMERIC_OK ? arithmetic(out, out, &cells[c], FX_MULTIPLY) : status;
}

fx_numeric_status fx_linalg_scalar(fx_linalg_result *out,
                                   const fx_linalg_value *input,
                                   const fx_number *scalar,
                                   fx_linalg_scalar_op operation,
                                   const fx_linalg_context *context)
{
    fx_linalg_result result;
    fx_number factor;
    fx_numeric_status status;
    unsigned row, col, index, scalar_index = 9;
    if (!out || !scalar || !valid(input, context) ||
        operation < FX_LINALG_SCALE || operation > FX_LINALG_FRACTION_DIVIDE)
        return FX_NUMERIC_INVALID;
    factor = *scalar;
    for (index = 0; index < 9; ++index)
        if (scalar == &input->cells[index]) scalar_index = index;
    begin(&result, input);
    if ((factor.bytes[0] >> 4) >= 6 || (kind(input) != 6 && kind(input) != 9)) {
        reject(&result, 3); *out = result; return FX_NUMERIC_OK;
    }
    if (!input->rows || !input->columns) {
        reject(&result, 9); *out = result; return FX_NUMERIC_OK;
    }
    for (row = 0; row < input->rows; ++row) for (col = 0; col < input->columns; ++col) {
        index = row * 3 + col;
        if (scalar_index < 9) factor = result.value.cells[scalar_index];
        status = operation == FX_LINALG_FRACTION_DIVIDE
            ? fraction_divide(&result.value.cells[index], &result.value.cells[index], &factor)
            : arithmetic(&result.value.cells[index], &result.value.cells[index], &factor,
                         operation == FX_LINALG_SCALE ? FX_MULTIPLY : FX_DIVIDE);
        if (status != FX_NUMERIC_OK) return status;
        if (error(&result.value.cells[index])) { reject(&result, error(&result.value.cells[index])); goto done; }
        if (interrupted(&result, context)) { reject(&result, 1); goto done; }
    }
done:
    *out = result; return FX_NUMERIC_OK;
}

fx_numeric_status fx_linalg_binary(fx_linalg_result *out,
                                   const fx_linalg_value *left,
                                   const fx_linalg_value *right,
                                   fx_linalg_binary_op operation,
                                   const fx_linalg_context *context)
{
    fx_linalg_result result;
    fx_linalg_value a, b;
    fx_number temp[9], product, second;
    fx_numeric_status status;
    unsigned row, col, inner, index;
    if (!out || !valid(left, context) || !valid(right, context) ||
        operation < FX_LINALG_ADD || operation > FX_LINALG_CROSS) return FX_NUMERIC_INVALID;
    a = *left; b = *right; begin(&result, &a);
    if (kind(&a) != kind(&b) ||
        (operation == FX_LINALG_MATRIX_MULTIPLY ? kind(&a) != 6 :
         operation >= FX_LINALG_DOT ? kind(&a) != 9 : kind(&a) != 6 && kind(&a) != 9)) {
        reject(&result, 3); goto done;
    }
    if (operation == FX_LINALG_MATRIX_MULTIPLY) {
        if (a.columns != b.rows || !a.columns) { reject(&result, 9); goto done; }
        result.value.columns = b.columns;
        if (!a.rows || !b.columns) { reject(&result, 9); goto done; }
        for (index = 0; index < 9; ++index) fx_number_zero(&temp[index]);
        for (row = 0; row < a.rows; ++row) for (col = 0; col < b.columns; ++col)
            for (inner = 0; inner < a.columns; ++inner) {
                index = row * 3 + col;
                status = arithmetic(&product, &a.cells[row * 3 + inner], &b.cells[inner * 3 + col], FX_MULTIPLY);
                if (status == FX_NUMERIC_OK) status = arithmetic(&temp[index], &temp[index], &product, FX_ADD);
                if (status != FX_NUMERIC_OK) return status;
                if (error(&temp[index])) { reject(&result, error(&temp[index])); goto done; }
                if (interrupted(&result, context)) { reject(&result, 1); goto done; }
            }
        for (index = 0; index < 9; ++index) result.value.cells[index] = temp[index];
    } else {
        if (a.rows != b.rows || a.columns != b.columns || !a.rows || !a.columns) {
            reject(&result, 9); goto done;
        }
        if (operation <= FX_LINALG_SUBTRACT) {
            for (row = 0; row < a.rows; ++row) for (col = 0; col < a.columns; ++col) {
                index = row * 3 + col;
                status = arithmetic(&result.value.cells[index], &a.cells[index], &b.cells[index],
                                    operation == FX_LINALG_ADD ? FX_ADD : FX_SUBTRACT);
                if (status != FX_NUMERIC_OK) return status;
                if (error(&result.value.cells[index])) { reject(&result, error(&result.value.cells[index])); goto done; }
            }
        } else if (operation == FX_LINALG_DOT) {
            fx_number_zero(&result.value.reference);
            for (index = 0; index < a.columns; ++index) {
                status = arithmetic(&product, &a.cells[index], &b.cells[index], FX_MULTIPLY);
                if (status == FX_NUMERIC_OK) status = arithmetic(&result.value.reference, &result.value.reference, &product, FX_ADD);
                if (status != FX_NUMERIC_OK) return status;
                if (error(&result.value.reference)) { reject(&result, error(&result.value.reference)); goto done; }
            }
        } else {
            result.value.rows = 1; result.value.columns = 3;
            fx_number_zero(&temp[0]); fx_number_zero(&temp[1]);
            for (index = a.columns == 3 ? 0 : 2; index < 3; ++index) {
                unsigned first = (index + 1) % 3, next = (index + 2) % 3;
                status = arithmetic(&product, &a.cells[first], &b.cells[next], FX_MULTIPLY);
                if (status == FX_NUMERIC_OK) status = arithmetic(&second, &a.cells[next], &b.cells[first], FX_MULTIPLY);
                if (status == FX_NUMERIC_OK) status = arithmetic(&temp[index], &product, &second, FX_SUBTRACT);
                if (status != FX_NUMERIC_OK) return status;
                if (error(&temp[index])) { reject(&result, error(&temp[index])); goto done; }
            }
            for (index = 0; index < 3; ++index) result.value.cells[index] = temp[index];
        }
    }
done:
    *out = result; return FX_NUMERIC_OK;
}

static fx_numeric_status determinant(fx_number *out, fx_linalg_result *result,
                                     const fx_number cells[9], unsigned size,
                                     const fx_linalg_context *context)
{
    static const unsigned cycles[6][3] = {{0,4,8},{1,5,6},{2,3,7},{2,4,6},{1,3,8},{0,5,7}};
    fx_number product;
    fx_numeric_status status;
    unsigned index;
    if (size == 1) { *out = cells[0]; return FX_NUMERIC_OK; }
    if (size == 2) {
        status = minor(out, cells, 0, 4, 1, 3);
        if (status != FX_NUMERIC_OK) return status;
        if (error(out)) { reject(result, error(out)); return FX_NUMERIC_OK; }
        if (interrupted(result, context)) reject(result, 1);
        return FX_NUMERIC_OK;
    }
    status = triple(out, cells, 0, 4, 8);
    for (index = 1; status == FX_NUMERIC_OK && index < 6; ++index) {
        status = triple(&product, cells, cycles[index][0], cycles[index][1], cycles[index][2]);
        if (status == FX_NUMERIC_OK)
            status = arithmetic(out, out, &product, index < 3 ? FX_ADD : FX_SUBTRACT);
        if (index == 2 && interrupted(result, context)) { reject(result, 1); return status; }
    }
    if (status != FX_NUMERIC_OK) return status;
    if (error(out)) reject(result, error(out));
    else if (interrupted(result, context)) reject(result, 1);
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_linalg_unary(fx_linalg_result *out,
                                  const fx_linalg_value *input,
                                  fx_linalg_unary_op operation,
                                  const fx_linalg_context *context)
{
    static const unsigned cofactors[9][4] = {
        {4,8,5,7},{2,7,1,8},{1,5,2,4},
        {5,6,3,8},{0,8,2,6},{2,3,0,5},
        {3,7,4,6},{1,6,0,7},{0,4,1,3}};
    fx_linalg_result result;
    fx_number workspace[9], det, swap;
    fx_complex pair, magnitude;
    fx_numeric_status status;
    uint8_t classification, native;
    unsigned row, col, index, dimension;
    if (!out || !valid(input, context) || operation < FX_LINALG_TRANSPOSE ||
        operation > FX_LINALG_CUBE) return FX_NUMERIC_INVALID;
    begin(&result, input);
    if (operation == FX_LINALG_NEGATE) {
        fx_decimal_from_integer(&det, -1);
        return fx_linalg_scalar(out, input, &det, FX_LINALG_SCALE, context);
    }
    if (operation == FX_LINALG_SQUARE || operation == FX_LINALG_CUBE) {
        fx_linalg_value original = *input;
        fx_linalg_result stage;
        fx_linalg_context following = *context;
        status = fx_linalg_binary(&stage, &original, &original, FX_LINALG_MATRIX_MULTIPLY, context);
        if (status != FX_NUMERIC_OK) return status;
        if (operation == FX_LINALG_CUBE && !stage.firmware_status) {
            unsigned previous_checks = stage.cancellation_checks;
            following.cancel_at = context->cancel_at > previous_checks
                ? context->cancel_at - previous_checks : 0;
            status = fx_linalg_binary(&stage, &stage.value, &original, FX_LINALG_MATRIX_MULTIPLY, &following);
            if (status != FX_NUMERIC_OK) return status;
            stage.cancellation_checks += previous_checks;
        }
        *out = stage; return FX_NUMERIC_OK;
    }
    if (operation == FX_LINALG_VECTOR_MAGNITUDE ? kind(input) != 9 :
        operation == FX_LINALG_DISPLAY_ROUND || operation == FX_LINALG_INTEGER_CLEANUP
        ? kind(input) != 6 && kind(input) != 9 : kind(input) != 6) {
        reject(&result, 3); goto done;
    }
    if (!input->rows || !input->columns) { reject(&result, 9); goto done; }
    if (operation == FX_LINALG_TRANSPOSE) {
        result.value.rows = input->columns; result.value.columns = input->rows;
        for (row = 1; row < 3; ++row) for (col = 0; col < row; ++col) {
            swap = result.value.cells[row * 3 + col];
            result.value.cells[row * 3 + col] = result.value.cells[col * 3 + row];
            result.value.cells[col * 3 + row] = swap;
        }
    } else if (operation == FX_LINALG_VECTOR_MAGNITUDE) {
        pair.real = input->cells[0];
        for (index = 1; index < (input->columns < 2 ? 2 : input->columns); ++index) {
            pair.imaginary = input->cells[index];
            status = fx_complex_magnitude(&magnitude, &pair, context->exact_math);
            if (status == FX_NUMERIC_OK)
                status = fx_complex_firmware_status(&native, FX_COMPLEX_MAGNITUDE_RETURN, &pair, &magnitude);
            if (status != FX_NUMERIC_OK) return status;
            pair.real = magnitude.real;
            if (native) { reject(&result, native); goto done; }
        }
        result.value.reference = pair.real;
    } else if (operation >= FX_LINALG_ABSOLUTE) {
        for (row = 0; row < input->rows; ++row) for (col = 0; col < input->columns; ++col) {
            index = row * 3 + col;
            switch (operation) {
            case FX_LINALG_ABSOLUTE: status = absolute(&result.value.cells[index], &result.value.cells[index]); break;
            case FX_LINALG_DISPLAY_ROUND: status = fx_scalar_display_round(&result.value.cells[index], &result.value.cells[index], context->display_mode, context->digits, &native); break;
            case FX_LINALG_RATIONAL_PREPARE: status = prepare(&result.value.cells[index], &result.value.cells[index]); break;
            default: status = fx_decimal_integer_cleanup(&result.value.cells[index]); break;
            }
            if (status != FX_NUMERIC_OK) return status;
            if ((operation == FX_LINALG_ABSOLUTE || operation == FX_LINALG_INTEGER_CLEANUP) && error(&result.value.cells[index])) {
                reject(&result, error(&result.value.cells[index])); goto done;
            }
        }
    } else {
        if (input->rows != input->columns) { reject(&result, 9); goto done; }
        dimension = input->rows;
        for (index = 0; index < 9; ++index) fx_number_zero(&workspace[index]);
        for (row = 0; row < dimension; ++row) for (col = 0; col < dimension; ++col) {
            index = row * 3 + col;
            status = prepare(&workspace[index], &input->cells[index]);
            if (status != FX_NUMERIC_OK) return status;
            if (interrupted(&result, context)) { reject(&result, 1); goto done; }
        }
        status = determinant(&det, &result, workspace, dimension, context);
        if (status != FX_NUMERIC_OK) return status;
        if (result.firmware_status) goto done;
        if (operation == FX_LINALG_DETERMINANT) result.value.reference = det;
        else {
            status = fx_scalar_numeric_classify(&classification, &det);
            if (status != FX_NUMERIC_OK) return status;
            if (classification == 1) { reject(&result, 3); goto done; }
            if (dimension == 1) fx_decimal_from_u8(&result.value.cells[0], 1);
            else if (dimension == 2) {
                result.value.cells[0] = workspace[4]; result.value.cells[4] = workspace[0];
                status = fx_number_negate(&result.value.cells[1], &workspace[1]);
                if (status == FX_NUMERIC_OK) status = fx_number_negate(&result.value.cells[3], &workspace[3]);
                if (status != FX_NUMERIC_OK) return status;
                if (interrupted(&result, context)) { reject(&result, 1); goto done; }
            } else for (index = 0; index < 9; ++index) {
                status = minor(&result.value.cells[index], workspace, cofactors[index][0], cofactors[index][1], cofactors[index][2], cofactors[index][3]);
                if (status != FX_NUMERIC_OK) return status;
                if (index % 3 == 2 && interrupted(&result, context)) { reject(&result, 1); goto done; }
            }
            if ((det.bytes[0] >> 4) >= 6) { reject(&result, 3); goto done; }
            for (row = 0; row < dimension; ++row) for (col = 0; col < dimension; ++col) {
                index = row * 3 + col;
                status = fraction_divide(&result.value.cells[index], &result.value.cells[index], &det);
                if (status != FX_NUMERIC_OK) return status;
                if (error(&result.value.cells[index])) { reject(&result, error(&result.value.cells[index])); goto done; }
                if (interrupted(&result, context)) { reject(&result, 1); goto done; }
            }
        }
    }
done:
    *out = result; return FX_NUMERIC_OK;
}
