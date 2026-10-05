/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_CLEAR_CONTROLLER_H
#define FX_CLEAR_CONTROLLER_H
#include "ui/fx_parameter_menu_controller.h"

/* Named D426 locals and resumable DFDE/1DD62 waits. This state and service
 * context are externally owned; they must not overlap platform RAM or the
 * parent parameter controller object reset by begin(). The provider and child
 * must outlive that parent, as separate sibling objects. */
typedef struct {
    fx_menu_navigator menu;
    fx_key_controller confirmation;
    uint8_t selection, send_ac, returned, phase, reset_source, active;
} fx_clear_controller;

fx_menu_status fx_clear_controller_begin(fx_platform *, fx_clear_controller *);
fx_menu_status fx_clear_controller_tick(fx_platform *, fx_clear_controller *);
fx_menu_status fx_clear_controller_resume_timer(fx_platform *, fx_clear_controller *);
fx_menu_status fx_clear_controller_finish(fx_clear_controller *, uint8_t *);
uint8_t fx_clear_controller_export_mask(const fx_clear_controller *);
uint16_t fx_clear_controller_timer_period(const fx_clear_controller *);
/* Only CLEAR requests are owned. Other child requests remain REQUEST. */
void fx_clear_controller_services(fx_parameter_menu_services *, fx_clear_controller *);
#endif
