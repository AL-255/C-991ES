/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_TABLE_H
#define FX_TABLE_H

#include "../numeric/fx_numeric.h"
#include <stdint.h>

typedef enum {
    FX_TABLE_OK = 0, FX_TABLE_CANCELLED = 1, FX_TABLE_SYNTAX = 2,
    FX_TABLE_MATH = 3, FX_TABLE_RANGE = 4,
    FX_TABLE_INVALID = -1, FX_TABLE_UNIMPLEMENTED = -3
} fx_table_status;

/* The native171EA callback uses the actual TABLE calculation mode88 and
 * continuation1 (R6=1). It returns255 on a completed expression, or the
 * original evaluator error/status. source is the live returned cursor;
 * output is a named numerical value, separate from RAM and CPU frames.
 * An unsupported host callback returns a negative implementation status.
 */
typedef int (*fx_table_evaluate)(void *userdata, uint8_t ram[65536],
    uint8_t calculation_mode, uint8_t continuation,
    uint16_t *source, fx_number *output);
/* Native5550 is polled between committed rows. A nonzero returned status
 * stops generation while retaining its committed prefix. Device effects
 * belong to this explicit callback, not an instruction interpreter.
 */
typedef int (*fx_table_poll)(void *userdata, uint8_t ram[65536]);
typedef struct {
    fx_table_evaluate evaluate;
    fx_table_poll poll;
    void *userdata;
} fx_table_control;
typedef struct {
    uint16_t source;
    uint8_t planned_rows, evaluated_rows, committed_rows;
    uint32_t polls;
} fx_table_result;

/* Prepared004F26 TABLE generation over the supplied complete RAM view.
 * source_pointer_word is the actual word containing the expression cursor.
 * Its two bytes must lie wholly in RAM8000..FFFF; ROM/wrapped pointer words
 * return an explicit implementation gap before mutation.
 * Start/End/Step are829E/82A8/82B2; X is8276; table data starts82EE.
 * Mode88 is required. Start/End comparison admits unmarked decimal records;
 * unsupported tags are nativeMathError3. Step also admits a rational or marked
 * decimal record, used in decimal arithmetic while its stored form is retained.
 *
 * 810E selects one/two functions; its bit0 controls the30/20 row bound.
 * 8138.bit0 selects the second pass and bit7 its native two-column stride.
 * A first pass clears all600 table bytes and resets native row/UI metadata;
 * the second pass retains X/F and writes G according to the live stride.
 * MathError3 is stored asF3 and generation continues; other evaluator errors
 * abort before the row is committed. Cancellation occurs between rows.
 * Full numeric/CPU register scratch and CPU frames are not synthesized.
 */
fx_table_status fx_table_generate(uint8_t ram[65536],
    uint16_t source_pointer_word, const fx_table_control *control,
    fx_table_result *result);

/* The evaluator source is a named caller-owned cursor. Only calculator
 * data RAM is modeled; no native CPU pointer word is synthesized. */
fx_table_status fx_table_generate_source(uint8_t ram[65536],
    uint16_t *source, const fx_table_control *control, fx_table_result *result);

#endif
