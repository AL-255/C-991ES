/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EVAL_TABLE_H
#define FX_EVAL_TABLE_H
#include "fx_eval_transport.h"

/* Actual171EA, calculation mode88, continuation1. Successful evaluation
 * returns255; Math/Syntax/Argument retain native error channels. The caller
 * owns the returned record and delimiter cursor. Input may be live RAM. */
int fx_evaluate_table_expression(const uint8_t *input,size_t input_length,
    fx_eval_storage *storage,fx_eval_effects *effects,fx_eval_result *result);

/* Actual171F4 ordinary mode88 parameter evaluation over live calculator
 * input/output addresses, with a named caller-owned source cursor. */
int fx_evaluate_table_parameter_source(size_t input_length,
    fx_eval_storage *storage,const fx_eval_source *source,
    uint16_t *returned_source,const fx_number *prior_answer,
    fx_eval_result *result);

/* Host input compatibility seam for independently prepared parameter calls.
 * Physical calculus/input aliases require the source entry above. */
int fx_evaluate_table_parameter(const uint8_t *input,size_t input_length,
    fx_eval_storage *storage,const fx_number *retained_secondary,
    const fx_number *prior_answer,fx_eval_result *result);
#endif
