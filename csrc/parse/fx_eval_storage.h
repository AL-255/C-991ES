/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EVAL_STORAGE_H
#define FX_EVAL_STORAGE_H
#include "../numeric/fx_numeric.h"

/* A prepared segment-zero data view. ram_size must be65536. Below8000,
 * reads use immutable ROM data and writes are rejected. No CPU executes. */
typedef struct {
    uint8_t *ram;
    size_t ram_size;
    const uint8_t *rom;
    size_t rom_size;
} fx_eval_storage;

typedef enum {
    FX_EVAL_STORAGE_SCALAR = 0,
    FX_EVAL_STORAGE_RICH = 1,
    FX_EVAL_STORAGE_ERROR = 2
} fx_eval_storage_route;
typedef struct {
    uint8_t operation, native_status, route;
} fx_eval_storage_result;

/* Native allocation only chooses4..8. Raw mark/release shifts wrap modulo8,
 * so slot9 uses bit04; all byte-valued identities are admitted here. */
uint8_t fx_eval_storage_first_free(uint8_t mask);
uint8_t fx_eval_storage_reserve(uint8_t mask, uint8_t identity);
uint8_t fx_eval_storage_release(uint8_t mask, uint8_t identity);

/*1695C masks both headers to their low nibble. Dimension word is copied
 * first, then45 ascending word transfers, including inactive payload. All16
 * identities are physical addresses, including aliases of scalar variables. */
fx_numeric_status fx_eval_storage_copy_slot(fx_eval_storage *storage,
    uint8_t destination_header, uint8_t source_header);
/*00B942 copies ascending bytes without an overlap snapshot. The bounded
 * host contract rejects wraparound or a ROM destination before any write. */
fx_numeric_status fx_eval_storage_copy_bytes(fx_eval_storage *storage,
    uint16_t destination, uint16_t source, size_t length);

/* Selected16494/164FC temporary construction, regardless of the old slot.
 * Header rewrite precedes dimension/payload copy; mask commits to8125 last.
 * A full mask returns native7 without mutation. The named record and mask
 * must be separate host objects, outside the storage view. */
fx_numeric_status fx_eval_storage_temporary(fx_eval_storage *storage,
    fx_number *reference, uint8_t *mask, uint8_t *native_status);
/* Address adapter preserves aliases when the reference itself is in RAM. */
fx_numeric_status fx_eval_storage_temporary_address(fx_eval_storage *storage,
    uint16_t reference, uint8_t *mask, uint8_t *native_status);

/* Prepared163F0..16538 storage/type selection. The caller supplies both
 * working complex records and the native logical operand count. No numeric
 * leaf runs. Stack depth0..9 supplies the explicit8078 operand-data position
 * for15BDA's swap; unary count1 also admits depth10 without a stack swap.
 * These are data records, not a CPU frame. Named records,
 * mask and result must lie outside ram. Context is the supplied80F9 byte.
 * Arity1,2 andFF are the prepared selectors; other values are unsupported.
 * Count2/FF at depth10 and every selector above depth10 are unsupported. */
fx_numeric_status fx_eval_storage_stage(fx_eval_storage *storage,
    fx_number current[2], fx_number other[2], uint8_t operation,
    uint8_t operand_count, uint8_t operand_depth, uint8_t *mask,
    fx_eval_storage_result *result);
/* Pair consists of current at0 and other at20, each with room for20 bytes.
 * CPU frame overlap is outside the prepared contract. */
fx_numeric_status fx_eval_storage_stage_address(fx_eval_storage *storage,
    uint16_t pair, uint8_t operation, uint8_t operand_count,
    uint8_t operand_depth, uint8_t *mask, fx_eval_storage_result *result);
#endif
