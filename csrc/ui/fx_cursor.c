/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_cursor.h"

static uint8_t byte_at(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static uint16_t word_at(fx_platform *p, uint16_t address)
{
    uint16_t low = byte_at(p, address);
    return (uint16_t)(low | (uint16_t)byte_at(p, (uint16_t)(address+1)) << 8);
}

static void put_byte(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

void fx_cursor_capture(fx_platform *p, uint16_t packed, uint16_t framebuffer)
{
    uint8_t row = 0;
    while (row < byte_at(p, 0x811b)) {
        uint16_t destination = (uint16_t)(packed + 2u*row);
        put_byte(p, destination, byte_at(p, framebuffer));
        put_byte(p, (uint16_t)(destination+1), byte_at(p, (uint16_t)(framebuffer+1)));
        framebuffer = (uint16_t)(framebuffer+16);
        ++row;
    }
}

void fx_cursor_restore(fx_platform *p, uint16_t framebuffer, uint16_t packed)
{
    uint8_t row = 0;
    while (row < byte_at(p, 0x811b)) {
        uint16_t source = (uint16_t)(packed + 2u*row);
        put_byte(p, framebuffer, byte_at(p, source));
        put_byte(p, (uint16_t)(framebuffer+1), byte_at(p, (uint16_t)(source+1)));
        framebuffer = (uint16_t)(framebuffer+16);
        ++row;
    }
}

void fx_cursor_tick(fx_platform *p, uint16_t state)
{
    uint16_t countdown = (uint16_t)(state+45);
    put_byte(p, countdown, (uint8_t)(byte_at(p, countdown)-1));
    if (!byte_at(p, countdown)) {
        uint16_t phase = (uint16_t)(state+40);
        put_byte(p, phase, (uint8_t)(byte_at(p, phase)^1));
        put_byte(p, countdown, byte_at(p, (uint16_t)(state+44)));
        uint16_t remaining_address = (uint16_t)(state+46);
        uint16_t remaining = (uint16_t)(word_at(p, remaining_address)-1);
        put_byte(p, remaining_address, (uint8_t)remaining);
        put_byte(p, (uint16_t)(remaining_address+1), (uint8_t)(remaining >> 8));
    }
    if (byte_at(p, (uint16_t)(state+41))) {
        uint16_t bitmap = byte_at(p, (uint16_t)(state+40)) ? state : (uint16_t)(state+20);
        fx_cursor_restore(p, word_at(p, (uint16_t)(state+42)), bitmap);
    }
}

uint8_t fx_cursor_is_visible(fx_platform *p)
{
    return (uint8_t)(!byte_at(p, 0x80dd) && !byte_at(p, 0x80fb) && byte_at(p, 0x80fe) == 1);
}
