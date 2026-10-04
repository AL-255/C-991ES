#include "fx_result_special.h"
#include "fx_render_memory.h"
#include "fx_render_context.h"
#include "../format/fx_format.h"
#include "../format/fx_format_base.h"
#include "fx_result_format_state.h"
#include "../numeric/fx_surd_components.h"

static uint8_t read_byte(const fx_render *render, uint16_t address)
{
    if (address >= 0x8000) return render->memory[address];
    return address < render->rom_size ? render->rom[address] : 0;
}

static void base_indicator(fx_render *render)
{
    uint16_t source = (uint16_t)(0x36a8 + 4 * (render->memory[0x80fa] >> 2));
    fx_draw_text(render, 78, 12, &source);
}

int fx_display_special_real_number(fx_render *render, const fx_number *value,
                                   fx_box *final_box)
{
    uint8_t font = render->memory[0x811f], mode = render->memory[0x80f9];
    if (font != 6 && font != 7 && font != 10) return -1;
    int error = value && (value->bytes[0] & 0xf0) == 0xf0;
    if (value && !error && (mode == 137 || render->memory[0x8127]
                          || (mode != 2 && (render->memory[0x80ff] & 0x10)))) return -1;
    if (mode == 2) base_indicator(render);
    /*37BC formats a caller-owned copy. Compact real values leave the
     * ordered six-component view in the persistent pool as part of17576. */
    fx_number prepared;
    if (value) {
        prepared=*value;value=&prepared;
        if ((render->memory[0x80f9]==6 || render->memory[0x80f9]==7) &&
            (value->bytes[0]&0xf0)==0x80 &&
            fx_surd_components_emit_copy(render->memory,value)!=FX_NUMERIC_OK)
            return 0;
    }
    uint8_t text[512] = {0};
    size_t length = 0;
    if (value) {
        fx_format_options options = fx_format_default_options();
        options.selection = render->memory[0x8100];
        options.math_output = (uint8_t)fx_display_has_natural_result(render);
        options.mixed_fraction = render->memory[0x8107];
        options.display_mode = render->memory[0x8102];
        options.digits = render->memory[0x8103];
        options.decimal_dot = render->memory[0x8104];
        fx_format_result result;
        fx_format_status status = mode == 2 && !error
            ? fx_format_base(value, render->memory[0x80fa], text, sizeof text, &result)
            : fx_format_number(value, &options, text, sizeof text, &result);
        if (status != FX_FORMAT_OK)
            return 0;
        length = result.length;
        if (mode == 2) render->memory[0x8100] &= 15;
        else fx_apply_result_format_state(render, value, options.selection, result.kind);
    } else render->memory[0x8100] &= 15;
    uint8_t y = font == 10 ? 22 : 25;
    fx_clear_from_row(render, y);
    uint8_t x = (uint8_t)(96 - (uint8_t)(length * 6));
    unsigned advance = font == 6 ? 4 : 6, maximum = font == 6 ? 24 : 16;
    for (unsigned n = 0; n < length && text[n] && x <= 96 - advance && n < maximum;
         ++n, x = (uint8_t)(x + advance))
        fx_draw_glyph(render, x, (int8_t)y, text[n]);
    if (final_box) {
        final_box->width = (uint16_t)(length * 6);
        final_box->height = fx_font_height(render);
        final_box->depth = fx_font_depth(render);
    }
    return 1;
}

int fx_display_special_real_result(fx_render *render, uint16_t value_address,
                                   fx_box *final_box)
{
    if (!value_address) return fx_display_special_real_number(render, NULL, final_box);
    fx_number value;
    for (unsigned n = 0; n < sizeof value.bytes; ++n)
        value.bytes[n] = read_byte(render, (uint16_t)(value_address + n));
    return fx_display_special_real_number(render, &value, final_box);
}
