/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_input_prepare.h"
#include "fx_editor.h"
#include "fx_input_codec.h"
#include "../parse/fx_tokens.h"

static uint8_t read_byte(fx_platform *p, uint16_t a)
{
    return fx_data_read(p, 0, a);
}

static void write_byte(fx_platform *p, uint16_t a, uint8_t v)
{
    fx_data_write(p, 0, a, v);
}

static uint16_t read_word(fx_platform *p, uint16_t a)
{
    return (uint16_t)(read_byte(p, a) | (uint16_t)read_byte(p, (uint16_t)(a + 1)) << 8);
}

static void write_word(fx_platform *p, uint16_t a, uint16_t v)
{
    write_byte(p, a, (uint8_t)v);
    write_byte(p, (uint16_t)(a + 1), (uint8_t)(v >> 8));
}

static int string_length(fx_platform *p, uint16_t source, uint16_t *length)
{
    if (!source) { *length = 0; return 0; }
    for (unsigned i = 0; i < 65536; ++i) {
        if (!read_byte(p, (uint16_t)(source + i))) {
            *length = (uint16_t)i;
            return 0;
        }
    }
    return -1;
}

/* Native32D4 is a forward copy, including its terminator; it does not use
 * memmove when buffers overlap. A zero destination is a no-op. */
static int copy_string(fx_platform *p, uint16_t destination, uint16_t source)
{
    if (!destination) return 0;
    if (!source) { write_byte(p, destination, 0); return 0; }
    for (unsigned i = 0; i < 65536; ++i) {
        uint8_t byte = read_byte(p, source++);
        write_byte(p, destination++, byte);
        if (!byte) return 0;
    }
    return -1;
}

uint16_t fx_input_workspace(fx_platform *p)
{
    uint8_t mode = read_byte(p, 0x80f9);
    if (mode == 0x88 || (mode & 0x40 && !(mode & 0x80))) return 0x8546;
    return mode & 0x80 ? 0x8398 : 0;
}

uint8_t fx_input_needs_export(fx_platform *p)
{
    return (uint8_t)(!fx_editor_is_special_view(p) && (read_byte(p, 0x80f9) & 0x80) != 0);
}

int fx_input_append_variable_suffix(fx_platform *p, uint16_t source)
{
    uint16_t length;
    if (read_byte(p, 0x80fc) != 1) return 0;
    if (string_length(p, source, &length)) return -1;
    /* The firmware compares R0, not the full ER0 string length. */
    if ((uint8_t)length == 1) {
        fx_evaluator_token decoded = fx_decode_evaluator_token(read_byte(p, source), read_byte(p, 0x80f9));
        if (decoded.kind == 1 && (decoded.value < 33 || decoded.value == 95)) {
            write_byte(p, (uint16_t)(source + 1), 0x8b);
            write_byte(p, (uint16_t)(source + 2), 0);
        }
    }
    return 0;
}

int fx_input_normalize_equation(fx_platform *p, uint16_t source)
{
    if (read_byte(p, 0x80f9) != 0x89) return 0;
    for (unsigned i = 0; i < 65536; ++i) {
        uint8_t token = read_byte(p, (uint16_t)(source + i));
        if (token >= 0x3c && token <= 0x3e) return 0;
        if (token >= 0x94 && token <= 0x96) return 0;
        if (!token) {
            write_byte(p, 0x8114, (uint8_t)i);
            if (fx_editor_insert_byte(p, '=') < 0) return -1;
            if (fx_editor_insert_byte(p, '0') < 0) return -1;
            return 0;
        }
    }
    return -1;
}

int fx_input_prepare_direct(fx_platform *p, uint16_t *source)
{
    if (!p || !source) return -1;
    *source = 0x8154;
    if (!fx_editor_is_special_view(p)) {
        if (read_byte(p, 0x80fe) & 0x40) write_word(p, 0x812c, read_word(p, 0x812e));
        else {
            if (fx_input_append_variable_suffix(p, *source)) return -1;
            uint8_t screen = read_byte(p, 0x80fc);
            if (!(read_byte(p, 0x80f9) & 0x80) && (screen == 1 || screen & 0x80)) {
                if (copy_string(p, 0x81b8, 0x8154)) return -1;
            }
        }
    }
    return 1;
}

static int export_display(fx_platform *p, uint16_t source, uint8_t continuation)
{
    if (fx_editor_has_natural_input(p)) {
        int allowed = fx_editor_input_boundaries(p, 0x8154);
        if (allowed <= 0) return allowed;
        return fx_editor_export_input(p, 0x8154, source, 0, 1) ? -1 : 1;
    }
    if (copy_string(p, source, 0x8154)) return -1;
    if (continuation) {
        /* E8B4 subtracts only the source low byte and zero-extends the
         * byte result before adding it to the display-root pointer. */
        uint8_t delta = (uint8_t)(read_byte(p, 0x812e) - (uint8_t)source);
        write_word(p, 0x812c, (uint16_t)(read_word(p, 0x812c) + delta));
    }
    return 1;
}

int fx_input_prepare_exported(fx_platform *p, uint16_t *source)
{
    if (!p || !source) return -1;
    *source = fx_input_workspace(p);
    if (read_byte(p, 0x80fc) == 6 && read_byte(p, 0x80fd) == 4) {
        if (copy_string(p, 0x8154, 0x81b8)) return -1;
    } else if (!(read_byte(p, 0x80fe) & 0x40)) {
        if (fx_input_append_variable_suffix(p, 0x8154) || fx_input_normalize_equation(p, 0x8154)
            || copy_string(p, 0x81b8, 0x8154)) return -1;
    }
    return export_display(p, *source, read_byte(p, 0x80fe) & 0x40);
}

int fx_input_prepare_saved_solve(fx_platform *p, uint16_t *source)
{
    if (!p || !source) return -1;
    *source = fx_input_workspace(p);
    if (copy_string(p, 0x8154, 0x85aa)) return -1;
    return export_display(p, *source, 0);
}
