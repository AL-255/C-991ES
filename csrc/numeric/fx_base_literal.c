/* BASE-N digit scanning and signed radix literal semantics, native16828.
 * GPL-3.0-or-later. No original ROM execution or host floating point. */
#include "fx_base.h"
#include "../parse/fx_tokens.h"
#include <string.h>

fx_numeric_status fx_base_parse_literal(fx_number *out, const uint8_t *tokens,
                                       size_t length, uint8_t input_base,
                                       uint8_t selected_base,
                                       fx_base_literal_result *result)
{
    unsigned radix, width, count = 0, state = 0;
    uint32_t word = 0;
    size_t cursor;
    fx_number original, parsed;
    fx_numeric_status status;
    unsigned encoding_status;
    if (!out || !tokens || !result) return FX_NUMERIC_INVALID;
    switch (input_base) {
    case FX_BASE_BIN: radix = 2; width = 16; break;
    case FX_BASE_OCT: radix = 8; width = 11; break;
    case FX_BASE_DEC: radix = 10; width = 10; break;
    case FX_BASE_HEX: radix = 16; width = 8; break;
    default: return FX_NUMERIC_UNIMPLEMENTED;
    }
    if (selected_base != FX_BASE_BIN && selected_base != FX_BASE_OCT &&
        selected_base != FX_BASE_DEC && selected_base != FX_BASE_HEX)
        return FX_NUMERIC_UNIMPLEMENTED;
    original = *out;
    memset(result, 0, sizeof(*result));
    for (cursor = 0; cursor < length; ++cursor) {
        fx_evaluator_token token = fx_decode_evaluator_token(tokens[cursor], 2);
        result->consumed = cursor + 1;
        if (token.kind > 10) {
            result->native_status = 2;
            return FX_NUMERIC_OK;
        }
        if (token.kind == 4) {
            if (token.value > input_base) {
                result->native_status = 2;
                return FX_NUMERIC_OK;
            }
            if (!token.value && state != 2) { state = 1; continue; }
            state = 2;
            if (count == width ||
                (input_base == FX_BASE_OCT && count == 10 && word >= UINT32_C(536870912)) ||
                (input_base == FX_BASE_DEC && count == 9 &&
                 ((uint64_t)word * 10 + token.value > UINT64_C(2147483647)))) {
                result->native_status = 3;
                return FX_NUMERIC_OK;
            }
            word = word * radix + token.value;
            ++count;
            continue;
        }
        if (!state) {
            result->native_status = 2;
            return FX_NUMERIC_OK;
        }
        if (state == 1) {
            fx_number_zero(&parsed);
        } else if (input_base == FX_BASE_DEC) {
            status = fx_decimal_from_integer(&parsed, (int64_t)word);
            if (status != FX_NUMERIC_OK) return status;
            if (selected_base == FX_BASE_BIN && word >= 32768) {
                *out = parsed;
                result->native_status = 3;
                return FX_NUMERIC_OK;
            }
        } else {
            /* The binary input width is16; HEX/OCT accumulate32 bits. */
            if (input_base == FX_BASE_BIN && (word & UINT32_C(0x8000)))
                word |= UINT32_C(0xffff0000);
            status = fx_base_encode_word(&parsed, word, selected_base, &encoding_status);
            if (status != FX_NUMERIC_OK) return status;
            if (encoding_status) {
                /* 168CE..168D4 clears the mantissa tail before checking the
                 * signed-word serializer, leaving byte0/exponent/sign. */
                *out = original;
                memset(out->bytes + 1, 0, 7);
                result->native_status = 3;
                return FX_NUMERIC_OK;
            }
        }
        *out = parsed;
        result->consumed = cursor;
        result->native_kind = 4;
        return FX_NUMERIC_OK;
    }
    /* A bounded host input must supply the following token that the native
     * scanner reads. Do not manufacture a terminator beyond its capacity. */
    return FX_NUMERIC_INVALID;
}
