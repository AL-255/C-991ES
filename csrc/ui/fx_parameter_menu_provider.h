/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_PARAMETER_MENU_PROVIDER_H
#define FX_PARAMETER_MENU_PROVIDER_H
#include "fx_statistics_menu_controller.h"
#include "fx_distribution_menu_controller.h"
#include "fx_constant_menu_controller.h"

/* All child objects and this retained routing object must outlive the parent
 * parameter controller. In particular none may lie inside that parent's
 * memset range. The runtime keeps each in a separate named sibling object. */
typedef struct {
    fx_statistics_menu_controller *statistics;
    fx_distribution_menu_controller *distribution;
    fx_constant_menu_controller *constant;
    fx_parameter_menu_services selected;
    fx_parameter_menu_child active_kind;
} fx_parameter_menu_provider;

/* Real STAT/DIST/CONSTANT/CONVERSION children only. CLEAR and other unowned
 * requests retain REQUEST without RAM writes or an accepted fake result. */
void fx_parameter_menu_provider_services(fx_parameter_menu_services *,
    fx_parameter_menu_provider *,fx_statistics_menu_controller *,
    fx_distribution_menu_controller *,fx_constant_menu_controller *);
#endif
