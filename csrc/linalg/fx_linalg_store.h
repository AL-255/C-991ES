/* Readable prepared matrix/vector storage. GPL-3.0-or-later. */
#ifndef FX_LINALG_STORE_H
#define FX_LINALG_STORE_H
#include "fx_linalg.h"

typedef struct {
    uint8_t rows, columns;
    fx_number cells[9];
} fx_linalg_slot;

typedef struct {
    fx_linalg_slot slots[9];
    uint8_t temporary_mask;
} fx_linalg_bank;

/* Named A/B/C and Ans share slots0/1/2/3 between both kinds. The active
 * calculation mode owns that bank's lifetime. Temporary slots are4..8. */
/* Storage reset preserves the separately managed evaluator temporary mask. */
void fx_linalg_bank_reset(fx_linalg_bank *bank);
fx_numeric_status fx_linalg_bank_define(fx_linalg_bank *bank, unsigned identity,
    uint8_t rows, uint8_t columns);
fx_numeric_status fx_linalg_bank_ensure_dimensions(fx_linalg_bank *bank,
    unsigned identity, uint8_t rows, uint8_t columns);
fx_numeric_status fx_linalg_bank_copy(fx_linalg_bank *bank,
    unsigned destination, unsigned source);
fx_numeric_status fx_linalg_bank_copy_answer(fx_linalg_bank *bank,
    const fx_number *reference);

void fx_linalg_bank_begin_evaluation(fx_linalg_bank *bank, uint8_t context);
unsigned fx_linalg_bank_first_free(uint8_t mask);
fx_numeric_status fx_linalg_bank_mark(fx_linalg_bank *bank, unsigned identity);
fx_numeric_status fx_linalg_bank_release(fx_linalg_bank *bank, unsigned identity);

/* These mirror1705C's early dimension-word test, not17274's later cleanup.
 * A partial dimension word is allowed and will fail in the consuming leaf.
 * Dimension-word zero sets status9 and leaves the existing output unchanged. */
fx_numeric_status fx_linalg_bank_reference(fx_number *out,
    const fx_linalg_bank *bank, uint8_t kind, unsigned identity,
    uint8_t *firmware_status);
fx_numeric_status fx_linalg_bank_value(fx_linalg_value *out,
    const fx_linalg_bank *bank, const fx_number *reference);

/* Cell UI helpers1D362/1D3C4 accept slots0..5 and one-based row/column.
 * Record pointers may partially overlap cells; five descending-word copies
 * preserve native observable alias effects. Legal positive indices are the
 * prepared contract; native index0 does
 * unchecked address arithmetic and is outside this safe host API. */
fx_numeric_status fx_linalg_bank_write_cell(fx_linalg_bank *bank,
    unsigned identity, unsigned row, unsigned column, const fx_number *value,
    uint8_t *firmware_status);
fx_numeric_status fx_linalg_bank_read_cell(fx_number *out,
    const fx_linalg_bank *bank, unsigned identity, unsigned row,
    unsigned column, uint8_t *firmware_status);
/* Requested persistent-to-temporary stage1648E..164A4; preserves all ten
 * reference bytes except low slot nibble. Full dispatcher chooses when used. */
fx_numeric_status fx_linalg_bank_temporary(fx_number *out, fx_linalg_bank *bank,
    const fx_number *reference, uint8_t *firmware_status);
/* Prepared leaf state can be committed even when its reference became an
 * error/scalar; the original bank identity is therefore passed separately. */
fx_numeric_status fx_linalg_bank_store_value(fx_linalg_bank *bank,
    unsigned identity, const fx_linalg_value *value);
#endif
