/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_TABLE_PRESENTATION_H
#define FX_TABLE_PRESENTATION_H
#include "fx_table_controller.h"

int fx_table_draw_linear_expression(fx_platform *platform);
int fx_table_paint_grid(fx_platform *platform,uint8_t columns);
int fx_table_present_request(fx_platform *platform,fx_table_controller *state);
/* DE7E preparation stops before the whole D9EE input action. */
int fx_table_prepare_range_prompt(fx_platform *platform,uint8_t item,
    uint8_t *refresh);
int fx_table_refresh_expression(fx_platform *platform);
/*5550 timer/status lifecycle with explicitly supplied external readiness. */
int fx_table_poll_device(fx_platform *platform,uint8_t readiness);
#endif
