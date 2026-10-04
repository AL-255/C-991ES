/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EVAL_RICH_H
#define FX_EVAL_RICH_H

#include "fx_eval_storage.h"
#include "../complex/fx_complex.h"
#include "../linalg/fx_linalg.h"

/* Exact post-storage table indices. The multiplication selectors differ:
 * index14 is vector cross product; index15 is matrix multiplication. */
typedef enum {
    FX_EVAL_RICH_VECTOR_MAGNITUDE = 0,
    FX_EVAL_RICH_MATRIX_ABSOLUTE = 1,
    FX_EVAL_RICH_DISPLAY_ROUND = 2,
    FX_EVAL_RICH_DETERMINANT = 3,
    FX_EVAL_RICH_TRANSPOSE = 4,
    FX_EVAL_RICH_NEGATE = 5,
    FX_EVAL_RICH_INVERSE = 6,
    FX_EVAL_RICH_SQUARE = 7,
    FX_EVAL_RICH_CUBE = 8,
    FX_EVAL_RICH_ADD = 9,
    FX_EVAL_RICH_SUBTRACT = 10,
    FX_EVAL_RICH_SCALE = 11,
    FX_EVAL_RICH_DIVIDE = 12,
    FX_EVAL_RICH_DOT = 13,
    FX_EVAL_RICH_CROSS = 14,
    FX_EVAL_RICH_MATRIX_MULTIPLY = 15,
    FX_EVAL_RICH_REF = 16,
    FX_EVAL_RICH_RREF = 17,
    FX_EVAL_RICH_VECTOR_NORMAL_R = 21,
    FX_EVAL_RICH_VECTOR_NOT = 22,
    /* The native doubled table offset wraps at256 bytes. */
    FX_EVAL_RICH_ACOSH = 162,
    FX_EVAL_RICH_ATANH = 163,
    FX_EVAL_RICH_EXPONENTIAL = 164
} fx_eval_rich_selector;

typedef int (*fx_eval_rich_cancel)(void *userdata);

typedef struct fx_eval_rich_context {
    /* The actual80F9 byte at the post-stage boundary, including COMP,
     * CMPLX and BASE. It is retained across numerical bank writes. */
    uint8_t calculation_context;
    /* exact_math is the resolved18212 permission (80F9.bit6 and the
     * relevant8106/context selectors), rather than a raw setup flag. */
    fx_linalg_context numeric;
    /* Called at each native5564 cancellation sample, after prior physical
     * commits and timer setup. Return nonzero to cancel. It may inspect or
     * update the supplied storage through userdata. NULL leaves only the
     * deterministic numeric.cancel_at fixture control active. */
    fx_eval_rich_cancel cancelled;
    void *userdata;
} fx_eval_rich_context;

typedef struct {
    fx_complex value;
    /* The leaf may construct constants or overwrite this work record. */
    fx_complex other;
    uint8_t firmware_status;
    uint32_t cancellation_checks;
} fx_eval_rich_result;

void fx_eval_rich_context_default(fx_eval_rich_context *context,
                                 uint8_t calculation_context);

/* Shared numerical-leaf polling seam. Storage writes are live before this
 * call; timer setup precedes the callback, and cancellation flags/8E00
 * consumption follow it. No evaluator storage stage is performed. */
int fx_eval_rich_poll(fx_eval_storage *storage, uint32_t *checks,
                      const fx_eval_rich_context *context);

/* Start at16538 after fx_eval_storage_stage has completed. This API never
 * allocates, copies a bank slot, reserves/releases a temporary, or restages
 * an operand. Physical identities0..15 resolve to the full storage view;
 * both active and inactive payload remain observable. current/other and out
 * are separate host objects outside storage; current supplies the retained
 * imaginary record. Native status is independent of the returned header.
 * An unsupported architectural domain leaves already staged RAM intact. */
fx_numeric_status fx_eval_rich_dispatch(fx_eval_rich_result *out,
    fx_eval_storage *storage, const fx_complex *current,
    const fx_complex *other, uint8_t selector,
    const fx_eval_rich_context *context);

/* Explicit current/other work records at pair and pair+20. The address
 * adapter preserves proven binary live aliases with bank dimensions and
 * cells. Odd addresses and unary work-record/bank overlaps are explicit
 * unsupported architectural domains until their bus copies are modeled. */
fx_numeric_status fx_eval_rich_dispatch_address(fx_eval_rich_result *out,
    fx_eval_storage *storage, uint16_t pair, uint8_t selector,
    const fx_eval_rich_context *context);

#endif
