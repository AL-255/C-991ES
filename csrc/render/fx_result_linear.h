#ifndef FX_RESULT_LINEAR_H
#define FX_RESULT_LINEAR_H
#include "fx_render.h"

/* B070's ordinary real legacy-text branch. This includes natural-input
 * selection 10, cached natural-expression reuse, and linear settings in
 * ordinary COMP contexts. New formatting requires a zero imaginary part.
 * Return 1 on success, 0 on formatting
 * failure, -1 for an unimplemented context. Numeric operand workspace writes
 * are not yet modeled; see parity-ledger.json. */
int fx_display_real_linear_result(fx_render *render, uint16_t value_address,
                                   fx_box *final_box);
#endif
