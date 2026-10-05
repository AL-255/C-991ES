/* SPDX-License-Identifier: GPL-3.0-only. */
#ifndef FX_RUNTIME_H
#define FX_RUNTIME_H
#include "platform/fx_boot_events.h"
#include "platform/fx_main_loop.h"
#include "ui/fx_ui_controller.h"
#include "ui/fx_mode_setup.h"
#include "ui/fx_mode_bank_menu.h"
#include "ui/fx_parameter_menu_controller.h"
#include "ui/fx_parameter_menu_provider.h"
#include "ui/fx_equation_controller.h"
#include "ui/fx_polynomial_equation_controller.h"
#include "table/fx_table_body.h"

typedef enum {
    FX_RUNTIME_WAIT = 0, FX_RUNTIME_ADVANCED = 1,
    FX_RUNTIME_EXPORT = 2, FX_RUNTIME_TIMER = 3,
    FX_RUNTIME_REQUEST = 4, FX_RUNTIME_RESET = 5,
    FX_RUNTIME_INVALID = -1
} fx_runtime_status;
typedef enum {
    FX_RUNTIME_IDLE = 0, FX_RUNTIME_BOOT, FX_RUNTIME_MAIN,
    FX_RUNTIME_START_INPUT, FX_RUNTIME_INPUT, FX_RUNTIME_RETURN_INPUT,
    FX_RUNTIME_START_MENU, FX_RUNTIME_MENU, FX_RUNTIME_RETURN_MENU,
    FX_RUNTIME_START_BANK, FX_RUNTIME_BANK, FX_RUNTIME_RETURN_BANK,
    FX_RUNTIME_BODY,
    FX_RUNTIME_START_EQUATION, FX_RUNTIME_EQUATION, FX_RUNTIME_RETURN_EQUATION,
    FX_RUNTIME_START_TABLE, FX_RUNTIME_TABLE, FX_RUNTIME_RETURN_TABLE,
    FX_RUNTIME_START_PARAMETER, FX_RUNTIME_PARAMETER, FX_RUNTIME_RETURN_PARAMETER,
    FX_RUNTIME_START_POLYNOMIAL, FX_RUNTIME_POLYNOMIAL, FX_RUNTIME_RETURN_POLYNOMIAL
} fx_runtime_phase;
typedef enum {
    FX_RUNTIME_EVENT_NONE = 0, FX_RUNTIME_EVENT_BOOT_READY,
    FX_RUNTIME_EVENT_MAIN_HANDLER, FX_RUNTIME_EVENT_INPUT_PREPARED,
    FX_RUNTIME_EVENT_HANDLER_RETURN, FX_RUNTIME_EVENT_CYCLE_RETURN,
    FX_RUNTIME_EVENT_WAIT_ENTER, FX_RUNTIME_EVENT_WAIT_ITERATION,
    FX_RUNTIME_EVENT_BANK_ENTRY, FX_RUNTIME_EVENT_TIMER,
    FX_RUNTIME_EVENT_EXPORT, FX_RUNTIME_EVENT_BODY, FX_RUNTIME_EVENT_RESET
} fx_runtime_event;
typedef enum {
    FX_RUNTIME_BODY_NONE = 0, FX_RUNTIME_MAIN_BODY,
    FX_RUNTIME_INPUT_BODY, FX_RUNTIME_INPUT_GAP,
    FX_RUNTIME_MENU_GAP, FX_RUNTIME_BOOT_GAP, FX_RUNTIME_MAIN_GAP,
    FX_RUNTIME_EQUATION_GAP, FX_RUNTIME_TABLE_GAP, FX_RUNTIME_PARAMETER_GAP,
    FX_RUNTIME_POLYNOMIAL_GAP
} fx_runtime_body_kind;
typedef struct {
    fx_runtime_body_kind kind;
    unsigned operation;       /* fx_main_request or fx_ui_request_kind. */
    uint8_t argument, context_return, action;
    int status;               /* Explicit dependency/admission failure. */
    uint16_t expression_address, result_address;
    uint16_t prepared_source, current_source;
    uint8_t page;             /* Actual page of a pending parameter child. */
} fx_runtime_request;
/* INPUT_BODY/SPECIAL_CONTEXT delegates the remaining wholeD9EE action.
 * It is not an F12A entry: token dispatch/admission still belongs to that
 * body. TABLE/rich providers must retain their actual F12A gate. */
/* All retained controller locals live in named host objects. No emulated
 * CPU frame, code address, artificial RAM local, or instruction executor. */
typedef struct {
    fx_boot_events boot;
    fx_main_loop main;
    fx_ui_controller input;
    fx_mode_setup mode;
    fx_mode_bank_menu bank;
    fx_parameter_menu_controller parameter;
    fx_distribution_menu_controller distribution;
    fx_statistics_menu_controller statistics;
    fx_constant_menu_controller constant;
    fx_parameter_menu_provider parameter_provider;
    fx_equation_controller equation;
    fx_table_body table;
    fx_calculus_control cancellation;
    fx_runtime_request request;
    fx_runtime_phase phase;
    fx_runtime_event event;
    uint32_t steps;
    uint16_t timer_period;
    uint8_t active, timer_pending, export_mask, returned, menu_kind;
    fx_polynomial_equation_controller polynomial;
} fx_runtime;

/* Reset and ordinary boot tail are real available high-level controllers.
 * Welcome/diagnostic continues in bounded steps. */
fx_runtime_status fx_runtime_reset(fx_platform *, fx_runtime *,
    const fx_calculus_control *);
/* Implemented linear EQN and TABLE main bodies are owned by this runtime.
 * Incomplete body prefixes remain typed gaps and cannot be accepted as success.
 * Exactly one semantic controller step. Raw8E01/02 packets remain host-owned.
 * A pending timer performs no writes until timer_elapsed is nonzero. */
fx_runtime_status fx_runtime_step(fx_platform *, fx_runtime *,
    const fx_key_input *physical_input, uint8_t timer_elapsed);
void fx_runtime_submit_pair(fx_platform *, fx_key_state);
/* Complete only a genuinely delegated MAIN/INPUT body. Context return is
 * independent of the INPUT handler action, as in wholeD9EE. Gap requests
 * require an implementation or reset and cannot be fabricated into success. */
fx_runtime_status fx_runtime_accept_body(fx_platform *, fx_runtime *,
    uint8_t action, uint8_t context_return);
#endif
