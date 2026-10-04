/* Decimal digit budgets used by3500, with shared33D6/3374 glyph semantics.
 * GPL-3.0-or-later. No ROM execution or host floating point. */
#include "fx_format_budget.h"
#include <string.h>

typedef struct { uint8_t *tokens; size_t capacity, length; } budget_writer;

static void append(budget_writer *writer, unsigned token)
{
    if (writer->length + 1 < writer->capacity)
        writer->tokens[writer->length] = (uint8_t)token;
    ++writer->length;
}

static fx_format_status finish(budget_writer *writer, fx_format_result *result,
                               fx_format_status status)
{
    if (writer->capacity)
        writer->tokens[writer->length < writer->capacity ? writer->length : writer->capacity - 1] = 0;
    result->length = writer->length;
    if (status == FX_FORMAT_OK && writer->length >= writer->capacity)
        return FX_FORMAT_BUFFER_TOO_SMALL;
    return status;
}

static void round_ten(fx_decimal *value)
{
    const uint64_t unit = UINT64_C(100000);
    uint64_t original = value->mantissa;
    value->mantissa = ((original + unit / 2) / unit) * unit;
    if (value->mantissa < UINT64_C(1000000000000000)) return;
    /* CC90 retries overflowing exponent99 with truncation. */
    if (value->exponent == 99) value->mantissa = original / unit * unit;
    else { value->mantissa /= 10; ++value->exponent; }
}

fx_format_status fx_format_budget(const fx_number *number, uint8_t budget,
                                  uint8_t small_exponent, uint8_t extended_norm,
                                  uint8_t decimal_dot, uint8_t *tokens,
                                  size_t capacity, fx_format_result *result)
{
    budget_writer writer = {tokens, capacity, 0};
    fx_number decimal;
    fx_decimal value;
    uint8_t digits[15], exponent_tokens[4];
    unsigned digit_base = budget == 6 ? 0xd0 : '0';
    unsigned point = budget == 6 ? (decimal_dot ? 0xdc : 0xed) : (decimal_dot ? '.' : ',');
    unsigned exponent_prefix = small_exponent ? 0xe0 : budget == 6 ? 0xdd : 0x90;
    unsigned exponent_digit = small_exponent ? 0xf0 : budget == 6 ? 0xd0 : 0xa0;
    unsigned count, width, exponent_length, magnitude;
    int last, scientific, exponent;
    if (!result || (!tokens && capacity)) return FX_FORMAT_INVALID;
    memset(result, 0, sizeof(*result)); result->kind = 10;
    if (budget != 6 && budget != 12) return finish(&writer, result, FX_FORMAT_INVALID);
    if (!number) return finish(&writer, result, FX_FORMAT_OK);
    /* 15C82 first converts a surd, then rejects a header above4F. In
     * particular a marked rational6x produces ERROR rather than following
     * the ordinary rational2x decimal-conversion path. */
    decimal = *number;
    if (fx_number_kind(number) == FX_NUMBER_SURD &&
        fx_number_to_decimal(&decimal, number) != FX_NUMERIC_OK)
        return finish(&writer, result, FX_FORMAT_INVALID);
    if (decimal.bytes[0] > 0x4f) {
        static const uint8_t error[] = {'E', 'R', 'R', 'O', 'R'};
        static const uint8_t small_error[] = {0xe4, 0xe9, 0xe9, 0xe7, 0xe9};
        for (count = 0; count < 5; ++count)
            append(&writer, budget == 6 ? small_error[count] : error[count]);
        return finish(&writer, result, FX_FORMAT_OK);
    }
    if (fx_number_to_decimal(&decimal, &decimal) != FX_NUMERIC_OK)
        return finish(&writer, result, FX_FORMAT_INVALID);
    decimal.bytes[0] &= (uint8_t)~0x40;
    if (fx_decimal_decode(&value, &decimal) != FX_NUMERIC_OK)
        return finish(&writer, result, FX_FORMAT_INVALID);
    round_ten(&value);
    magnitude = (unsigned)(value.exponent < 0 ? -value.exponent : value.exponent);
    exponent_length = magnitude >= 10 ? 4 : 3;
    exponent_tokens[0] = (uint8_t)exponent_prefix;
    exponent_tokens[1] = (uint8_t)(exponent_prefix + (value.exponent < 0 ? 2 : 1));
    if (magnitude >= 10) exponent_tokens[2] = (uint8_t)(exponent_digit + magnitude / 10);
    exponent_tokens[exponent_length - 1] = (uint8_t)(exponent_digit + magnitude % 10);
    {
        uint64_t mantissa = value.mantissa;
        for (last = 14; last >= 0; --last) { digits[last] = (uint8_t)(mantissa % 10); mantissa /= 10; }
    }
    width = budget;
    if (value.mantissa && value.sign < 0) {
        append(&writer, budget == 6 ? 0xdb : 0x60); --width;
    }
    exponent = value.exponent;
    scientific = exponent >= 10 || exponent < (extended_norm ? -3 : -2) || exponent >= (int)width;
    if (!value.mantissa) { append(&writer, digit_base); return finish(&writer, result, FX_FORMAT_OK); }
    if (scientific) {
        count = width - exponent_length;
        if (value.sign >= 0 || count > 1) --count;
        last = (int)count - 1;
        while (last > 0 && !digits[last]) --last;
        append(&writer, digit_base + digits[0]);
        if (last) append(&writer, point);
        for (int i = 1; i <= last; ++i) append(&writer, digit_base + digits[i]);
        for (count = 0; count < exponent_length; ++count) append(&writer, exponent_tokens[count]);
    } else if (exponent < 0) {
        count = (unsigned)(exponent + (int)width - 1);
        last = (int)count - 1;
        while (last > 0 && !digits[last]) --last;
        append(&writer, digit_base); append(&writer, point);
        for (int i = 0; i < -exponent - 1; ++i) append(&writer, digit_base);
        for (int i = 0; i <= last; ++i) append(&writer, digit_base + digits[i]);
    } else {
        count = exponent <= (int)width - 2 ? width - 1 : width;
        last = (int)count - 1;
        while (last > exponent && !digits[last]) --last;
        for (int i = 0; i <= last; ++i) {
            append(&writer, digit_base + digits[i]);
            if (i == exponent && last > exponent) append(&writer, point);
        }
    }
    return finish(&writer, result, FX_FORMAT_OK);
}
