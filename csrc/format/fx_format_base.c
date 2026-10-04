/* Readable BASE-N decimal extraction and radix serialization158B8.
 * GPL-3.0-or-later. No instruction execution or host floating point. */
#include "fx_format_base.h"
#include <string.h>

typedef struct { uint8_t *tokens; size_t capacity, length; } base_writer;

static void append(base_writer *writer, unsigned token)
{
    if (writer->length + 1 < writer->capacity) writer->tokens[writer->length] = (uint8_t)token;
    ++writer->length;
}
static fx_format_status finish(base_writer *writer, fx_format_result *result,
                               fx_format_status status)
{
    if (writer->capacity)
        writer->tokens[writer->length < writer->capacity ? writer->length : writer->capacity - 1] = 0;
    result->length = writer->length;
    if (status == FX_FORMAT_OK && writer->length >= writer->capacity) return FX_FORMAT_BUFFER_TOO_SMALL;
    return status;
}

fx_format_status fx_format_base(const fx_number *number, uint8_t base_mask,
                                uint8_t *tokens, size_t capacity,
                                fx_format_result *result)
{
    fx_decimal value;
    fx_number absolute, bias, biased;
    fx_numeric_status numeric_status;
    base_writer writer = {tokens, capacity, 0};
    uint64_t magnitude = 0;
    uint32_t word;
    unsigned index, width, bits;
    int negative;
    if (!number || !result || (!tokens && capacity)) return FX_FORMAT_INVALID;
    memset(result, 0, sizeof(*result));
    if (number->bytes[0] >= 0x10) return finish(&writer, result, FX_FORMAT_OK);
    if (base_mask != 1 && base_mask != 7 && base_mask != 9 && base_mask != 15)
        return finish(&writer, result, FX_FORMAT_UNIMPLEMENTED);
    if (fx_decimal_decode(&value, number) != FX_NUMERIC_OK)
        return finish(&writer, result, FX_FORMAT_UNIMPLEMENTED);
    negative = value.sign < 0;
    value.sign = value.mantissa ? 1 : 0;
    (void)fx_decimal_encode(&absolute, &value);
    (void)fx_decimal_from_integer(&bias, INT64_C(10000000000));
    numeric_status = fx_decimal_binary(&biased, &absolute, &bias, FX_ADD);
    if (numeric_status != FX_NUMERIC_OK || fx_number_kind(&biased) != FX_NUMBER_DECIMAL)
        return finish(&writer, result, FX_FORMAT_UNIMPLEMENTED);
    /* 15A1E adds10^10, then15A56 reads the ten mantissa digits immediately
     * after the leading digit. This also preserves the native behavior for
     * fractional and out-of-range decimal records supplied directly. */
    for (index = 1; index <= 5; ++index) {
        magnitude = magnitude * 10 + (biased.bytes[index] >> 4);
        magnitude = magnitude * 10 + (biased.bytes[index] & 15);
    }
    if (base_mask == 9) {
        uint8_t digits[10]; unsigned count = 0;
        if (negative) append(&writer, 0x60);
        do { digits[count++] = (uint8_t)(magnitude % 10); magnitude /= 10; } while (magnitude);
        while (count) append(&writer, '0' + digits[--count]);
        return finish(&writer, result, FX_FORMAT_OK);
    }
    word = (uint32_t)magnitude;
    if (base_mask == 1 && (word > 32768 || (word == 32768 && !negative)))
        return finish(&writer, result, FX_FORMAT_OK);
    if (negative) word = UINT32_C(0) - word;
    width = base_mask == 1 ? 16 : base_mask == 7 ? 11 : 8;
    bits = base_mask == 1 ? 1 : base_mask == 7 ? 3 : 4;
    while (width--) {
        unsigned digit = (word >> (width * bits)) & base_mask;
        append(&writer, digit + '0' + (digit >= 10 ? 126 : 0));
    }
    return finish(&writer, result, FX_FORMAT_OK);
}
