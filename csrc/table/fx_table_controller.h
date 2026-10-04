/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_TABLE_CONTROLLER_H
#define FX_TABLE_CONTROLLER_H
#include "../ui/fx_input_controller.h"

typedef enum {
    FX_TABLE_CONTROLLER_WAIT = 0,
    FX_TABLE_CONTROLLER_COMPLETE = 1,
    FX_TABLE_CONTROLLER_RESET = 2,
    FX_TABLE_CONTROLLER_EXPORT = 3,
    FX_TABLE_CONTROLLER_REQUEST = 5,
    FX_TABLE_CONTROLLER_INVALID = -1,
    FX_TABLE_CONTROLLER_UNIMPLEMENTED = -2,
    FX_TABLE_CONTROLLER_RESOURCE_LIMIT = -3
} fx_table_controller_status;

typedef enum {
    FX_TABLE_REQUEST_NONE = 0,
    FX_TABLE_REQUEST_PARAMETER_EVALUATION,
    FX_TABLE_REQUEST_GENERATION,
    FX_TABLE_REQUEST_RANGE_PROMPT,
    FX_TABLE_REQUEST_INPUT_ACTION,
    FX_TABLE_REQUEST_GRID_PAINT,
    FX_TABLE_REQUEST_SELECTED_RESULT
} fx_table_controller_request;

/* Host-owned lifecycle state. Bus RAM remains live across subordinate calls;
 * the source, old result and caller context do not occupy an emulated CPU frame.
 * A request remains retained until the host completes its actual body. */
typedef struct {
    fx_input_context context;
    fx_error_event error;
    fx_number saved_result[2];
    uint16_t prepared_source, current_source, selected_address;
    fx_table_controller_request request;
    uint8_t phase, active, handler_action, execution_status, second_pass;
    uint8_t preparation_ok, argument, columns, initial_rows, two_functions;
} fx_table_controller;

/* Actual TABLE88 F12A function/range branches, with ordinary display/context
 * addresses and expressions of at most99 bytes. Function acceptance saves
 * text without validating it. The standard special_view policy is admitted
 * for range items1..3; natural input and saved-Math restoration are unsupported.
 * PARAMETER_EVALUATION requests ordinary171F4, using context.result_address
 * and current_source. GENERATION requests the TABLE kernel: only its evaluator
 * callback uses actual171EA mode88/continuation1 and unsigned255 success.
 * Generation's source is named host state; no CPU pointer word is written. */
fx_table_controller_status fx_table_controller_begin(fx_platform *platform,
    fx_table_controller *state, const fx_input_context *context);
/* The host executes the requested body against the live bus before accepting
 * its status and updated source. Kernel success is0; evaluator success retains
 * its ordinary byte status. Negative host gaps preserve existing body writes. */
fx_table_controller_status fx_table_controller_accept_execution(
    fx_platform *platform, fx_table_controller *state, int status,
    uint16_t returned_source);

/* E1BE range-key caller, with token already in80F5 and command state in80F7.
 * RANGE_PROMPT requests DE7E(argument,1), including its preparation/input body.
 * INPUT_ACTION requests D9EE(0). Their return is ignored by the outer handler.
 * Range item4 selectsED and completes with action0 for immediate scheduling. */
fx_table_controller_status fx_table_controller_range_key(fx_platform *platform,
    fx_table_controller *state, uint8_t token);
/* E22A grid selection: physical cell copy/error13, shared cursor policy and
 * TABLE's no-delete branch. GRID_PAINT requests E3D4..E402, then the controller
 * commits font7 and requests37BC(selected_address), which may be zero.
 * INPUT_ACTION is requested only by actual4120 admission on a populated cell.
 * Row >=253 cannot finish the original byte iterator and is an explicit gap;
 * out-of-bounds native CPU-local selections are not modeled as persistent RAM. */
fx_table_controller_status fx_table_controller_navigate(fx_platform *platform,
    fx_table_controller *state, uint8_t token);
fx_table_controller_status fx_table_controller_accept_handler(
    fx_platform *platform, fx_table_controller *state, uint8_t returned);

/* Retain REQUEST/COMPLETE/RESET without rerunning their bodies. WAIT advances
 * the existing verified error-key controller; EXPORT is nonterminal. AC saves
 * no generated rollback and returns to editing the saved F expression. Left/
 * right recover the same range field. RESET is a host lifecycle request. */
fx_table_controller_status fx_table_controller_tick(fx_platform *platform,
    fx_table_controller *state);
/* Consume COMPLETE/RESET. F12A/range action0 allows immediate main-loop work;
 * action1 requests editable refresh. The main loop ignores E22A's raw return. */
fx_table_controller_status fx_table_controller_finish(fx_table_controller *state,
    uint8_t *handler_action);
#endif
