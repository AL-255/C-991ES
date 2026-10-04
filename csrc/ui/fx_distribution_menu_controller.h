/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_DISTRIBUTION_MENU_CONTROLLER_H
#define FX_DISTRIBUTION_MENU_CONTROLLER_H
#include "fx_parameter_menu_controller.h"

/* CFA8's saved initial page and retained kind are distinct from the current
 * generic menu selection. They remain live across submenu62/back navigation. */
typedef struct {
    fx_menu_navigator menu;
    uint8_t initial_page, kind, returned, phase, active;
} fx_distribution_menu_controller;

/* Whole CFA8..D074, including the real generic menu and table-edit services.
 * Child byte0/FF is available only after DONE. Export, timer and reset are
 * retained host states; no probability calculation or following screen body
 * is completed by this menu. The direct native child has no mode admission
 * guard; its conditional data clear independently requires live mode12. */
fx_menu_status fx_distribution_menu_controller_begin(fx_platform *,
    fx_distribution_menu_controller *, uint8_t initial_page);
fx_menu_status fx_distribution_menu_controller_tick(fx_platform *,
    fx_distribution_menu_controller *);
fx_menu_status fx_distribution_menu_controller_resume_timer(fx_platform *,
    fx_distribution_menu_controller *);
fx_menu_status fx_distribution_menu_controller_finish(
    fx_distribution_menu_controller *, uint8_t *actual_return);
uint8_t fx_distribution_menu_controller_export_mask(
    const fx_distribution_menu_controller *);
uint16_t fx_distribution_menu_controller_timer_period(
    const fx_distribution_menu_controller *);

/* A real installed parameter-child provider. Only DISTRIBUTION is owned;
 * other typed requests remain REQUEST without RAM writes or fake returns. */
void fx_distribution_menu_controller_services(fx_parameter_menu_services *,
    fx_distribution_menu_controller *);
#endif
