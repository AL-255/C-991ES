/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_device_session.h"
#include "../data/fx_rom_data.h"
#include <stdlib.h>
#include <string.h>

struct fx_device_session {
    uint8_t ram[FX_DEVICE_RAM_BYTES];
    fx_platform platform;
    fx_runtime runtime;
    fx_runtime_status last_status;
};

fx_device_session *fx_device_session_create(
    const fx_device_configuration *configuration)
{
    uint8_t variant = 0;
    if (configuration) {
        if ((configuration->initial_ram &&
             configuration->initial_ram_bytes != FX_DEVICE_RAM_BYTES) ||
            (!configuration->initial_ram && configuration->initial_ram_bytes))
            return NULL;
        variant = configuration->variant;
    }
    fx_device_session *session = calloc(1, sizeof *session);
    if (!session) return NULL;
    if (configuration && configuration->initial_ram)
        memcpy(session->ram, configuration->initial_ram, FX_DEVICE_RAM_BYTES);
    else session->ram[0xf040] = 0xff;
    session->ram[0xf050] = variant;
    session->platform.rom = fx_rom_data;
    session->platform.rom_size = FX_ROM_DATA_SIZE;
    session->platform.ram = session->ram;
    session->platform.status = FX_MEMORY_OK;
    session->last_status = FX_RUNTIME_INVALID;
    return session;
}

void fx_device_session_destroy(fx_device_session *session)
{
    free(session);
}

fx_runtime_status fx_device_session_reset(fx_device_session *session)
{
    if (!session) return FX_RUNTIME_INVALID;
    session->last_status = fx_runtime_reset(&session->platform,
                                           &session->runtime, NULL);
    return session->last_status;
}

int fx_device_session_submit_pair(fx_device_session *session,
    uint8_t columns, uint8_t rows)
{
    if (!session) return -1;
    fx_key_state pair = {columns, rows};
    fx_runtime_submit_pair(&session->platform, pair);
    return 0;
}

int fx_device_session_release(fx_device_session *session)
{
    return fx_device_session_submit_pair(session, 0, 0);
}

fx_runtime_status fx_device_session_step(fx_device_session *session,
    const fx_key_input *physical_input, uint8_t timer_elapsed)
{
    if (!session) return FX_RUNTIME_INVALID;
    session->last_status = fx_runtime_step(&session->platform,
        &session->runtime, physical_input, timer_elapsed);
    return session->last_status;
}

fx_runtime_status fx_device_session_ack_timer(fx_device_session *session,
    const fx_key_input *physical_input)
{
    if (!session || !session->runtime.active ||
        !session->runtime.timer_pending) return FX_RUNTIME_INVALID;
    return fx_device_session_step(session, physical_input, 1);
}

uint8_t fx_device_session_take_callback(fx_device_session *session)
{
    return session ? fx_take_callback(&session->platform) : 0;
}

int fx_device_session_snapshot(const fx_device_session *session,
    fx_device_snapshot *snapshot)
{
    if (!session || !snapshot) return -1;
    memset(snapshot, 0, sizeof *snapshot);
    for (unsigned row = 0; row < 32; ++row)
        memcpy(snapshot->framebuffer + row * 12,
               session->ram + 0xf800 + row * 16, 12);
    snapshot->last_status = session->last_status;
    snapshot->phase = session->runtime.phase;
    snapshot->event = session->runtime.event;
    snapshot->request = session->runtime.request;
    snapshot->memory_status = session->platform.status;
    snapshot->steps = session->runtime.steps;
    snapshot->timer_period = session->runtime.timer_period;
    snapshot->active = session->runtime.active;
    snapshot->timer_pending = session->runtime.timer_pending;
    snapshot->export_mask = session->runtime.export_mask;
    snapshot->returned = session->runtime.returned;
    snapshot->callback_pending = session->platform.callback_pending;
    snapshot->main_request = session->runtime.main.pending_request;
    snapshot->wait_required = session->runtime.main.wait_required;
    snapshot->last_menu_result = session->runtime.main.last_menu_result;
    snapshot->input_action = session->runtime.input.handler_action;
    snapshot->input_context_return = session->runtime.input.context.return_value;
    snapshot->mode_result = session->runtime.mode.result;
    snapshot->bank_result = session->runtime.bank.result;
    snapshot->mode_request = (uint8_t)session->runtime.mode.request;
    snapshot->mode_page = session->runtime.mode.menu.page;
    snapshot->bank_page = session->runtime.bank.page;
    snapshot->unsupported_token = session->runtime.input.input.unsupported_token;
    snapshot->key_columns = session->ram[0x8e01];
    snapshot->key_rows = session->ram[0x8e02];
    snapshot->host_wait = session->ram[0x8e00];
    return 0;
}

int fx_device_session_read_ram(const fx_device_session *session,
    uint16_t address, uint8_t *output, size_t bytes)
{
    if (!session || bytes > FX_DEVICE_RAM_BYTES - (size_t)address ||
        (!output && bytes)) return -1;
    if (bytes) memcpy(output, session->ram + address, bytes);
    return 0;
}
