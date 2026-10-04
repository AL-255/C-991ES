#include "fx_linalg_dispatch.h"
#include "../numeric/fx_base.h"
#include "fx_linalg_reduce.h"
#include <string.h>
#include "../numeric/fx_raw_fraction_convert.h"
#include "../numeric/fx_raw_decimal_exp.h"
#include "../trig/fx_trig_hyperbolic.h"

static int reference(const fx_number *number)
{
    unsigned kind = number->bytes[0] & 0xf0;
    return kind == 0x60 || kind == 0x90;
}
static int native_reference(const fx_number *number)
{
    unsigned header = number->bytes[0];
    return header >= 0x90 || (header >= 0x60 && header < 0x80);
}
static int valid(const fx_linalg_bank *bank,
                 const fx_linalg_dispatch_context *context)
{
    unsigned i;
    if (!bank || !context || (context->calculation_context != 6 &&
        context->calculation_context != 7) || context->numeric.exact_math > 1 ||
        context->numeric.digits > 9 || (context->numeric.display_mode != 0 &&
        context->numeric.display_mode != 4 && context->numeric.display_mode != 8 &&
        context->numeric.display_mode != 9)) return 0;
    for (i = 0; i < 9; ++i)
        if (bank->slots[i].rows > 3 || bank->slots[i].columns > 3) return 0;
    return 1;
}
void fx_linalg_dispatch_context_default(fx_linalg_dispatch_context *context,
                                        uint8_t calculation_context)
{
    if (!context) return;
    context->calculation_context = calculation_context;
    fx_linalg_context_default(&context->numeric);
}
static int admitted(const fx_number *number, unsigned flags)
{
    unsigned kind = number->bytes[0] >> 4;
    if (kind == 15) return 0;
    if (flags == 255) return 1;
    if (!flags) return kind >= 6 && kind != 8;
    return !((flags & 1 && kind == 9) || (flags & 2 && kind == 6));
}
static void begin(fx_linalg_dispatch_result *out, const fx_complex *input)
{
    out->value = *input; out->firmware_status = 0;
    out->cancellation_checks = 0;
}
static fx_numeric_status cleanup(fx_linalg_dispatch_result *out)
{
    fx_numeric_status status;
    if (out->firmware_status || out->value.real.bytes[0] >= 0x60)
        return FX_NUMERIC_OK;
    status = fx_decimal_integer_cleanup(&out->value.real);
    if (status == FX_NUMERIC_OK)
        out->firmware_status = out->value.real.bytes[0] >= 0xf0 ?
            out->value.real.bytes[0] & 15 : 0;
    return status;
}
/* Admission and token selection occasionally expose an error header as a
 * rich operand. Load the literal low slot, retaining its header for the leaf
 * to reject; the public bank_value API intentionally accepts only6x/9x. */
static fx_numeric_status load(fx_linalg_value *out, const fx_linalg_bank *bank,
                              const fx_number *number)
{
    unsigned identity = number->bytes[0] & 15;
    if (identity >= 9) {
        /* High-F arithmetic candidates are rejected by the leaf's kind
         * check before native bank addressing. Keep a dummy backing for
         * that safe path; genuine out-of-bank references remain invalid. */
        if ((number->bytes[0] & 0xf0) != 0xf0) return FX_NUMERIC_INVALID;
        memset(out,0,sizeof *out); out->reference = *number;
        return FX_NUMERIC_OK;
    }
    out->reference = *number;
    out->rows = bank->slots[identity].rows;
    out->columns = bank->slots[identity].columns;
    memcpy(out->cells,bank->slots[identity].cells,sizeof out->cells);
    return FX_NUMERIC_OK;
}
static void release(fx_linalg_bank *bank, const fx_number *number)
{
    unsigned identity = number->bytes[0] & 15;
    if (identity >= 4 && identity <= 8) fx_linalg_bank_release(bank,identity);
    else if (identity >= 9)
        bank->temporary_mask &= (uint8_t)~(0x80 >> ((identity-4) & 7));
}
static fx_numeric_status temporary(fx_linalg_dispatch_result *out,
                                    fx_linalg_bank *bank, int always)
{
    unsigned source = out->value.real.bytes[0] & 15, destination;
    if (!always && source >= 4) return FX_NUMERIC_OK;
    if (source >= 9) return FX_NUMERIC_INVALID;
    destination = fx_linalg_bank_first_free(bank->temporary_mask);
    if (!destination) { out->firmware_status = 7; return FX_NUMERIC_OK; }
    fx_linalg_bank_mark(bank,destination);
    fx_linalg_bank_copy(bank,destination,source);
    out->value.real.bytes[0] = (uint8_t)((out->value.real.bytes[0] & 0xf0) | destination);
    return FX_NUMERIC_OK;
}
static fx_numeric_status commit(fx_linalg_dispatch_result *out,
                                fx_linalg_bank *bank, unsigned identity,
                                const fx_linalg_result *leaf)
{
    fx_numeric_status status = identity < 9 ?
        fx_linalg_bank_store_value(bank,identity,&leaf->value) :
        leaf->firmware_status == 3 ? FX_NUMERIC_OK : FX_NUMERIC_INVALID;
    if (status != FX_NUMERIC_OK) return status;
    out->value.real = leaf->value.reference;
    out->firmware_status = leaf->firmware_status;
    out->cancellation_checks = leaf->cancellation_checks;
    return cleanup(out);
}
static int real_only(uint8_t token)
{
    return token == 0x98 || token == 0xa8 || token == 0x68 || token == 0xa3 ||
        token == 0x73 || token == 0x93 || token == 0x25 || token == 0x57 ||
        (token >= 0x70 && token <= 0x72) || (token >= 0x90 && token <= 0x92) ||
        (token >= 0xa0 && token <= 0xa2) || (token >= 0xb0 && token <= 0xb2) ||
        (token >= 0x85 && token <= 0x87);
}
fx_numeric_status fx_linalg_dispatch_unary(fx_linalg_dispatch_result *out,
    fx_linalg_bank *bank, const fx_complex *input, uint8_t token,
    const fx_linalg_dispatch_context *context)
{
    fx_linalg_dispatch_result result;
    fx_linalg_value value;
    fx_linalg_result leaf;
    fx_linalg_context numeric;
    fx_numeric_status status;
    fx_linalg_unary_op operation;
    unsigned kind, identity;
    int scalar_output = 0, new_slot = 0, reduced = -1, scalar_leaf = 0;
    if (!out || !input || !valid(bank,context)) return FX_NUMERIC_INVALID;
    if (!reference(&input->real)) return FX_NUMERIC_UNIMPLEMENTED;
    if ((input->real.bytes[0] & 15) >= 9) return FX_NUMERIC_INVALID;
    begin(&result,input); kind = input->real.bytes[0] & 0xf0;
    if (real_only(token) || ((token >= 0x75 && token <= 0x77) && kind == 0x90)) {
        result.firmware_status = 3; *out = result; return FX_NUMERIC_OK;
    }
    switch (token) {
    case 0x61: case 0x62:
        /* Rich selector7/8 becomes162/163. Doubling its byte-sized table
         * index wraps to1C4EA/1C4D8: inverse cosh/tanh, not BASE NOT/Neg.
         * Matrix selection always stages a new copy; vectors reuse temps. */
        scalar_leaf = token == 0x61 ? 4 : 5;
        new_slot = kind == 0x60;
        operation = FX_LINALG_TRANSPOSE; break;
    case 0xc0: operation = FX_LINALG_DETERMINANT; scalar_output = kind == 0x60; break;
    case 0xc1: operation = FX_LINALG_TRANSPOSE; break;
    case 0xc3: operation = FX_LINALG_VECTOR_MAGNITUDE; break;
    case 0x88:
        scalar_leaf = kind == 0x60 ? 3 : 1;
        new_slot = kind == 0x60;
        operation = FX_LINALG_TRANSPOSE; break;
    case 0x63: operation = kind == 0x90 ? FX_LINALG_VECTOR_MAGNITUDE : FX_LINALG_ABSOLUTE; scalar_output = kind == 0x90; break;
    case 0xb3: operation = FX_LINALG_DISPLAY_ROUND; break;
    case 0x60: operation = FX_LINALG_NEGATE; break;
    case 0x77: operation = FX_LINALG_INVERSE; break;
    case 0x75: case 0x76: operation = token == 0x75 ? FX_LINALG_SQUARE : FX_LINALG_CUBE; new_slot = 1; break;
    case 0x5a: case 0x5b:
        /* Vector index adjustment selects scalar normal-R and bitwise NOT.
         * They still pass through ordinary temporary-reference allocation. */
        if (kind == 0x90) scalar_leaf = token == 0x5a ? 1 : 2;
        else reduced = token == 0x5b;
        operation = FX_LINALG_TRANSPOSE; break;
    default: return FX_NUMERIC_UNIMPLEMENTED;
    }
    if (scalar_output) release(bank,&input->real);
    else {
        status = temporary(&result,bank,new_slot);
        if (status != FX_NUMERIC_OK) return status;
        if (result.firmware_status) { *out = result; return FX_NUMERIC_OK; }
        if (new_slot) release(bank,&input->real);
    }
    if (scalar_leaf) {
        /* Both normal-R and exponential conversion reject kind9 before
         * reading payload. NOT first adds10^10: scalar conversion likewise
         * emits a canonical F3, then its unchecked ten-digit extraction sees
         * zero. Complement and signed serialization still execute. */
        fx_number failed_conversion;
        if (scalar_leaf >= 4) {
            fx_number converted;
            fx_decimal decoded;
            if (kind == 0x90) {
                fx_number_error(&result.value.real,3);
                result.firmware_status = 3;
                *out = result; return FX_NUMERIC_OK;
            }
            status = fx_raw_fraction_convert(&converted,&result.value.real);
            if (status != FX_NUMERIC_OK) return status;
            /* The unchecked fraction converter can retain malformed finite
             * digits. They are outside the ordinary hyperbolic helper's
             * contract; preserve staging, leaving the output uncommitted. */
            if (converted.bytes[0] < 0xf0 &&
                fx_decimal_decode(&decoded,&converted) != FX_NUMERIC_OK)
                return FX_NUMERIC_UNIMPLEMENTED;
            status = fx_hyperbolic_decimal(&result.value.real,&converted,
                scalar_leaf == 4 ? FX_COSINE : FX_TANGENT,1);
            if (status == FX_NUMERIC_INVALID) return FX_NUMERIC_UNIMPLEMENTED;
            if (status != FX_NUMERIC_OK) return status;
            result.firmware_status = result.value.real.bytes[0] >= 0xf0 ?
                result.value.real.bytes[0] & 15 : 0;
            status = cleanup(&result);
            if (status == FX_NUMERIC_OK) *out = result;
            return status;
        }
        if (scalar_leaf == 3) {
            fx_number converted;
            unsigned native_status;
            status = fx_raw_fraction_convert(&converted,&result.value.real);
            if (status == FX_NUMERIC_OK)
                status = fx_raw_decimal_exp(&result.value.real,&converted,&native_status);
            if (status != FX_NUMERIC_OK) return status;
            result.firmware_status = (uint8_t)native_status;
            status = cleanup(&result);
            if (status == FX_NUMERIC_OK) *out = result;
            return status;
        }
        fx_number_error(&failed_conversion,3);
        if (scalar_leaf == 1) {
            result.value.real = failed_conversion; result.firmware_status = 3;
            *out = result; return FX_NUMERIC_OK;
        } else {
            uint32_t word = 0;
            unsigned digit, native_status;
            for (digit = 1; digit <= 5; ++digit) {
                word = word * 10 + (failed_conversion.bytes[digit] >> 4);
                word = word * 10 + (failed_conversion.bytes[digit] & 15);
            }
            /* This resulting signed word fits every native radix. */
            status = fx_base_encode_word(&result.value.real,~word,
                                          FX_BASE_DEC,&native_status);
            if (status != FX_NUMERIC_OK) return status;
            result.firmware_status = (uint8_t)native_status;
            status = cleanup(&result);
            if (status == FX_NUMERIC_OK) *out = result;
            return status;
        }
    }
    identity = result.value.real.bytes[0] & 15;
    status = load(&value,bank,&result.value.real);
    numeric = context->numeric;
    /*18212 requires calculation-context bit6. Ordinary MATRIX6/VECTOR7
     * cannot enable compact-surds recognition just by setting8106. */
    if (operation == FX_LINALG_VECTOR_MAGNITUDE) numeric.exact_math = 0;
    if (status == FX_NUMERIC_OK && operation == FX_LINALG_CUBE &&
        identity == (input->real.bytes[0] & 15)) {
        /* An unmarked temporary can be selected as its own new destination.
         * Native15BFC retains a reference to that same bank slot, so its
         * second multiply reads the square just committed by the first. */
        status = fx_linalg_unary(&leaf,&value,FX_LINALG_SQUARE,&numeric);
        if (status == FX_NUMERIC_OK && !leaf.firmware_status) {
            uint32_t previous = leaf.cancellation_checks;
            numeric.cancel_at = numeric.cancel_at > previous ? numeric.cancel_at - previous : 0;
            status = fx_linalg_binary(&leaf,&leaf.value,&leaf.value,
                FX_LINALG_MATRIX_MULTIPLY,&numeric);
            leaf.cancellation_checks += previous;
        }
    } else if (status == FX_NUMERIC_OK)
        status = reduced >= 0 ? fx_linalg_echelon(&leaf,&value,reduced,&numeric) :
            fx_linalg_unary(&leaf,&value,operation,&numeric);
    if (status == FX_NUMERIC_OK) status = commit(&result,bank,identity,&leaf);
    if (status == FX_NUMERIC_OK) *out = result;
    return status;
}
fx_numeric_status fx_linalg_dispatch_binary(fx_linalg_dispatch_result *out,
    fx_linalg_bank *bank, const fx_complex *left, const fx_complex *right,
    uint8_t token, const fx_linalg_dispatch_context *context)
{
    fx_complex a,b;
    fx_linalg_dispatch_result result;
    fx_linalg_value first,second;
    fx_linalg_result leaf;
    fx_numeric_status status;
    fx_linalg_binary_op operation = FX_LINALG_ADD;
    unsigned identity;
    int scalar = 0;
    if (!out || !left || !right || !valid(bank,context)) return FX_NUMERIC_INVALID;
    a = *left; b = *right;
    if (!reference(&a.real) && !reference(&b.real)) return FX_NUMERIC_UNIMPLEMENTED;
    begin(&result,&b);
    if (token == 0x5e || token == 0x9f || token == 0xbe || token == 0xbf || token == 0x68 || token == 0x9e) {
        unsigned flags = token == 0x9e ? 0 : token == 0x5e ? 3 : 7;
        if (!admitted(&b.real,flags)) { result.firmware_status = 3; *out = result; return FX_NUMERIC_OK; }
        result.value.real = a.real;
        if (token == 0x5e && (a.real.bytes[0] & 0xf0) == 0x60) {
            result.firmware_status = 2; *out = result; return FX_NUMERIC_OK;
        }
        if (!admitted(&a.real,token == 0x5e ? 1 : flags)) {
            result.firmware_status = 3; *out = result; return FX_NUMERIC_OK;
        }
        if (token != 0x9e) return FX_NUMERIC_UNIMPLEMENTED;
    } else {
        if (token != 0x2b && token != 0x2d && token != 0x4e && token != 0x4f)
            return FX_NUMERIC_UNIMPLEMENTED;
        result.value.real = a.real;
    }
    /* Admission can safely reject F9..FF without addressing their literal
     * low slot. Bound the storage path only after those native checks. */
    if ((reference(&a.real) && (a.real.bytes[0] & 15) >= 9) ||
        (reference(&b.real) && (b.real.bytes[0] & 15) >= 9)) return FX_NUMERIC_INVALID;
    if (!native_reference(&a.real)) {
        if (token != 0x4e) { result.firmware_status = 3; *out = result; return FX_NUMERIC_OK; }
        result.value.real = b.real;
        b.real = a.real;
    }
    if (token == 0x9e) release(bank,&result.value.real);
    else {
        status = temporary(&result,bank,0);
        if (status != FX_NUMERIC_OK) return status;
        if (result.firmware_status) { *out = result; return FX_NUMERIC_OK; }
    }
    if (native_reference(&b.real)) release(bank,&b.real);
    identity = result.value.real.bytes[0] & 15;
    status = load(&first,bank,&result.value.real);
    if (status != FX_NUMERIC_OK) return status;
    switch (token) {
    case 0x2b: operation = FX_LINALG_ADD; break;
    case 0x2d: operation = FX_LINALG_SUBTRACT; break;
    case 0x9e: operation = FX_LINALG_DOT; break;
    case 0x4f: scalar = 1; break;
    default:
        if (b.real.bytes[0] >= 0x90) operation = FX_LINALG_CROSS;
        else if (b.real.bytes[0] >= 0x60 && b.real.bytes[0] < 0x80)
            operation = FX_LINALG_MATRIX_MULTIPLY;
        else scalar = 1;
    }
    if (scalar) status = fx_linalg_scalar(&leaf,&first,&b.real,
        token == 0x4f ? FX_LINALG_DIVIDE : FX_LINALG_SCALE,&context->numeric);
    else {
        /* Non-reference right records still reach the kind check in add/sub
         * and dot; their unused storage address is never dereferenced there. */
        if (native_reference(&b.real)) status = load(&second,bank,&b.real);
        else { memset(&second,0,sizeof second); second.reference = b.real; }
        if (status == FX_NUMERIC_OK) status = fx_linalg_binary(&leaf,&first,&second,operation,&context->numeric);
    }
    if (status == FX_NUMERIC_OK) status = commit(&result,bank,identity,&leaf);
    if (status == FX_NUMERIC_OK) *out = result;
    return status;
}
