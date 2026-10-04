#include "fx_result_linalg.h"
#include "../format/fx_format_budget.h"
#include "fx_result_special.h"
#include "fx_render_context.h"
#include <string.h>

int fx_display_linalg_cell(fx_render *render, const fx_number *number,
                            uint8_t row, uint8_t column, uint8_t selected)
{
    if (!render || !render->memory || !row || row > 3 || !column || column > 3)
        return -1;
    uint8_t text[32];
    fx_format_result result;
    if (fx_format_budget(number, 6, render->memory[0x8127] == 1,
                         render->memory[0x80ff] == 20, render->memory[0x8104],
                         text, sizeof text, &result) != FX_FORMAT_OK)
        return 0;
    /* 3EC0 pads on the left and selects the final six serialized bytes. */
    size_t padding = result.length < 6 ? 6 - result.length : 0;
    size_t start = result.length > 6 ? result.length - 6 : 0;
    uint8_t x = (uint8_t)(12 + 28 * (column - 1));
    uint8_t y = (uint8_t)(7 + 6 * (row - 1));
    render->memory[0x811f] = 6;
    if (selected) render->memory[0x8120] = 4;
    for (size_t i = 0; i < 6 && x <= 92;
         ++i, x = (uint8_t)(x + 4))
        fx_draw_glyph(render, x, (int8_t)y, i < padding ? 0xec : text[start+i-padding]);
    render->memory[0x8120] = 0;
    return 1;
}

int fx_display_linalg_grid(fx_render *render, const fx_linalg_value *value,
                            uint8_t selected_row, uint8_t selected_column)
{
    if (!value || !value->rows || value->rows > 3 || !value->columns
        || value->columns > 3) return -1;
    for (uint8_t row = 1; row <= value->rows; ++row)
        for (uint8_t column = 1; column <= value->columns; ++column)
            if (fx_display_linalg_cell(render, &value->cells[3*(row-1)+column-1],
                    row, column, row == selected_row && column == selected_column) != 1)
                return 0;
    return 1;
}

int fx_display_linalg_caption(fx_render *render, uint8_t slot)
{
    if (!render || !render->memory || slot > 3) return -1;
    render->memory[0x811f] = 6;
    uint16_t source = (uint16_t)(0xfe8 + 4 * slot);
    fx_draw_text(render, 1, 1, &source);
    return 1;
}

int fx_display_linalg_border(fx_render *render, uint8_t rows, uint8_t columns)
{
    if (!render || !render->memory || !rows || rows > 3 || !columns || columns > 3)
        return -1;
    uint8_t bottom = (uint8_t)(6 + 6 * rows);
    fx_draw_vertical(render, 10, 7, bottom, 0xc0);
    fx_draw_vertical(render, (uint8_t)(10 + 28 * columns), 7, bottom, 0x30);
    return 1;
}

int fx_display_linalg_value(fx_render *render, const fx_linalg_value *value,
                             uint8_t slot, uint8_t selected_row,
                             uint8_t selected_column)
{
    if (!render || !render->memory || !value || !value->rows || value->rows > 3
        || !value->columns || value->columns > 3 || slot > 3
        || !selected_row || selected_row > value->rows
        || !selected_column || selected_column > value->columns) return -1;
    const fx_number *number = &value->cells[3*(selected_row-1)+selected_column-1];
    /*6x/9x are rich references in matrix/vector storage, not scalar cell
     * records. Their tiny grid spelling is ERROR; the selected full-value
     * formatter's foreign-reference fallback is outside this typed API. */
    if ((number->bytes[0] & 0xf0) == 0x60 || (number->bytes[0] & 0xf0) == 0x90)
        return -1;
    /* The selected-value controller's extended/small exponent branches
     * are not yet translated by fx_display_special_real_number. */
    if ((number->bytes[0] & 0xf0) != 0xf0
        && (render->memory[0x80f9] == 137 || render->memory[0x8127]
            || (render->memory[0x80f9] != 2 && (render->memory[0x80ff] & 0x10))))
        return -1;
    /* The original selected-value line has a26-byte CPU-stack buffer.
     * Oversized serializations corrupt that caller's saved registers. The
     * portable API reports this native ABI boundary before drawing. */
    fx_format_options options = fx_format_default_options();
    options.selection = render->memory[0x8100];
    options.math_output = (uint8_t)fx_display_has_natural_result(render);
    options.mixed_fraction = render->memory[0x8107];
    options.display_mode = render->memory[0x8102];
    options.digits = render->memory[0x8103];
    options.decimal_dot = render->memory[0x8104];
    uint8_t text[512];
    fx_format_result formatted;
    if (fx_format_number(number, &options, text, sizeof text, &formatted) != FX_FORMAT_OK)
        return 0;
    if (formatted.length >= 26) return -1;
    memset(render->memory + 0x814a, 0, 10);
    memcpy(render->memory + 0x8140, number->bytes, 10);
    fx_clear_framebuffer(render);
    if (fx_display_linalg_caption(render, slot) != 1
        || fx_display_linalg_border(render, value->rows, value->columns) != 1
        || fx_display_linalg_grid(render, value, selected_row, selected_column) != 1)
        return 0;
    render->memory[0x811f] = 7;
    return fx_display_special_real_number(render, number, NULL);
}

int fx_linalg_move_selection(uint8_t rows, uint8_t columns,
                              uint8_t key, uint8_t *row, uint8_t *column)
{
    if (!row || !column || !rows || rows > 3 || !columns || columns > 3
        || !*row || *row > rows || !*column || *column > columns) return -1;
    switch (key) {
    case 0xe0:
        if (*row <= 1) return 1;
        --*row;
        break;
    case 0xe1:
        if (*row >= rows) return 1;
        ++*row;
        break;
    case 0xe2:
    case 0xed:
        if (*column < columns) ++*column;
        else if (*row < rows) { ++*row; *column = 1; }
        else return 1;
        break;
    case 0xe3:
        if (*column > 1) --*column;
        else if (*row > 1) { --*row; *column = columns; }
        else return 1;
        break;
    default: return 1;
    }
    return 0;
}

int fx_linalg_selection_event(fx_render *render, uint8_t rows,
                               uint8_t columns, uint8_t key)
{
    if (!render || !render->memory) return -1;
    int status = fx_linalg_move_selection(rows, columns, key,
                       &render->memory[0x811d], &render->memory[0x811e]);
    if (!status) {
        render->memory[0x8101] = 0;
        render->memory[0x8100] = 0;
        render->memory[0x8130] = 0;
    }
    return status;
}
