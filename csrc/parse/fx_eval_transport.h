/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EVAL_TRANSPORT_H
#define FX_EVAL_TRANSPORT_H
#include "fx_eval.h"

/* Explicit native data addresses. Input is read from live physical RAM,
 * cursor is committed only when the outer evaluator returns, and output
 * supplies the integral's inherited error sink. Named host results remain
 * separate from RAM. No address is inferred from a foreign host pointer. */
typedef void (*fx_eval_before_sample)(fx_eval_storage *storage,
    uint16_t input_cursor, uint16_t output_sink, void *userdata);

typedef struct {
    uint16_t input_address, cursor_address, output_address;
    fx_eval_before_sample before_sample;
    void *userdata;
} fx_eval_transport;

fx_eval_status fx_evaluate_prepared_physical(size_t input_length,
    const fx_eval_options *options, const fx_eval_environment *environment,
    const fx_eval_state *state, const fx_calculus_control *control,
    const fx_number *prior_answer, fx_eval_storage *storage,
    const fx_eval_transport *transport, fx_eval_effects *effects,
    fx_eval_result *result);

/* Prepared F12A/ordinary INPUT uses a host-owned local source word. Only
 * input and output have calculator RAM addresses; no CPU stack is invented.
 * returned_source, result, effects and state are separate host objects, not
 * aliases into calculator RAM. Invalid transport admission leaves those
 * outputs untouched. Successful admission publishes the final source once
 * the outer evaluator returns, including numerical and syntax errors. */
typedef struct {
    uint16_t input_address, output_address;
    fx_eval_before_sample before_sample;
    void *userdata;
} fx_eval_source;

fx_eval_status fx_evaluate_prepared_source(size_t input_length,
    const fx_eval_options *options, const fx_eval_environment *environment,
    const fx_eval_state *state, const fx_calculus_control *control,
    const fx_number *prior_answer, fx_eval_storage *storage,
    const fx_eval_source *source, uint16_t *returned_source,
    fx_eval_effects *effects, fx_eval_result *result);
#endif
