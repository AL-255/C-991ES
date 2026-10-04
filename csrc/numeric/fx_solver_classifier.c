/* Native finite-decimal rank diagnostics and zero-pivot shortcuts.
 * GPL-3.0-or-later. No instruction execution or host floating point. */
#include "fx_solver.h"

/* These are determinant and minor formulas, in their original sum order.
 * Swapping pivots or reordering terms changes native cancellation behavior. */
static const uint8_t coefficient_determinant[6][3] = {
    {0,4,8},{0,5,7},{1,3,8},{1,5,6},{2,3,7},{2,4,6}
};
static const uint8_t augmented_determinants[3][6][3] = {
    {{0,4,11},{0,10,7},{1,3,11},{1,10,6},{9,3,7},{9,4,6}},
    {{1,5,11},{1,10,8},{2,4,11},{2,10,7},{9,4,8},{9,5,7}},
    {{0,5,11},{0,10,8},{2,3,11},{2,10,6},{9,3,8},{9,5,6}}
};
static const uint8_t coefficient_minors[9][4] = {
    {0,4,1,3},{1,5,2,4},{0,5,2,3},{3,7,4,6},{4,8,5,7},
    {3,8,5,6},{0,7,1,6},{1,8,2,7},{0,8,2,6}
};
static const uint8_t rhs_minors[9][4] = {
    {0,10,9,3},{1,10,9,4},{2,10,9,5},{3,11,10,6},{4,11,10,7},
    {5,11,10,8},{0,11,9,6},{1,11,9,7},{2,11,9,8}
};

static fx_numeric_status number_class(uint8_t *out, const fx_number *in)
{
    return fx_scalar_numeric_classify(out, in);
}
static fx_numeric_status ordinary_operand(fx_number *out, const fx_number *in)
{
    fx_number_type type = fx_number_kind(in);
    fx_numeric_status status;
    if (type != FX_NUMBER_DECIMAL && type != FX_NUMBER_RATIONAL) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    *out = *in;
    if (type != FX_NUMBER_RATIONAL) return FX_NUMERIC_OK;
    out->bytes[0] &= (uint8_t)~0x40;
    status = fx_number_to_decimal(out, out);
    if (status == FX_NUMERIC_OK) out->bytes[0] |= in->bytes[0] & 0x40;
    return status;
}
static fx_numeric_status ordinary(fx_number *out, const fx_number *a,
                                  const fx_number *b, fx_binary_op operation)
{
    fx_number first, second;
    fx_numeric_status status = ordinary_operand(&first, a);
    if (status == FX_NUMERIC_OK) status = ordinary_operand(&second, b);
    if (status != FX_NUMERIC_OK) return status;
    if (first.bytes[0] >= 0xf0 || second.bytes[0] >= 0xf0) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    return operation == FX_SUBTRACT ? fx_decimal_subtract_cancel(out, &first, &second) :
                                     fx_decimal_binary(out, &first, &second, operation);
}
/* 0x1181a rejects multiplication underflow of two nonzero source values. */
static fx_numeric_status checked_product(fx_number *out, const fx_number *a,
                                         const fx_number *b)
{
    uint8_t first_type, second_type, result_type;
    fx_numeric_status status = number_class(&first_type, a);
    if (status == FX_NUMERIC_OK) status = number_class(&second_type, b);
    if (status == FX_NUMERIC_OK) status = ordinary(out, a, b, FX_MULTIPLY);
    if (status != FX_NUMERIC_OK || out->bytes[0] >= 0xf0) return status;
    status = number_class(&result_type, out);
    if (status == FX_NUMERIC_OK && result_type == 1 && first_type != 1 && second_type != 1)
        fx_number_error(out, 3);
    return status;
}
static fx_numeric_status minor_class(uint8_t *out, const fx_number c[12],
                                     const uint8_t indices[4])
{
    fx_number first, second;
    fx_numeric_status status = checked_product(&first, &c[indices[0]], &c[indices[1]]);
    if (status == FX_NUMERIC_OK) status = checked_product(&second, &c[indices[2]], &c[indices[3]]);
    if (status == FX_NUMERIC_OK) status = ordinary(&first, &first, &second, FX_SUBTRACT);
    return status == FX_NUMERIC_OK ? number_class(out, &first) : status;
}
static fx_numeric_status triple(fx_number *out, const fx_number c[12],
                                const uint8_t indices[3])
{
    fx_numeric_status status = checked_product(out, &c[indices[0]], &c[indices[1]]);
    return status == FX_NUMERIC_OK ? checked_product(out, out, &c[indices[2]]) : status;
}
static fx_numeric_status determinant_class(uint8_t *out, const fx_number c[12],
                                           const uint8_t terms[6][3])
{
    fx_number sum, product;
    unsigned i;
    fx_numeric_status status = triple(&sum, c, terms[0]);
    for (i = 1; status == FX_NUMERIC_OK && i < 6; ++i) {
        status = triple(&product, c, terms[i]);
        if (status == FX_NUMERIC_OK)
            status = ordinary(&sum, &sum, &product, i == 3 || i == 4 ? FX_ADD : FX_SUBTRACT);
    }
    return status == FX_NUMERIC_OK ? number_class(out, &sum) : status;
}
static fx_numeric_status column_class(uint8_t *out, const fx_number c[12],
                                      unsigned first, unsigned stride)
{
    unsigned i;
    fx_numeric_status status;
    for (i = 0; i < 3; ++i) {
        status = number_class(out, &c[first+i*stride]);
        if (status != FX_NUMERIC_OK || *out != 1) return status;
    }
    return FX_NUMERIC_OK;
}
static uint8_t consistency_result(uint8_t type)
{
    return type == 1 ? 1 : type == 0xf0 ? 3 : 2;
}
#define STEP(operation) do { status = (operation); if (status != FX_NUMERIC_OK) return status; } while (0)
static fx_numeric_status two_equations(uint8_t *out, const fx_number c[12])
{
    static const uint8_t b_rhs[4] = {1,5,2,4}, determinant[4] = {0,4,1,3},
                         a_rhs[4] = {0,5,2,3};
    uint8_t a0, a1, b0, b1, rhs0, rhs1, type;
    fx_numeric_status status;
    STEP(number_class(&a0, &c[0]));
    if (a0 == 1) { STEP(number_class(&a1, &c[3])); }
    else a1 = 0;
    if (a0 == 1 && a1 == 1) {
        STEP(number_class(&b0, &c[1]));
        if (b0 == 1) {
            STEP(number_class(&b1, &c[4])); STEP(number_class(&rhs0, &c[2]));
            if (b1 == 1 && rhs0 == 1) { STEP(number_class(&rhs1, &c[5])); }
            else rhs1 = 1;
            *out = rhs0 == 1 && rhs1 == 1 ? 1 : 2; return FX_NUMERIC_OK;
        }
        STEP(number_class(&b1, &c[4]));
        if (b1 == 1) {
            STEP(number_class(&rhs1, &c[5])); *out = rhs1 == 1 ? 1 : 2;
            return FX_NUMERIC_OK;
        }
        STEP(minor_class(&type, c, b_rhs)); *out = consistency_result(type);
        return FX_NUMERIC_OK;
    }
    STEP(minor_class(&type, c, determinant));
    if (type != 1) { *out = 3; return FX_NUMERIC_OK; }
    STEP(minor_class(&type, c, a_rhs)); *out = consistency_result(type);
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_solver_classify_degenerate(uint8_t *classification,
                                               const fx_number coefficients[12],
                                               fx_solver_kind kind)
{
    static const uint8_t last_column_rhs[2][4] = {{2,10,9,5},{2,11,9,8}};
    uint8_t type, first_column;
    unsigned i;
    fx_numeric_status status;
    if (!classification || !coefficients || kind < FX_SOLVER_LINEAR2 || kind > FX_SOLVER_LINEAR3)
        return FX_NUMERIC_INVALID;
    if (kind == FX_SOLVER_LINEAR2) return two_equations(classification, coefficients);
    STEP(column_class(&first_column, coefficients, 0, 3));
    if (first_column == 1) {
        STEP(column_class(&type, coefficients, 1, 3));
        if (type == 1) {
            STEP(column_class(&type, coefficients, 2, 3));
            if (type == 1) {
                STEP(column_class(&type, coefficients, 9, 1));
                *classification = consistency_result(type); return FX_NUMERIC_OK;
            }
            /* Native deliberately keeps the first row as pivot here. */
            STEP(minor_class(&type, coefficients, last_column_rhs[0]));
            if (type == 1) STEP(minor_class(&type, coefficients, last_column_rhs[1]));
            *classification = consistency_result(type); return FX_NUMERIC_OK;
        }
    } else {
        STEP(determinant_class(&type, coefficients, coefficient_determinant));
        if (type != 1) { *classification = 3; return FX_NUMERIC_OK; }
    }
    for (i = 0; i < 3; ++i) {
        STEP(determinant_class(&type, coefficients, augmented_determinants[i]));
        if (type != 1) { *classification = consistency_result(type); return FX_NUMERIC_OK; }
    }
    for (i = 0; i < 9; ++i) {
        STEP(minor_class(&type, coefficients, coefficient_minors[i]));
        if (type != 1) { *classification = type == 0xf0 ? 3 : 1; return FX_NUMERIC_OK; }
    }
    for (i = 0; i < 9; ++i) {
        STEP(minor_class(&type, coefficients, rhs_minors[i]));
        if (type != 1) { *classification = consistency_result(type); return FX_NUMERIC_OK; }
    }
    *classification = 1; return FX_NUMERIC_OK;
}
#undef STEP
