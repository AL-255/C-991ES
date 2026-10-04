/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_editor.h"
#include "../parse/fx_tokens.h"
#include "../render/fx_layout_validate.h"

/* A construct is assembled before the edit is committed. The original also
 * uses a temporary string; no instruction or CPU state is represented here. */
typedef struct {
    uint8_t bytes[520];
    unsigned length;
} construct_string;

static uint8_t byte_at(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void put_byte(fx_platform *p, uint16_t address, uint8_t byte)
{
    fx_data_write(p, 0, address, byte);
}

static int append_byte(construct_string *s, uint8_t byte)
{
    if (s->length + 1 >= sizeof(s->bytes)) return -1;
    s->bytes[s->length++] = byte;
    s->bytes[s->length] = 0;
    return 0;
}

static int append_constant(fx_platform *p, construct_string *s, uint16_t address)
{
    for (unsigned i = 0; i < 65536; ++i) {
        uint8_t byte = byte_at(p, (uint16_t)(address + i));
        if (!byte) return 0;
        if (append_byte(s, byte)) return -1;
    }
    return -1;
}

static int append_field(fx_platform *p, construct_string *s, uint8_t index, uint8_t count)
{
    uint16_t source = (uint16_t)(0x8154 + index);
    if (!count || byte_at(p, source) == '^') {
        if (append_byte(s, '!')) return -1;
    }
    for (unsigned i = 0; i < count; ++i)
        if (append_byte(s, byte_at(p, (uint16_t)(source + i)))) return -1;
    return 0;
}

static int has_previous_operand(fx_platform *p, uint16_t position)
{
    uint16_t root = (uint16_t)(byte_at(p, 0x812c) | (uint16_t)byte_at(p, 0x812d) << 8);
    if (position <= root) return 0;
    uint8_t previous = byte_at(p, (uint16_t)(position - 1));
    if (previous == 0xb9 || previous == 0xbc) return 1;
    if (previous == 0xb8 || previous == 0xba || previous == 0x97) return 0;
    uint8_t kind = fx_decode_evaluator_token(previous, byte_at(p, 0x80f9)).kind;
    return kind == 3 || kind == 4 || kind == 5 || kind == 6 || kind == 7 || kind == 8;
}

static int needs_power_placeholder(fx_platform *p, uint16_t preceding)
{
    uint16_t root = (uint16_t)(byte_at(p, 0x812c) | (uint16_t)byte_at(p, 0x812d) << 8);
    if (preceding < root) return 1;
    uint8_t category = fx_editor_cursor_category(p, preceding);
    return category == 2 || category == 5 || category == 8 || category == 10 || category >= 12;
}

int fx_editor_insert_construct(fx_platform *p, uint8_t token)
{
    if (!fx_editor_has_natural_input(p)) return fx_editor_insert_byte(p, token);
    unsigned expression_length;
    for (expression_length = 0; expression_length < 65536; ++expression_length)
        if (!byte_at(p, (uint16_t)(0x8154 + expression_length))) break;
    if (expression_length == 65536) return -1;
    uint8_t cursor = byte_at(p, 0x8114), insertion = cursor;
    uint8_t overwrite = (uint8_t)!!(byte_at(p, 0x80f8) & 0x80);
    uint16_t position = (uint16_t)(0x8154 + cursor);
    uint16_t backup = byte_at(p, 0x80f9) == 136 ? 0x8546 : 0x8398;
    for (unsigned i = 0; i <= expression_length; ++i)
        put_byte(p, (uint16_t)(backup + i), byte_at(p, (uint16_t)(0x8154 + i)));
    put_byte(p, 0x8006, cursor);
    fx_render view = {p->rom, p->rom_size, p->ram};
    uint8_t captured = 0, previous = 0, advance = 2;
    if (overwrite || token == '^' || token == 0x9f || token == 0xae || token == 0x7c)
        captured = fx_atom_length(&view, position, 0, overwrite);
    uint8_t construct = token;
    if (token >= 0x75 && token <= 0x77) {
        construct = '^'; captured = 0;
        advance = token == 0x77 ? 5 : 4;
    } else if (token == 0xa8) construct = 0x9f;
    construct_string generated = {{0}, 0};
    if (construct && append_byte(&generated, construct)) return -1;
    uint8_t type = 5;
    if (fx_classify_display_token(construct) == 1)
        type = byte_at(p, (uint16_t)(0x2c64 + fx_classify_construct_token(construct)));
    int leading_placeholder = construct == '^' && needs_power_placeholder(p, (uint16_t)(position - 1));
    if (leading_placeholder) {
        generated.length = 0; generated.bytes[0] = 0;
        if (append_constant(p, &generated, 0x2ccb)) return -1;
        advance = 0;
    }
    uint8_t cost = byte_at(p, (uint16_t)(0x2cb8 + type));
    if ((uint8_t)(cost + captured + (byte_at(p, position) == '^') + leading_placeholder) >= 100) return 0;

    if (type == 0) {
        if (append_constant(p, &generated, 0x1ac6)) return -1;
        if (token >= 0x75 && token <= 0x77) {
            if (append_constant(p, &generated, token == 0x75 ? 0x2cce : token == 0x76 ? 0x2cd0 : 0x2cd2)) return -1;
        } else if (append_field(p, &generated, cursor, captured)) return -1;
        if (append_constant(p, &generated, 0x1ac8)) return -1;
    } else if (type == 1) {
        if (append_constant(p, &generated, 0x1ac6) ||
            append_field(p, &generated, cursor, token == 0x68 ? 0 : captured) ||
            append_constant(p, &generated, 0x2cd5) ||
            append_field(p, &generated, cursor, token == 0x68 ? captured : 0) ||
            append_constant(p, &generated, 0x1ac8)) return -1;
    } else if (type == 3) {
        if (append_constant(p, &generated, 0x1ac6) || append_field(p, &generated, cursor, captured) ||
            append_constant(p, &generated, 0x2cda)) return -1;
    } else if (type == 2 || type == 4) {
        advance = type == 2 ? 3 : 4;
        if (type == 4 || token != 0xa8) {
            if (has_previous_operand(p, position)) {
                uint16_t start = fx_previous_atom_start(&view, position);
                previous = (uint8_t)(position - start);
                if (!previous) return 0;
                if ((uint8_t)(captured + previous + cost + (byte_at(p, position) == '^') +
                              (byte_at(p, start) == '^')) >= 100) return 0;
                insertion = (uint8_t)(insertion - previous);
                advance = (uint8_t)(advance + previous + (byte_at(p, start) == '^') + 2);
            }
        }
        if (type == 4) {
            if (append_constant(p, &generated, 0x2ce0) || append_field(p, &generated, insertion, previous) ||
                append_constant(p, &generated, 0x1aca) ||
                append_field(p, &generated, cursor, cursor == insertion ? 0 : captured) ||
                append_constant(p, &generated, 0x1aca) ||
                append_field(p, &generated, cursor, cursor == insertion ? captured : 0) ||
                append_constant(p, &generated, 0x1acd)) return -1;
        } else {
            if (append_constant(p, &generated, 0x2cd7)) return -1;
            if (token == 0xa8) {
                if (append_constant(p, &generated, 0x2cd0)) return -1;
                advance = 6;
            } else if (append_field(p, &generated, insertion, previous)) return -1;
            if (append_constant(p, &generated, 0x1aca) || append_field(p, &generated, cursor, captured) ||
                append_constant(p, &generated, 0x1acd)) return -1;
        }
        captured = (uint8_t)(captured + previous);
    }
    uint8_t growth = (uint8_t)(generated.length - captured);
    if (byte_at(p, position) == '!' && !captured) --growth;
    uint8_t length = (uint8_t)expression_length;
    if ((uint8_t)(length + growth) > 99) return 0;
    unsigned tail = length;
    for (;;) {
        uint16_t source = (uint16_t)(0x8154 + tail);
        put_byte(p, (uint16_t)(source + growth), byte_at(p, source));
        if (tail <= insertion) break;
        --tail;
    }
    /* Native string copy writes the first byte even for an empty string. */
    unsigned copy = 0;
    do {
        put_byte(p, (uint16_t)(0x8154 + insertion + copy), generated.bytes[copy]);
        ++copy;
    } while (generated.bytes[copy]);
    put_byte(p, 0x8114, (uint8_t)(insertion + advance));
    return 1;
}
