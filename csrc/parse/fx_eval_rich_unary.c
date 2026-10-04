/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_eval_rich_unary.h"
#include "fx_eval_rich.h"
#include "fx_eval_surd_workspace.h"
#include "../complex/fx_complex_round.h"
#include "../linalg/fx_linalg.h"
#include "../numeric/fx_raw_fraction_convert.h"
#include "../numeric/fx_raw_decimal_exp.h"
#include "../trig/fx_trig_hyperbolic.h"
#include "../platform/fx_platform.h"
#include "../platform/fx_result_classify.h"
#include <string.h>

static uint8_t record_error(const fx_number *number)
{
    return number->bytes[0] >= 0xf0 ? number->bytes[0] & 15u : 0;
}
static void reject(fx_eval_rich_unary_result *result, uint8_t status)
{
    fx_number_error(&result->value.real,status); result->native_status = status;
}
static unsigned slot(const fx_number *reference) { return reference->bytes[0] & 15u; }
static void load(fx_linalg_value *out, const fx_eval_storage *storage,
                  const fx_number *reference)
{
    unsigned id = slot(reference);
    out->reference = *reference;
    out->rows = storage->ram[0x80e0u+2u*id];
    out->columns = storage->ram[0x80e1u+2u*id];
    memcpy(out->cells,storage->ram+0x829eu+90u*id,sizeof out->cells);
}
static void commit(fx_eval_storage *storage, unsigned id,
                    const fx_linalg_value *value)
{
    storage->ram[0x80e0u+2u*id] = value->rows;
    storage->ram[0x80e1u+2u*id] = value->columns;
    memcpy(storage->ram+0x829eu+90u*id,value->cells,sizeof value->cells);
}
/* The exact square-root wrapper expands a short positive scalar into
 * seven mathematical components at8640. It leaves the original prepared
 * radicand in the seventh component after reducing its square factors. */
static void square_factors(uint64_t value, uint64_t *coefficient, uint64_t *radicand)
{
    uint64_t candidate;
    *coefficient = 1; *radicand = value;
    for (candidate = 2; candidate <= 97 && candidate <= *radicand/candidate; ++candidate)
        while (*radicand % (candidate*candidate) == 0) {
            *radicand /= candidate*candidate; *coefficient *= candidate;
        }
}
static fx_numeric_status magnitude_workspace(fx_eval_storage *storage,
    const fx_number *left, const fx_number *right, int exact_math)
{
    fx_number x,y,xx,yy,source,components[7];
    fx_decimal dx,dy,ds;
    fx_rational fraction;
    uint64_t numerator,denominator,ncoefficient,nradical,dcoefficient,dradical;
    int64_t integer;
    unsigned index;
    fx_numeric_status status;
    if (!exact_math || left->bytes[0] >= 0xf0 || right->bytes[0] >= 0xf0 ||
        !left->bytes[0] || !right->bytes[0]) return FX_NUMERIC_OK;
    status = fx_number_to_decimal(&x,left);
    if (status == FX_NUMERIC_OK) status = fx_number_to_decimal(&y,right);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_decimal_decode(&dx,&x) != FX_NUMERIC_OK ||
        fx_decimal_decode(&dy,&y) != FX_NUMERIC_OK) return FX_NUMERIC_UNIMPLEMENTED;
    if (!dx.mantissa || !dy.mantissa || dx.exponent <= -50 || dx.exponent >= 49 ||
        dy.exponent <= -50 || dy.exponent >= 49) return FX_NUMERIC_OK;
    status = fx_number_integer_power(&xx,&x,2);
    if (status == FX_NUMERIC_OK) status = fx_number_integer_power(&yy,&y,2);
    if (status == FX_NUMERIC_OK) status = fx_decimal_binary(&source,&xx,&yy,FX_ADD);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_decimal_decode(&ds,&source) != FX_NUMERIC_OK) return FX_NUMERIC_UNIMPLEMENTED;
    if (!ds.mantissa || ds.sign != 1 || ds.exponent >= 7) return FX_NUMERIC_OK;
    if (fx_number_recognize_rational(&fraction,&source)) {
        status = fx_rational_encode(&source,&fraction);
        if (status != FX_NUMERIC_OK) return status;
        if (fraction.numerator <= 0) return FX_NUMERIC_UNIMPLEMENTED;
        numerator = (uint64_t)fraction.numerator; denominator = fraction.denominator;
    } else if (fx_decimal_to_integer(&integer,&source) == FX_NUMERIC_OK && integer > 0) {
        numerator = (uint64_t)integer; denominator = 1;
    } else return FX_NUMERIC_OK;
    for (index = 0; index < 7; ++index) fx_number_zero(&components[index]);
    (void)fx_decimal_from_integer(&components[2],1);
    (void)fx_decimal_from_integer(&components[3],(int64_t)numerator);
    (void)fx_decimal_from_integer(&components[4],1);
    (void)fx_decimal_from_integer(&components[5],(int64_t)denominator);
    if (numerator >= 10000000u || denominator >= 10000u) {
        memcpy(storage->ram+0x8640,components,60); return FX_NUMERIC_OK;
    }
    square_factors(numerator,&ncoefficient,&nradical);
    square_factors(denominator,&dcoefficient,&dradical);
    (void)fx_decimal_from_integer(&components[3],(int64_t)ncoefficient);
    (void)fx_decimal_from_integer(&components[4],(int64_t)(nradical*dradical));
    (void)fx_decimal_from_integer(&components[5],(int64_t)(dcoefficient*dradical));
    components[6] = source;
    memcpy(storage->ram+0x8640,components,sizeof components);
    return FX_NUMERIC_OK;
}
/* 1CADE first takes the absolute values of its two private component
 * records. Opposite-sign compact surds classify through a decimal temporary
 * at workspace record zero. Only the nonzero two-component path then unfolds
 * both absolute values for decimal magnitude arithmetic. These writes occur
 * even when exact square-root output is disabled. */
static fx_numeric_status magnitude_component_workspace(fx_eval_storage *storage,
    fx_number *component)
{
    fx_number parts[6],converted;
    fx_numeric_status status;
    uint8_t classification;
    if ((component->bytes[0] & 0xf0u) == 0x80 && component->bytes[9] &&
        (uint8_t)(component->bytes[8]+component->bytes[9]) == 7) {
        status = fx_surd_unpack(parts,component);
        if (status == FX_NUMERIC_OK)
            memcpy(storage->ram+0x8640u,parts,sizeof parts);
        if (status == FX_NUMERIC_OK) status = fx_number_to_decimal(&converted,component);
        if (status != FX_NUMERIC_OK) return status;
        memcpy(storage->ram+0x8640u,&converted,10);
    }
    status = fx_scalar_numeric_classify(&classification,component);
    if (status != FX_NUMERIC_OK) return status;
    if (classification == 0xf0) fx_number_error(component,3);
    else {
        component->bytes[0] &= (uint8_t)~0x40;
        if (classification == 2) return fx_number_negate(component,component);
    }
    return FX_NUMERIC_OK;
}
static fx_numeric_status magnitude_prepare_workspace(fx_eval_storage *storage,
    const fx_complex *input)
{
    fx_complex absolute = *input;
    fx_number parts[6];
    fx_numeric_status status;
    unsigned index;
    if (input->real.bytes[0] >= 0xf0 || input->imaginary.bytes[0] >= 0xf0)
        return FX_NUMERIC_OK;
    status = magnitude_component_workspace(storage,&absolute.real);
    if (status == FX_NUMERIC_OK)
        status = magnitude_component_workspace(storage,&absolute.imaginary);
    if (status != FX_NUMERIC_OK || !absolute.real.bytes[0] ||
        !absolute.imaginary.bytes[0]) return status;
    for (index = 0; index < 2; ++index) {
        const fx_number *component = index ? &absolute.imaginary : &absolute.real;
        if ((component->bytes[0] & 0xf0u) == 0x80) {
            status = fx_surd_unpack(parts,component);
            if (status != FX_NUMERIC_OK) return status;
            memcpy(storage->ram+0x8640u,parts,sizeof parts);
        }
    }
    return FX_NUMERIC_OK;
}
static fx_numeric_status live_magnitude(fx_linalg_result *out,
    fx_eval_storage *storage, const fx_linalg_value *input,
    const fx_linalg_context *context)
{
    fx_linalg_result result;
    fx_complex pair,magnitude;
    fx_numeric_status status;
    uint8_t native;
    unsigned column,columns = input->columns < 2 ? 2 : input->columns;
    result.value = *input; result.firmware_status = 0; result.cancellation_checks = 0;
    memcpy(&pair.real,storage->ram+0x829eu+90u*slot(&input->reference),10);
    for (column = 1; column < columns; ++column) {
        memcpy(&pair.imaginary,storage->ram+0x829eu+90u*slot(&input->reference)+10u*column,10);
        status = magnitude_prepare_workspace(storage,&pair);
        if (status == FX_NUMERIC_OK)
            status = fx_complex_magnitude(&magnitude,&pair,context->exact_math);
        if (status == FX_NUMERIC_OK)
            status = fx_complex_firmware_status(&native,FX_COMPLEX_MAGNITUDE_RETURN,&pair,&magnitude);
        if (status != FX_NUMERIC_OK) return status;
        status = magnitude_workspace(storage,&pair.real,&pair.imaginary,context->exact_math);
        if (status != FX_NUMERIC_OK) return status;
        pair.real = magnitude.real;
        if (native) {
            fx_number_error(&result.value.reference,native); result.firmware_status = native;
            *out = result; return FX_NUMERIC_OK;
        }
    }
    result.value.reference = pair.real; *out = result; return FX_NUMERIC_OK;
}
static fx_numeric_status live_cells(fx_eval_rich_unary_result *result,
    fx_eval_storage *storage, unsigned rows, unsigned columns, unsigned identity,
    uint8_t selector, const fx_complex_dispatch_context *context,
    const fx_eval_rich_context *poll_context, uint16_t working_pair)
{
    unsigned row,column;
    fx_number cell,value;
    fx_numeric_status status;
    uint8_t classification,native;
    for (row = 0; row < rows; ++row) for (column = 0; column < columns; ++column) {
        unsigned address = 0x829eu+90u*identity+10u*((3u*row+column)&255u);
        /* Extended coordinates can enter a caller's CPU-local save area.
         * Keep every preceding numerical write, but do not interpret a
         * machine frame as an ordinary numeric cell. */
        if (address >= 0x8b00u && address < 0x8e00u) return FX_NUMERIC_UNIMPLEMENTED;
        memcpy(&cell,storage->ram+address,10);
        if (selector == 1) {
            fx_platform platform = {storage->rom,storage->rom_size,storage->ram,0,FX_MEMORY_OK};
            fx_result_classification observed;
            status = fx_result_classify_address(&platform,(uint16_t)address,
                (uint16_t)(10u*((3u*row+column)&255u)),&observed);
            if (status != FX_NUMERIC_OK) return status;
            classification = observed.classification;
            memcpy(&cell,storage->ram+address,10);
            if (classification == 0xf0) fx_number_error(&value,3);
            else {
                value = cell; value.bytes[0] &= (uint8_t)~0x40;
                status = classification == 2 ? fx_number_negate(&value,&value) : FX_NUMERIC_OK;
            }
            native = record_error(&value);
        } else if (selector == 2) {
            uint8_t mode = context->display_mode;
            fx_number saved_companion;
            if (context->calculation_context == 0xc4 || context->digits > 9)
                return FX_NUMERIC_UNIMPLEMENTED;
            if (mode != 0 && mode != 4 && mode != 8 && mode != 9) mode = 0;
            memcpy(&saved_companion,storage->ram+address+20u,10);
            if ((cell.bytes[0] & 0xf0u) == 0x80) {
                fx_number components[6],converted;
                /* 173FA expands the live compact surd before committing its
                 * decimal conversion back to the same physical cell. */
                if (address >= 0x8640u && address < 0x867cu)
                    return FX_NUMERIC_UNIMPLEMENTED;
                status = fx_surd_unpack(components,&cell);
                if (status == FX_NUMERIC_OK)
                    memcpy(storage->ram+0x8640u,components,sizeof components);
                if (status == FX_NUMERIC_OK) status = fx_number_to_decimal(&converted,&cell);
                if (status != FX_NUMERIC_OK) return status;
                memcpy(storage->ram+address,&converted,10);
                cell = converted;
            }
            status = fx_scalar_display_round(&value,&cell,mode,context->digits,&native);
            /* 15C9E restores the physical cell+20 record after the round leaf,
             * including when surd expansion overwrote that workspace slot. */
            memcpy(storage->ram+address+20u,&saved_companion,10);
            native = 0; /*14114 discards the scalar round leaf status.*/
        } else {
            unsigned scalar_kind = cell.bytes[0] & 0xb0u;
            if (working_pair)
                memcpy(&result->other,storage->ram+working_pair+20u,sizeof result->other);
            if (scalar_kind != 0 && scalar_kind != 0x20 && scalar_kind != 0x80) {
                fx_number_error(&value,3); status = FX_NUMERIC_OK;
            } else {
                status = scalar_kind == 0x80 ||
                    (result->other.real.bytes[0] & 0xf0u) == 0x80 ?
                    fx_eval_surd_workspace_binary(&value,storage->ram,&cell,
                        &result->other.real,(uint16_t)address,0,FX_MULTIPLY) :
                    fx_number_binary(&value,&cell,&result->other.real,FX_MULTIPLY);
                if (status == FX_NUMERIC_INVALID && (cell.bytes[0] & 0xf0u) == 0x60) {
                    fx_number converted;
                    status = fx_raw_fraction_convert(&converted,&cell);
                    if (status == FX_NUMERIC_OK) {
                        if (converted.bytes[0] >= 0xf0) fx_number_error(&value,3);
                        else status = fx_number_binary(&value,&converted,&result->other.real,FX_MULTIPLY);
                    }
                }
            }
            native = record_error(&value);
        }
        if (status != FX_NUMERIC_OK) return status;
        memcpy(storage->ram+address,&value,10);
        if (native) { reject(result,native); return FX_NUMERIC_OK; }
        if (selector == 5) {
            if (fx_eval_rich_poll(storage,&result->cancellation_checks,poll_context)) {
                reject(result,1); return FX_NUMERIC_OK;
            }
        }
    }
    return FX_NUMERIC_OK;
}
static fx_numeric_status retained_powers(fx_eval_rich_unary_result *result,
    fx_eval_storage *storage, uint8_t selector,
    const fx_eval_rich_context *poll_context, uint16_t working_pair)
{
    fx_eval_rich_context context;
    fx_eval_rich_result stage;
    fx_numeric_status status;
    unsigned iteration,count = selector == 8 ? 2 : 1;
    context = *poll_context;
    context.calculation_context = 0xc1;
    /* Only the outer16562 stage performs captured-context cleanup. The
     * reusable binary entry has scalarC1 cleanup, which skips references. */
    for (iteration = 0; iteration < count; ++iteration) {
        context.numeric.cancel_at = poll_context->numeric.cancel_at > result->cancellation_checks ?
            poll_context->numeric.cancel_at-result->cancellation_checks : 0;
        status = working_pair ?
            fx_eval_rich_dispatch_address(&stage,storage,working_pair,
                FX_EVAL_RICH_MATRIX_MULTIPLY,&context) :
            fx_eval_rich_dispatch(&stage,storage,&result->value,&result->other,
                FX_EVAL_RICH_MATRIX_MULTIPLY,&context);
        if (status != FX_NUMERIC_OK) return status;
        result->value = stage.value; result->other = stage.other;
        result->native_status = stage.firmware_status;
        result->cancellation_checks += stage.cancellation_checks;
        if (result->native_status) break;
    }
    return FX_NUMERIC_OK;
}
static int admitted(uint8_t selector, unsigned kind)
{
    if (selector == 0) return kind == 9;
    if (selector == 2 || selector == 5) return kind == 6 || kind == 9;
    return kind == 6;
}
static fx_numeric_status converted_scalar(fx_number *out, const fx_number *in)
{
    unsigned kind = in->bytes[0] & 0xb0u;
    if (kind == 0x20) return fx_raw_fraction_convert(out,in);
    fx_number_error(out,3); return FX_NUMERIC_OK;
}
static fx_numeric_status wrapped_scalar(fx_eval_rich_unary_result *result,
                                          uint8_t selector)
{
    fx_number converted;
    fx_numeric_status status = converted_scalar(&converted,&result->value.real);
    unsigned native_status;
    if (status != FX_NUMERIC_OK) return status;
    if (selector == 164) {
        status = fx_raw_decimal_exp(&result->value.real,&converted,&native_status);
        if (status == FX_NUMERIC_OK) result->native_status = (uint8_t)native_status;
    } else {
        fx_decimal decoded;
        if (converted.bytes[0] < 0xf0 && fx_decimal_decode(&decoded,&converted) != FX_NUMERIC_OK)
            return FX_NUMERIC_UNIMPLEMENTED;
        status = fx_hyperbolic_decimal(&result->value.real,&converted,
            selector == 162 ? FX_COSINE : FX_TANGENT,1);
        if (status == FX_NUMERIC_OK) result->native_status = record_error(&result->value.real);
    }
    return status;
}
static uint8_t component_error(const fx_number *number)
{
    return number->bytes[0] >= 0xf0u ? number->bytes[0] & 15u : 0;
}
static void reject_leaf(fx_eval_rich_unary_result *result, uint8_t status)
{
    fx_number_error(&result->value.real,status);
    result->native_status = status;
}
static int sample_cancel(fx_eval_rich_unary_result *result,
    fx_eval_storage *storage, const fx_eval_rich_context *context)
{
    if (!fx_eval_rich_poll(storage,&result->cancellation_checks,context)) return 0;
    reject_leaf(result,1);
    return 1;
}

/* 142FA copies the physical source before CEC0 and11110. The prepared
 * nine-cell array is private CPU-local state in native code. A callback can
 * change a source that has not been read yet; it cannot change this snapshot. */
static fx_numeric_status prepare_cell(fx_number *out, const fx_number *input)
{
    fx_rational fraction;
    *out = *input;
    if ((out->bytes[0] & 0xf0u) == 0x40u) out->bytes[0] &= (uint8_t)~0x40u;
    if (fx_number_recognize_rational(&fraction,out))
        return fx_rational_encode(out,&fraction);
    return FX_NUMERIC_OK;
}

/* A nonzero destination represents the native scalar current record.
 * It is copied before the call and committed immediately afterwards. The
 * other operand has already been copied to a private CPU-local record.
 * Determinant accumulators and second cofactor products use address0. */
static fx_numeric_status scalar(fx_number *out, fx_eval_storage *storage,
    const fx_number *a, const fx_number *b, fx_binary_op operation,
    uint16_t destination)
{
    fx_number left = *a,right = *b;
    fx_numeric_status status;
    if (destination) memcpy(storage->ram+destination,&left,10);
    /*1C6E0 enters the surd path before its scalar error predicate. Even an
     * unchecked surd+F* product therefore has saved/component writes. */
    if ((left.bytes[0] & 0xf0u) == 0x80u ||
        (right.bytes[0] & 0xf0u) == 0x80u) {
        status = fx_eval_surd_workspace_binary(out,storage->ram,&left,&right,
            destination,0,operation);
    } else {
        if (left.bytes[0] >= 0xf0u || right.bytes[0] >= 0xf0u) {
            fx_number_error(out,3);
            status = FX_NUMERIC_OK;
        } else status = fx_number_binary(out,&left,&right,operation);
        if (status == FX_NUMERIC_INVALID) {
            const fx_number *operands[2] = {&left,&right};
            unsigned index;
            for (index = 0; index < 2; ++index)
                if ((operands[index]->bytes[0] & 0xf0u) == 0x60u) {
                    fx_rational fraction;
                    fx_number converted;
                    if (fx_rational_decode(&fraction,operands[index]) == FX_NUMERIC_OK)
                        continue;
                    status = fx_raw_fraction_convert(&converted,operands[index]);
                    if (status != FX_NUMERIC_OK) return status;
                    if (converted.bytes[0] >= 0xf0u) {
                        fx_number_error(out,3); status = FX_NUMERIC_OK;
                    } else return FX_NUMERIC_UNIMPLEMENTED;
                    break;
                }
        }
    }
    if (status == FX_NUMERIC_OK && destination)
        memcpy(storage->ram+destination,out,10);
    return status;
}

/* 1453A: commit a*b, compute c*d privately, then reread and subtract.
 * The second product can overwrite the first physical destination through
 * the shared surd workspace, so its first product cannot be cached there. */
static fx_numeric_status cofactor(fx_number *out, fx_eval_storage *storage,
    const fx_number cells[9], unsigned a, unsigned b, unsigned c, unsigned d,
    uint16_t destination)
{
    fx_number first,second;
    fx_numeric_status status = scalar(&first,storage,&cells[a],&cells[b],
        FX_MULTIPLY,destination);
    if (status == FX_NUMERIC_OK)
        status = scalar(&second,storage,&cells[c],&cells[d],FX_MULTIPLY,0);
    if (status == FX_NUMERIC_OK) {
        if (destination) memcpy(&first,storage->ram+destination,10);
        status = scalar(out,storage,&first,&second,FX_SUBTRACT,destination);
    }
    return status;
}
static fx_numeric_status triple(fx_number *out, fx_eval_storage *storage,
    const fx_number cells[9], unsigned a, unsigned b, unsigned c)
{
    fx_number first;
    fx_numeric_status status = scalar(&first,storage,&cells[a],&cells[b],FX_MULTIPLY,0);
    return status == FX_NUMERIC_OK ?
        scalar(out,storage,&first,&cells[c],FX_MULTIPLY,0) : status;
}

static fx_numeric_status determinant(fx_number *out,
    fx_eval_rich_unary_result *result, fx_eval_storage *storage,
    const fx_number cells[9], unsigned size, const fx_eval_rich_context *context)
{
    static const unsigned cycles[6][3] = {
        {0,4,8},{1,5,6},{2,3,7},{2,4,6},{1,3,8},{0,5,7}};
    fx_number product;
    fx_numeric_status status;
    unsigned index;
    if (size == 1) { *out = cells[0]; return FX_NUMERIC_OK; }
    if (size == 2) {
        status = cofactor(out,storage,cells,0,4,1,3,0);
        if (status != FX_NUMERIC_OK) return status;
        if (component_error(out)) reject_leaf(result,component_error(out));
        else (void)sample_cancel(result,storage,context);
        return FX_NUMERIC_OK;
    }
    status = triple(out,storage,cells,0,4,8);
    for (index = 1; status == FX_NUMERIC_OK && index < 6; ++index) {
        status = triple(&product,storage,cells,cycles[index][0],
            cycles[index][1],cycles[index][2]);
        if (status == FX_NUMERIC_OK)
            status = scalar(out,storage,out,&product,index < 3 ? FX_ADD : FX_SUBTRACT,0);
        /*14392 samples after all three positive terms, even if their
         * accumulator already has an arithmetic error header. */
        if (index == 2 && sample_cancel(result,storage,context)) return status;
    }
    if (status != FX_NUMERIC_OK) return status;
    if (component_error(out)) reject_leaf(result,component_error(out));
    else (void)sample_cancel(result,storage,context);
    return FX_NUMERIC_OK;
}

/* 14400 CCF6 may unfold an opposite-sign determinant into pool0..5 and
 * convert at pool0 before testing for zero. Its source is a private record,
 * so these writes do not corrupt the compact source during178BA. */
static fx_numeric_status determinant_classify(uint8_t *classification,
    fx_eval_storage *storage, const fx_number *number)
{
    fx_number parts[6],converted;
    fx_numeric_status status;
    if ((number->bytes[0] & 0xf0u) == 0x80u && number->bytes[9] &&
        (uint8_t)(number->bytes[8]+number->bytes[9]) == 7) {
        status = fx_surd_unpack(parts,number);
        if (status == FX_NUMERIC_OK)
            memcpy(storage->ram+0x8640u,parts,sizeof parts);
        if (status == FX_NUMERIC_OK) status = fx_number_to_decimal(&converted,number);
        if (status != FX_NUMERIC_OK) return status;
        memcpy(storage->ram+0x8640u,&converted,10);
    }
    return fx_scalar_numeric_classify(classification,number);
}

/* Frozen94EC fraction admission: only bounded integer pairs are packed;
 * larger integer division must retain its native ordinary guard digits. */
static fx_numeric_status fraction_divide(fx_number *out,
    fx_eval_storage *storage, const fx_number *a, const fx_number *b)
{
    int64_t numerator,denominator;
    fx_number left = *a,right = *b;
    fx_numeric_status status;
    left.bytes[0] &= (uint8_t)~0x40u;
    right.bytes[0] &= (uint8_t)~0x40u;
    if (((left.bytes[0] & 0xf0u) != 0 && (left.bytes[0] & 0xf0u) != 0x20u) ||
        ((right.bytes[0] & 0xf0u) != 0 && (right.bytes[0] & 0xf0u) != 0x20u)) {
        fx_number_error(out,3); return FX_NUMERIC_OK;
    }
    if (left.bytes[0] < 10 && right.bytes[0] < 10 &&
        fx_number_fractional_status(&left) == 0 &&
        fx_number_fractional_status(&right) == 0 &&
        fx_decimal_to_integer(&numerator,&left) == FX_NUMERIC_OK &&
        fx_decimal_to_integer(&denominator,&right) == FX_NUMERIC_OK && denominator) {
        fx_rational ratio;
        if (denominator < 0) { numerator = -numerator; denominator = -denominator; }
        ratio.numerator = numerator;
        ratio.denominator = (uint64_t)denominator;
        ratio.flags = 0;
        return fx_rational_encode(out,&ratio);
    }
    status = scalar(out,storage,&left,&right,FX_DIVIDE,0);
    if (status == FX_NUMERIC_INVALID) {
        const fx_number *operands[2] = {&left,&right};
        unsigned index;
        /* CA3E admission has already cleared bit40. A callback can place
         * a malformed2x/6x fraction in a future physical numerator after
         * cofactor construction. Preserve the proven scalar converter's
         * finite error result instead of reporting a host input error. */
        for (index = 0; index < 2; ++index)
            if ((operands[index]->bytes[0] & 0xf0u) == 0x20u) {
                fx_rational fraction;
                fx_number converted;
                if (fx_rational_decode(&fraction,operands[index]) == FX_NUMERIC_OK)
                    continue;
                status = fx_raw_fraction_convert(&converted,operands[index]);
                if (status != FX_NUMERIC_OK) return status;
                if (converted.bytes[0] >= 0xf0u) {
                    fx_number_error(out,3); return FX_NUMERIC_OK;
                }
                return FX_NUMERIC_UNIMPLEMENTED;
            }
    }
    return status;
}

/* API: mappedselector3(det) or6(inverse), after16538 storage handling.
 * Source/output host objects must be outside storage.ram. The result carries
 * the input's unchanged imaginary/other records and the real native R0.
 * Already performed physical writes and callback actions survive a host gap.
 * Square dimensions>3 remain an explicit nativeCPU-frame boundary. */
static fx_numeric_status callback_determinant(
    fx_eval_rich_unary_result *out, fx_eval_storage *storage,
    const fx_complex *current, const fx_complex *other, uint8_t selector,
    const fx_eval_rich_context *context)
{
    static const unsigned cofactors[9][4] = {
        {4,8,5,7},{2,7,1,8},{1,5,2,4},
        {5,6,3,8},{0,8,2,6},{2,3,0,5},
        {3,7,4,6},{1,6,0,7},{0,4,1,3}};
    fx_eval_rich_unary_result result;
    fx_number prepared[9],source,det,value;
    fx_numeric_status status;
    uint8_t classification;
    unsigned identity,dimensions,base,size,columns,row,column,index;
    if (!out || !storage || !storage->ram || storage->ram_size != 65536u ||
        !current || !other || !context || (selector != 3 && selector != 6))
        return FX_NUMERIC_INVALID;
    result.value = *current; result.other = *other;
    result.native_status = 0; result.cancellation_checks = 0;
    if ((current->real.bytes[0] >> 4) != 6) {
        reject_leaf(&result,3); goto done;
    }
    identity = current->real.bytes[0] & 15u;
    dimensions = 0x80e0u+2u*identity;
    size = storage->ram[dimensions]; columns = storage->ram[dimensions+1u];
    if (!size || !columns || size != columns) {
        reject_leaf(&result,9); goto done;
    }
    if (size > 3) return FX_NUMERIC_UNIMPLEMENTED;
    base = 0x829eu+90u*identity;
    for (index = 0; index < 9; ++index) fx_number_zero(&prepared[index]);
    for (row = 0; row < size; ++row) for (column = 0; column < size; ++column) {
        index = 3u*row+column;
        memcpy(&source,storage->ram+base+10u*index,10);
        status = prepare_cell(&prepared[index],&source);
        if (status != FX_NUMERIC_OK) return status;
        if (sample_cancel(&result,storage,context)) goto done;
    }
    status = determinant(&det,&result,storage,prepared,size,context);
    if (status != FX_NUMERIC_OK) return status;
    if (result.native_status) goto done;
    if (selector == 3) {
        result.value.real = det; goto done;
    }
    status = determinant_classify(&classification,storage,&det);
    if (status != FX_NUMERIC_OK) return status;
    if (classification == 1) { reject_leaf(&result,3); goto done; }
    if (size == 1) {
        fx_decimal_from_u8(&value,1);
        memcpy(storage->ram+base,&value,10);
    } else if (size == 2) {
        /*14424,1442A,14430,14438: all four physical commits precede poll. */
        memcpy(storage->ram+base,&prepared[4],10);
        status = fx_number_negate(&value,&prepared[1]);
        if (status != FX_NUMERIC_OK) return status;
        memcpy(storage->ram+base+10u,&value,10);
        status = fx_number_negate(&value,&prepared[3]);
        if (status != FX_NUMERIC_OK) return status;
        memcpy(storage->ram+base+30u,&value,10);
        memcpy(storage->ram+base+40u,&prepared[0],10);
        if (sample_cancel(&result,storage,context)) goto done;
    } else for (index = 0; index < 9; ++index) {
        status = cofactor(&value,storage,prepared,cofactors[index][0],
            cofactors[index][1],cofactors[index][2],cofactors[index][3],
            (uint16_t)(base+10u*index));
        if (status != FX_NUMERIC_OK) return status;
        if (index % 3u == 2u && sample_cancel(&result,storage,context)) goto done;
    }
    if ((det.bytes[0] >> 4) >= 6) { reject_leaf(&result,3); goto done; }
    for (row = 0; row < size; ++row) for (column = 0; column < size; ++column) {
        index = 3u*row+column;
        memcpy(&source,storage->ram+base+10u*index,10);
        status = fraction_divide(&value,storage,&source,&det);
        if (status != FX_NUMERIC_OK) return status;
        memcpy(storage->ram+base+10u*index,&value,10);
        if (component_error(&value)) {
            reject_leaf(&result,component_error(&value)); goto done;
        }
        if (sample_cancel(&result,storage,context)) goto done;
    }
done:
    *out = result;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_eval_rich_unary_after_storage(
    fx_eval_rich_unary_result *out, fx_eval_storage *storage,
    const fx_complex *current, const fx_complex *other, uint8_t selector,
    const fx_eval_rich_context *context, uint16_t working_pair)
{
    fx_eval_rich_unary_result result;
    fx_linalg_value input;
    fx_linalg_result leaf;
    fx_linalg_context numeric;
    fx_complex_dispatch_context captured;
    fx_numeric_status status;
    unsigned identity, kind;
    if (!out || !storage || !storage->ram || storage->ram_size != 65536u ||
        !current || !other || !context) return FX_NUMERIC_INVALID;
    if (working_pair && ((working_pair & 1u) || working_pair > 65536u-40u))
        return FX_NUMERIC_UNIMPLEMENTED;
    result.value = *current; result.other = *other;
    result.native_status = 0; result.cancellation_checks = 0;
    captured = fx_complex_dispatch_default_context();
    captured.exact_math = context->numeric.exact_math;
    captured.calculation_context = storage->ram[0x80f9];
    captured.display_mode = storage->ram[0x8102];
    captured.digits = storage->ram[0x8103];
    if (selector == 162 || selector == 163 || selector == 164) {
        status = wrapped_scalar(&result,selector);
    } else if (selector <= 8) {
        kind = result.value.real.bytes[0] >> 4;
        if (selector == 5) {
            (void)fx_decimal_from_integer(&result.other.real,-1);
            if (captured.calculation_context == 0xc4)
                (void)fx_decimal_from_integer(&result.other.imaginary,2);
            if (working_pair)
                memcpy(storage->ram+working_pair+20u,&result.other,sizeof result.other);
        }
        if (!admitted(selector,kind) ||
            (selector >= 7 && result.other.real.bytes[0] >> 4 != 6)) {
            reject(&result,3); status = FX_NUMERIC_OK;
        } else if (selector == 3 || selector == 6) {
            status = callback_determinant(&result,storage,&result.value,&result.other,
                selector,context);
        } else if (selector == 7 || selector == 8) {
            status = retained_powers(&result,storage,selector,context,working_pair);
        } else {
            identity = slot(&result.value.real);
            load(&input,storage,&result.value.real);
            if (!input.rows || !input.columns) {
                reject(&result,9); status = FX_NUMERIC_OK;
            } else if (selector == 4) {
                fx_number swap;
                unsigned row,col;
                uint8_t dimension = input.rows;
                input.rows = input.columns; input.columns = dimension;
                for (row = 1; row < 3; ++row) for (col = 0; col < row; ++col) {
                    swap = input.cells[row*3+col];
                    input.cells[row*3+col] = input.cells[col*3+row];
                    input.cells[col*3+row] = swap;
                }
                commit(storage,identity,&input); status = FX_NUMERIC_OK;
            } else if ((selector == 3 || selector == 6) && input.rows != input.columns) {
                reject(&result,9); status = FX_NUMERIC_OK;
            } else if (selector == 1 || selector == 2 || selector == 5) {
                status = live_cells(&result,storage,input.rows,input.columns,identity,
                    selector,&captured,context,working_pair);
            } else if ((selector != 0 && input.rows > 3) ||
                       input.columns > (selector == 0 ? 9 : 3))
                return FX_NUMERIC_UNIMPLEMENTED;
            else {
                fx_linalg_context_default(&numeric);
                numeric.exact_math = captured.exact_math;
                status = live_magnitude(&leaf,storage,&input,&numeric);
                if (status == FX_NUMERIC_OK) {
                    result.value.real = leaf.value.reference;
                    result.native_status = leaf.firmware_status;
                    result.cancellation_checks = leaf.cancellation_checks;
                }
            }
        }
    } else return FX_NUMERIC_UNIMPLEMENTED;
    if (status != FX_NUMERIC_OK) return status;
    if (working_pair) {
        /* Scalar-returning leaves and error exits replace the real record.
         * Reference-preserving leaves leave callback changes in that record
         * live. Both cases reread the imaginary and other work records. */
        if (result.native_status || selector == 0 || selector == 3 || selector >= 162)
            memcpy(storage->ram+working_pair,&result.value.real,10);
        memcpy(&result.value,storage->ram+working_pair,sizeof result.value);
        memcpy(&result.other,storage->ram+working_pair+20u,sizeof result.other);
    }
    status = fx_complex_dispatch_cleanup(&result.value,&result.value,
        result.native_status,&captured,&result.native_status);
    if (status == FX_NUMERIC_OK) {
        if (working_pair) memcpy(storage->ram+working_pair,&result.value,sizeof result.value);
        *out = result;
    }
    return status;
}
