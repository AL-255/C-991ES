#include "fx_result_linear.h"
#include "fx_render_memory.h"
#include "fx_render_context.h"
#include "fx_result_format_state.h"
#include "../format/fx_format.h"

#include <string.h>

/* 0x3664: width arithmetic deliberately uses a byte even for longer text.
 * The underlying 0x3A4A font-dependent start bound and maximum count remain. */
static void right_aligned_text(fx_render *r, const uint8_t *text, size_t length)
{
    uint8_t x = (uint8_t)(96 - (uint8_t)(length * 6));
    unsigned advance = r->memory[0x811f] == 6 ? 4 : 6;
    unsigned maximum = r->memory[0x811f] == 6 ? 24 : 16;
    for (unsigned n = 0; n < length && text[n] && x <= 96 - advance && n < maximum;
         ++n, x = (uint8_t)(x + advance))
        fx_draw_glyph(r, x, 22, text[n]);
}

/* AF5A/796E with the legacy branch's complete second-line text. */
static void history(fx_render *r, const uint8_t *text, size_t length)
{
    memcpy(r->memory + 0x9838, text, length + 1);
    memset(r->memory + 0x9804, 0, 48);
    r->memory[0x9804] = 17;
    r->memory[0x9805] = 255;
    r->memory[0x9807] = 48;
    for (unsigned n = 0; n < 4; ++n) r->memory[0x9808 + n] = 255;
    uint8_t angle = r->memory[0x8105];
    r->memory[0x980d] = angle >= 4 && angle <= 6 ? (uint8_t)(angle - 3) : 0;
    const unsigned bits[] = {7, 3, 2, 1, 0};
    const unsigned offsets[] = {10, 11, 12, 14, 15};
    for (unsigned n = 0; n < 5; ++n)
        r->memory[0x9804 + offsets[n]] = (r->memory[0x80f8] >> bits[n]) & 1;
    if (!r->memory[0x80dd] && !r->memory[0x80fb] && r->memory[0x80fe] == 1) {
        r->memory[0x9808] = 0;
        r->memory[0x9809] = r->memory[0x8118];
        r->memory[0x980a] = 0;
        r->memory[0x980b] = r->memory[0x8119];
        r->memory[0x980c] = (uint8_t)(r->memory[0x811b] | (r->memory[0x811a] == 204 ? 128 : 0));
    }
    unsigned record_length = (unsigned)length + 1;
    if (length) {
        record_length += 4;
        r->memory[0x9834] = 34;
        r->memory[0x9835] = 255;
        r->memory[0x9836] = (uint8_t)(record_length >> 8);
        r->memory[0x9837] = (uint8_t)record_length;
    } else r->memory[0x9834] = 0;
    unsigned full_length = record_length + 48;
    static const uint8_t hexadecimal[] = "0123456789ABCDEF";
    for (unsigned n = 0; n < 4; ++n)
        r->memory[0x9800 + n] = hexadecimal[(full_length >> (12 - n * 4)) & 15];
}

int fx_display_real_linear_result(fx_render *r, uint16_t address, fx_box *final_box)
{
    uint8_t mode = r->memory[0x80f9], selection_byte = r->memory[0x8100];
    uint8_t selection = selection_byte & 15;
    uint8_t font = r->memory[0x811f];
    if ((font != 6 && font != 7 && font != 10) || r->memory[0x8127] || (r->memory[0x80ff] & 0x10)
        || (mode != 1 && mode != 65 && mode != 129 && mode != 193 && mode != 136)
        || !fx_display_has_formula_view(r) || selection >= 14 || address < 0x8000 || address > 0xffec)
        return -1;
    int natural = r->memory[0x8106] && (mode & 0xc0);
    if (natural && selection != 10) return -1;
    /* B15E takes a separate cached viewport path before text formatting. */
    if (natural && r->memory[0x8130]) return -1;
    fx_number value, imaginary, decimal_imaginary;
    fx_decimal decoded;
    memcpy(value.bytes, r->memory + address, 10);
    memcpy(imaginary.bytes, r->memory + address + 10, 10);
    if (fx_number_to_decimal(&decimal_imaginary, &imaginary) != FX_NUMERIC_OK
        || fx_decimal_decode(&decoded, &decimal_imaginary) != FX_NUMERIC_OK
        || decoded.mantissa) return -1;
    if (!natural) memset(r->memory + FX_RAM_FRAMEBUFFER + 12 * 12, 0, 20 * 12);
    r->memory[0x8114] = 0;
    uint16_t persistent = mode == 136 || !(mode & 0x80) ? 0x8546 : 0x8398;
    if (natural) r->memory[persistent] = 0;
    fx_format_options options = fx_format_default_options();
    options.selection = selection_byte;
    options.math_output = 0;
    options.mixed_fraction = r->memory[0x8107];
    options.display_mode = r->memory[0x8102];
    options.digits = r->memory[0x8103];
    options.decimal_dot = r->memory[0x8104];
    options.format_context = 0;
    fx_format_result result;
    uint8_t text[512];
    if (fx_format_number(&value, &options, text, sizeof text, &result) != FX_FORMAT_OK
        || result.length >= sizeof text) return 0;
    if (natural) {
        memcpy(r->memory + persistent, text, result.length + 1);
        r->memory[persistent] = 0;
        if ((uint8_t)(r->memory[0x8115] + (uint8_t)(result.length * 6)) > 90)
            fx_make_result_space(r, 10);
    }
    fx_apply_result_format_state(r, &value, selection_byte, result.kind);
    right_aligned_text(r, text, result.length);
    history(r, text, result.length);
    if (final_box) {
        final_box->width = (uint16_t)(result.length * 6);
        final_box->height = fx_font_height(r);
        final_box->depth = fx_font_depth(r);
    }
    return 1;
}
