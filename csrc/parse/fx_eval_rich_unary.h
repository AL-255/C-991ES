/* SPDX-License-Identifier: GPL-3.0-only */
/* Prepared rich unary numerical stage after storage handling; no parser/CPU. */
#ifndef FX_EVAL_RICH_UNARY_H
#define FX_EVAL_RICH_UNARY_H
#include "fx_eval_storage.h"
#include "../complex/fx_complex_dispatch.h"

typedef struct {
    fx_complex value, other;
    uint8_t native_status;
    uint32_t cancellation_checks;
} fx_eval_rich_unary_result;
struct fx_eval_rich_context;

/* current and other are already staged snapshots. Selector is the mapped
 * byte entering 16538, not a raw input token. The context carries resolved
 * 18212 exact-output permission in numeric.exact_math; live RAM supplies display settings and 80F9
 * is captured before leaf writes, as at 1653E. All 16 physical slot identities
 * are accepted. Negation replaces other.real with -1 and, in C4, copies the
 * adjacent ROM numeric constant +2 into other.imaginary. Square/cube retain
 * the supplied other reference and reread it after each product commit.
 * Absolute value, negate and round iterate live wide rows/columns until an
 * explicit CPU-local memory boundary. Magnitude ignores rows and supports up
 * to nine live components. Larger vectors remain an explicit gap, with native
 * work-record, CPU-local and instruction-limit outcomes retained separately.
 * Transpose always uses the fixed nine cells. Surd preparation effects occur
 * before the next live cell is read, even when exact output is disabled.
 * Opposite-sign abs and round surds use ordered physical component emission
 * for prepared aliases in 8640..867B. Round preserves the physical cell+20.
 * Arbitrary malformed component roots remain explicit numerical host gaps.
 * Non-square determinant/inverse shapes return native 9. Wide square kernels
 * can overwrite the original CPU local buffer and are an explicit
 * architectural boundary. C4 display-round likewise overwrites a 10-byte
 * local save with 20-byte copying; this value API does not simulate frames.
 * Output and snapshots must lie outside storage.ram. No allocation, copy of a
 * bank, reserve/release, or admission preflight is repeated here. Cancellation
 * callbacks run at each native poll after the preceding physical commits.
 * working_pair zero selects private host work records; a nonzero address
 * exposes the native current/other record updates before those callbacks. */
fx_numeric_status fx_eval_rich_unary_after_storage(
    fx_eval_rich_unary_result *out, fx_eval_storage *storage,
    const fx_complex *current, const fx_complex *other, uint8_t selector,
    const struct fx_eval_rich_context *context, uint16_t working_pair);
#endif
