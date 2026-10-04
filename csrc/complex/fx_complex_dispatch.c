/* Readable CMPLX scalar/operator selection. GPL-3.0-or-later. */
#include "fx_complex_dispatch.h"
#include "fx_complex_angle.h"
#include "fx_complex_round.h"
#include "../numeric/fx_transcend.h"
#include "../numeric/fx_root.h"
#include "../numeric/fx_combinatorics.h"
#include "../numeric/fx_logbase.h"
#include "../trig/fx_trig_inverse.h"
#include "../trig/fx_trig_hyperbolic.h"
#include <string.h>

static unsigned scalar_status(const fx_number *number)
{
    return number->bytes[0] >= 0xf0 ? number->bytes[0] & 15 : 0;
}
static int valid_context(const fx_complex_dispatch_context *context)
{
    return context && context->calculation_context == 0xc4 &&
        context->angle_unit >= 4 && context->angle_unit <= 6 &&
        context->digits <= 9;
}
fx_complex_dispatch_context fx_complex_dispatch_default_context(void)
{
    fx_complex_dispatch_context context = {0xc4,1,4,0,0};
    return context;
}
fx_numeric_status fx_complex_dispatch_cleanup(fx_complex *out, const fx_complex *in,
    uint8_t leaf_status, const fx_complex_dispatch_context *context, uint8_t *firmware_status)
{
    fx_complex value;
    fx_numeric_status status = FX_NUMERIC_OK;
    unsigned header;
    if (!out || !in || !context || !firmware_status) return FX_NUMERIC_INVALID;
    value = *in; header = value.real.bytes[0] & 0xf0;
    *firmware_status = leaf_status;
    if (!leaf_status) {
        if (context->calculation_context == 0xc4 && header != 0x80 && header != 0x40) {
            status = fx_complex_cleanup(&value,in);
            if (status == FX_NUMERIC_OK)
                status = fx_complex_firmware_status(firmware_status,FX_COMPLEX_CLEANUP_RETURN,in,&value);
        } else if ((context->calculation_context == 0xc4 && header == 0x40) ||
                   (context->calculation_context != 0xc4 && header < 0x60)) {
            status = fx_decimal_integer_cleanup(&value.real);
            if (status == FX_NUMERIC_OK) *firmware_status = (uint8_t)scalar_status(&value.real);
        }
    }
    if (status == FX_NUMERIC_OK) *out = value;
    return status;
}
fx_numeric_status fx_complex_dispatch_constant(fx_complex *out, uint8_t token,
    const fx_complex_dispatch_context *context, uint8_t *firmware_status)
{
    if (!out || !firmware_status || !valid_context(context)) return FX_NUMERIC_INVALID;
    if (token != 0x80) return FX_NUMERIC_UNIMPLEMENTED;
    fx_complex_zero(out); fx_decimal_from_u8(&out->imaginary,1);
    *firmware_status = 0; return FX_NUMERIC_OK;
}

/* Real-only admission in16336/16A14 uses the raw imaginary exponent/sign
 * word, not a numeric equality test. Compact surd cancellation is rejected.
 * The conjugate/argument/absolute prefixes permit arbitrary imaginary input,
 * but all three reject an error in the real header before calling their leaf. */
static int admitted(const fx_complex *input, int real_only, int reject_dms)
{
    unsigned header = input->real.bytes[0] & 0xf0;
    if (header == 0xf0 || (reject_dms && header == 0x90)) return 0;
    if (!real_only) return 1;
    if (header == 0x60 || header == 0x90) return 0;
    if (header == 0 || header == 0x20 || header == 0x80)
        return !input->imaginary.bytes[8] && !input->imaginary.bytes[9];
    return 1;
}
static int real_prefix(uint8_t token)
{
    return token == 0x98 || token == 0xa8 || token == 0x68 || token == 0xa3 ||
        token == 0x73 || token == 0x93 || (token >= 0x70 && token <= 0x72) ||
        (token >= 0x90 && token <= 0x92) || (token >= 0xa0 && token <= 0xa2) ||
        (token >= 0xb0 && token <= 0xb2) || token == 0x25 || token == 0x57 ||
        (token >= 0x85 && token <= 0x87);
}
fx_numeric_status fx_complex_dispatch_unary(fx_complex *out, const fx_complex *in,
    uint8_t token, const fx_complex_dispatch_context *context, uint8_t *firmware_status)
{
    fx_complex input, result;
    fx_numeric_status status;
    fx_complex_return_kind kind = FX_COMPLEX_ARITHMETIC_RETURN;
    uint8_t leaf = 0;
    int native_kind = 0, real_only = real_prefix(token);
    if (!out || !in || !firmware_status || !valid_context(context)) return FX_NUMERIC_INVALID;
    input = *in; result = input;
    if ((real_only || token == 0x63 || token == 0x88 || token == 0xc3 ||
         token == 0xb3 || (token >= 0x75 && token <= 0x77)) &&
        !admitted(&input,real_only,real_only || (token >= 0x75 && token <= 0x77))) {
        *out = input; *firmware_status = 3; return FX_NUMERIC_OK;
    }
    switch (token) {
    case 0x60: case '-':
        status = fx_complex_negate(&result,&input); kind = FX_COMPLEX_NEGATE_RETURN; native_kind = 1; break;
    case 0x88:
        status = fx_complex_conjugate(&result,&input); kind = FX_COMPLEX_CONJUGATE_RETURN; native_kind = 1; break;
    case 0xc3:
        status = fx_complex_argument(&result,&input,(fx_angle_unit)(context->angle_unit-4));
        kind = FX_COMPLEX_ARGUMENT_RETURN; native_kind = 1; break;
    case 0x63:
        status = fx_complex_magnitude(&result,&input,context->exact_math);
        kind = FX_COMPLEX_MAGNITUDE_RETURN; native_kind = 1; break;
    case 0x98:
        status = fx_complex_sqrt(&result,&input,context->exact_math);
        kind = FX_COMPLEX_SQRT_RETURN; native_kind = 1; break;
    case 0x75: case 0x76:
        status = fx_complex_integer_power(&result,&input,token == 0x75 ? 2 : 3); break;
    case 0x77:
        if (!input.imaginary.bytes[0]) status = fx_number_integer_power(&result.real,&input.real,-1);
        else status = fx_complex_integer_power(&result,&input,-1);
        break;
    case 0xb3:
        status = fx_complex_display_round(&result,&input,context->display_mode,context->digits,&leaf);
        return status == FX_NUMERIC_OK ? fx_complex_dispatch_cleanup(out,&result,leaf,context,firmware_status) : status;
    case 0xa8: status = fx_number_cbrt(&result.real,&input.real); break;
    case 0x68: status = fx_number_log10(&result.real,&input.real); break;
    case 0xa3: status = fx_number_ln(&result.real,&input.real); break;
    case 0x73: status = fx_number_exp(&result.real,&input.real); break;
    case 0x93: status = fx_number_exp10(&result.real,&input.real); break;
    case 0x25: status = fx_number_percent(&result.real,&input.real); break;
    case 0x57: status = fx_number_factorial(&result.real,&input.real); break;
    case 0x85: case 0x86: case 0x87:
        status = fx_angle_convert(&result.real,&input.real,(fx_angle_unit)(token-0x85),
                                 (fx_angle_unit)(context->angle_unit-4)); break;
    default:
        if (token >= 0x70 && token <= 0x72)
            status = fx_hyperbolic_decimal(&result.real,&input.real,(fx_trig_function)(token-0x70),0);
        else if (token >= 0x90 && token <= 0x92)
            status = fx_hyperbolic_decimal(&result.real,&input.real,(fx_trig_function)(token-0x90),1);
        else if (token >= 0xa0 && token <= 0xa2)
            status = fx_trig_evaluate(&result.real,&input.real,(fx_trig_function)(token-0xa0),
                (fx_angle_unit)(context->angle_unit-4),context->exact_math,0);
        else if (token >= 0xb0 && token <= 0xb2)
            status = fx_trig_inverse_decimal(&result.real,&input.real,(fx_trig_function)(token-0xb0),
                (fx_angle_unit)(context->angle_unit-4));
        else return FX_NUMERIC_UNIMPLEMENTED;
    }
    if (status != FX_NUMERIC_OK) return status;
    if (native_kind) status = fx_complex_firmware_status(&leaf,kind,&input,&result);
    else leaf = (uint8_t)scalar_status(&result.real);
    return status == FX_NUMERIC_OK ? fx_complex_dispatch_cleanup(out,&result,leaf,context,firmware_status) : status;
}

static fx_numeric_status prepared_dispatch_binary(fx_number *out,
    const fx_number *a, const fx_number *b, fx_binary_op operation,
    const fx_complex_preparation *preparation)
{
    return preparation && preparation->binary ?
        preparation->binary(out,a,b,operation,preparation->userdata) :
        fx_number_binary(out,a,b,operation);
}

fx_numeric_status fx_complex_dispatch_binary_with_preparation(fx_complex *out, const fx_complex *left,
    const fx_complex *right, uint8_t token, const fx_complex_dispatch_context *context,
    uint8_t *firmware_status,
    const fx_complex_preparation *preparation)
{
    static const fx_number one = {{1,0,0,0,0,0,0,0,0,1}};
    fx_complex a, b, result;
    fx_numeric_status status;
    fx_binary_op operation;
    uint8_t left_class, right_class, leaf;
    int real_path;
    int64_t fast_power;
    if (!out || !left || !right || !firmware_status || !valid_context(context)) return FX_NUMERIC_INVALID;
    switch (token) {
    case '+': operation = FX_ADD; break;
    case '-': operation = FX_SUBTRACT; break;
    case 0x4e: operation = FX_MULTIPLY; break;
    case 0x4f: operation = FX_DIVIDE; break;
    case '^': case 0x9f: case 0xbe: case 0xbf: case 0x68:
        operation = FX_ADD; break; /* Separate real-function/power selection below. */
    default: return FX_NUMERIC_UNIMPLEMENTED;
    }
    a = *left; b = *right; result = a;
    if (token == 0x9f || token == 0xbe || token == 0xbf || token == 0x68) {
        /* The parser admits the right argument first, restores the left, then
         * admits it before these leaves. Either rejection preserves the left pair. */
        if (!admitted(&b,1,1) || !admitted(&a,1,1)) {
            *out = a; *firmware_status = 3; return FX_NUMERIC_OK;
        }
        if (token == 0x9f) status = fx_number_nthroot(&result.real,&b.real,&a.real);
        else if (token == 0xbe) status = fx_number_permutation(&result.real,&a.real,&b.real);
        else if (token == 0xbf) status = fx_number_combination(&result.real,&a.real,&b.real);
        else status = fx_number_log_base(&result.real,&a.real,&b.real);
        if (status != FX_NUMERIC_OK) return status;
        return fx_complex_dispatch_cleanup(out,&result,(uint8_t)scalar_status(&result.real),
                                           context,firmware_status);
    }
    status = preparation && preparation->classify ?
        preparation->classify(&left_class,&a.imaginary,preparation->userdata) :
        fx_scalar_numeric_classify(&left_class,&a.imaginary);
    if (status != FX_NUMERIC_OK) return status;
    real_path = left_class == 1;
    if (real_path) {
        status = preparation && preparation->classify ?
        preparation->classify(&right_class,&b.imaginary,preparation->userdata) :
        fx_scalar_numeric_classify(&right_class,&b.imaginary);
        if (status != FX_NUMERIC_OK) return status;
        real_path = right_class == 1;
    }
    if (token == '^') status = real_path ? fx_number_power(&result.real,&a.real,&b.real)
                                         : fx_complex_power(&result,&a,&b);
    else if (real_path) {
        if (a.real.bytes[0] >= 0xf0 || b.real.bytes[0] >= 0xf0) {
            fx_number_error(&result.real,3); status = FX_NUMERIC_OK;
        } else status = prepared_dispatch_binary(&result.real,&a.real,&b.real,operation,preparation);
    }
    else if (operation == FX_MULTIPLY && b.imaginary.bytes[0] == 1 &&
             !memcmp(&b.imaginary,&one,sizeof(one))) {
        status = preparation && preparation->classify ?
        preparation->classify(&right_class,&b.real,preparation->userdata) :
        fx_scalar_numeric_classify(&right_class,&b.real);
        if (status != FX_NUMERIC_OK) return status;
        if (right_class == 1) {
            /* Native16000 negates old imaginary, rotates old real to imaginary,
             * clears the marker on new imaginary and forces a zero leaf return. */
            result.imaginary = a.real; result.imaginary.bytes[0] &= (uint8_t)~0x40;
            status = fx_number_negate(&result.real,&a.imaginary);
            return status == FX_NUMERIC_OK ? fx_complex_dispatch_cleanup(out,&result,0,context,firmware_status) : status;
        }
        status = fx_complex_binary_with_preparation(&result,&a,&b,operation,preparation);
    } else status = fx_complex_binary_with_preparation(&result,&a,&b,operation,preparation);
    if (status != FX_NUMERIC_OK) return status;
    leaf = (uint8_t)scalar_status(&result.real);
    /* General real power1118E reports30 on its format guard, even though
     * the numerical output isF3. Its short decimal powers bypass that guard. */
    if (token == '^' && real_path &&
        !(fx_number_kind(&b.real) == FX_NUMBER_DECIMAL &&
          fx_decimal_to_integer(&fast_power,&b.real) == FX_NUMERIC_OK &&
          (fast_power == -1 || fast_power == 2 || fast_power == 3)) &&
        (((a.real.bytes[0] & 0xf0) >= 0x30 && (a.real.bytes[0] & 0xf0) != 0x40 &&
          (a.real.bytes[0] & 0xf0) != 0x80) ||
         ((b.real.bytes[0] & 0xf0) >= 0x30 && (b.real.bytes[0] & 0xf0) != 0x40 &&
          (b.real.bytes[0] & 0xf0) != 0x80))) leaf = 0x30;
    return fx_complex_dispatch_cleanup(out,&result,leaf,context,firmware_status);
}

fx_numeric_status fx_complex_dispatch_binary(fx_complex *out, const fx_complex *left,
    const fx_complex *right, uint8_t token, const fx_complex_dispatch_context *context,
    uint8_t *firmware_status)
{
    return fx_complex_dispatch_binary_with_preparation(out,left,right,token,
        context,firmware_status,NULL);
}
