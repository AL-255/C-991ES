/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EVAL_SURD_WORKSPACE_H
#define FX_EVAL_SURD_WORKSPACE_H

#include "../numeric/fx_numeric.h"
#include <stdint.h>

/* Exact scalar arithmetic with ordered writes to the actual 32-record surd
 * workspace in supplied65536-byte RAM. Physical payload aliases are live.
 *
 * A physical address0 selects the corresponding named host-private input.
 * Nonzero physical addresses are reread from RAM at the native copy points.
 * The caller commits the returned record to its current destination after
 * success. Decimal fallback additionally commits its intermediate converted
 * left operand there before converting right, matching native alias effects.
 *
 * This seam does not stage rich operands, allocate/release slots, emit CPU
 * stack frames, or serialize an entire operation after it has completed.
 * Integer GCD/factor cases beyond int64 return FX_NUMERIC_UNIMPLEMENTED with
 * preceding workspace writes retained, rather than a guessed decimal result.
 */
fx_numeric_status fx_eval_surd_workspace_binary(fx_number *out,
    uint8_t storage_ram[65536], const fx_number *current, const fx_number *other,
    uint16_t physical_current, uint16_t physical_other, fx_binary_op operation);

/* Scalar1C780/1C76C policy for named value records. exact_math denies or
 * permits approximate rational/compact-radical recognition. Decodable20
 * rational operands with full sign bytes1/6 retain an exact fraction when their independent
 * numerator and denominator roots pass native integer admission.
 * Marked headers and other tail metadata use the unchanged value fallback.
 * Some malformed decoded fields remain outside the verified native domain.
 * Output may alias input; this value helper emits no physical RAM writes. */
fx_numeric_status fx_eval_scalar_square_root(fx_number *out,
    const fx_number *input, int exact_math);

/* Ordered bounded exact square-root stages1C780. Initial expansion and
 * numerator/denominator normalization are committed before result packing.
 * Existing numeric kernels own numerical fallback and error records. */
fx_numeric_status fx_eval_surd_workspace_sqrt(fx_number *out,
    uint8_t storage_ram[65536], const fx_number *input, int exact_math);

#endif
