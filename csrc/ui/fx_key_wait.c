/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_key_wait.h"
#include "fx_cursor.h"
#include "../render/fx_render.h"
#include <string.h>

static uint8_t read_byte(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void write_byte(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

static uint16_t read_word(fx_platform *p, uint16_t address)
{
    uint16_t low = read_byte(p, address);
    return (uint16_t)(low | (uint16_t)read_byte(p, (uint16_t)(address+1)) << 8);
}

static void capture(fx_platform *p, uint8_t bitmap[20], uint16_t address)
{
    uint8_t row = 0;
    while (row < read_byte(p, 0x811b)) {
        bitmap[2u*row] = read_byte(p, address);
        bitmap[2u*row+1] = read_byte(p, (uint16_t)(address+1));
        address = (uint16_t)(address+16);
        ++row;
    }
}

static void restore(fx_platform *p, const uint8_t bitmap[20], uint16_t address)
{
    uint8_t row = 0;
    while (row < read_byte(p, 0x811b)) {
        write_byte(p, address, bitmap[2u*row]);
        write_byte(p, (uint16_t)(address+1), bitmap[2u*row+1]);
        address = (uint16_t)(address+16);
        ++row;
    }
}

int fx_key_wait_begin(fx_platform *p, fx_key_wait *state, uint16_t destination)
{
    if (!p || !p->ram || !state) return -1;
    uint8_t height = read_byte(p, 0x811b);
    uint8_t enabled = fx_cursor_is_visible(p);
    if (height > 10 || (enabled && height != 6 && height != 7 && height != 10))
        return -2;
    memset(state, 0, sizeof(*state));
    state->captured_height = height;
    state->cursor_enabled = enabled;
    state->pair_destination = destination;
    state->period = state->countdown = 1;
    state->remaining_transitions = 1195;

    write_byte(p, 0x811f, height);
    write_byte(p, 0x8120, 1);
    write_byte(p, 0x8121, 0);
    uint8_t offset;
    uint8_t x = read_byte(p, 0x8118), y = read_byte(p, 0x8119);
    state->framebuffer = fx_pixel_address(0, x, (int8_t)y, &offset);
    capture(p, state->hidden, state->framebuffer);
    if (enabled) {
        fx_render render = {p->rom, p->rom_size, p->ram};
        uint8_t character = read_byte(p, 0x811a);
        fx_draw_glyph(&render, x, (int8_t)y, character);
        /* Wrapped cursor coordinates can reach the callback port. The
         * shared rasterizer writes raw display memory, so retain the data
         * bus callback event when its first row touchesF000. */
        int8_t glyph_y = (int8_t)y;
        if (height == 7 && character < 32) glyph_y = (int8_t)(glyph_y-1);
        if (glyph_y == -128 && x < 8 && p->ram[0xf000])
            write_byte(p, 0xf000, p->ram[0xf000]);
    }
    capture(p, state->shown, state->framebuffer);
    write_byte(p, 0x8121, 1);
    write_byte(p, 0x8120, 0);
    write_byte(p, 0x8e00, 1);
    state->active = 1;
    return 0;
}

int fx_key_wait_tick(fx_platform *p, fx_key_wait *state)
{
    if (!p || !p->ram || !state || !state->active) return -1;
    if (state->ready) return 1;
    if (state->captured_height > 10 || read_byte(p, 0x811b) > state->captured_height) return -2;
    state->countdown = (uint8_t)(state->countdown-1);
    if (!state->countdown) {
        state->phase ^= 1;
        state->countdown = state->period;
        state->remaining_transitions = (uint16_t)(state->remaining_transitions-1);
    }
    if (state->cursor_enabled)
        restore(p, state->phase ? state->shown : state->hidden, state->framebuffer);
    fx_timer_start(p, 0x129a);
    if (read_byte(p, 0x8e01) | read_byte(p, 0x8e02)) {
        state->ready = 1;
        return 1;
    }
    state->last_idle_counter = (uint16_t)(read_word(p, 0x8224)+1);
    write_byte(p, 0x8224, (uint8_t)state->last_idle_counter);
    write_byte(p, 0x8225, (uint8_t)(state->last_idle_counter >> 8));
    return 0;
}

int fx_key_wait_finish(fx_platform *p, fx_key_wait *state, fx_key_state *key)
{
    if (!p || !p->ram || !state || !state->active || !state->ready) return -1;
    uint8_t height = read_byte(p, 0x811b);
    if (state->captured_height > 10 || height > state->captured_height) return -2;
    /* A destination which changes the row count into uncaptured native
     * local bytes cannot be modeled by bounded host bitmaps. */
    if ((state->pair_destination == 0x811b && read_byte(p, 0x8e01) > state->captured_height) ||
        (state->pair_destination == 0x811a && read_byte(p, 0x8e02) > state->captured_height))
        return -2;
    write_byte(p, 0x8e00, 0);
    uint8_t columns = read_byte(p, 0x8e01);
    write_byte(p, state->pair_destination, columns);
    uint8_t rows = read_byte(p, 0x8e02);
    write_byte(p, (uint16_t)(state->pair_destination+1), rows);
    restore(p, state->hidden, state->framebuffer);
    if (key) { key->columns = columns; key->rows = rows; }
    state->active = state->ready = 0;
    return 0;
}
