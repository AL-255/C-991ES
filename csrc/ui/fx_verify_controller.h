/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_VERIFY_CONTROLLER_H
#define FX_VERIFY_CONTROLLER_H
#include "fx_ui_controller.h"

typedef struct { fx_ui_controller screen; } fx_verify_controller;

/* Actual ordinary VERIFY137/screen1 main-screen transaction. Mapped keys
 * are supplied by the caller in80F5/80F7, exactly as for D9EE. Shared editor,
 * INPUT preparation, error keys and result renderer retain their own native
 * ordering; evaluation uses138EE's relation chain and actual137 operands.
 * No CPU body or callback completion is supplied. Cancellation userdata is
 * borrowed and must remain live throughout the retained transaction. The
 * state is a separate host object, outside calculator RAM. Invalid initial
 * admission leaves it untouched. Other screens/modes are explicit gaps.
 * This does not perform key matrix scanning, boot or native CPU execution. */
fx_ui_status fx_verify_controller_begin(fx_platform *platform,
    fx_verify_controller *state,uint8_t refresh_only,
    const fx_calculus_control *cancellation);
fx_ui_status fx_verify_controller_tick(fx_platform *platform,
    fx_verify_controller *state);
fx_ui_status fx_verify_controller_finish(fx_verify_controller *state,
    uint8_t *context_return);
uint8_t fx_verify_controller_export_mask(const fx_verify_controller *state);
#endif
