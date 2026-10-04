/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_input_codec.h"
#include "../parse/fx_tokens.h"
#include "../render/fx_layout_validate.h"

static uint8_t byte_at(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void put_byte(fx_platform *p, uint16_t address, uint8_t byte)
{
    fx_data_write(p, 0, address, byte);
}

static uint16_t word_at(fx_platform *p, uint16_t address)
{
    return (uint16_t)(byte_at(p, address) | (uint16_t)byte_at(p, (uint16_t)(address + 1)) << 8);
}

static void put_word(fx_platform *p, uint16_t address, uint16_t word)
{
    put_byte(p, address, (uint8_t)word);
    put_byte(p, (uint16_t)(address + 1), (uint8_t)(word >> 8));
}

/* A closing field followed by another field has an infix fraction/root
 * operator. Walk balanced field brackets to identify the containing prefix. */
static int field_separator(fx_platform *p, uint16_t closing, uint8_t *separator)
{
    uint8_t depth = 0;
    for (unsigned scanned = 0; scanned < 65536; ++scanned) {
        uint8_t token = byte_at(p, closing--);
        if (token == 0xb9) ++depth;
        else if (token == 0xb8 && !--depth) {
            token = byte_at(p, closing);
            if (token == 0xbb) {
                token = byte_at(p, --closing);
                if (token == 0xbd) token = byte_at(p, --closing);
                *separator = token == 0x7c ? 0xae : token;
            } else *separator = token == 0xb9 ? 0xae : 0;
            return 0;
        }
    }
    return -1;
}

static void map_cursor(fx_platform *p, uint16_t source_begin, uint16_t source)
{
    uint8_t token = byte_at(p, source);
    if (token == 0xbc || token == 0xb8) ++source;
    else if (token == 0xbb) --source;
    if (byte_at(p, source) == 0xbd) --source;
    put_byte(p, 0x8114, (uint8_t)(source - source_begin));
}

int fx_editor_export_input(fx_platform *p, uint16_t source, uint16_t destination,
                           uint8_t input_cursor, uint8_t full_expression)
{
    uint16_t source_begin = source, destination_begin = destination;
    uint8_t tracked_root = byte_at(p, 0x80fe) & 0x40;
    fx_render view = {p->rom, p->rom_size, p->ram};
    for (unsigned scanned = 0; scanned < 65536; ++scanned) {
        uint8_t category = fx_editor_navigation_category(p, source);
        uint8_t token = byte_at(p, source);
        switch (category) {
        case 1: {
            uint8_t type = 5;
            if (fx_editor_cursor_category(p, source) == 1)
                type = byte_at(p, (uint16_t)(0x2c64 + fx_classify_construct_token(token)));
            if (type == 4) ++source;
            else if (type != 2) put_byte(p, destination++, token);
            break;
        }
        case 2: {
            uint8_t preceding = byte_at(p, (uint16_t)(destination - 1));
            if (fx_classify_display_token(preceding) != 1 || preceding == 0xae)
                put_byte(p, destination++, '(');
            break;
        }
        case 3: {
            uint8_t parameter;
            uint16_t owner = fx_owning_construct(&view, source, &parameter);
            if (byte_at(p, owner) != 0xa4) put_byte(p, destination++, ')');
            break;
        }
        case 4: {
            put_byte(p, destination++, ')');
            if (!full_expression && destination == (uint16_t)(destination_begin + input_cursor + 1)) {
                put_byte(p, 0x8114, (uint8_t)(source - source_begin));
                return 0;
            }
            uint8_t separator;
            if (field_separator(p, source, &separator)) return -1;
            put_byte(p, destination++, separator);
            break;
        }
        case 5:
            put_byte(p, destination++, ','); break;
        case 6:
            put_byte(p, destination++, '('); break;
        case 7:
            put_byte(p, destination++, ')'); break;
        default:
            put_byte(p, destination++, token); break;
        }
        if (!full_expression && destination == (uint16_t)(destination_begin + input_cursor + 1)) {
            map_cursor(p, source_begin, source);
            return 0;
        }
        if (full_expression && tracked_root && word_at(p, 0x812e) == destination &&
            word_at(p, 0x812c) == source_begin)
            put_word(p, 0x812c, (uint16_t)(source + 1));
        ++source;
        if (!byte_at(p, source)) {
            put_byte(p, destination, 0);
            if (!full_expression) put_byte(p, 0x8114, (uint8_t)(source - source_begin));
            return 0;
        }
    }
    return -1;
}

int fx_editor_input_boundaries(fx_platform *p, uint16_t source)
{
    fx_render view = {p->rom, p->rom_size, p->ram};
    uint8_t index = 0;
    for (unsigned scanned = 0; scanned < 65536; ++scanned, ++source, ++index) {
        uint8_t token = byte_at(p, source);
        if (!token) return 1;
        uint8_t category = fx_editor_cursor_category(p, source);
        int violation = 0;
        if (category == 8 || category == 10) {
            uint16_t end = (uint16_t)(source + fx_parenthesis_length(&view, source));
            token = byte_at(p, end);
            violation = token == 0xb9 || token == 0xba;
        } else if (category == 9) {
            uint8_t matched;
            uint16_t opening = fx_parenthesis_start(&view, source, &matched);
            token = byte_at(p, opening);
            violation = token == 0xb8 || token == 0xba;
        } else if (category == 12) {
            int allowed_comma = 0;
            if (token == ',') {
                uint8_t matched;
                uint16_t opening = fx_parenthesis_start(&view, source, &matched);
                token = byte_at(p, opening);
                allowed_comma = token == 0x68 || token == 0x6c || token == 0x6d || token == 0xc2 ||
                                token == '?' || token == 0xa6 || token == 0xa7;
            }
            if (!allowed_comma) {
                uint8_t parameter;
                violation = fx_owning_construct(&view, source, &parameter) != 0;
            }
        }
        if (violation) {
            put_byte(p, 0x8114, index);
            return 0;
        }
    }
    return -1;
}
