/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_ERROR_EVENT_H
#define FX_ERROR_EVENT_H
#include "fx_key_controller.h"

typedef struct {
    uint16_t display_address;
    uint8_t calculation_mode;
} fx_error_context;

typedef struct {
    fx_key_controller key;
    uint8_t error;
    uint8_t token;
    uint8_t event;
    uint8_t active;
} fx_error_event;

/* DFD6: map error1..12 to the emulator's host message and publish its status
 * packet. Other16-bit values select the native unknown-error message.
 * The original local descriptor/table become immutable C data and locals. */
int fx_error_write_host_text(fx_platform *platform, uint16_t error);
/*41A8: AC is always accepted; left/right require the command-input flag. */
uint8_t fx_error_accepts_token(fx_platform *platform, uint8_t token);
/* E47E: publish error text, paint the error dialog, then begin an outer key
 * controller. Each tick exposes host exports/reset requests and accepts AC
 * or the eligible direction tokens. Other tokens restart the native wait.
 * No key bytes are cleared and no blocking host input is performed. */
fx_key_controller_status fx_error_event_begin(fx_platform *platform,
                                              fx_error_event *state,
                                              uint8_t error);
fx_key_controller_status fx_error_event_tick(fx_platform *platform,
                                             fx_error_event *state);
fx_key_controller_status fx_error_event_finish(fx_error_event *state,
                                               uint8_t *token);
/* EC72: restore the editable display after an accepted cursor token.
 * Returns1 after recovery,4 when the native policy declines it,-1 for a
 * bounded malformed expression or an unsupported editor initialization.
 * The caller owns the source/mode context rather than a CPU-frame address. */
int fx_error_cursor_restore(fx_platform *platform,
                             const fx_error_context *context);
/* ED16: adjust the cursor of a cached natural result after a direction key.
 * Returns3 when handled,4 when ineligible. */
int fx_error_result_cursor(fx_platform *platform);
#endif
