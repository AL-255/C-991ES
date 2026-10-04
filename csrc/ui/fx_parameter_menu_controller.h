/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_PARAMETER_MENU_CONTROLLER_H
#define FX_PARAMETER_MENU_CONTROLLER_H
#include "fx_mode_bank_menu.h"

typedef enum {
    FX_PARAMETER_MENU_WAIT = 0, FX_PARAMETER_MENU_DONE = 1,
    FX_PARAMETER_MENU_RESET = 2, FX_PARAMETER_MENU_EXPORT = 3,
    FX_PARAMETER_MENU_TIMER = 4, FX_PARAMETER_MENU_REQUEST = 5,
    FX_PARAMETER_MENU_INVALID = -1, FX_PARAMETER_MENU_UNIMPLEMENTED = -2
} fx_parameter_menu_status;

typedef enum {
    FX_PARAMETER_MENU_CHILD_NONE = 0,
    FX_PARAMETER_MENU_STATISTICS,
    FX_PARAMETER_MENU_DISTRIBUTION,
    FX_PARAMETER_MENU_RECALL,
    FX_PARAMETER_MENU_STORE,
    FX_PARAMETER_MENU_CLEAR
} fx_parameter_menu_child;

/* A pending request identifies the actual child service and its initial
 * arguments. It is not an acknowledgement that the child has completed. */
typedef struct {
    fx_parameter_menu_child kind;
    uint8_t page, argument;
} fx_parameter_menu_request;

/* An installed provider must retain its actual high-level child controller.
 * finish consumes that controller's genuine completed result. No function
 * accepts an arbitrary returned byte to resolve a pending child request. */
typedef struct {
    void *context;
    fx_parameter_menu_status (*begin)(fx_platform *, void *,
                                      const fx_parameter_menu_request *);
    fx_parameter_menu_status (*tick)(fx_platform *, void *);
    fx_parameter_menu_status (*resume_timer)(fx_platform *, void *);
    fx_parameter_menu_status (*finish)(void *, uint8_t *);
    uint8_t (*export_mask)(const void *);
    uint16_t (*timer_period)(const void *);
} fx_parameter_menu_services;

typedef struct {
    fx_menu_navigator menu;
    fx_mode_bank_menu bank;
    fx_parameter_menu_services services;
    fx_parameter_menu_request request;
    /* Immutable-table descriptor metadata, never executable C state. */
    uint16_t target_offset;
    /* A reset request retains the nested export metadata until consumed. */
    uint8_t target_segment, key, phase, active, returned, reset_source;
} fx_parameter_menu_controller;

/* CD66 admission/far-descriptor policy and the owned E17E, MATRIX/VECTOR
 * children. Other recognized children remain typed pending requests when
 * no real services are installed. Unknown far targets are unimplemented.
 * D9D2's main-loop completion policy belongs to fx_main_loop_accept_handler;
 * this controller returns the child's byte unchanged, including FF. */
fx_parameter_menu_status fx_parameter_menu_controller_begin(fx_platform *,
    fx_parameter_menu_controller *, const fx_parameter_menu_services *);
fx_parameter_menu_status fx_parameter_menu_controller_tick(fx_platform *,
    fx_parameter_menu_controller *);
fx_parameter_menu_status fx_parameter_menu_controller_resume_timer(fx_platform *,
    fx_parameter_menu_controller *);
fx_parameter_menu_status fx_parameter_menu_controller_finish(
    fx_parameter_menu_controller *, uint8_t *);
uint8_t fx_parameter_menu_controller_export_mask(const fx_parameter_menu_controller *);
uint16_t fx_parameter_menu_controller_timer_period(const fx_parameter_menu_controller *);
#endif
