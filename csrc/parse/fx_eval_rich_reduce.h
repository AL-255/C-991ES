/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EVAL_RICH_REDUCE_H
#define FX_EVAL_RICH_REDUCE_H
#include "fx_eval_rich.h"

/* Prepared16538 leaf indices16/17 execute physical REF/RREF. Indices21/22
 * are the vector mappings to1C371C normalR and15C1C bitwise NOT. This seam
 * performs no storage selection, allocation, release, or16562 cleanup.
 * Dimensions are captured once; active cells are read live and each native
 * write precedes its cancellation callback. Inactive cells participate in
 * the native90-byte pending copies. A nonzero pair names the live current
 * and other20-byte records; zero selects separate host records.
 * Positive shapes require 3*(rows-1)+columns-1 <9, preserving the native
 * stride-three coordinates. Larger shapes, work-record overlaps with the bank/dimension tables,
 * CPU-frame overlaps, odd/wrapped addresses, and unsupported compact-surd
 * conversion aliases return UNIMPLEMENTED, retaining preceding RAM effects.
 * Unchecked malformed fractions in CA3E division or pivot comparison are
 * explicit host gaps; their native rational core can return finite values
 * unlike the standalone decimal converter. Other scalar arithmetic retains
 * its proven marked-fraction converter-error fallback. Wrapped vector NOT
 * admits the proven calculation contexts6/7. No CPU frames are emitted. */
fx_numeric_status fx_eval_rich_reduce_after_storage(fx_eval_rich_result *out,
    fx_eval_storage *storage, const fx_complex *current,
    const fx_complex *other, uint8_t selector,
    const fx_eval_rich_context *context, uint16_t pair);
#endif
