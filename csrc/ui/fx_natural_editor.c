/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_editor.h"
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

static int copy_tail(fx_platform *p, uint16_t destination, uint16_t source)
{
    for (unsigned i = 0; i < 65536; ++i) {
        uint8_t byte = byte_at(p, source++);
        put_byte(p, destination++, byte);
        if (!byte) return 0;
    }
    return -1;
}

/* A missing operand is necessary before a following power, or between an
 * opening field delimiter and its closing/next-field delimiter. */
static int requires_placeholder(fx_platform *p, uint16_t preceding, uint16_t following)
{
    uint16_t root = (uint16_t)(byte_at(p, 0x812c) | (uint16_t)byte_at(p, 0x812d) << 8);
    uint8_t category = fx_editor_cursor_category(p, preceding);
    int needs_operand = preceding < root || category == 2 || category == 5 || category == 8 ||
                        category == 10 || category >= 12;
    if (needs_operand && byte_at(p, following) == '^') return 1;
    uint8_t previous = byte_at(p, preceding), next = byte_at(p, following);
    return (previous == 0xb8 || previous == 0xba) && (next == 0xb9 || next == 0xba);
}

static int move_field(fx_platform *p, const fx_render *view, uint16_t position, uint8_t token)
{
    /* Climb enclosing constructs until a construct offers a vertical field
     * transition. Powers and ordinary functions simply defer to their owner. */
    for (unsigned searched = 0; searched < 65536; ++searched) {
        uint8_t parameter;
        uint16_t owner = fx_owning_construct(view, position, &parameter);
        if (!owner) { fx_clear_busy(p); return 0; }
        uint8_t construct = byte_at(p, owner), target = 0;
        int at_end = 0, available = 1;
        if (construct == 0x5d || construct == 0x69 || construct == 0x6a) {
            target = token == 0xe0 ? 2 : 1;
            at_end = token != 0xe0;
        } else if (construct == 0x7c && parameter) {
            target = token == 0xe0 ? 1 : 2;
            at_end = token == 0xe0;
        } else if (construct == 0xae) {
            target = token == 0xe0 ? 0 : 1;
            at_end = token == 0xe0;
        } else available = 0;
        if (!available || target == parameter) { position = owner; continue; }
        uint8_t offset = fx_parameter_length(view, owner, target);
        uint8_t length = at_end ? fx_field_length(view, (uint16_t)(owner + offset)) : 0;
        put_byte(p, 0x8114, (uint8_t)(owner - 0x8154 + offset + length));
        return fx_editor_resolve_position(p, 0) ? 0 : -1;
    }
    return -1;
}

static int remove_at_cursor(fx_platform *p, const fx_render *view, uint16_t position, uint8_t cursor)
{
    if (!byte_at(p, position)) {
        if (cursor <= 1) {
            put_byte(p, 0x8114, 0); put_byte(p, 0x8154, 0);
        } else {
            uint8_t preceding = byte_at(p, (uint16_t)(position - 1));
            if (preceding < 0xb8 || preceding > 0xbd)
                put_byte(p, (uint16_t)(position - 1), 0);
            if (!fx_editor_step(p, 0)) return -1;
        }
        return 0;
    }
    position = fx_editor_step(p, 0);
    if (!position) return -1;
    uint16_t following = (uint16_t)(position + 1);
    if (byte_at(p, position) == '!') {
        if (position != 0x8154) return 0;
        ++position;
    }
    uint8_t current = byte_at(p, position);
    if (current == 0xb9 || current == 0xba) return 0;
    if (fx_editor_cursor_category(p, position) != 1) {
        if (requires_placeholder(p, (uint16_t)(position - 1), following)) {
            put_byte(p, position, '!'); return 0;
        }
        return copy_tail(p, position, following);
    }
    /* Removing the construct shell preserves the eligible argument strings.
     * Log's base and integration/summation bounds are deliberately discarded. */
    uint8_t construct = byte_at(p, position);
    uint8_t type = byte_at(p, (uint16_t)(0x2c64 + fx_classify_construct_token(construct)));
    uint8_t span = (uint8_t)(fx_construct_length(view, position) + 1);
    uint8_t offsets[3] = {
        construct == 0x68 ? 0 : fx_parameter_length(view, position, 0),
        type == 3 || construct == 0x6b ? 0 : fx_parameter_length(view, position, 1),
        type == 4 ? fx_parameter_length(view, position, 2) : 0
    };
    uint16_t destination = position;
    if (construct == '^') {
        destination = fx_editor_resolve_position(p, 0);
        if (!destination) return -1;
    }
    uint16_t original_destination = destination;
    for (unsigned field = 0; field < 3; ++field) {
        if (!offsets[field]) continue;
        uint16_t source = (uint16_t)(position + offsets[field]);
        uint8_t next = byte_at(p, (uint16_t)(source + 1));
        uint8_t length = byte_at(p, source) == '!' && (next == 0xb9 || next == 0xba)
                         ? 0 : fx_field_length(view, source);
        for (unsigned i = 0; i < length; ++i)
            put_byte(p, destination++, byte_at(p, (uint16_t)(source + i)));
    }
    uint16_t tail = (uint16_t)(position + span);
    if (destination == original_destination && requires_placeholder(p, (uint16_t)(destination - 1), tail))
        put_byte(p, destination++, '!');
    return copy_tail(p, destination, tail);
}

int fx_editor_natural_action(fx_platform *p, uint8_t token)
{
    uint8_t cursor = byte_at(p, 0x8114);
    uint16_t position = (uint16_t)(0x8154 + cursor);
    uint16_t backup = byte_at(p, 0x80f9) == 136 ? 0x8546 : 0x8398;
    if (copy_tail(p, backup, 0x8154)) return -1;
    put_byte(p, 0x8006, cursor);
    fx_render view = {p->rom, p->rom_size, p->ram};
    switch (token) {
    case 0xe0:
    case 0xe1:
        (void)fx_acquire_busy(p);
        return move_field(p, &view, position, token);
    case 0xe2:
        (void)fx_acquire_busy(p);
        if (byte_at(p, position)) {
            if (!fx_editor_step(p, 1)) return -1;
            uint16_t next = fx_editor_resolve_position(p, 1);
            if (!next) return -1;
            if (!byte_at(p, next)) fx_clear_busy(p);
        } else put_byte(p, 0x8114, 0);
        if (!byte_at(p, 0x8154)) fx_clear_busy(p);
        return 0;
    case 0xe3:
        (void)fx_acquire_busy(p);
        if (cursor) {
            if (!fx_editor_step(p, 0)) return -1;
            uint16_t previous = fx_editor_resolve_position(p, 0);
            if (!previous) return -1;
            if (previous == 0x8154) fx_clear_busy(p);
        } else {
            unsigned length;
            for (length = 0; length < 65536; ++length)
                if (!byte_at(p, (uint16_t)(0x8154 + length))) break;
            if (length == 65536) return -1;
            put_byte(p, 0x8114, (uint8_t)length);
        }
        if (!byte_at(p, 0x8154)) fx_clear_busy(p);
        return 0;
    case 0xfe:
        return remove_at_cursor(p, &view, position, cursor);
    default:
        return 0;
    }
}
