/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_KEY_CONTROLLER_H
#define FX_KEY_CONTROLLER_H
#include "fx_key_wait.h"
#include "../platform/fx_host_bridge.h"

typedef enum {
    FX_KEY_CONTROLLER_WAIT = 0,
    FX_KEY_CONTROLLER_TOKEN = 1,
    FX_KEY_CONTROLLER_RESET = 2,
    FX_KEY_CONTROLLER_EXPORT = 3,
    FX_KEY_CONTROLLER_INVALID = -1,
    FX_KEY_CONTROLLER_UNIMPLEMENTED = -2
} fx_key_controller_status;
enum {
    FX_KEY_EXPORT_STATUS = 1,
    FX_KEY_EXPORT_FRAMEBUFFER = 2,
    FX_KEY_EXPORT_NUMBER = 4
};
/* Named semantic locals of 1DB34, with no CPU registers, stack or code PC. */
typedef struct {
    fx_key_wait wait;
    fx_host_descriptor host;
    fx_key_state raw_key;
    uint8_t token;
    uint8_t event;
    uint8_t active;
    uint8_t export_mask;
} fx_key_controller;

/* Prepare the ordinary header and begin a host key wait. The default host
 * descriptor is retained in this object, without allocating RAM locals. */
fx_key_controller_status fx_key_controller_begin(fx_platform *platform,
                                                 fx_key_controller *state);
/* One nonblocking native wait iteration, followed by complete key routing
 * when a pair is ready. Modifiers restart with a header refresh; host exports
 * restart directly at the wait. EXPORT exposes export_mask and remains active.
 * A TOKEN or RESET event is retained until finish. The host clears 8E01/02
 * when it has delivered its pair; this controller never clears those bytes. */
fx_key_controller_status fx_key_controller_tick(fx_platform *platform,
                                                fx_key_controller *state);
/* Consume the retained TOKEN or RESET event. token may be NULL. Reset means
 * the host should invoke its boot lifecycle; no BRK or CPU reset is executed. */
fx_key_controller_status fx_key_controller_finish(fx_key_controller *state,
                                                  uint8_t *token);
#endif
