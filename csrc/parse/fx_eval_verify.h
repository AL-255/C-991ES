/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EVAL_VERIFY_H
#define FX_EVAL_VERIFY_H
#include "fx_eval_transport.h"

/* Ordinary171F4 operand entry used by138EE, in actual live mode137.
 * Input remains live physical RAM. The named result receives the operand;
 * this entry does not publish that local operand into source.output_address.
 * That physical address remains an explicit inherited sample/error sink.
 * returned_source is the post-read delimiter cursor, including native error
 * cursors. Scalar output preserves the sink's companion. Relation terminals
 * drain pending groups/functions; '=' never enables SOLVE equation flags.
 * Source/result/cursor/control are separate host objects. Invalid transport
 * admission leaves them untouched. This is an operand, not a Boolean chain. */
fx_eval_status fx_evaluate_verify_operand_source(size_t input_length,
    fx_eval_storage *storage,const fx_eval_source *source,
    uint16_t *returned_source,const fx_calculus_control *control,
    fx_eval_result *result);
#endif
