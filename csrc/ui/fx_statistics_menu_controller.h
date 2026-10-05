/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_STATISTICS_MENU_CONTROLLER_H
#define FX_STATISTICS_MENU_CONTROLLER_H
#include "fx_parameter_menu_controller.h"

typedef struct {
    fx_menu_navigator menu;
    fx_key_controller confirmation;
    uint8_t initial_page, constraint, page, selected_kind;
    uint8_t returned, phase, reset_source, active;
} fx_statistics_menu_controller;

/* CEB0 and its actual CE54/1DD62 confirmation. constraint is the cached
 * incoming high-byte argument, not live RAM. Genuine menu/confirmation keys
 * determine completion. Returned child byte0/1/FF or selected kind is consumed
 * only after DONE; following STAT grids/numerical screens remain separate. */
fx_menu_status fx_statistics_menu_controller_begin(fx_platform *,
    fx_statistics_menu_controller *,uint8_t page,uint8_t constraint);
fx_menu_status fx_statistics_menu_controller_tick(fx_platform *,
    fx_statistics_menu_controller *);
fx_menu_status fx_statistics_menu_controller_resume_timer(fx_platform *,
    fx_statistics_menu_controller *);
fx_menu_status fx_statistics_menu_controller_finish(
    fx_statistics_menu_controller *,uint8_t *actual_return);
uint8_t fx_statistics_menu_controller_export_mask(const fx_statistics_menu_controller *);
uint16_t fx_statistics_menu_controller_timer_period(const fx_statistics_menu_controller *);
/* Actual STAT provider only. Every other typed child remains REQUEST. */
void fx_statistics_menu_controller_services(fx_parameter_menu_services *,
    fx_statistics_menu_controller *);
#endif
