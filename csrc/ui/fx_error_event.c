/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_error_event.h"
#include "fx_error_display.h"
#include "fx_editor.h"
#include "../platform/fx_boot.h"
#include "../platform/fx_host_bridge.h"

static uint8_t read_byte(fx_platform *p, uint16_t a)
{
    return fx_data_read(p, 0, a);
}

static void write_byte(fx_platform *p, uint16_t a, uint8_t v)
{
    fx_data_write(p, 0, a, v);
}

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

int fx_error_write_host_text(fx_platform *p, uint16_t error)
{
    /*300A selects these twelve semantic error IDs from the original local
     *48-entry message table. Its unselected entries have no persistent effect.
     *The fifth firmware error maps to ID48; error6 maps to unknown ID23. */
    static const struct { uint16_t text; uint8_t append_error; } messages[12] = {
        {0x3022,0}, {0x302a,1}, {0x3031,1}, {0x3034,1},
        {0x3189,0}, {0x30da,1}, {0x3046,1}, {0x304c,1},
        {0x3055,1}, {0x3107,0}, {0x3180,0}, {0x30b8,0}
    };
    if (!p) return -1;
    unsigned index = error >= 1 && error <= 12 ? error - 1u : 5u;
    if (copy_string(p, 0x9838, messages[index].text)) return -1;
    if (messages[index].append_error) {
        unsigned length;
        for (length = 0; length < 65536 && read_byte(p, (uint16_t)(0x9838 + length)); ++length) {}
        if (length == 65536 || copy_string(p, (uint16_t)(0x9838 + length), 0x3197)) return -1;
    }
    fx_host_descriptor descriptor;
    fx_host_descriptor_default(&descriptor);
    return fx_host_write_text_packet_fields(p, &descriptor);
}

static uint8_t cursor_token(fx_platform *p, uint8_t token)
{
    return (uint8_t)(read_byte(p, 0x80f7) && (token == 0xe2 || token == 0xe3));
}

uint8_t fx_error_accepts_token(fx_platform *p, uint8_t token)
{
    return (uint8_t)(token == 0xe6 || cursor_token(p, token));
}

fx_key_controller_status fx_error_event_begin(fx_platform *p,
                                              fx_error_event *state,
                                              uint8_t error)
{
    if (!p || !state) return FX_KEY_CONTROLLER_INVALID;
    state->error = error;
    state->token = state->event = 0;
    state->active = 0;
    if (fx_error_write_host_text(p, error) || fx_error_display(p, error))
        return FX_KEY_CONTROLLER_UNIMPLEMENTED;
    fx_key_controller_status result = fx_key_controller_begin(p, &state->key);
    if (result == FX_KEY_CONTROLLER_WAIT) state->active = 1;
    return result;
}

fx_key_controller_status fx_error_event_tick(fx_platform *p,
                                             fx_error_event *state)
{
    if (!p || !state || !state->active) return FX_KEY_CONTROLLER_INVALID;
    if (state->event) return (fx_key_controller_status)state->event;
    fx_key_controller_status result = fx_key_controller_tick(p, &state->key);
    if (result == FX_KEY_CONTROLLER_TOKEN) {
        uint8_t token;
        (void)fx_key_controller_finish(&state->key, &token);
        if (fx_error_accepts_token(p, token)) {
            state->token = token;
            state->event = FX_KEY_CONTROLLER_TOKEN;
            return FX_KEY_CONTROLLER_TOKEN;
        }
        return fx_key_controller_begin(p, &state->key);
    }
    if (result == FX_KEY_CONTROLLER_RESET) {
        (void)fx_key_controller_finish(&state->key, &state->token);
        state->event = FX_KEY_CONTROLLER_RESET;
    }
    return result;
}

fx_key_controller_status fx_error_event_finish(fx_error_event *state,
                                               uint8_t *token)
{
    if (!state || !state->active || !state->event) return FX_KEY_CONTROLLER_INVALID;
    if (token) *token = state->token;
    state->active = 0;
    return (fx_key_controller_status)state->event;
}

static void prepare_input(fx_platform *p)
{
    /*1D652: select ordinary editable input without clearing its expression. */
    write_byte(p, 0x80fc, 1);
    write_byte(p, 0x80fd, 0);
    write_byte(p, 0x80fe, 1);
    write_byte(p, 0x80ff, 0);
}

int fx_error_cursor_restore(fx_platform *p, const fx_error_context *context)
{
    if (!p || !context) return -1;
    uint8_t token = read_byte(p, 0x80f5);
    if (!cursor_token(p, token)) return 4;
    uint8_t screen = read_byte(p, 0x80fc);
    if (read_byte(p, 0x80fe) & 0x80) {
        if (!fx_editor_is_special_view(p) && ((screen & 0x80) || screen == 6)) prepare_input(p);
        if (fx_boot_initialize_editor(p, 0x82) != FX_BOOT_READY) return -1;
    } else {
        if (context->calculation_mode == 0x88 || context->calculation_mode == 0x45
            || context->calculation_mode == 0x4b || context->calculation_mode == 0x0c) return 4;
        uint8_t display_state = read_byte(p, 0x80fe) & 15;
        if (display_state == 3 || display_state == 5) {
            prepare_input(p);
            if (fx_boot_initialize_editor(p, 0x80) != FX_BOOT_READY) return -1;
        } else {
            if (read_byte(p, context->display_address) || screen != 1) return 4;
            if (copy_string(p, context->display_address, 0x81b8)) return -1;
        }
        uint16_t length = 0;
        if (token != 0xe2 && context->display_address) {
            unsigned i;
            for (i = 0; i < 65536 && read_byte(p, (uint16_t)(context->display_address + i)); ++i) {}
            if (i == 65536) return -1;
            length = (uint16_t)i;
        }
        write_byte(p, 0x8114, (uint8_t)length);
    }
    (void)fx_acquire_busy(p);
    return 1;
}

int fx_error_result_cursor(fx_platform *p)
{
    if (!p) return -1;
    uint8_t token = read_byte(p, 0x80f5);
    uint8_t display_state = read_byte(p, 0x80fe) & 15;
    if (!cursor_token(p, token) || !fx_editor_has_natural_result(p)
        || (display_state != 3 && display_state != 5) || !read_byte(p, 0x8130)) return 4;
    (void)fx_acquire_busy(p);
    uint8_t cursor = read_byte(p, 0x8114);
    if (token == 0xe2) write_byte(p, 0x8114, (uint8_t)(cursor + 1));
    else if (cursor) write_byte(p, 0x8114, (uint8_t)(cursor - 1));
    else fx_clear_busy(p);
    return 3;
}
