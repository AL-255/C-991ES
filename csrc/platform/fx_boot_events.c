/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_boot_events.h"
#include "../render/fx_render_memory.h"
#include <string.h>

static uint8_t read_byte(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void write_byte(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

static fx_render display(fx_platform *p)
{
    fx_render render = {p->rom, p->rom_size, p->ram};
    return render;
}

/* Text assembled by native CPU locals is supplied directly to the renderer.
 * This follows3A4A's bounds without inventing persistent calculator RAM. */
static void draw_bytes(fx_platform *p, uint8_t x, int8_t y,
                       const uint8_t *text, size_t length)
{
    fx_render render = display(p);
    write_byte(p, 0x811f, 7);
    for (size_t n = 0; n < length && n < 16 && text[n] && x <= 90; ++n) {
        fx_draw_glyph(&render, x, y, text[n]);
        x = (uint8_t)(x + 6);
    }
}

static void draw_rom(fx_platform *p, int8_t y, uint16_t text)
{
    fx_render render = display(p);
    write_byte(p, 0x811f, 7);
    fx_draw_text(&render, 0, y, &text);
}

static void flush(fx_platform *p)
{
    fx_render render = display(p);
    fx_flush_framebuffer(&render);
}

void fx_welcome_draw_banner(fx_platform *p)
{
    fx_render render = display(p);
    fx_fill_display(&render, 0, 1);
    draw_rom(p, 1, 0x2da7);
    draw_rom(p, 22, 0x2d8c);
    flush(p);
}

void fx_welcome_begin(fx_welcome_state *state)
{
    if (!state) return;
    state->remaining = 0x094d;
    state->remembered.columns = 0x80;
    state->remembered.rows = 1;
    state->decision = 0;
    state->phase = FX_WELCOME_RELEASE;
    state->active = 1;
}

static fx_boot_event_status welcome_done(fx_platform *p, fx_welcome_state *state)
{
    fx_key_deselect_all(p);
    state->phase = FX_WELCOME_DONE;
    state->active = 0;
    return FX_BOOT_EVENT_READY;
}

fx_boot_event_status fx_welcome_accept_pair(fx_platform *p,
    fx_welcome_state *state, fx_key_state key)
{
    if (!p || !p->ram || !state || !state->active ||
        state->phase != FX_WELCOME_SCAN) return FX_BOOT_EVENT_INVALID;
    if (key.columns == 4 && key.rows == 4) {
        state->decision = 1;
        return welcome_done(p, state);
    }
    if (key.columns == 4 && key.rows == 16) return welcome_done(p, state);
    state->remembered = key;
    state->phase = FX_WELCOME_RELEASE;
    return FX_BOOT_EVENT_WAIT;
}

fx_boot_event_status fx_welcome_tick(fx_platform *p,
    fx_welcome_state *state, const fx_key_input *input)
{
    if (!p || !p->ram || !state) return FX_BOOT_EVENT_INVALID;
    if (state->phase == FX_WELCOME_DONE) return FX_BOOT_EVENT_READY;
    if (!state->active) return FX_BOOT_EVENT_INVALID;
    if (state->phase == FX_WELCOME_RELEASE) {
        uint16_t old_remaining = state->remaining--;
        if (!old_remaining) return welcome_done(p, state);
        fx_timer_start(p, 20);
        if (fx_key_is_held(p, input, &state->remembered)) return FX_BOOT_EVENT_WAIT;
        fx_key_drive_enable(p);
        fx_key_select_all(p);
        state->phase = FX_WELCOME_POLL;
        return FX_BOOT_EVENT_WAIT;
    }
    if (state->phase == FX_WELCOME_POLL) {
        if (!--state->remaining) {
            fx_key_deselect_all(p);
            fx_key_drive_disable(p);
            return welcome_done(p, state);
        }
        fx_timer_start(p, 20);
        fx_key_select_all(p);
        uint8_t columns = input && input->sample ? input->sample(input->context, 0x7f)
                                                : read_byte(p, 0xf040);
        if (columns != 0xff) state->phase = FX_WELCOME_SCAN;
        return FX_BOOT_EVENT_WAIT;
    }
    if (state->phase == FX_WELCOME_SCAN) {
        fx_key_state captured = {0, 0};
        fx_key_deselect_all(p);
        fx_key_drive_disable(p);
        fx_timer_start(p, 1);
        if (fx_key_scan(p, input, &captured) && fx_key_debounce(p, input, &captured))
            return fx_welcome_accept_pair(p, state, captured);
        fx_key_drive_enable(p);
        fx_key_select_all(p);
        state->phase = FX_WELCOME_POLL;
        return FX_BOOT_EVENT_WAIT;
    }
    return FX_BOOT_EVENT_INVALID;
}

int fx_host_control_begin(fx_platform *p, fx_host_control_state *state)
{
    if (!p || !p->ram || !state) return -1;
    write_byte(p, 0x8e00, 2);
    fx_timer_start(p, 0x129a);
    state->active = 1;
    return 0;
}

int fx_host_control_finish(fx_platform *p, fx_host_control_state *state)
{
    if (!p || !p->ram || !state || !state->active) return -1;
    uint8_t available = read_byte(p, 0x8e00) != 0;
    if (available) {
        write_byte(p, 0x80f2, 4);
        write_byte(p, 0x80f3, 16);
    }
    write_byte(p, 0x8e00, 0);
    state->active = 0;
    return available;
}

void fx_host_control_notify(fx_platform *p)
{
    write_byte(p, 0x8e00, 4);
    fx_timer_start(p, 0x129a);
}

void fx_host_control_clear(fx_platform *p, uint16_t period)
{
    write_byte(p, 0x8e00, 0);
    fx_timer_start(p, period);
}

uint16_t fx_diagnostic_checksum(fx_platform *p)
{
    uint16_t checksum = 0;
    for (unsigned n = 0; n < 65536; ++n)
        checksum = (uint16_t)(checksum - fx_data_read(p, 8, (uint16_t)n));
    for (unsigned n = 0; n < 65532; ++n)
        checksum = (uint16_t)(checksum - fx_data_read(p, 1, (uint16_t)n));
    return checksum;
}

static uint8_t hex_digit(unsigned nibble)
{
    return (uint8_t)(nibble < 10 ? '0' + nibble : 'A' + nibble - 10);
}

void fx_diagnostic_draw_screen(fx_platform *p, uint8_t read_test_result)
{
    fx_render render = display(p);
    fx_clear_framebuffer(&render);
    uint8_t version[12];
    for (unsigned n = 0; n < 6; ++n)
        version[n] = fx_data_read(p, 1, (uint16_t)(0xfff4 + n));
    memcpy(version + 6, " Ver", 4);
    version[10] = fx_data_read(p, 1, 0xfffa);
    version[11] = fx_data_read(p, 1, 0xfffb);
    draw_bytes(p, 0, 1, version, sizeof version);
    flush(p);
    uint16_t checksum = fx_diagnostic_checksum(p);
    uint16_t stored = (uint16_t)(fx_data_read(p, 1, 0xfffc) |
                               (uint16_t)fx_data_read(p, 1, 0xfffd) << 8);
    uint8_t sum[] = "SUM 0000 NG";
    for (unsigned n = 0; n < 4; ++n) sum[4 + n] = hex_digit((checksum >> (12 - 4*n)) & 15);
    if (checksum == stored) { sum[9] = 'O'; sum[10] = 'K'; }
    draw_bytes(p, 0, 8, sum, sizeof sum);
    uint8_t port = read_byte(p, 0xf050);
    uint8_t caption[3] = {'P', 'd', port ? (uint8_t)(port | 0x30) : '-'};
    draw_bytes(p, 0, 15, caption, sizeof caption);
    flush(p);
    const uint8_t *read_caption = (const uint8_t *)(read_test_result == 0xa5 ? "Read OK" : "Read NG");
    draw_bytes(p, 24, 15, read_caption, 7);
    draw_rom(p, 22, 0x2d8c);
    write_byte(p, 0xf049, 1);
    write_byte(p, 0xf04a, 1);
    write_byte(p, 0xf04b, 1);
    write_byte(p, 0xf04c, 0);
    flush(p);
}

int fx_diagnostic_draw_pattern(fx_platform *p, uint8_t pattern)
{
    if (!p || !p->ram || pattern > 4) return -1;
    if (pattern < 2) {
        fx_render render = display(p);
        fx_fill_display(&render, pattern ? 0 : 0xff, 1);
    } else if (pattern == 2) {
        for (unsigned n = 0; n < 12; ++n) {
            write_byte(p, (uint16_t)(0x87dc + n), 0xff);
            write_byte(p, (uint16_t)(0x8944 + n), 0xff);
        }
        for (unsigned row = 1; row < 32; ++row) {
            uint16_t left = (uint16_t)(0x87d0 + 12*row);
            uint16_t right = (uint16_t)(left + 11);
            write_byte(p, left, (uint8_t)(read_byte(p, left) | 0x80));
            write_byte(p, right, (uint8_t)(read_byte(p, right) | 1));
        }
    } else {
        for (unsigned row = 0; row < 32; ++row) {
            uint8_t value = ((row & 1) ^ (pattern == 4)) ? 0xaa : 0x55;
            for (unsigned n = 0; n < 12; ++n)
                write_byte(p, (uint16_t)(0x87d0 + row*12 + n), value);
        }
    }
    flush(p);
    return 0;
}

uint8_t fx_diagnostic_single_bit(uint8_t value)
{
    if (value < 3) return value;
    if ((value & (uint8_t)(value - 1)) != 0) return 16;
    uint8_t position = 1;
    while ((value >>= 1) != 0) ++position;
    return position;
}

int fx_diagnostic_draw_key_counter(fx_platform *p, uint8_t index)
{
    if (!p || !p->ram || index >= 49) return -1;
    uint8_t text[2] = {(uint8_t)('0' + index/10), (uint8_t)('0' + index%10)};
    draw_bytes(p, 0, 1, text, sizeof text);
    flush(p);
    return 0;
}

static void invalidate_signature(fx_platform *p)
{
    for (unsigned n = 0; n < 4; ++n) write_byte(p, (uint16_t)(0x860e + n), 0);
    write_byte(p, 0x80dd, 1);
}

static fx_boot_event_status begin_raw_wait(fx_platform *p, fx_boot_events *state)
{
    int result = fx_key_wait_begin_host(p, &state->raw_wait);
    return result == 0 ? FX_BOOT_EVENT_WAIT : FX_BOOT_EVENT_UNIMPLEMENTED;
}

static fx_boot_event_status boot_tail(fx_platform *p, fx_boot_events *state)
{
    if (state->boot_continuation) {
        uint8_t mode = read_byte(p, 0x80f9);
        fx_render render = display(p);
        if (mode == 0x45 || mode == 0x4b || mode == 0x4a) {
            write_byte(p, 0x80fe, 0);
            write_byte(p, 0x80f5, 0);
            fx_fill_display(&render, 0, 2);
            write_byte(p, 0x80fc, (uint8_t)(mode == 0x45 ? 21 : mode == 0x4b ? 24 : 23));
        }
        if (mode == 12) {
            write_byte(p, 0x80f5, 0);
            fx_fill_display(&render, 0, 2);
            fx_boot_initialize_mode12(p);
        }
    }
    state->phase = FX_BOOT_EVENTS_DONE;
    state->active = 0;
    return FX_BOOT_EVENT_READY;
}

static fx_boot_event_status begin_diagnostic_screen(fx_platform *p, fx_boot_events *state)
{
    fx_diagnostic_draw_screen(p, 0xa5);
    fx_host_control_begin(p, &state->control);
    state->phase = FX_BOOT_EVENTS_DIAGNOSTIC;
    return FX_BOOT_EVENT_WAIT;
}

static fx_boot_event_status sequence_start(fx_platform *p, fx_boot_events *state)
{
    invalidate_signature(p);
    state->full_diagnostic = 1;
    state->pattern = 0;
    state->phase = FX_BOOT_EVENTS_PATTERN;
    fx_diagnostic_draw_pattern(p, 0);
    return begin_raw_wait(p, state);
}

fx_boot_event_status fx_boot_diagnostic_sequence_begin(fx_platform *p, fx_boot_events *state)
{
    if (!p || !p->ram || !state) return FX_BOOT_EVENT_INVALID;
    memset(state, 0, sizeof *state);
    state->active = 1;
    return sequence_start(p, state);
}

fx_boot_event_status fx_boot_events_begin(fx_platform *p, fx_boot_events *state, fx_boot_status request)
{
    if (!p || !p->ram || !state || (request != FX_BOOT_WELCOME && request != FX_BOOT_DIAGNOSTIC))
        return FX_BOOT_EVENT_INVALID;
    memset(state, 0, sizeof *state);
    state->active = 1;
    state->boot_continuation = 1;
    if (request == FX_BOOT_WELCOME) {
        fx_welcome_draw_banner(p);
        fx_welcome_begin(&state->welcome);
        state->phase = FX_BOOT_EVENTS_WELCOME;
        return FX_BOOT_EVENT_WAIT;
    }
    invalidate_signature(p);
    return begin_diagnostic_screen(p, state);
}

static fx_boot_event_status begin_key_test(fx_platform *p, fx_boot_events *state)
{
    fx_render render = display(p);
    fx_clear_framebuffer(&render);
    state->key_index = 0;
    state->phase = FX_BOOT_EVENTS_KEY_TEST;
    fx_diagnostic_draw_key_counter(p, 0);
    return begin_raw_wait(p, state);
}

static fx_boot_event_status begin_reset_prompt(fx_platform *p, fx_boot_events *state)
{
    draw_rom(p, 1, 0x2d95);
    draw_rom(p, 15, 0x2d9d);
    draw_rom(p, 22, 0x2d8c);
    flush(p);
    state->phase = FX_BOOT_EVENTS_RESET_PROMPT;
    return begin_raw_wait(p, state);
}

fx_boot_event_status fx_boot_events_tick(fx_platform *p, fx_boot_events *state,
                                       const fx_key_input *physical_input)
{
    if (!p || !p->ram || !state) return FX_BOOT_EVENT_INVALID;
    if (state->phase == FX_BOOT_EVENTS_DONE) return FX_BOOT_EVENT_READY;
    if (!state->active) return FX_BOOT_EVENT_INVALID;
    if (state->phase == FX_BOOT_EVENTS_WELCOME) {
        fx_boot_event_status result = fx_welcome_tick(p, &state->welcome, physical_input);
        if (result != FX_BOOT_EVENT_READY) return result;
        return state->welcome.decision ? sequence_start(p, state) : boot_tail(p, state);
    }
    if (state->phase == FX_BOOT_EVENTS_DIAGNOSTIC) {
        int accepted = fx_host_control_finish(p, &state->control);
        if (accepted < 0) return FX_BOOT_EVENT_INVALID;
        if (!accepted) {
            flush(p);
            fx_host_control_begin(p, &state->control);
            return FX_BOOT_EVENT_WAIT;
        }
        fx_configure_key_port(p);
        if (state->full_diagnostic) {
            fx_key_update_modifiers(p, 0);
            if (fx_diagnostic_contrast_begin(p, &state->contrast, 1) < 0)
                return FX_BOOT_EVENT_UNIMPLEMENTED;
            state->phase = FX_BOOT_EVENTS_CONTRAST;
            int result = fx_key_controller_begin(p, &state->keys);
            return result < 0 ? FX_BOOT_EVENT_UNIMPLEMENTED : FX_BOOT_EVENT_WAIT;
        }
        if (fx_boot_cold_reset(p) != FX_BOOT_READY || fx_boot_default_screen(p) != FX_BOOT_READY)
            return FX_BOOT_EVENT_UNIMPLEMENTED;
        if (!fx_boot_probe_welcome_key(p)) {
            fx_welcome_draw_banner(p);
            fx_welcome_begin(&state->welcome);
            state->phase = FX_BOOT_EVENTS_WELCOME;
            return FX_BOOT_EVENT_WAIT;
        }
        return boot_tail(p, state);
    }
    if (state->phase == FX_BOOT_EVENTS_CONTRAST) {
        fx_key_controller_status result = fx_key_controller_tick(p, &state->keys);
        if (result == FX_KEY_CONTROLLER_WAIT) return FX_BOOT_EVENT_WAIT;
        if (result == FX_KEY_CONTROLLER_EXPORT) return FX_BOOT_EVENT_EXPORT;
        if (result == FX_KEY_CONTROLLER_RESET) return FX_BOOT_EVENT_RESET;
        if (result != FX_KEY_CONTROLLER_TOKEN) return FX_BOOT_EVENT_UNIMPLEMENTED;
        uint8_t token;
        fx_key_controller_finish(&state->keys, &token);
        if (fx_diagnostic_contrast_step(p, &state->contrast, token) == FX_DIAGNOSTIC_CONTRAST_DONE)
            return begin_key_test(p, state);
        result = fx_key_controller_begin(p, &state->keys);
        return result < 0 ? FX_BOOT_EVENT_UNIMPLEMENTED : FX_BOOT_EVENT_WAIT;
    }
    if (state->phase == FX_BOOT_EVENTS_PATTERN || state->phase == FX_BOOT_EVENTS_KEY_TEST ||
        state->phase == FX_BOOT_EVENTS_RESET_PROMPT) {
        int ready = fx_key_wait_tick(p, &state->raw_wait);
        if (ready < 0) return FX_BOOT_EVENT_UNIMPLEMENTED;
        if (!ready) return FX_BOOT_EVENT_WAIT;
        fx_key_state key;
        if (fx_key_wait_finish_host(p, &state->raw_wait, &key)) return FX_BOOT_EVENT_UNIMPLEMENTED;
        if (state->phase == FX_BOOT_EVENTS_PATTERN) {
            if (fx_key_map(p, key, 0x07fe) != 0xe9) return begin_raw_wait(p, state);
            if (++state->pattern == 5) return begin_diagnostic_screen(p, state);
            fx_diagnostic_draw_pattern(p, state->pattern);
            return begin_raw_wait(p, state);
        }
        if (state->phase == FX_BOOT_EVENTS_KEY_TEST) {
            uint8_t code = (uint8_t)((fx_diagnostic_single_bit(key.columns) << 4) |
                                     fx_diagnostic_single_bit(key.rows));
            if (code == fx_data_read(p, 0, (uint16_t)(0x2d5a + state->key_index))) ++state->key_index;
            if (state->key_index == 49) return begin_reset_prompt(p, state);
            fx_diagnostic_draw_key_counter(p, state->key_index);
            return begin_raw_wait(p, state);
        }
        uint8_t contrast = read_byte(p, 0x8112);
        if (fx_boot_cold_reset(p) != FX_BOOT_READY) return FX_BOOT_EVENT_UNIMPLEMENTED;
        write_byte(p, 0x8112, contrast);
        write_byte(p, 0xf032, contrast);
        if (fx_boot_default_screen(p) != FX_BOOT_READY) return FX_BOOT_EVENT_UNIMPLEMENTED;
        return boot_tail(p, state);
    }
    return FX_BOOT_EVENT_INVALID;
}
