/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_device_protocol.h"
#include <stdint.h>
#include <stdlib.h>

/* The schema contains only fixed names, status literals, integers and hex.
 * Keep its transport independent of libc's general floating-point formatter. */
typedef struct {
    char *data;
    size_t used, capacity;
    unsigned fields, failed;
} json_writer;

static void character(json_writer *writer, char value)
{
    if (writer->used + 1u >= writer->capacity) {
        writer->failed = 1;
        return;
    }
    writer->data[writer->used++] = value;
}

static void text(json_writer *writer, const char *value)
{
    while (*value) character(writer, *value++);
}

static void unsigned_integer(json_writer *writer, uint32_t value)
{
    char digits[10];
    size_t count = 0;
    do {
        digits[count++] = (char)('0' + value % 10u);
        value /= 10u;
    } while (value);
    while (count) character(writer, digits[--count]);
}

static void signed_integer(json_writer *writer, int32_t value)
{
    uint32_t magnitude = (uint32_t)value;
    if (value < 0) {
        character(writer, '-');
        magnitude = 0u - magnitude;
    }
    unsigned_integer(writer, magnitude);
}

static void field(json_writer *writer, const char *name)
{
    if (writer->fields++) character(writer, ',');
    character(writer, '"');
    text(writer, name);
    text(writer, "\":");
}

static void unsigned_field(json_writer *writer, const char *name, uint32_t value)
{
    field(writer, name);
    unsigned_integer(writer, value);
}

static void signed_field(json_writer *writer, const char *name, int32_t value)
{
    field(writer, name);
    signed_integer(writer, value);
}

static void text_field(json_writer *writer, const char *name, const char *value)
{
    field(writer, name);
    character(writer, '"');
    text(writer, value);
    character(writer, '"');
}

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
    json_writer writer = {json, 0, capacity, 0, 0};
    character(&writer, '{');
    text_field(&writer, "status", status_name(state.last_status));
    signed_field(&writer, "runtime_status", (int32_t)state.last_status);
    signed_field(&writer, "phase", (int32_t)state.phase);
    signed_field(&writer, "event", (int32_t)state.event);
    signed_field(&writer, "memory_status", (int32_t)state.memory_status);
    unsigned_field(&writer, "steps", state.steps);
    unsigned_field(&writer, "active", state.active);
    unsigned_field(&writer, "timer_pending", state.timer_pending);
    unsigned_field(&writer, "timer_period", state.timer_period);
    unsigned_field(&writer, "export_mask", state.export_mask);
    unsigned_field(&writer, "callback_pending", state.callback_pending);
    unsigned_field(&writer, "returned", state.returned);
    unsigned_field(&writer, "host_wait", state.host_wait);
    unsigned_field(&writer, "key_columns", state.key_columns);
    unsigned_field(&writer, "key_rows", state.key_rows);
    unsigned_field(&writer, "mode", settings[0]);
    unsigned_field(&writer, "submode", settings[1]);
    unsigned_field(&writer, "screen", settings[3]);
    unsigned_field(&writer, "main_request", state.main_request);
    unsigned_field(&writer, "wait_required", state.wait_required);
    unsigned_field(&writer, "last_menu_result", state.last_menu_result);
    unsigned_field(&writer, "input_action", state.input_action);
    unsigned_field(&writer, "input_context_return", state.input_context_return);
    unsigned_field(&writer, "mode_result", state.mode_result);
    unsigned_field(&writer, "bank_result", state.bank_result);
    unsigned_field(&writer, "mode_request", state.mode_request);
    unsigned_field(&writer, "mode_page", state.mode_page);
    unsigned_field(&writer, "bank_page", state.bank_page);
    unsigned_field(&writer, "unsupported_token", state.unsupported_token);
    field(&writer, "request");
    character(&writer, '{');
    writer.fields = 0;
    signed_field(&writer, "kind", (int32_t)state.request.kind);
    unsigned_field(&writer, "operation", state.request.operation);
    unsigned_field(&writer, "page", state.request.page);
    unsigned_field(&writer, "argument", state.request.argument);
    unsigned_field(&writer, "context_return", state.request.context_return);
    unsigned_field(&writer, "action", state.request.action);
    signed_field(&writer, "status", (int32_t)state.request.status);
    unsigned_field(&writer, "expression_address", state.request.expression_address);
    unsigned_field(&writer, "result_address", state.request.result_address);
    unsigned_field(&writer, "prepared_source", state.request.prepared_source);
    unsigned_field(&writer, "current_source", state.request.current_source);
    character(&writer, '}');
    /* The parent already contains fields; only comma presence is needed. */
    writer.fields = 1;
    unsigned_field(&writer, "width", 96);
    unsigned_field(&writer, "height", 32);
    text_field(&writer, "framebuffer", pixels);
    character(&writer, '}');
    if (writer.failed) {
        free(json);
        return NULL;
    }
    json[writer.used] = '\0';
    return json;
}
