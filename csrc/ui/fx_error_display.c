/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_error_display.h"
#include "../render/fx_render.h"

enum {
    FONT = 0x811f, COMPOSITE_MODE = 0x8120, SELECT_RAM = 0x8121,
    LCD_BASE = 0xf800, LCD_BYTES = 512, FONT_DATA_END = 0x2ac4,
    ERROR_TABLE = 0x113e, LINE_WIDTH = 16, LINE_COUNT = 4
};

static uint8_t read_byte(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static int validate(fx_platform *p, const uint16_t lines[4], uint16_t stack_end)
{
    unsigned line, offset;
    if (!p || !p->ram || !p->rom || !lines || p->rom_size < FONT_DATA_END) return -1;
    for (line = 0; line < LINE_COUNT; ++line) {
        for (offset = 0; offset < LINE_WIDTH; ++offset) {
            uint16_t address = (uint16_t)(lines[line] + offset);
            if (address < 0x8000 && address >= p->rom_size) return -2;
            /* Native nested glyph calls overwrite their own CPU stack.
             * Those incidental source aliases are not host dialog data. */
            if (address >= 0x8d00 && address < stack_end) return -2;
        }
    }
    return 0;
}

static void clear_bit(fx_platform *p, uint16_t address, uint8_t mask)
{
    fx_data_write(p, 0, address, (uint8_t)(read_byte(p, address) & (uint8_t)~mask));
}

static void composite(fx_platform *p, uint16_t destination, uint8_t source, uint8_t mask)
{
    fx_data_write(p, 0, destination,
                  fx_composite_byte(read_byte(p, destination), source, mask,
                                    read_byte(p, COMPOSITE_MODE)));
}

/* The dialog admits only the fixed small font and visible LCD coordinates.
 * Reuse the shared glyph decoder and compositing formula, retaining every
 * first/second-byte raster store on the platform bus. */
static void draw_character(fx_platform *p, fx_render *render, uint8_t x,
                           uint8_t y, uint8_t character)
{
    uint8_t rows[9], offset, first_mask, second_mask;
    uint16_t destination;
    unsigned row, height = character < 32 ? 8 : 7;
    fx_decode_glyph(render, character, rows);
    if (character < 32) --y;
    destination = fx_pixel_address(0, x, (int8_t)y, &offset);
    first_mask = read_byte(p, (uint16_t)(0x2ab4 + offset));
    second_mask = read_byte(p, (uint16_t)(0x2abc + ((x + 6) & 7)));
    for (row = 0; row < height; ++row) {
        uint8_t source = row ? rows[row-1] : read_byte(p, 0x22);
        if (!offset) composite(p, destination, source, second_mask);
        else {
            composite(p, destination, (uint8_t)((source >> offset) & first_mask), first_mask);
            if (offset >= 3)
                composite(p, (uint16_t)(destination + 1),
                          (uint8_t)((source << (8-offset)) & second_mask), second_mask);
        }
        destination = (uint16_t)(destination + 16);
    }
}

static void draw_dialog(fx_platform *p, const uint16_t lines[4])
{
    unsigned line, column, offset;
    fx_render render = {p->rom, p->rom_size, p->ram};
    fx_data_write(p, 0, FONT, 7);
    fx_data_write(p, 0, SELECT_RAM, 0);
    /* 402E enters54E6, bypassing the conditional sleep entry54E0. */
    fx_data_write(p, 0, 0xf031, 6);
    clear_bit(p, 0xf800, 0x10);
    clear_bit(p, 0xf800, 0x04);
    clear_bit(p, 0xf801, 0x02);
    clear_bit(p, 0xf802, 0x40);
    clear_bit(p, 0xf80b, 0x80);
    clear_bit(p, 0xf80a, 0x08);
    clear_bit(p, 0xf80b, 0x10);
    for (offset = 0; offset < LCD_BYTES; ++offset)
        fx_data_write(p, 0, (uint16_t)(LCD_BASE + offset), 0);

    for (line = 0; line < LINE_COUNT; ++line) {
        uint16_t address = lines[line];
        for (column = 0; column < LINE_WIDTH; ++column) {
            uint8_t character = read_byte(p, address);
            if (!character) break;
            draw_character(p, &render, (uint8_t)(column * 6),
                           (uint8_t)(1 + line * 8), character);
            ++address;
        }
    }
    fx_data_write(p, 0, SELECT_RAM, 1);
    fx_data_write(p, 0, 0xf031, 5);
}

int fx_error_dialog_draw(fx_platform *p, const uint16_t lines[4])
{
    uint16_t pointers[LINE_COUNT];
    unsigned i;
    int status = validate(p, lines, 0x8df2);
    if (status) return status;
    for (i = 0; i < LINE_COUNT; ++i) pointers[i] = lines[i];
    draw_dialog(p, pointers);
    return 0;
}

int fx_error_display(fx_platform *p, uint8_t error)
{
    uint16_t pointers[LINE_COUNT] = {0, 0x11a1, 0x1292, 0x1158};
    uint16_t table_address;
    int status;
    if (!p || !p->ram || !p->rom || p->rom_size < FONT_DATA_END) return -1;
    table_address = (uint16_t)(ERROR_TABLE + 2u * (uint8_t)(error-1));
    pointers[0] = read_byte(p, table_address);
    pointers[0] |= (uint16_t)read_byte(p, (uint16_t)(table_address+1)) << 8;
    status = validate(p, pointers, 0x8dee);
    if (status) return status;
    fx_data_write(p, 0, FONT, 7); /* 4074's write precedes3FBA/402E. */
    draw_dialog(p, pointers);
    return 0;
}
