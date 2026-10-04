/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_MENU_NAVIGATOR_H
#define FX_MENU_NAVIGATOR_H
#include "fx_key_controller.h"

typedef enum {
    FX_MENU_WAIT = 0,
    FX_MENU_DONE = 1,
    FX_MENU_RESET = 2,
    FX_MENU_EXPORT = 3,
    FX_MENU_TIMER = 4,
    FX_MENU_INVALID = -1,
    FX_MENU_UNIMPLEMENTED = -2
} fx_menu_status;

/* Named locals of DFDE. A selection passed by the original caller on its
 * CPU stack is held by the host, without allocating persistent RAM. */
typedef struct {
    fx_key_controller keys;
    uint16_t heading;
    uint16_t timer_period;
    uint8_t page;
    uint8_t selection;
    uint8_t result;
    uint8_t mode_close_policy;
    uint8_t phase;
    uint8_t cancel_after_timer;
    uint8_t active;
} fx_menu_navigator;

/* 3FBA/3FEE/400C: four explicit lines, or heading plus three consecutive
 * body lines. Each terminated line advances through the original data bus. */
void fx_menu_paint_lines(fx_platform *platform, const uint16_t lines[4]);
void fx_menu_paint_body(fx_platform *platform, uint16_t heading, uint16_t body);
/* heading FFFF is MODE's sentinel: no heading and a distinct close policy.
 * An initial page with bit7 set is still painted; only later navigation to
 * such a page completes immediately. Initial page0 enters a key wait. */
fx_menu_status fx_menu_navigator_begin(fx_platform *platform,
    fx_menu_navigator *state, uint8_t selection, uint16_t heading);
fx_menu_status fx_menu_navigator_tick(fx_platform *platform,
    fx_menu_navigator *state);
/* Prepared E04E adapter after a semantic token has already been delivered.
 * This does not reproduce a CPU frame or run keyboard mapping a second time. */
fx_menu_status fx_menu_navigator_accept_token(fx_platform *platform,
    fx_menu_navigator *state, uint8_t token);
/* TIMER retains the native 0770-period blink until the host acknowledges its
 * delay. Repeated tick calls during that delay do not perform extra writes. */
fx_menu_status fx_menu_navigator_resume_timer(fx_platform *platform,
    fx_menu_navigator *state);
/* Native completion result:0 cancel,1 close/navigation,2 action leaf,3 leaf.
 * A RESET remains an explicit host request. Both outputs may be NULL. */
fx_menu_status fx_menu_navigator_finish(fx_menu_navigator *state,
    uint8_t *selection, uint8_t *result);
#endif
