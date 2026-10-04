/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_TABLE_BODY_H
#define FX_TABLE_BODY_H
#include "../platform/fx_main_loop.h"
#include "../ui/fx_ui_controller.h"

typedef struct {
    fx_table_controller table;
    fx_ui_controller input;
    fx_calculus_control cancellation;
    fx_main_request operation;
    uint8_t active, phase, returned;
} fx_table_body;
/* Only actual TABLE88 main SCREEN6, SCREEN18 admission and SCREEN18 routes.
 * A retained nested whole INPUT owns its token/editor/F12A policies. */
fx_ui_status fx_table_body_begin(fx_platform *,fx_table_body *,
    fx_main_request operation,const fx_calculus_control *);
fx_ui_status fx_table_body_tick(fx_platform *,fx_table_body *);
uint8_t fx_table_body_export_mask(const fx_table_body *);
#endif
