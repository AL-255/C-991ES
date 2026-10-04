#ifndef FX_RENDER_H
#define FX_RENDER_H

#include <stddef.h>
#include <stdint.h>

/* Portable translations of the fx-991ES PLUS C Ver.4 display routines.
 * ROM is supplied as data only; no instruction interpreter is used here.
 * The 64 KiB memory image exposes firmware settings and original address
 * wrapping, including glyph spill outside the visible framebuffer. */
typedef struct {
    const uint8_t *rom;
    size_t rom_size;
    uint8_t *memory;                 /* exactly 65536 addressable bytes */
} fx_render;

typedef struct {
    uint16_t width;
    uint8_t height;
    uint8_t depth;
} fx_box;

enum {
    FX_RAM_FRAMEBUFFER = 0x87d0,
    FX_LCD_FRAMEBUFFER = 0xf800,
    FX_FRAMEBUFFER_BYTES = 384,
    FX_RENDER_MEMORY_BYTES = 65536
};

/* 0x3d28: y is signed, x is unsigned; mapping does not clip. */
uint16_t fx_pixel_address(uint8_t selected_ram, uint8_t x, int8_t y,
                          uint8_t *bit_offset);
/* 0x3bbc: unpack the font selected by memory[0x811f].  Nine bytes suffice.
 * All byte-valued character codes are accepted, as in the original. */
unsigned fx_decode_glyph(const fx_render *render, uint8_t character,
                         uint8_t rows[9]);
/* Store unpacked rows with the original destination-pointer behavior. */
void fx_decode_glyph_to_memory(fx_render *render, uint8_t character,
                               uint16_t destination);
/* 0x3c8e: preserves the lower address guard and mask==0 behavior. */
uint8_t fx_composite_byte(uint8_t destination, uint8_t source,
                          uint8_t mask, uint8_t mode);
void fx_composite_at(fx_render *render, uint16_t destination,
                     uint8_t source, uint8_t mask);
/* 0x3a8a: x is an unsigned byte and y a signed byte. */
void fx_draw_glyph(fx_render *render, uint8_t x, int8_t y,
                   uint8_t character);
/* 0x3a4a: draw zero-terminated character bytes.  Return count and advance
 * the address through the characters actually consumed. */
uint8_t fx_draw_text(fx_render *render, uint8_t x, int8_t y,
                     uint16_t *address);
/* 0x3b88 and 0x39a8: RAM framebuffer, independent of selected map/mode. */
void fx_set_pixel(fx_render *render, int8_t x, int8_t y);
void fx_draw_line(fx_render *render, int8_t x0, int8_t y0,
                  int8_t x1, int8_t y1);
/* 0x3960: optional extra endpoint pixels encoded in decoration bits. */
void fx_draw_vertical(fx_render *render, uint8_t x, uint8_t y0,
                      uint8_t y1, uint8_t decoration);
/* 0x3908, 0x3cfc: leave LCD row padding untouched. */
void fx_clear_framebuffer(fx_render *render);
void fx_flush_framebuffer(fx_render *render);
/* 0xc544: width is unchanged; malformed height<depth has zero ascent. */
void fx_merge_vertical(fx_box *destination, const fx_box *source);
/* 0xc634, 0xc664, 0xc514, 0xc524, 0xc534. */
void fx_begin_layout_pass(fx_render *render, uint8_t draw);
uint8_t fx_select_small_font(fx_render *render);
uint8_t fx_font_height(const fx_render *render);
uint8_t fx_font_depth(const fx_render *render);
uint8_t fx_font_ascent(const fx_render *render);
/* 0x31e2 and 0x327a: table-driven token classifiers. */
uint8_t fx_construct_class(const fx_render *render, uint8_t token);
uint8_t fx_construct_index(uint8_t token);
/* 0x9cd6 and translated construct handlers.  Returned address is the
 * stopping delimiter; zero denotes malformed input or a resource failure.
 * All 14 structured construct handlers are translated. Call measurement
 * and drawing with fx_begin_layout_pass(), retaining the measurement cache.
 * Cursor geometry and blink metadata are updated. Physical CPU stack
 * availability remains an explicit gap. */
uint16_t fx_layout_sequence(fx_render *render, uint16_t expression,
                            fx_box *box, uint16_t x, uint8_t baseline);
/* 0x8c56: two-pass screen placement using the expression pointer at 0x812c.
 * Returns zero when the recursive layout cannot be completed. Editor cursor
 * painting belongs to the UI. Successful native fallback replacement is
 * modeled; failed second measurements remain an explicit gap. */
int fx_render_viewport(fx_render *render, fx_box *final_box);
/* High-level translation of B070's ordinary real Math-result path.
 * The address points to a 20-byte complex record with a zero imaginary part.
 * Returns 1 after drawing, 0 on formatting/layout failure, or -1 for a
 * controller mode whose complete branch has not yet been translated.
 * Native numeric workspace 0x8006/inactive 0x8640 slots are an explicit RAM gap. */
int fx_display_real_math_result(fx_render *render, uint16_t value_address,
                                fx_box *final_box);

#endif
