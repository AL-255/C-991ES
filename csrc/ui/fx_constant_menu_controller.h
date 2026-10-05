/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_CONSTANT_MENU_CONTROLLER_H
#define FX_CONSTANT_MENU_CONTROLLER_H
#include "ui/fx_parameter_menu_controller.h"

typedef enum { FX_CONSTANT_SELECTOR=0, FX_CONSTANT_MENU=1,
               FX_CONVERSION_MENU=2 } fx_constant_menu_kind;
typedef struct {
    fx_key_controller keys;
    uint8_t prompt[5], cursor, value, lower, upper, weight, trigger;
    uint8_t kind, returned, phase, active;
} fx_constant_menu_controller;

/* D312's two-digit selector, or complete D3B6/D3EE wrappers. The historical
 * parameter-child names RECALL/STORE denote CONSTANT/CONVERSION here. They
 * publish an expression token at80F5; they do not store calculator variables.
 * Real key exports, reset and129A timer readiness remain retained host events.
 * Following expression insertion/evaluation is outside this child contract. */
fx_menu_status fx_constant_menu_controller_begin(fx_platform *,
    fx_constant_menu_controller *,fx_constant_menu_kind,uint8_t trigger);
fx_menu_status fx_constant_menu_controller_tick(fx_platform *,
    fx_constant_menu_controller *);
fx_menu_status fx_constant_menu_controller_resume_timer(fx_platform *,
    fx_constant_menu_controller *);
fx_menu_status fx_constant_menu_controller_finish(fx_constant_menu_controller *,
    uint8_t *actual_return);
uint8_t fx_constant_menu_controller_export_mask(const fx_constant_menu_controller *);
uint16_t fx_constant_menu_controller_timer_period(const fx_constant_menu_controller *);
void fx_constant_menu_controller_services(fx_parameter_menu_services *,
    fx_constant_menu_controller *);
#endif
