#include "fx_result_format_state.h"

static int fractional_part_nonzero(const fx_number *value)
{
    fx_number decimal;
    fx_decimal decoded;
    if (fx_number_to_decimal(&decimal, value) != FX_NUMERIC_OK
        || fx_decimal_integer_cleanup(&decimal) != FX_NUMERIC_OK
        || fx_decimal_decode(&decoded, &decimal) != FX_NUMERIC_OK || !decoded.mantissa
        || decoded.exponent >= 14) return 0;
    if (decoded.exponent < 0) return 1;
    uint64_t divisor = 1;
    for (int n = decoded.exponent; n < 14; ++n) divisor *= 10;
    return decoded.mantissa % divisor != 0;
}

static void store_result_kind(fx_render *render, const fx_number *value,
                              uint8_t selection_byte, uint8_t kind)
{
    uint8_t selection = selection_byte & 15, previous = selection_byte >> 4;
    uint8_t current = selection;
    if (kind >= 2 && kind <= 9) current = kind;
    int sexagesimal_fallback = kind == 10 &&
        (selection == 1 || (selection > 10 && previous == 1)
         || ((value->bytes[0] & 0xf0) == 0x40
             && (selection == 0 || (selection == 13 && !previous))));
    fx_number unmarked = *value;
    unmarked.bytes[0] &= (uint8_t)~0x40;
    fx_rational recognized_value;
    int recurring_fallback = selection == 14 && kind != 14
        && fractional_part_nonzero(value)
        && (fx_number_kind(value) == FX_NUMBER_RATIONAL
            || (fx_number_kind(value) == FX_NUMBER_DECIMAL
                && fx_number_recognize_rational(&recognized_value, &unmarked)));
    if (sexagesimal_fallback || (recurring_fallback && (kind < 2 || kind > 9))) current = 10;
    if (current != selection || sexagesimal_fallback || recurring_fallback || (kind >= 2 && kind <= 9))
        render->memory[0x8130] = 0;
    render->memory[0x8100] = (uint8_t)(current | (kind << 4));
}

/* AB8E enters the display-port sleep operation for a nonzero fractional
 * part before trying fraction/surd recognition. Integers, DMS-first and
 * engineering/decimal-only paths bypass it. Prime factorization calls it
 * unconditionally. These are persistent LCD/MMIO writes; record-only
 * formatting deliberately leaves them to the controller. */
static void formatter_display_state(fx_render *render, const fx_number *value,
                                     uint8_t selection_byte)
{
    uint8_t selection = selection_byte & 15, previous = selection_byte >> 4;
    if (selection >= 1 && selection <= 10) return;
    if ((value->bytes[0] & 0xf0) == 0x40
        && (selection == 0 || (selection == 13 && !previous))) return;
    if (selection != 15 && !fractional_part_nonzero(value)) return;
    if (!(render->memory[0x80fc] & 0x10)) render->memory[0xf031] = 6;
    render->memory[0xf800] &= (uint8_t)~0x14;
    render->memory[0xf801] &= (uint8_t)~2;
    render->memory[0xf802] &= (uint8_t)~0x40;
    render->memory[0xf80b] &= (uint8_t)~0x90;
    render->memory[0xf80a] &= (uint8_t)~8;
}

void fx_apply_result_format_state(fx_render *render, const fx_number *value,
                                   uint8_t selection_byte, uint8_t result_kind)
{
    formatter_display_state(render, value, selection_byte);
    store_result_kind(render, value, selection_byte, result_kind);
}
