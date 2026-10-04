/* Handwritten prepared DMS and unit-conversion kernels. GPL-3.0-or-later.
 * Original ROM constants remain immutable data; no instruction execution. */
#include "fx_sexagesimal.h"
#include "../data/fx_rom_data.h"
#include <string.h>

/*15C82 makes an ordinary scalar decimal, but leaves an unmasked header
 * above4F unchanged. Its caller here deliberately ignores that condition.
 * Ordinary arithmetic can subsequently clear40 from a surviving6x header. */
static fx_numeric_status prepare(fx_number *out, const fx_number *input) {
    fx_number value = *input;
    fx_numeric_status status;
    if ((value.bytes[0] & 0xf0) == 0x80) {
        status = fx_number_to_decimal(&value, &value);
        if (status != FX_NUMERIC_OK) return status;
    }
    if (value.bytes[0] <= 0x4f) {
        value.bytes[0] &= (uint8_t)~0x40;
        status = fx_number_to_decimal(&value, &value);
        if (status != FX_NUMERIC_OK) return status;
    }
    *out = value;
    return FX_NUMERIC_OK;
}

/*1BFxx uses the ordinary scalar loader, not the exact arithmetic dispatcher.
 * AB64 clears40 on non-F headers while saving the operand marker count. */
static fx_numeric_status ordinary(fx_number *out, const fx_number *a,
                                   const fx_number *b, fx_binary_op operation) {
    fx_number first, second;
    fx_numeric_status status;
    if ((fx_number_kind(a) != FX_NUMBER_DECIMAL && fx_number_kind(a) != FX_NUMBER_RATIONAL) ||
        (fx_number_kind(b) != FX_NUMBER_DECIMAL && fx_number_kind(b) != FX_NUMBER_RATIONAL)) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    if (fx_number_kind(a) == FX_NUMBER_RATIONAL) {
        status = fx_number_to_decimal(&first, a);
        if (status != FX_NUMERIC_OK) return status;
        first.bytes[0] |= a->bytes[0] & 0x40; a = &first;
    }
    if (fx_number_kind(b) == FX_NUMBER_RATIONAL) {
        status = fx_number_to_decimal(&second, b);
        if (status != FX_NUMERIC_OK) return status;
        second.bytes[0] |= b->bytes[0] & 0x40; b = &second;
    }
    if (fx_number_kind(a) == FX_NUMBER_ERROR || fx_number_kind(b) == FX_NUMBER_ERROR) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    return operation == FX_SUBTRACT ? fx_decimal_subtract_cancel(out, a, b) :
                                     fx_decimal_binary(out, a, b, operation);
}

static fx_numeric_status composition(fx_number *out, const fx_number *a,
                                      const fx_number *b, fx_binary_op operation) {
    if (fx_number_kind(a) == FX_NUMBER_ERROR || fx_number_kind(b) == FX_NUMBER_ERROR ||
        fx_number_kind(a) == FX_NUMBER_UNSUPPORTED || fx_number_kind(b) == FX_NUMBER_UNSUPPORTED) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    return fx_number_binary(out, a, b, operation);
}

fx_numeric_status fx_number_sexagesimal(fx_number *out,
                                        const fx_number *components,
                                        size_t count) {
    fx_number sum, value, divisor;
    fx_numeric_status status;
    size_t component;
    if (!out || !components || count < 1 || count > 3) return FX_NUMERIC_INVALID;
    fx_number_zero(&sum);
    /* The native reducer starts with seconds, then minutes, then degrees.
     * Its individual rational/surd preparations and storage boundaries must
     * remain in this order; a single exact weighted sum rounds differently. */
    for (component = count; component > 0; --component) {
        status = prepare(&value, &components[component - 1]);
        if (status != FX_NUMERIC_OK) return status;
        if (component > 1) {
            (void)fx_decimal_from_integer(&divisor, component == 3 ? 3600 : 60);
            status = composition(&value, &value, &divisor, FX_DIVIDE);
            if (status != FX_NUMERIC_OK) return status;
        }
        if (component == 3) {
            sum = value; continue;
        }
        status = composition(&sum, &value, &sum, FX_ADD);
        if (status != FX_NUMERIC_OK) return status;
    }
    status = fx_decimal_integer_cleanup(&sum);
    if (status != FX_NUMERIC_OK) return status;
    if (fx_number_kind(&sum) != FX_NUMBER_ERROR &&
        (sum.bytes[9] == 0 || sum.bytes[9] == 5 || sum.bytes[8] < 7))
        sum.bytes[0] |= 0x40;
    *out = sum;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_number_unit_convert(fx_number *out, const fx_number *input,
                                         unsigned conversion) {
    fx_number value, factor, offset;
    fx_numeric_status status;
    if (!out || !input || conversion >= 40) return FX_NUMERIC_INVALID;
    status = prepare(&value, input);
    if (status != FX_NUMERIC_OK) return status;
    memcpy(factor.bytes, fx_rom_data + 0x2814 + (conversion / 2) * 10, 10);
    memcpy(offset.bytes, fx_rom_data + 0x2622, 10);
    if (conversion == 37) {
        status = ordinary(&value, &value, &offset, FX_SUBTRACT);
        if (status != FX_NUMERIC_OK) return status;
    }
    status = ordinary(&value, &value, &factor,
                       conversion & 1 ? FX_DIVIDE : FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) return status;
    if (conversion == 36) {
        status = ordinary(&value, &value, &offset, FX_ADD);
        if (status != FX_NUMERIC_OK) return status;
    }
    status = fx_decimal_integer_cleanup(&value);
    if (status != FX_NUMERIC_OK) return status;
    *out = value;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_number_scientific_constant(fx_number *out, unsigned index) {
    if (!out || index >= 40) return FX_NUMERIC_INVALID;
    memcpy(out->bytes, fx_rom_data + 0x264a + index * 10, 10);
    return FX_NUMERIC_OK;
}
