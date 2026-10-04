/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_MODE_SETUP_H
#define FX_MODE_SETUP_H
#include "fx_menu_navigator.h"
#include "../platform/fx_diagnostic_contrast.h"

/* C77C: mode/submode transition, result flags, and each mode's persistent
 * storage policy. Native temporary numeric snapshots stay in host records.
 * Every byte-valued mode/submode is accepted, as in the original dispatcher. */
int fx_mode_set(fx_platform *platform, uint8_t mode, uint8_t submode);
/* D60A, D2FC, D31A/D354 and F8A0 storage/layout dependencies, without menus. */
void fx_mode_reset_statistics(fx_platform *platform);
void fx_mode_reset_bank(fx_platform *platform);
void fx_mode_initialize_equation(fx_platform *platform, uint8_t screen);
void fx_mode_reset_table(fx_platform *platform);
int fx_setup_set_layout(fx_platform *platform, uint8_t natural);
int fx_setup_reset_table_expression(fx_platform *platform);

typedef enum {
    FX_MODE_SETUP_WAIT = 0,
    FX_MODE_SETUP_DONE = 1,
    FX_MODE_SETUP_RESET = 2,
    FX_MODE_SETUP_EXPORT = 3,
    FX_MODE_SETUP_TIMER = 4,
    FX_MODE_SETUP_REQUEST = 5,
    FX_MODE_SETUP_INVALID = -1,
    FX_MODE_SETUP_UNIMPLEMENTED = -2
} fx_mode_setup_status;
typedef enum {
    FX_MODE_REQUEST_NONE = 0,
    FX_MODE_REQUEST_MATRIX = 1,
    FX_MODE_REQUEST_VECTOR = 2
} fx_mode_request;

typedef struct {
    fx_menu_navigator menu;
    fx_key_controller keys;
    fx_diagnostic_contrast_state contrast;
    uint8_t kind;
    uint8_t phase;
    uint8_t mode;
    uint8_t submode;
    uint8_t result;
    uint8_t option;
    uint8_t request;
    uint8_t active;
} fx_mode_setup;

fx_mode_setup_status fx_mode_menu_begin(fx_platform *platform, fx_mode_setup *state);
fx_mode_setup_status fx_setup_menu_begin(fx_platform *platform, fx_mode_setup *state);
fx_mode_setup_status fx_mode_setup_tick(fx_platform *platform, fx_mode_setup *state);
fx_mode_setup_status fx_mode_setup_resume_timer(fx_platform *platform, fx_mode_setup *state);
/* Prepared caller boundaries after generic DFDE returns, not a fabricated
 * CPU frame. The selection/result pair must be from the current menu. */
fx_mode_setup_status fx_mode_setup_accept_menu(fx_platform *platform,
    fx_mode_setup *state, uint8_t selection, uint8_t menu_result);
fx_mode_setup_status fx_mode_setup_accept_token(fx_platform *platform,
    fx_mode_setup *state, uint8_t token);
/* MATRIX/VECTOR requests transfer to the actual D0CC controller; that
 * controller must perform its own mode/storage policy before this return. */
fx_mode_setup_status fx_mode_setup_accept_handler(fx_platform *platform,
    fx_mode_setup *state, uint8_t result);
fx_mode_setup_status fx_mode_setup_finish(fx_mode_setup *state, uint8_t *result);
#endif
