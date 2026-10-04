/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EVAL_FINISH_H
#define FX_EVAL_FINISH_H
#include "fx_eval_storage.h"

/* Prepared1415A terminal reference cleanup. The low header nibble selects
 * any of the16 physical slots; dimensions are read once. Each active cell is
 * read and committed in row-major order, with native stride3 and byte-sized
 * index wrap. This adapter never allocates, releases or copies a slot.
 * A numerical error changes the reference and returns hostOK plus the
 * separate native_status. Earlier cell commits remain visible. Native17274
 * ignores this leaf status: the enclosing evaluator must retain its own
 * terminal status rather than infer it from the reference header.
 *
 * The named current and native_status are separate objects outside ram.
 * All16 slots, inactive cells and physical variable/workspace aliases remain
 * live. A cell address beyond829E..883D or a malformed decimal outside the
 * scalar cleanup contract returns UNIMPLEMENTED before that cell's write,
 * retaining any earlier commits. CPU frames and the leaf's8000..80DB numeric
 * workspace are outside this prepared data contract. */
fx_numeric_status fx_eval_finish_cleanup(fx_eval_storage *storage,
    fx_number *current, uint8_t *native_status);

/* Physical reference adapter. The ten-byte record may alias dimensions or
 * payload; error publication follows the original ascending word stores,
 * including odd-address EA alignment. Wrapping records, numeric workspace
 * and the conventional8D00..8DED CPU-frame region are unsupported. */
fx_numeric_status fx_eval_finish_cleanup_address(fx_eval_storage *storage,
    uint16_t current, uint8_t *native_status);
#endif
