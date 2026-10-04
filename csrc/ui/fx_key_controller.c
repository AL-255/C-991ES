/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_key_controller.h"
#include "fx_annunciator.h"
#include "fx_key_dispatch.h"
#include <string.h>

static int begin_wait(fx_platform *p, fx_key_controller *state, int header)
{
    if (header && !fx_data_read(p, 0, 0x80fb)) {
        int status = fx_annunciator_draw(p);
        if (status) return status;
    }
    return fx_key_wait_begin_host(p, &state->wait);
}

fx_key_controller_status fx_key_controller_begin(fx_platform *p,
                                                 fx_key_controller *state)
{
    if (!p || !p->ram || !state) return FX_KEY_CONTROLLER_INVALID;
    memset(state, 0, sizeof(*state));
    fx_host_descriptor_default(&state->host);
    if (begin_wait(p, state, 1)) return FX_KEY_CONTROLLER_UNIMPLEMENTED;
    state->active = 1;
    return FX_KEY_CONTROLLER_WAIT;
}

fx_key_controller_status fx_key_controller_tick(fx_platform *p,
                                                fx_key_controller *state)
{
    if (!p || !p->ram || !state || !state->active)
        return FX_KEY_CONTROLLER_INVALID;
    if (state->event) return (fx_key_controller_status)state->event;
    state->export_mask = 0;
    int status = fx_key_wait_tick(p, &state->wait);
    if (status < 0) return FX_KEY_CONTROLLER_UNIMPLEMENTED;
    if (!status) return FX_KEY_CONTROLLER_WAIT;
    if (fx_key_wait_finish_host(p, &state->wait, &state->raw_key))
        return FX_KEY_CONTROLLER_UNIMPLEMENTED;

    if (state->raw_key.rows == 0x80) {
        uint8_t columns = state->raw_key.columns;
        if (columns == 0x80 || columns == 0x40) {
            fx_host_write_framebuffer_fields(p, &state->host);
            if (fx_host_write_numeric_packet_fields(p, &state->host))
                return FX_KEY_CONTROLLER_UNIMPLEMENTED;
            if (fx_host_write_text_packet_fields(p, &state->host))
                return FX_KEY_CONTROLLER_UNIMPLEMENTED;
            state->export_mask = FX_KEY_EXPORT_STATUS | FX_KEY_EXPORT_FRAMEBUFFER | FX_KEY_EXPORT_NUMBER;
        } else if (columns == 0x20) {
            if (fx_host_write_text_packet_fields(p, &state->host))
                return FX_KEY_CONTROLLER_UNIMPLEMENTED;
            state->export_mask = FX_KEY_EXPORT_STATUS;
        } else if (columns == 0x10) {
            fx_data_write(p, 0, state->host.text, 0);
            if (fx_host_write_text_packet_fields(p, &state->host))
                return FX_KEY_CONTROLLER_UNIMPLEMENTED;
            state->export_mask = FX_KEY_EXPORT_STATUS;
            state->event = FX_KEY_CONTROLLER_RESET;
            return FX_KEY_CONTROLLER_RESET;
        }
        if (state->export_mask) {
            if (begin_wait(p, state, 0)) return FX_KEY_CONTROLLER_UNIMPLEMENTED;
            return FX_KEY_CONTROLLER_EXPORT;
        }
    }

    fx_data_write(p, 0, state->host.text, 0);
    if (fx_host_write_text_packet_fields(p, &state->host))
        return FX_KEY_CONTROLLER_UNIMPLEMENTED;
    uint8_t mapped = fx_key_map_current(p, state->raw_key);
    status = fx_key_process_token(p, mapped, state->host.wait_flag, &state->token);
    if (status < 0) return FX_KEY_CONTROLLER_UNIMPLEMENTED;
    if (!status) {
        if (begin_wait(p, state, 1)) return FX_KEY_CONTROLLER_UNIMPLEMENTED;
        return FX_KEY_CONTROLLER_WAIT;
    }
    state->event = FX_KEY_CONTROLLER_TOKEN;
    return FX_KEY_CONTROLLER_TOKEN;
}

fx_key_controller_status fx_key_controller_finish(fx_key_controller *state,
                                                  uint8_t *token)
{
    if (!state || !state->active || !state->event) return FX_KEY_CONTROLLER_INVALID;
    fx_key_controller_status event = (fx_key_controller_status)state->event;
    if (token) *token = state->token;
    state->active = 0;
    state->event = 0;
    return event;
}
