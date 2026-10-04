/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_MAIN_LOOP_H
#define FX_MAIN_LOOP_H
#include "../ui/fx_key_controller.h"

typedef enum {
    FX_MAIN_WAIT = 0,
    FX_MAIN_ADVANCED = 1,
    FX_MAIN_RESET = 2,
    FX_MAIN_EXPORT = 3,
    FX_MAIN_REQUEST = 4,
    FX_MAIN_INVALID = -1,
    FX_MAIN_UNIMPLEMENTED = -2
} fx_main_status;

typedef enum {
    FX_MAIN_INPUT = 1,
    FX_MAIN_MODE_MENU,
    FX_MAIN_SETUP_MENU,
    FX_MAIN_PARAMETER_MENU,
    FX_MAIN_SCREEN18_ADMISSION,
    FX_MAIN_SCREEN18,
    FX_MAIN_SCREEN19,
    FX_MAIN_SCREEN20,
    FX_MAIN_SCREEN21,
    FX_MAIN_SCREEN6,
    FX_MAIN_SCREEN_A0_C0,
    FX_MAIN_SCREEN24,
    FX_MAIN_SCREEN9
} fx_main_request;

typedef enum {
    FX_MAIN_NEXT_CYCLE = 1,
    FX_MAIN_KEY_WAIT,
    FX_MAIN_HANDLER_PENDING
} fx_main_phase;

typedef struct {
    fx_key_controller keys;
    uint8_t wait_required, last_menu_result;
    uint8_t phase, pending_request, argument, active;
} fx_main_loop;

/* D7AE: begin after an actual boot READY boundary. The first cycle dispatches
 * the boot token through the UI handler before starting the first key wait. */
void fx_main_loop_begin(fx_main_loop *state);
/* D7B4..D9E8: one bounded host phase. REQUEST retains a typed UI/menu/screen
 * dependency until its actual handler completes. No CPU call frame is used. */
fx_main_status fx_main_loop_tick(fx_platform *platform, fx_main_loop *state);
/* Prepared D7C2 boundary: apply a token already returned by the outer key
 * controller, with nonzero wait_required. This adapter does not scan or
 * consume host pair bytes. */
fx_main_status fx_main_loop_accept_token(fx_platform *platform,
    fx_main_loop *state, uint8_t token);
/* Complete the pending real handler using its semantic returned byte. A
 * screen18 admission result0 issues the subsequent screen18 request. */
fx_main_status fx_main_loop_accept_handler(fx_platform *platform,
    fx_main_loop *state, uint8_t returned);
/* Pure main-loop routing policy1DDE4. */
uint8_t fx_main_routes_input(fx_platform *platform);
#endif
