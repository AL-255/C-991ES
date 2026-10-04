/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_host_bridge.h"
#include "../ui/fx_cursor.h"

static uint8_t byte_at(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static uint16_t word_at(fx_platform *p, uint16_t address)
{
    return (uint16_t)(byte_at(p, address)
        | (uint16_t)byte_at(p, (uint16_t)(address + 1u)) << 8);
}

static void put_byte(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

static void put_word(fx_platform *p, uint16_t address, uint16_t value)
{
    put_byte(p, address, (uint8_t)value);
    put_byte(p, (uint16_t)(address + 1u), (uint8_t)(value >> 8));
}

void fx_host_write_descriptor(fx_platform *p, uint16_t destination)
{
    static const uint16_t pointers[10] = {
        0x8e00, 0x8e01, 0x8e02, 0x8e10, 0x9000,
        0x9800, 0x9804, 0x9808, 0x9834, 0x9838
    };
    for (unsigned n = 0; n < 10; ++n)
        put_word(p, (uint16_t)(destination + 2u*n), pointers[n]);
}

void fx_host_write_status(fx_platform *p, uint16_t destination)
{
    for (unsigned n = 0; n < 48; ++n)
        put_byte(p, (uint16_t)(destination + n), 0);
    put_byte(p, destination, 0x11);
    put_byte(p, (uint16_t)(destination + 1u), 0xff);
    put_byte(p, (uint16_t)(destination + 3u), 48);
    put_byte(p, (uint16_t)(destination + 5u), byte_at(p, 0x8118));
    put_byte(p, (uint16_t)(destination + 7u), byte_at(p, 0x8119));
    if (byte_at(p, 0x811b)) put_byte(p, (uint16_t)(destination + 8u), 1);
    static const struct { uint8_t mask, offset; } modifiers[] = {
        {0x80, 10}, {8, 11}, {4, 12}, {2, 14}, {1, 15}
    };
    for (unsigned n = 0; n < sizeof modifiers/sizeof modifiers[0]; ++n)
        if (byte_at(p, 0x80f8) & modifiers[n].mask)
            put_byte(p, (uint16_t)(destination + modifiers[n].offset), 1);
    uint8_t angle = byte_at(p, 0x8105);
    put_byte(p, (uint16_t)(destination + 9u),
             (uint8_t)(angle >= 4 && angle <= 6 ? angle - 3 : 0));
    if (fx_cursor_is_visible(p)) {
        put_byte(p, (uint16_t)(destination + 8u), byte_at(p, 0x811b));
        if (byte_at(p, 0x811a) == 0xcc)
            put_byte(p, (uint16_t)(destination + 8u),
                     (uint8_t)(byte_at(p, (uint16_t)(destination + 8u)) | 0x80));
    } else {
        put_byte(p, (uint16_t)(destination + 8u), 0);
        for (unsigned n = 4; n < 8; ++n)
            put_byte(p, (uint16_t)(destination + n), 0xff);
    }
}

void fx_host_write_framebuffer(fx_platform *p)
{
    uint16_t destination = 0x9000;
    put_byte(p, destination++, 0x80);
    put_byte(p, destination++, 1);
    for (unsigned row = 0; row < 32; ++row)
        for (unsigned column = 0; column < 12; ++column)
            put_byte(p, destination++, byte_at(p, (uint16_t)(0xf800 + 16u*row + column)));
}

int fx_host_write_text_packet(fx_platform *p, uint16_t descriptor)
{
    fx_host_write_status(p, word_at(p, (uint16_t)(descriptor + 12u)));
    uint16_t text = word_at(p, (uint16_t)(descriptor + 18u));
    unsigned length = 0;
    if (text) {
        while (length < 65536 && byte_at(p, (uint16_t)(text + length))) ++length;
        if (length == 65536) return -1;
    }
    uint16_t payload_length = (uint16_t)(length + 1u);
    if ((int16_t)payload_length > 1) {
        payload_length = (uint16_t)(payload_length + 4u);
        put_byte(p, word_at(p, (uint16_t)(descriptor + 16u)), 0x22);
        put_byte(p, (uint16_t)(word_at(p, (uint16_t)(descriptor + 16u)) + 1u), 0xff);
        put_byte(p, (uint16_t)(word_at(p, (uint16_t)(descriptor + 16u)) + 2u), (uint8_t)(payload_length >> 8));
        put_byte(p, (uint16_t)(word_at(p, (uint16_t)(descriptor + 16u)) + 3u), (uint8_t)payload_length);
    } else {
        put_byte(p, word_at(p, (uint16_t)(descriptor + 16u)), 0);
    }
    uint16_t total = (uint16_t)(payload_length + 48u);
    static const uint8_t hexadecimal[] = "0123456789ABCDEF";
    for (int digit = 3; digit >= 0; --digit) {
        uint8_t value = hexadecimal[total & 15u];
        total >>= 4; /* Only the original sixteen nibbles are emitted. */
        put_byte(p, (uint16_t)(word_at(p, (uint16_t)(descriptor + 10u)) + (unsigned)digit), value);
    }
    return 0;
}
