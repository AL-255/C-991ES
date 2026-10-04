#ifndef FX_RESULT_FORMAT_STATE_H
#define FX_RESULT_FORMAT_STATE_H
#include "fx_render.h"
#include "../numeric/fx_numeric.h"

/* Persistent state after an ordinary real C060/3634 formatting pair.
 * Model result-kind/current-selection updates, engineering/recurring scroll
 * reset, and the LCD/MMIO display-port sleep operation. The numeric record
 * is read-only. Native numeric operand/workspace bytes remain outside this
 * semantic API. This pair is not the intermediate state between complex
 * component formatting calls. */
void fx_apply_result_format_state(fx_render *render, const fx_number *value,
                                   uint8_t selection_byte, uint8_t result_kind);
#endif
