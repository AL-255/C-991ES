/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_DEVICE_BROWSER_H
#define FX_DEVICE_BROWSER_H
#include <stdint.h>
#include "fx_device_session.h"

/* Thin wasm32-facing transport for the real opaque persistent device.
 * Pointer arguments are owned handles, not arbitrary integers or RAM images.
 * Creation does not boot: reset must be requested explicitly. */
fx_device_session *fx_device_browser_create(uint32_t variant);
void fx_device_browser_destroy(fx_device_session *session);
int32_t fx_device_browser_reset(fx_device_session *session);
int32_t fx_device_browser_submit_pair(fx_device_session *session,
    uint32_t columns, uint32_t rows);
int32_t fx_device_browser_release(fx_device_session *session);
/* One semantic controller step, with no physical sample provider.
 * Only timer_elapsed 0 or 1 is valid. No implicit pumping or timer exists. */
int32_t fx_device_browser_step(fx_device_session *session,
    uint32_t timer_elapsed);
int32_t fx_device_browser_ack_timer(fx_device_session *session);
uint32_t fx_device_browser_take_callback(fx_device_session *session);
/* Allocated immutable observation: caller owns the returned UTF-8 JSON and
 * must release it with snapshot_free. Snapshot never steps or drains events.
 * NULL reports an invalid handle or allocation/observation failure. */
char *fx_device_browser_snapshot(const fx_device_session *session);
void fx_device_browser_snapshot_free(char *snapshot);
#endif
