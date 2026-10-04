/* High-level translations of the BASE-N prepared numeric kernels.
 * GPL-3.0-or-later. Integer and packed-decimal arithmetic only. */
#include "fx_base.h"

static int valid_base(uint8_t base)
{
    return base == FX_BASE_BIN || base == FX_BASE_OCT ||
           base == FX_BASE_DEC || base == FX_BASE_HEX;
}

static fx_numeric_status ordinary_decimal(fx_decimal *value,
                                           const fx_number *number)
{
    if (!number) return FX_NUMERIC_INVALID;
    if (number->bytes[0] >= 0x10) return FX_NUMERIC_UNIMPLEMENTED;
    return fx_decimal_decode(value, number);
}

static fx_numeric_status truncate_decimal(fx_number *out,
                                          const fx_number *number)
{
    fx_decimal value;
    fx_numeric_status status = ordinary_decimal(&value, number);
    uint64_t divisor = 1;
    int index;
    if (status != FX_NUMERIC_OK) return status;
    if (!value.mantissa || value.exponent < 0) {
        fx_number_zero(out);
        return FX_NUMERIC_OK;
    }
    if (value.exponent < 14) {
        for (index = value.exponent; index < 14; ++index) divisor *= 10;
        value.mantissa -= value.mantissa % divisor;
    }
    return fx_decimal_encode(out, &value);
}

fx_numeric_status fx_base_decode_word(uint32_t *word, unsigned *carry,
                                     const fx_number *number, uint8_t base_mask)
{
    fx_decimal value;
    fx_number absolute, bias, biased;
    fx_numeric_status status;
    uint32_t magnitude = 0;
    unsigned index;
    int negative;
    if (!word || !carry || !number) return FX_NUMERIC_INVALID;
    if (!valid_base(base_mask)) return FX_NUMERIC_UNIMPLEMENTED;
    status = ordinary_decimal(&value, number);
    if (status != FX_NUMERIC_OK) return status;
    negative = value.sign < 0;
    value.sign = value.mantissa ? 1 : 0;
    status = fx_decimal_encode(&absolute, &value);
    if (status != FX_NUMERIC_OK) return status;
    (void)fx_decimal_from_integer(&bias, INT64_C(10000000000));
    status = fx_decimal_binary(&biased, &absolute, &bias, FX_ADD);
    if (status != FX_NUMERIC_OK || fx_number_kind(&biased) != FX_NUMBER_DECIMAL)
        return FX_NUMERIC_UNIMPLEMENTED;
    /* 15A56 takes ten mantissa digits, without consulting the exponent.
     * Thus raw huge/fractional inputs retain the original extraction rule. */
    for (index = 1; index <= 5; ++index) {
        magnitude = magnitude * 10 + (biased.bytes[index] >> 4);
        magnitude = magnitude * 10 + (biased.bytes[index] & 15);
    }
    *carry = base_mask == FX_BASE_BIN &&
             (magnitude > 32768 || (magnitude == 32768 && !negative));
    *word = negative && !*carry ? UINT32_C(0) - magnitude : magnitude;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_base_encode_word(fx_number *out, uint32_t word,
                                     uint8_t base_mask, unsigned *native_status)
{
    int64_t signed_value;
    if (!out || !native_status) return FX_NUMERIC_INVALID;
    if (!valid_base(base_mask)) return FX_NUMERIC_UNIMPLEMENTED;
    /* Widen before subtracting: a uint32_t -> int32_t cast would depend on
     * the implementation for words whose top bit is set. */
    signed_value = word < UINT32_C(0x80000000) ? (int64_t)word :
                   (int64_t)word - INT64_C(4294967296);
    *native_status = base_mask == FX_BASE_BIN &&
                     (signed_value < -32768 || signed_value > 32767) ? 3 : 0;
    if (*native_status) return FX_NUMERIC_OK;
    return fx_decimal_from_integer(out, signed_value);
}

fx_numeric_status fx_base_validate(const fx_number *number, uint8_t base_mask,
                                  unsigned *native_status)
{
    fx_decimal value;
    fx_numeric_status status;
    uint64_t limit_mantissa;
    int limit_exponent, comparison;
    if (!number || !native_status) return FX_NUMERIC_INVALID;
    if (!valid_base(base_mask)) return FX_NUMERIC_UNIMPLEMENTED;
    status = ordinary_decimal(&value, number);
    if (status != FX_NUMERIC_OK) return status;
    if (!value.mantissa) { *native_status = 0; return FX_NUMERIC_OK; }
    limit_mantissa = base_mask == FX_BASE_BIN ? UINT64_C(327680000000000) :
                                               UINT64_C(214748364800000);
    limit_exponent = base_mask == FX_BASE_BIN ? 4 : 9;
    comparison = value.exponent < limit_exponent ? -1 :
                 value.exponent > limit_exponent ? 1 :
                 value.mantissa < limit_mantissa ? -1 :
                 value.mantissa > limit_mantissa ? 1 : 0;
    *native_status = (value.sign < 0 ? comparison > 0 : comparison >= 0) ? 3 : 0;
    return FX_NUMERIC_OK;
}

/* 1CCF6 tests the packed sign fields. Its surd branch deliberately does
 * not apply the ordinary zero test after an opposite-sign conversion. */
static fx_numeric_status raw_scalar_classify(uint8_t *classification,
                                              const fx_number *number)
{
    unsigned header = number->bytes[0] & 0xf0;
    unsigned sign;
    fx_number converted;
    fx_numeric_status status;
    if (!number->bytes[0]) *classification = 1;
    else if (header == 0x80) {
        sign = number->bytes[9] ? number->bytes[8] + number->bytes[9] :
                                 number->bytes[8];
        if (number->bytes[9] && sign == 7) {
            status = fx_number_to_decimal(&converted, number);
            if (status != FX_NUMERIC_OK) return status;
            sign = converted.bytes[9];
        }
        *classification = sign >= 4 ? 2 : 4;
    } else if (header >= 0x50) *classification = 0xf0;
    else if (!number->bytes[8] && !number->bytes[9]) *classification = 1;
    else *classification = number->bytes[9] >= 4 ? 2 : 4;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_base_validate_raw(const fx_number *number,
                                      uint8_t base_mask,
                                      unsigned *native_status)
{
    uint8_t classification;
    fx_numeric_status status;
    if (!number || !native_status) return FX_NUMERIC_INVALID;
    if (!valid_base(base_mask)) return FX_NUMERIC_UNIMPLEMENTED;
    if (fx_number_kind(number) == FX_NUMBER_UNSUPPORTED)
        return FX_NUMERIC_UNIMPLEMENTED;
    status = raw_scalar_classify(&classification, number);
    if (status != FX_NUMERIC_OK) return status;
    if (classification == 1) {
        *native_status = 0;
        return FX_NUMERIC_OK;
    }
    /* CD60/AB36/AB3E compares only records whose raw header is below 0A.
     * Rejected comparisons return F0. 15E82 requires comparison == 2
     * for a positive value, but comparison != 2 for every other class. */
    if (number->bytes[0] >= 0x0a) {
        *native_status = classification == 4 ? 3 : 0;
        return FX_NUMERIC_OK;
    }
    return fx_base_validate(number, base_mask, native_status);
}

static fx_numeric_status truncate_raw_scalar(fx_number *out,
                                              const fx_number *number,
                                              unsigned *native_status)
{
    fx_number converted;
    fx_numeric_status status = fx_number_to_decimal(&converted, number);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_number_kind(&converted) == FX_NUMBER_ERROR) {
        *out = converted;
        *native_status = converted.bytes[0] & 15;
        return FX_NUMERIC_OK;
    }
    /* 1D040 converts the scalar and removes its marker before truncation. */
    converted.bytes[0] &= 0xbf;
    return truncate_decimal(out, &converted);
}

fx_numeric_status fx_base_prepare(fx_number *out, const fx_number *number,
                                 uint8_t base_mask, unsigned *native_status)
{
    fx_numeric_status status;
    if (!out || !number || !native_status) return FX_NUMERIC_INVALID;
    if (!valid_base(base_mask)) return FX_NUMERIC_UNIMPLEMENTED;
    status = truncate_decimal(out, number);
    if (status != FX_NUMERIC_OK) return status;
    return fx_base_validate(out, base_mask, native_status);
}

fx_numeric_status fx_base_prepare_scalar(fx_number *out, const fx_number *number,
                                        uint8_t base_mask, unsigned *native_status)
{
    fx_number source, converted;
    fx_numeric_status status;
    if (!out || !number || !native_status) return FX_NUMERIC_INVALID;
    if (!valid_base(base_mask)) return FX_NUMERIC_UNIMPLEMENTED;
    source = *number;
    if (fx_number_kind(&source) == FX_NUMBER_ERROR) {
        fx_number_error(out, 3); *native_status = 3;
        return FX_NUMERIC_OK;
    }
    if (source.bytes[0] < 0x80) source.bytes[0] &= 0xbf;
    status = fx_number_to_decimal(&converted, &source);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_number_kind(&converted) == FX_NUMBER_ERROR) {
        fx_number_error(out, 3); *native_status = 3;
        return FX_NUMERIC_OK;
    }
    return fx_base_prepare(out, &converted, base_mask, native_status);
}

fx_numeric_status fx_base_unary(fx_number *out, const fx_number *number,
                               uint8_t base_mask, fx_base_unary_op operation,
                               unsigned *native_status)
{
    uint32_t word;
    unsigned carry;
    fx_number original;
    fx_numeric_status status;
    if (!out || !number || !native_status) return FX_NUMERIC_INVALID;
    if (operation != FX_BASE_NOT && operation != FX_BASE_NEGATE)
        return FX_NUMERIC_INVALID;
    original = *number;
    status = fx_base_decode_word(&word, &carry, &original, base_mask);
    if (status != FX_NUMERIC_OK) return status;
    if (operation == FX_BASE_NOT) {
        /* The original NOT ignores conversion/serialization errors, which
         * can loop forever on invalid BIN records. Those raw paths are not
         * a prepared operation and remain explicitly unsupported. */
        if (carry) return FX_NUMERIC_UNIMPLEMENTED;
        word = ~word;
    } else {
        word = UINT32_C(0) - word;
        if (word == UINT32_C(0x80000000)) {
            *out = original; *native_status = 3;
            return FX_NUMERIC_OK;
        }
    }
    *out = original;
    status = fx_base_encode_word(out, word, base_mask, native_status);
    if (operation == FX_BASE_NOT && status == FX_NUMERIC_OK && *native_status)
        return FX_NUMERIC_UNIMPLEMENTED;
    return status;
}

fx_numeric_status fx_base_binary(fx_number *out, const fx_number *left,
                                const fx_number *right, uint8_t base_mask,
                                fx_base_binary_op operation,
                                unsigned *native_status)
{
    fx_number a, b, result;
    fx_decimal check;
    fx_numeric_status status;
    uint32_t first, second, word;
    unsigned carry_first, carry_second;
    if (!out || !left || !right || !native_status) return FX_NUMERIC_INVALID;
    if (!valid_base(base_mask)) return FX_NUMERIC_UNIMPLEMENTED;
    if (operation < FX_BASE_ADD || operation > FX_BASE_AND) return FX_NUMERIC_INVALID;
    a = *left; b = *right;
    if (operation <= FX_BASE_DIVIDE) {
        /* The C6 arithmetic wrappers reject every incoming F* record at
         * AB64/BF7A, rather than propagating its original error code. */
        if (fx_number_kind(&a) == FX_NUMBER_ERROR ||
            fx_number_kind(&b) == FX_NUMBER_ERROR) {
            fx_number_error(out, 3);
            *native_status = 3;
            return FX_NUMERIC_OK;
        }
        status = fx_number_binary(&result, &a, &b, (fx_binary_op)operation);
        if (status != FX_NUMERIC_OK) return status;
        *native_status = fx_number_kind(&result) == FX_NUMBER_ERROR ?
                         result.bytes[0] & 15 : 0;
        if (!*native_status) {
            if (operation == FX_BASE_DIVIDE)
                status = truncate_raw_scalar(&result, &result, native_status);
            else status = fx_base_validate_raw(&result, base_mask, native_status);
        }
        if (status != FX_NUMERIC_OK) return status;
        *out = result;
        return FX_NUMERIC_OK;
    }
    status = ordinary_decimal(&check, &a);
    if (status != FX_NUMERIC_OK) return status;
    status = ordinary_decimal(&check, &b);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_base_decode_word(&first, &carry_first, &a, base_mask);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_base_decode_word(&second, &carry_second, &b, base_mask);
    if (status != FX_NUMERIC_OK) return status;
    if (carry_first || carry_second) return FX_NUMERIC_UNIMPLEMENTED;
    switch (operation) {
    case FX_BASE_OR: word = first | second; break;
    case FX_BASE_XOR: word = first ^ second; break;
    case FX_BASE_XNOR: word = ~(first ^ second); break;
    default: word = first & second; break;
    }
    status = fx_base_encode_word(&result, word, base_mask, native_status);
    if (status != FX_NUMERIC_OK) return status;
    if (*native_status) return FX_NUMERIC_UNIMPLEMENTED;
    *out = result;
    return FX_NUMERIC_OK;
}
