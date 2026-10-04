#include "fx_render.h"

#include <string.h>

static uint8_t rom_byte(const fx_render *r, uint16_t address)
{
    return address < r->rom_size ? r->rom[address] : 0;
}

uint16_t fx_pixel_address(uint8_t selected_ram, uint8_t x, int8_t y,
                          uint8_t *bit_offset)
{
    unsigned base = selected_ram ? FX_RAM_FRAMEBUFFER : FX_LCD_FRAMEBUFFER;
    int stride = selected_ram ? 12 : 16;
    if (bit_offset) *bit_offset = x & 7;
    return (uint16_t)((int)base + (int)y * stride + (x >> 3));
}

unsigned fx_decode_glyph(const fx_render *r, uint8_t character,
                         uint8_t rows[9])
{
    uint8_t font = r->memory[0x811f];
    unsigned height, base, index, group, shift;
    if (font == 6) {
        /* The addition really is byte-sized: this also specifies how codes
         * outside the documented tiny-font range behave. */
        index = (uint8_t)(character + 48);
        base = 0x694 + (index >> 1) * 5;
        for (unsigned row = 0; row < 5; ++row)
            rows[row] = (uint8_t)(rom_byte(r, (uint16_t)(base + row))
                                  << ((index & 1) * 4)) & 0xf0;
        return 5;
    }
    height = font == 7 ? 6 : 9;
    base = font == 7 ? 0x400 : 0x22;
    if (character < 32) {
        base = font == 7 ? 0x754 : 0x70c;
        if (font == 7) ++height;
        character = (uint8_t)(character + 31);
    }
    if (character == 124) {
        memset(rows, 0xc0, height);
        return height;
    }
    index = (uint8_t)(character - 32) * 5;
    group = index >> 3;
    shift = index & 7;
    base += group * height;
    for (unsigned row = 0; row < height; ++row) {
        unsigned bits = (unsigned)rom_byte(r, (uint16_t)(base + row)) << 8;
        if (shift > 3)
            bits |= rom_byte(r, (uint16_t)(base + height + row));
        rows[row] = (uint8_t)(((bits >> (11 - shift)) & 31) << 2);
    }
    return height;
}

void fx_decode_glyph_to_memory(fx_render *r, uint8_t character,
                               uint16_t destination)
{
    uint8_t rows[9];
    unsigned height = fx_decode_glyph(r, character, rows);
    int tiny = r->memory[0x811f] == 6;
    for (unsigned row = 0; row < height; ++row) {
        if (destination >= 0x8000) r->memory[destination] = rows[row];
        /* Tiny fonts increment R2 alone. Ordinary fonts increment ER2. */
        if (tiny)
            destination = (destination & 0xff00) | (uint8_t)(destination + 1);
        else
            ++destination;
    }
}

uint8_t fx_composite_byte(uint8_t destination, uint8_t source,
                          uint8_t mask, uint8_t mode)
{
    if (mask) source &= mask;
    switch (mode) {
    case 0: return (uint8_t)((destination & (uint8_t)~mask) | source);
    case 1: return destination | source;
    case 2: return destination & (uint8_t)((uint8_t)~mask | source);
    case 4: return (uint8_t)((destination & (uint8_t)~mask)
                              | ((uint8_t)~source & mask));
    default: return destination ^ source;
    }
}

void fx_composite_at(fx_render *r, uint16_t destination,
                     uint8_t source, uint8_t mask)
{
    if (destination < 0x87dc) return;
    r->memory[destination] = fx_composite_byte(r->memory[destination], source,
                                              mask, r->memory[0x8120]);
}

void fx_draw_glyph(fx_render *r, uint8_t x, int8_t y, uint8_t character)
{
    uint8_t rows[9], offset;
    uint8_t font = r->memory[0x811f];
    unsigned width = font == 6 ? 4 : 6;
    unsigned right_cutoff = font == 6 ? 4 : 2;
    unsigned logical_height = font;
    unsigned stride = r->memory[0x8121] ? 12 : 16;
    uint16_t last = r->memory[0x8121] ? 0x894f : 0xf9ff;
    if (x > 95 || y >= 32) return;
    if (font == 7 && character < 32) {
        ++logical_height;
        y = (int8_t)(y - 1);
    }
    unsigned unpacked_height = fx_decode_glyph(r, character, rows);
    uint16_t destination = fx_pixel_address(r->memory[0x8121], x, y, &offset);
    uint8_t first_mask = rom_byte(r, (uint16_t)(0x2ab4 + offset));
    uint8_t second_mask = rom_byte(r, (uint16_t)(0x2abc + ((x + width) & 7)));
    /* The original rasterizer puts one blank source row before the glyph.
     * The callers use heights 6, 7, or 10; font 7 controls use height 8. */
    for (unsigned row = 0; row < logical_height; ++row) {
        uint8_t source = row == 0 ? rom_byte(r, 0x22)
                       : row <= unpacked_height ? rows[row - 1] : 0;
        if (offset == 0) {
            fx_composite_at(r, destination, source, second_mask);
        } else {
            fx_composite_at(r, destination,
                            (uint8_t)((source >> offset) & first_mask), first_mask);
            if (offset >= right_cutoff + 1)
                fx_composite_at(r, (uint16_t)(destination + 1),
                                (uint8_t)((source << (8 - offset)) & second_mask),
                                second_mask);
        }
        destination = (uint16_t)(destination + stride);
        if (destination > last) break;
    }
}

uint8_t fx_draw_text(fx_render *r, uint8_t x, int8_t y, uint16_t *address)
{
    unsigned advance = r->memory[0x811f] == 6 ? 4 : 6;
    unsigned maximum = r->memory[0x811f] == 6 ? 24 : 16;
    uint8_t count = 0;
    while (x <= 96 - advance && count < maximum) {
        uint8_t character = *address < 0x8000
                            ? rom_byte(r, *address) : r->memory[*address];
        if (!character) break;
        fx_draw_glyph(r, x, y, character);
        ++*address;
        x = (uint8_t)(x + advance);
        ++count;
    }
    return count;
}

static void set_pixel_unclipped(fx_render *r, uint8_t x, uint8_t y)
{
    uint16_t address = (uint16_t)(FX_RAM_FRAMEBUFFER + y * 12 + (x >> 3));
    r->memory[address] |= (uint8_t)(0x80 >> (x & 7));
}

void fx_set_pixel(fx_render *r, int8_t x, int8_t y)
{
    if (x < 0 || x > 95 || y < 0 || y > 31) return;
    set_pixel_unclipped(r, (uint8_t)x, (uint8_t)y);
}

void fx_draw_line(fx_render *r, int8_t x0, int8_t y0,
                  int8_t x1, int8_t y1)
{
    int dx = (int)x1 - x0, dy = (int)y1 - y0;
    int sx = dx < 0 ? -1 : 1, sy = dy < 0 ? -1 : 1;
    unsigned ax = dx < 0 ? (unsigned)-dx : (unsigned)dx;
    unsigned ay = dy < 0 ? (unsigned)-dy : (unsigned)dy;
    uint8_t major_position = (uint8_t)x0, minor_position = (uint8_t)y0;
    unsigned major = ax, minor = ay;
    int major_step = sx, minor_step = sy;
    int swapped = ay > ax;
    fx_set_pixel(r, x0, y0);
    if (swapped) {
        major_position = (uint8_t)y0; minor_position = (uint8_t)x0;
        major = ay; minor = ax; major_step = sy; minor_step = sx;
    }
    int error = (int)major;
    for (unsigned n = 0; n < major; ++n) {
        error -= (int)(2 * minor);
        if (error < 0) {
            error += (int)(2 * major);
            minor_position = (uint8_t)(minor_position + minor_step);
        }
        major_position = (uint8_t)(major_position + major_step);
        fx_set_pixel(r, (int8_t)(swapped ? minor_position : major_position),
                       (int8_t)(swapped ? major_position : minor_position));
    }
}

void fx_draw_vertical(fx_render *r, uint8_t x, uint8_t y0,
                      uint8_t y1, uint8_t decoration)
{
    if (decoration & 0x80) set_pixel_unclipped(r, (uint8_t)(x + 1), y0);
    if (decoration & 0x20) set_pixel_unclipped(r, (uint8_t)(x - 1), y0);
    uint8_t y = y0;
    do {
        set_pixel_unclipped(r, x, y);
        if (y == y1) break;
        ++y;
    } while (y != y0);
    if (decoration & 0x40) set_pixel_unclipped(r, (uint8_t)(x + 1), y);
    if (decoration & 0x10) set_pixel_unclipped(r, (uint8_t)(x - 1), y);
}

void fx_clear_framebuffer(fx_render *r)
{
    memset(r->memory + FX_RAM_FRAMEBUFFER, 0, FX_FRAMEBUFFER_BYTES);
}

void fx_flush_framebuffer(fx_render *r)
{
    for (unsigned row = 0; row < 32; ++row)
        memcpy(r->memory + FX_LCD_FRAMEBUFFER + row * 16,
               r->memory + FX_RAM_FRAMEBUFFER + row * 12, 12);
}

void fx_merge_vertical(fx_box *destination, const fx_box *source)
{
    unsigned da = destination->height >= destination->depth
                  ? destination->height - destination->depth : 0;
    unsigned sa = source->height >= source->depth
                  ? source->height - source->depth : 0;
    destination->depth = destination->depth > source->depth
                         ? destination->depth : source->depth;
    destination->height = (uint8_t)((da > sa ? da : sa) + destination->depth);
}

void fx_begin_layout_pass(fx_render *r, uint8_t draw)
{
    r->memory[0x8009] = draw;
    r->memory[0x811f] = 10;
    r->memory[0x800a] = r->memory[0x8008] = 0;
    r->memory[0x8120] = r->memory[0x8007] = 0;
}

uint8_t fx_select_small_font(fx_render *r)
{
    uint8_t previous = r->memory[0x811f];
    r->memory[0x811f] = 7;
    return previous;
}

uint8_t fx_font_height(const fx_render *r) { return r->memory[0x811f] == 7 ? 7 : 10; }
uint8_t fx_font_depth(const fx_render *r) { return r->memory[0x811f] == 7 ? 3 : 5; }
uint8_t fx_font_ascent(const fx_render *r) { return r->memory[0x811f] == 7 ? 4 : 5; }

uint8_t fx_construct_class(const fx_render *r, uint8_t token)
{
    return (rom_byte(r, (uint16_t)(0x31fa + token / 2)) >> ((token & 1) * 4)) & 15;
}

uint8_t fx_construct_index(uint8_t token)
{
    static const uint8_t constructs[14] = {
        0x5d, 0x5e, 0x63, 0x68, 0x69, 0x6a, 0x6b,
        0x73, 0x7c, 0x93, 0x98, 0x9f, 0xa4, 0xae
    };
    for (unsigned index = 0; index < sizeof constructs; ++index)
        if (constructs[index] == token) return (uint8_t)index;
    return 15;
}
