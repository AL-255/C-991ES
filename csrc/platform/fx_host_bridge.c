/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_host_bridge.h"
#include "../ui/fx_cursor.h"

static const fx_host_descriptor default_descriptor = {
    0x8e00, 0x8e01, 0x8e02, 0x8e10, 0x9000,
    0x9800, 0x9804, 0x9808, 0x9834, 0x9838
};

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

static uint16_t descriptor_pointer(fx_platform *p,
                                  const fx_host_descriptor *fields,
                                  uint16_t ram_descriptor, unsigned offset)
{
    /* The RAM adapter rereads each pointer after packet writes, preserving
     * native descriptor/destination aliasing. Host fields need no RAM copy. */
    if (!fields) return word_at(p, (uint16_t)(ram_descriptor + offset));
    switch (offset) {
    case 0: return fields->wait_flag;
    case 2: return fields->key_columns;
    case 4: return fields->key_rows;
    case 6: return fields->numeric_packet;
    case 8: return fields->framebuffer_packet;
    case 10: return fields->packet_length;
    case 12: return fields->status_packet;
    case 14: return fields->status_details;
    case 16: return fields->text_header;
    case 18: return fields->text;
    default: return 0;
    }
}

void fx_host_descriptor_default(fx_host_descriptor *descriptor)
{
    *descriptor = default_descriptor;
}

void fx_host_write_descriptor(fx_platform *p, uint16_t destination)
{
    for (unsigned n = 0; n < 10; ++n)
        put_word(p, (uint16_t)(destination + 2u*n),
                 descriptor_pointer(p, &default_descriptor, 0, 2u*n));
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
    fx_host_write_framebuffer_fields(p, &default_descriptor);
}

void fx_host_write_framebuffer_fields(fx_platform *p,
                                      const fx_host_descriptor *descriptor)
{
    uint16_t destination = descriptor->framebuffer_packet;
    put_byte(p, destination++, 0x80);
    put_byte(p, destination++, 1);
    for (unsigned row = 0; row < 32; ++row)
        for (unsigned column = 0; column < 12; ++column)
            put_byte(p, destination++, byte_at(p, (uint16_t)(0xf800 + 16u*row + column)));
}

static int write_text_packet(fx_platform *p, const fx_host_descriptor *fields,
                             uint16_t descriptor)
{
    fx_host_write_status(p, descriptor_pointer(p, fields, descriptor, 12));
    uint16_t text = descriptor_pointer(p, fields, descriptor, 18);
    unsigned length = 0;
    if (text) {
        while (length < 65536 && byte_at(p, (uint16_t)(text + length))) ++length;
        if (length == 65536) return -1;
    }
    uint16_t payload_length = (uint16_t)(length + 1u);
    if ((int16_t)payload_length > 1) {
        payload_length = (uint16_t)(payload_length + 4u);
        put_byte(p, descriptor_pointer(p, fields, descriptor, 16), 0x22);
        put_byte(p, (uint16_t)(descriptor_pointer(p, fields, descriptor, 16) + 1u), 0xff);
        put_byte(p, (uint16_t)(descriptor_pointer(p, fields, descriptor, 16) + 2u), (uint8_t)(payload_length >> 8));
        put_byte(p, (uint16_t)(descriptor_pointer(p, fields, descriptor, 16) + 3u), (uint8_t)payload_length);
    } else {
        put_byte(p, descriptor_pointer(p, fields, descriptor, 16), 0);
    }
    uint16_t total = (uint16_t)(payload_length + 48u);
    static const uint8_t hexadecimal[] = "0123456789ABCDEF";
    for (int digit = 3; digit >= 0; --digit) {
        uint8_t value = hexadecimal[total & 15u];
        total >>= 4; /* Only the original sixteen nibbles are emitted. */
        put_byte(p, (uint16_t)(descriptor_pointer(p, fields, descriptor, 10) + (unsigned)digit), value);
    }
    return 0;
}

int fx_host_write_text_packet(fx_platform *p, uint16_t descriptor)
{
    return write_text_packet(p, NULL, descriptor);
}

int fx_host_write_text_packet_fields(fx_platform *p,
                                    const fx_host_descriptor *descriptor)
{
    if (!descriptor) return -1;
    return write_text_packet(p, descriptor, 0);
}

static uint8_t export_digit(unsigned nibble)
{
    return (uint8_t)(nibble == 10 ? 'a' : '0' + nibble);
}

static void export_pair(uint8_t *output, uint8_t packed)
{
    output[0] = export_digit(packed >> 4);
    output[1] = export_digit(packed & 15u);
}

int fx_host_format_number(const fx_number *number, uint8_t output[23])
{
    if (!number || !output) return -1;
    /* Native numeric output uses a copied record, including when source and
     * destination overlap. No decimal/rational normalization is performed. */
    fx_number copied = *number;
    const uint8_t *record = copied.bytes;
    unsigned kind = record[0] >> 4;
    if (kind == 15) {
        static const uint8_t error[] = "ERROR";
        for (unsigned n = 0; n < sizeof error; ++n) output[n] = error[n];
        return 1;
    }
    if (!(record[8] | record[9])) {
        static const uint8_t zero[] = "+0.00000000000000E+000";
        for (unsigned n = 0; n < sizeof zero; ++n) output[n] = zero[n];
        return 0;
    }
    unsigned sign_byte = record[9];
    uint8_t sign = (uint8_t)(sign_byte >= 5 ? '-' : '+');
    if (sign_byte >= 5) sign_byte -= 5;
    int exponent = (int)(100u*(sign_byte & 15u)
                 + 10u*(record[8] >> 4) + (record[8] & 15u)) - 100;
    unsigned magnitude = (unsigned)(exponent < 0 ? -exponent : exponent);
    if (kind == 2 && magnitude >= 22) return -1;

    if (kind == 8) {
        output[0] = sign;
        export_pair(output + 1, record[2]);
        output[3] = 'r';
        output[4] = export_digit(record[0] & 15u);
        export_pair(output + 5, record[1]);
        output[7] = 's';
        export_pair(output + 8, record[3]);
        output[10] = (uint8_t)(record[8] >= 5 ? '-' : '+');
        export_pair(output + 11, record[6]);
        output[13] = 'r';
        output[14] = export_digit(record[4] & 15u);
        export_pair(output + 15, record[5]);
        output[17] = 's';
        export_pair(output + 18, record[7]);
        output[20] = ' ';
        output[21] = 'T';
        return 0;
    }

    unsigned position = 0;
    output[position++] = sign;
    output[position++] = export_digit(record[0] & 15u);
    if (kind != 2) output[position++] = '.';
    for (unsigned n = 1; n < 8; ++n) {
        export_pair(output + position, record[n]);
        position += 2;
    }
    output[position++] = 'E';
    output[position++] = (uint8_t)(exponent < 0 ? '-' : '+');
    if (kind == 2) {
        for (unsigned n = magnitude + 1; n < 22; ++n) output[n] = ' ';
        output[22] = 0;
        output[17] = 'B';
    } else {
        output[position++] = (uint8_t)('0' + magnitude/100);
        output[position++] = (uint8_t)('0' + (magnitude/10)%10);
        output[position++] = (uint8_t)('0' + magnitude%10);
        output[position] = 0;
    }
    return 0;
}

int fx_host_write_numeric_packet_fields(fx_platform *p,
                                       const fx_host_descriptor *descriptor)
{
    if (!descriptor) return -1;
    fx_number real, imaginary = {{0}};
    for (unsigned n = 0; n < 10; ++n) real.bytes[n] = byte_at(p, (uint16_t)(0x8230 + n));
    if (byte_at(p, 0x80f9) == 0xc4)
        for (unsigned n = 0; n < 10; ++n)
            imaginary.bytes[n] = byte_at(p, (uint16_t)(0x8412 + n));
    uint8_t real_field[23] = {0}, imaginary_field[23] = {0};
    if (fx_host_format_number(&real, real_field) < 0
        || fx_host_format_number(&imaginary, imaginary_field) < 0) return -1;
    uint16_t destination = descriptor->numeric_packet;
    static const uint8_t header[4] = {0x30, 0, 0x43, 9};
    for (unsigned n = 0; n < 4; ++n) put_byte(p, destination++, header[n]);
    for (unsigned n = 0; n < 22; ++n) put_byte(p, destination++, real_field[n]);
    put_byte(p, destination++, 9);
    for (unsigned n = 0; n < 23; ++n) put_byte(p, destination++, imaginary_field[n]);
    return 0;
}

int fx_host_write_numeric_packet(fx_platform *p)
{
    return fx_host_write_numeric_packet_fields(p, &default_descriptor);
}
