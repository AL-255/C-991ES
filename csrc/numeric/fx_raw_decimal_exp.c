/* Readable unchecked exponential boundary around the existing factor core.
 * GPL-3.0-or-later. No machine state or instruction interpretation. */
#include "fx_raw_decimal_exp.h"
#include "fx_raw_decimal_parts.h"
#include "fx_raw_decimal_divide.h"
#include "fx_transcend.h"
#include "fx_transcend_guarded.h"
#include <string.h>

#define RAW_COORDINATE_MODULUS UINT64_C(1000000000000000000)

static const uint64_t logarithm_coefficient[19] = {
    UINT64_C(43429448190325183), UINT64_C(30102999566398120),
    UINT64_C(41392685158225041), UINT64_C(43213737826425743),
    UINT64_C(43407747931864067), UINT64_C(43427276862669637),
    UINT64_C(43429231044531869), UINT64_C(43429426475615564),
    UINT64_C(43429446018852918), UINT64_C(43429447973177943),
    UINT64_C(43429448168610459), UINT64_C(43429448188153710),
    UINT64_C(43429448190108036), UINT64_C(43429448190303468),
    UINT64_C(43429448190323011), UINT64_C(43429448190324966),
    UINT64_C(43429448190325161), UINT64_C(43429448190325181),
    UINT64_C(43429448190325183)
};

static void read_external(uint8_t raw[10], const fx_number *external) {
    raw[0] = external->bytes[8]; raw[1] = external->bytes[9];
    for (unsigned i = 0; i < 8; ++i) raw[i+2] = external->bytes[7-i];
}
static void write_external(fx_number *external, const uint8_t raw[10]) {
    for (unsigned i = 0; i < 8; ++i) external->bytes[i] = raw[9-i];
    external->bytes[8] = raw[0]; external->bytes[9] = raw[1];
}
static void shift_pairs(uint8_t pairs[9], int left) {
    unsigned carry = 0;
    if (left) {
        for (unsigned i = 0; i < 9; ++i) {
            unsigned pair = pairs[i];
            pairs[i] = (uint8_t)((pair << 4) | carry);
            carry = pair >> 4;
        }
    } else {
        for (unsigned i = 9; i > 0; --i) {
            unsigned pair = pairs[i-1];
            pairs[i-1] = (uint8_t)((pair >> 4) | carry);
            carry = (pair & 15u) << 4;
        }
    }
}
static void add_mantissa(uint8_t out[8], const uint8_t left[8],
                          const uint8_t right[8]) {
    unsigned carry = 0;
    for (unsigned i = 0; i < 8; ++i)
        out[i] = fx_raw_decimal_pair_add(left[i],right[i],&carry);
}

fx_numeric_status fx_raw_decimal_exp_argument(uint8_t out[10],
                                               uint8_t *guard,
                                               const fx_number *converted) {
    uint8_t input[10], twice[8], triple[8], accumulator[9] = {0};
    unsigned carry = 0;
    if (!out || !guard || !converted) return FX_NUMERIC_INVALID;
    read_external(input,converted);
    if (input[9] >= 240u) {
        memcpy(out,input,10); *guard = 0; return FX_NUMERIC_OK;
    }
    out[0] = fx_raw_decimal_pair_add(153,input[0],&carry);
    out[1] = fx_raw_decimal_pair_add(0,input[1],&carry);
    carry = 0;
    out[1] = fx_raw_decimal_pair_subtract(out[1],1,&carry) & 15u;
    add_mantissa(twice,input+2,input+2);
    add_mantissa(triple,twice,input+2);
    uint64_t coefficient = logarithm_coefficient[0];
    for (unsigned position = 0; position < 17; ++position) {
        unsigned digit = (unsigned)(coefficient % 10);
        coefficient /= 10;
        for (unsigned group = 0; group < digit / 3; ++group)
            add_mantissa(accumulator+1,accumulator+1,triple);
        for (unsigned single = 0; single < digit % 3; ++single)
            add_mantissa(accumulator+1,accumulator+1,input+2);
        if (position + 1 < 17) shift_pairs(accumulator,0);
    }
    *guard = accumulator[0];
    if (accumulator[8] >= 16u)
        *guard = (uint8_t)((accumulator[1] << 4) | (accumulator[0] >> 4));
    memcpy(out+2,accumulator+1,8);
    fx_raw_decimal_normalize(out);
    return FX_NUMERIC_OK;
}

static void coefficient_pairs(uint8_t pairs[9], uint64_t value) {
    for (unsigned i = 0; i < 9; ++i) {
        unsigned low = (unsigned)(value % 10); value /= 10;
        unsigned high = (unsigned)(value % 10); value /= 10;
        pairs[i] = (uint8_t)(low | (high << 4));
    }
}
static uint64_t decimal_pairs(const uint8_t pairs[9]) {
    uint64_t value = 0;
    for (unsigned i = 9; i > 0; --i)
        value = value * 100 + (pairs[i-1] >> 4) * 10 + (pairs[i-1] & 15u);
    return value;
}
static unsigned finish(fx_number *out, unsigned *native_status) {
    *native_status = out->bytes[0] >= 240u ? out->bytes[0] & 15u : 0;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_raw_decimal_exp(fx_number *out,
                                      const fx_number *converted,
                                      unsigned *native_status) {
    fx_number source, value;
    fx_decimal ordinary;
    uint8_t argument[10], guard, field[9], coefficient[9], difference[9];
    uint8_t raw_value[10], one[10] = {0,1,0,0,0,0,0,0,0,1};
    unsigned whole = 0;
    if (!out || !converted || !native_status) return FX_NUMERIC_INVALID;
    source = *converted;
    if (source.bytes[0] >= 240u) {
        *out = source;
        return (fx_numeric_status)finish(out,native_status);
    }
    if (fx_decimal_decode(&ordinary,&source) == FX_NUMERIC_OK) {
        fx_numeric_status status = fx_number_exp(out,&source);
        if (status == FX_NUMERIC_OK) finish(out,native_status);
        return status;
    }
    fx_numeric_status status = fx_raw_decimal_exp_argument(argument,&guard,&source);
    if (status != FX_NUMERIC_OK) return status;
    if (argument[9] >= 240u) {
        write_external(out,argument);
        return (fx_numeric_status)finish(out,native_status);
    }
    unsigned kind = argument[1];
    if (kind != 0 && kind != 1 && kind != 5 && kind != 6)
        return FX_NUMERIC_UNIMPLEMENTED;
    int negative = kind >= 5;
    int exponent = (argument[0] >> 4) * 10 + (argument[0] & 15u);
    if (kind == 0 || kind == 5) exponent -= 100;
    if (exponent >= 2) {
        if (negative) fx_number_zero(out);
        else fx_number_error(out,3);
        return (fx_numeric_status)finish(out,native_status);
    }
    field[0] = guard;
    memcpy(field+1,argument+2,8);
    if ((argument[9] & 15u) >= 1u) {
        while (exponent >= 0) {
            whole = field[8];
            shift_pairs(field,1);
            --exponent;
        }
        field[8] &= 15u;
        field[0] &= 240u;
    } else {
        field[0] = (uint8_t)(kind == 1 || kind == 6);
    }
    unsigned borrow = 0;
    for (unsigned i = 0; i < 9; ++i)
        difference[i] = fx_raw_decimal_pair_subtract(field[i],i == 0 ? 1 : 0,&borrow);
    if (borrow) {
        (void)fx_decimal_from_integer(&value,1);
    } else {
        if (exponent < -99 || exponent > -1) return FX_NUMERIC_UNIMPLEMENTED;
        unsigned factor = (unsigned)(-1-exponent);
        uint64_t selected = logarithm_coefficient[factor < 18 ? factor+1 : 0];
        coefficient_pairs(coefficient,selected);
        borrow = 0;
        for (unsigned i = 0; i < 9; ++i)
            difference[i] = fx_raw_decimal_pair_subtract(field[i],coefficient[i],&borrow);
        /* The first committed subtraction decimal-corrects every pair.
         * Recover its equivalent canonical coordinate, retaining the exact
         * coefficient. Native restoration on borrow produces this value. */
        uint64_t coordinate = (decimal_pairs(difference) + selected) % RAW_COORDINATE_MODULUS;
        status = fx_transcend_exp10_guarded(&value,coordinate,exponent,1);
        if (status != FX_NUMERIC_OK) return status;
    }
    read_external(raw_value,&value);
    unsigned carry = 0;
    raw_value[0] = fx_raw_decimal_pair_add(raw_value[0],(uint8_t)whole,&carry);
    if (carry) {
        if (negative) fx_number_zero(out);
        else fx_number_error(out,3);
        return (fx_numeric_status)finish(out,native_status);
    }
    if (negative) {
        status = fx_raw_decimal_divide(raw_value,one,raw_value);
        if (status != FX_NUMERIC_OK) return status;
    }
    fx_raw_decimal_normalize(raw_value);
    write_external(out,raw_value);
    return (fx_numeric_status)finish(out,native_status);
}
