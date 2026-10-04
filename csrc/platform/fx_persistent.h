/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_PERSISTENT_H
#define FX_PERSISTENT_H
#include "fx_platform.h"
#include "../numeric/fx_numeric.h"

/* Standalone controller state operations, without editor/render side effects. */
void fx_result_clear(fx_platform *platform);                    /* 5176 */
void fx_result_clear_flags(fx_platform *platform);              /* 5192 */
void fx_result_clear_display_state(fx_platform *platform);      /* 51aa */
void fx_result_clear_format(fx_platform *platform);             /* 51ae */
void fx_result_reset_layout(fx_platform *platform);             /* 1d636 */
void fx_result_reset_layout_and_flags(fx_platform *platform);   /* 1d646 */
uint8_t fx_result_format_kind(fx_platform *platform);           /* 3624 */
uint8_t fx_result_selection(fx_platform *platform);             /* 362c */
void fx_result_set_selection(fx_platform *platform, uint8_t selection); /* 3644 */
void fx_result_set_format(fx_platform *platform, uint8_t format);       /* 3658 */

/* 522a: slot0 is M, slot1 is Ans, and slots2..9 are A..F/X/Y.
 * The address adapter performs native forward bus copies, including overlap.
 * The supplied-record adapter takes immutable host records, so transformed
 * Ans values need no synthetic CPU local in calculator RAM. ModeC4 writes
 * both components; other modes leave the imaginary variable slot unchanged.
 * The valid variable-slot domain is0..9. */
void fx_store_variable_address(fx_platform *platform, uint8_t slot, uint16_t source);
void fx_store_ans_address(fx_platform *platform, uint16_t source);
void fx_store_variable_records(fx_platform *platform, uint8_t slot,
                               const fx_number values[2]);
void fx_store_ans_records(fx_platform *platform, const fx_number values[2]);

/* 11092: active250-byte replay store, or0 when disabled for this mode.
 * Replay entries are independent of the renderer's9800 history packets. */
uint16_t fx_replay_buffer(fx_platform *platform);
/* Queries return0 with out_next=0 at the unused tail. Out-of-store starts,
 * capacity overflow and unterminated malformed tails return -1. Count/used
 * queries perform no persistent writes. */
int fx_replay_next(fx_platform *platform, uint16_t entry, uint16_t *out_next);
int fx_replay_count(fx_platform *platform, uint8_t *out_count);
int fx_replay_used(fx_platform *platform, uint16_t entry, uint8_t *out_used);
/* 1ea0c: append current8140 result and expression812c. Prepared entry is the
 * native1ea3e boundary after imaginary classification; only classification1
 * selects a ten-byte result, every other byte selects twenty. CPU register
 * snapshots and numeric operand scratch remain untouched by this host API.
 * The convenience entry computes classification from an immutable record.
 * Return0 for completion or the native disabled/over-capacity no-op;
 * -1 for bounded malformed data; -2 for unsupported numeric classification. */
int fx_replay_append_prepared(fx_platform *platform, uint8_t imaginary_classification);
int fx_replay_append(fx_platform *platform);
/* 1eb76: recall the1-based index8113, restoring input/result/format/flags and
 * history navigation. Index0 and disabled modes are native no-ops. Malformed
 * histories/indices or expressions beyond99 input bytes return -1 before
 * persistent writes. Editor failure returns -2. */
int fx_replay_recall(fx_platform *platform);
#endif
