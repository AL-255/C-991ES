/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_device_protocol.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

static const char *status_name(fx_runtime_status status)
{
    switch (status) {
    case FX_RUNTIME_WAIT: return "wait";
    case FX_RUNTIME_ADVANCED: return "advanced";
    case FX_RUNTIME_EXPORT: return "export";
    case FX_RUNTIME_TIMER: return "timer";
    case FX_RUNTIME_REQUEST: return "request";
    case FX_RUNTIME_RESET: return "reset";
    default: return "invalid";
    }
}

char *fx_device_session_json(const fx_device_session *session)
{
    fx_device_snapshot state;
    uint8_t settings[4];
    char pixels[FX_DEVICE_FRAMEBUFFER_BYTES * 2u + 1u];
    static const char digits[] = "0123456789abcdef";
    if (fx_device_session_snapshot(session, &state) ||
        fx_device_session_read_ram(session, 0x80f9, settings, sizeof settings))
        return NULL;
    for (size_t i = 0; i < FX_DEVICE_FRAMEBUFFER_BYTES; ++i) {
        pixels[i * 2u] = digits[state.framebuffer[i] >> 4];
        pixels[i * 2u + 1u] = digits[state.framebuffer[i] & 15u];
    }
    pixels[sizeof pixels - 1u] = '\0';
    const size_t capacity = 4096u;
    char *json = malloc(capacity);
    if (!json) return NULL;
    int length = snprintf(json, capacity,
        "{\"status\":\"%s\",\"runtime_status\":%d,"
        "\"phase\":%d,\"event\":%d,\"memory_status\":%d,"
        "\"steps\":%" PRIu32 ",\"active\":%u,"
        "\"timer_pending\":%u,\"timer_period\":%u,"
        "\"export_mask\":%u,\"callback_pending\":%u,"
        "\"returned\":%u,\"host_wait\":%u,"
        "\"key_columns\":%u,\"key_rows\":%u,"
        "\"mode\":%u,\"submode\":%u,\"screen\":%u,"
        "\"main_request\":%u,\"wait_required\":%u,"
        "\"last_menu_result\":%u,\"input_action\":%u,"
        "\"input_context_return\":%u,\"mode_result\":%u,"
        "\"bank_result\":%u,\"mode_request\":%u,"
        "\"mode_page\":%u,\"bank_page\":%u,"
        "\"unsupported_token\":%u,"
        "\"request\":{\"kind\":%d,\"operation\":%u,\"page\":%u,"
        "\"argument\":%u,\"context_return\":%u,\"action\":%u,"
        "\"status\":%d,\"expression_address\":%u,"
        "\"result_address\":%u,\"prepared_source\":%u,"
        "\"current_source\":%u},"
        "\"width\":96,\"height\":32,\"framebuffer\":\"%s\"}",
        status_name(state.last_status), (int)state.last_status,
        (int)state.phase, (int)state.event, (int)state.memory_status,
        state.steps, (unsigned)state.active,
        (unsigned)state.timer_pending, (unsigned)state.timer_period,
        (unsigned)state.export_mask, (unsigned)state.callback_pending,
        (unsigned)state.returned, (unsigned)state.host_wait,
        (unsigned)state.key_columns, (unsigned)state.key_rows,
        (unsigned)settings[0], (unsigned)settings[1], (unsigned)settings[3],
        (unsigned)state.main_request, (unsigned)state.wait_required,
        (unsigned)state.last_menu_result, (unsigned)state.input_action,
        (unsigned)state.input_context_return, (unsigned)state.mode_result,
        (unsigned)state.bank_result, (unsigned)state.mode_request,
        (unsigned)state.mode_page, (unsigned)state.bank_page,
        (unsigned)state.unsupported_token,
        (int)state.request.kind, state.request.operation, (unsigned)state.request.page,
        (unsigned)state.request.argument, (unsigned)state.request.context_return,
        (unsigned)state.request.action, state.request.status,
        (unsigned)state.request.expression_address,
        (unsigned)state.request.result_address,
        (unsigned)state.request.prepared_source,
        (unsigned)state.request.current_source, pixels);
    if (length < 0 || (size_t)length >= capacity) {
        free(json);
        return NULL;
    }
    return json;
}
