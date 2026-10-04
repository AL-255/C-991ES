/* Complex and polar result composition. GPL-3.0-or-later. */
#ifndef FX_RESULT_COMPLEX_H
#define FX_RESULT_COMPLEX_H
#include "fx_render.h"

/* B070's ordinary complex result flow. The address names two consecutive
 * ten-byte scalar records, real then imaginary. Prepared modes1/65/129/193/
 * 196/136, ordinary status, both display styles, and cached natural output
 * are supported. Cached output never reads the numeric record.
 * Return1 success,0 formatter/layout failure,-1 untranslated context.
 * Callers must keep the source separate from framebuffer/history/output
 * buffers. Numeric scratch, inactive layout slots, and CPU-stack aliases
 * remain outside the portable semantic API; see complex_manifest.json. */
int fx_display_complex_result(fx_render *render, uint16_t value_address,
                               fx_box *final_box);
#endif
