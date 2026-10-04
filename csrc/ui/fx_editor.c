/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_editor.h"
#include "../parse/fx_tokens.h"

static uint8_t read_byte(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void write_byte(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

static uint8_t current_setup_item(fx_platform *p)
{
    uint8_t mode = read_byte(p, 0x80fa);
    if (mode >= 4 && read_byte(p, 0x8137)) mode = (uint8_t)(mode + 4);
    return read_byte(p, (uint16_t)(0x2ac4 + 5 * (uint8_t)(mode - 1) + read_byte(p, 0x80fd)));
}

uint8_t fx_editor_is_special_view(fx_platform *p)
{
    uint8_t screen = read_byte(p, 0x80fc), item = read_byte(p, 0x80fd);
    if ((screen & 0x80) && item == 2) return 1;
    if (screen == 9) return (uint8_t)(current_setup_item(p) != 9);
    return (uint8_t)(screen == 6 && item >= 1 && item <= 3);
}

uint8_t fx_editor_has_formula_view(fx_platform *p)
{
    return (uint8_t)(!(read_byte(p, 0x80fc) & 0x10) && !fx_editor_is_special_view(p));
}

uint8_t fx_editor_has_natural_input(fx_platform *p)
{
    return (uint8_t)(fx_editor_has_formula_view(p) && read_byte(p, 0x8106) &&
                     (read_byte(p, 0x80f9) & 0x80));
}

uint8_t fx_editor_has_natural_result(fx_platform *p)
{
    if (!fx_editor_has_formula_view(p)) return 0;
    uint8_t selection = read_byte(p, 0x8100) & 0x0f;
    if (selection == 14 || selection == 15) return 1;
    return (uint8_t)(read_byte(p, 0x8106) && (read_byte(p, 0x80f9) & 0x40));
}

uint8_t fx_editor_cursor_category(fx_platform *p, uint16_t position)
{
    uint8_t token = read_byte(p, position);
    uint8_t category = fx_classify_display_token(token);
    if (category == 1) {
        uint8_t next = read_byte(p, (uint16_t)(position + 1));
        if (next != 0xb8 && next != 0xbb && next != 0xbd)
            category = (uint8_t)((token == 0xae || token == 0x7c) ? 13 : 10);
    }
    return category;
}

uint8_t fx_editor_navigation_category(fx_platform *p, uint16_t position)
{
    uint8_t category = fx_editor_cursor_category(p, position);
    if (category == 3 && read_byte(p, (uint16_t)(position + 1)) == 0xb8) category = 4;
    return category;
}

static uint8_t insertion_blocked(uint8_t category)
{
    return (uint8_t)(category == 3 || category == 5 || category == 9 ||
                     category == 11 || category == 12);
}

static int string_length(fx_platform *p, uint16_t address, uint16_t *length)
{
    for (unsigned scanned = 0; scanned < 65536; ++scanned) {
        if (!read_byte(p, (uint16_t)(address + scanned))) {
            *length = (uint16_t)scanned;
            return 0;
        }
    }
    return -1;
}

int fx_editor_refresh_cursor(fx_platform *p)
{
    uint8_t natural = fx_editor_has_natural_input(p);
    if (natural && insertion_blocked(fx_editor_cursor_category(p, (uint16_t)(0x8154 + read_byte(p, 0x8114))))) {
        uint8_t flags = read_byte(p, 0x80f8);
        if (flags & 0x80) write_byte(p, 0x80f8, (uint8_t)((flags + 128) & ~8u));
    }
    uint16_t length;
    if (string_length(p, 0x8154, &length)) return -1;
    uint8_t insert = read_byte(p, 0x80f8) & 0x80;
    uint8_t glyph = (uint8_t)((uint8_t)(length + 11) >= 100 ? 0xcc : (insert ? 0xcf : 0x7c));
    if (natural && insert) glyph = 0x9e;
    write_byte(p, 0x811a, glyph);
    return 0;
}

int fx_editor_place_cursor(fx_platform *p, uint8_t x, uint8_t y)
{
    write_byte(p, 0x8118, x);
    write_byte(p, 0x8119, y);
    int status = fx_editor_refresh_cursor(p);
    if (!status) write_byte(p, 0x811b, read_byte(p, 0x811f));
    return status;
}

int fx_editor_update_modifiers(fx_platform *p, uint8_t token)
{
    if (token != 0xec) return fx_key_update_modifiers(p, token);
    uint8_t flags = read_byte(p, 0x80f8);
    if (!read_byte(p, 0x80fb)) flags = (uint8_t)(flags + 128);
    flags &= 0xf7;
    write_byte(p, 0x80f8, flags);
    int status = fx_editor_refresh_cursor(p);
    /* The native caller restores its saved temporary flags after refreshing.
     * The glyph can consequently describe a different insertion state. */
    write_byte(p, 0x80f8, flags);
    return status;
}

static uint8_t is_control(fx_platform *p, uint8_t token)
{
    return (uint8_t)(fx_editor_has_natural_input(p) && token >= 0xb8 && token <= 0xbd);
}

uint16_t fx_editor_step(fx_platform *p, uint8_t forward)
{
    uint8_t index = read_byte(p, 0x8114);
    if (forward) ++index;
    else if (index) --index;
    for (unsigned scanned = 0; scanned < 256; ++scanned) {
        uint16_t position = (uint16_t)(0x8154 + index);
        uint8_t token = read_byte(p, position);
        uint8_t skip = is_control(p, token);
        if ((token == 0xb9 || token == 0xba) && read_byte(p, (uint16_t)(position - 1)) != 0x21) skip = 0;
        if (!skip) {
            write_byte(p, 0x8114, index);
            return position;
        }
        if (forward) ++index;
        else if (index) --index;
    }
    return 0;
}

uint16_t fx_editor_resolve_position(fx_platform *p, uint8_t forward)
{
    uint8_t index = read_byte(p, 0x8114);
    uint16_t position = (uint16_t)(0x8154 + index);
    if (index && read_byte(p, (uint16_t)(position - 1)) == 0x21)
        return fx_editor_step(p, forward);
    return position;
}

static uint8_t attaches_to_caret(uint8_t category)
{
    return (uint8_t)(category == 2 || category == 5 || category == 8 ||
                     category == 10 || category >= 12);
}

int fx_editor_insert_byte(fx_platform *p, uint8_t token)
{
    uint16_t length;
    if (string_length(p, 0x8154, &length)) return -1;
    uint8_t natural = fx_editor_has_natural_input(p);
    uint8_t cursor = read_byte(p, 0x8114);
    uint16_t position = (uint16_t)(0x8154 + cursor);
    uint8_t generated[8] = {token, 0};
    unsigned generated_length = token ? 1 : 0;
    if (natural) {
        uint8_t context = read_byte(p, 0x80f9);
        uint16_t backup = context == 136 ? 0x8546 : 0x8398;
        for (unsigned i = 0; i <= length; ++i)
            write_byte(p, (uint16_t)(backup + i), read_byte(p, (uint16_t)(0x8154 + i)));
        write_byte(p, 0x8006, cursor);
        uint8_t existing = read_byte(p, position);
        uint8_t caret = (uint8_t)(existing == '^' || (existing == 0x21 && read_byte(p, (uint16_t)(position + 1)) == '^'));
        uint8_t category = fx_classify_display_token(token);
        if (category == 1) category = (uint8_t)((token == 0xae || token == 0x7c) ? 13 : 10);
        if (caret && attaches_to_caret(category)) {
            for (unsigned i = 0; i < 6; ++i) {
                uint8_t suffix = read_byte(p, (uint16_t)(0x2cc9 + i));
                if (!suffix) break;
                generated[generated_length++] = suffix;
            }
        }
    }
    int growth = (int)generated_length;
    uint8_t existing = read_byte(p, position);
    if ((!natural && (read_byte(p, 0x80f8) & 0x80) && existing) || existing == 0x21) --growth;
    /* Native capacity arithmetic is byte-valued, including malformed indices. */
    if ((uint8_t)((uint8_t)length + (uint8_t)growth) > 99) return 0;
    uint8_t tail = (uint8_t)length;
    if (tail >= cursor) {
        for (unsigned i = tail + 1; i > cursor; --i) {
            uint16_t source = (uint16_t)(0x8154 + i - 1);
            write_byte(p, (uint16_t)(source + (uint8_t)growth), read_byte(p, source));
        }
    } else {
        /* The native shift still copies its final byte when index>length. */
        uint16_t source = (uint16_t)(0x8154 + tail);
        write_byte(p, (uint16_t)(source + (uint8_t)growth), read_byte(p, source));
    }
    if (!generated_length) write_byte(p, position, 0);
    else for (unsigned i = 0; i < generated_length; ++i)
        write_byte(p, (uint16_t)(position + i), generated[i]);
    write_byte(p, 0x8114, (uint8_t)(cursor + 1));
    return 1;
}

int fx_editor_text_action(fx_platform *p, uint8_t token)
{
    if (fx_editor_has_natural_input(p)) return fx_editor_natural_action(p, token);
    uint16_t length;
    if (string_length(p, 0x8154, &length)) return -1;
    uint8_t cursor = read_byte(p, 0x8114);
    uint16_t position = (uint16_t)(0x8154 + cursor);
    uint8_t current = read_byte(p, position);
    switch (token) {
    case 0xe0:
    case 0xe1:
        write_byte(p, 0x8114, token == 0xe0 ? 0 : (uint8_t)length);
        if (!read_byte(p, 0x8154)) fx_clear_busy(p);
        return 0;
    case 0xe2:
        (void)fx_acquire_busy(p);
        if (current) {
            (void)fx_editor_step(p, 1);
            uint16_t moved = fx_editor_resolve_position(p, 1);
            if (!read_byte(p, moved)) fx_clear_busy(p);
        }
        else fx_clear_busy(p);
        return 0;
    case 0xe3:
        (void)fx_acquire_busy(p);
        if (cursor) {
            (void)fx_editor_step(p, 0);
            uint16_t moved = fx_editor_resolve_position(p, 0);
            if (moved == 0x8154 || !read_byte(p, moved)) fx_clear_busy(p);
        }
        else fx_clear_busy(p);
        return 0;
    case 0xfe:
        if (!current) {
            if (cursor <= 1) {
                write_byte(p, 0x8114, 0);
                write_byte(p, 0x8154, 0);
            } else {
                write_byte(p, (uint16_t)(position - 1), 0);
                (void)fx_editor_step(p, 0);
            }
            return 0;
        }
        if (!(read_byte(p, 0x80f8) & 0x80)) position = fx_editor_step(p, 0);
        for (unsigned copied = 0; copied < 65536; ++copied) {
            uint8_t next = read_byte(p, (uint16_t)(position + 1));
            write_byte(p, position, next);
            if (!next) return 0;
            ++position;
        }
        return -1;
    default:
        return 0;
    }
}
