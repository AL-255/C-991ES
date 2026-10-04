/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_TABLE_RUNTIME_H
#define FX_TABLE_RUNTIME_H
#include "fx_table_controller.h"
#include "fx_table.h"
typedef struct {
    uint16_t returned_source;
    unsigned evaluator_calls;
    int body_status;
} fx_table_execution;
/* Complete one retained PARAMETER_EVALUATION or GENERATION request using
 * actual mode88 C parsing. Only between-row device polling is supplied by
 * the host. Return is the resulting named TABLE controller lifecycle state. */
fx_table_controller_status fx_table_execute_request(
    fx_platform *platform,fx_table_controller *state,
    fx_table_poll poll,void *userdata,fx_table_execution *execution);
#endif
