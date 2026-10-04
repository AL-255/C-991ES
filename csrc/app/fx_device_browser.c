/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_device_browser.h"
#include "fx_device_protocol.h"
#include <stdlib.h>

fx_device_session *fx_device_browser_create(uint32_t variant)
{
    if (variant > UINT8_MAX) return NULL;
    fx_device_configuration configuration = {NULL, 0, (uint8_t)variant};
    return fx_device_session_create(&configuration);
}
void fx_device_browser_destroy(fx_device_session *session)
{
    fx_device_session_destroy(session);
}
int32_t fx_device_browser_reset(fx_device_session *session)
{
    return (int32_t)fx_device_session_reset(session);
}
int32_t fx_device_browser_submit_pair(fx_device_session *session,
    uint32_t columns, uint32_t rows)
{
    if (columns > UINT8_MAX || rows > UINT8_MAX) return -1;
    return (int32_t)fx_device_session_submit_pair(session,
        (uint8_t)columns, (uint8_t)rows);
}
int32_t fx_device_browser_release(fx_device_session *session)
{
    return (int32_t)fx_device_session_release(session);
}
int32_t fx_device_browser_step(fx_device_session *session,
    uint32_t timer_elapsed)
{
    if (timer_elapsed > 1) return (int32_t)FX_RUNTIME_INVALID;
    return (int32_t)fx_device_session_step(session, NULL, (uint8_t)timer_elapsed);
}
int32_t fx_device_browser_ack_timer(fx_device_session *session)
{
    return (int32_t)fx_device_session_ack_timer(session, NULL);
}
uint32_t fx_device_browser_take_callback(fx_device_session *session)
{
    return (uint32_t)fx_device_session_take_callback(session);
}
char *fx_device_browser_snapshot(const fx_device_session *session)
{
    return fx_device_session_json(session);
}
void fx_device_browser_snapshot_free(char *snapshot)
{
    free(snapshot);
}
