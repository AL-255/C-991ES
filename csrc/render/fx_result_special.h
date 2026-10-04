#ifndef FX_RESULT_SPECIAL_H
#define FX_RESULT_SPECIAL_H
#include "fx_render.h"

/* 0x37bc, also B070's E844 special-view branch. A nonzero address names a
 * ten-byte real record; address zero clears the numeric line. The current
 * font and selected framebuffer remain in effect. BASE-N uses the full
 * 80FA byte (1/7/9/15); address zero permits the original title lookup for
 * all byte values. Returns 1 on success,
 * 0 for a formatter failure, or -1 for an untranslated input context.
 * Native numeric workspace bytes 0x8000..0x8009 are not exposed by the
 * record formatter. CPU-stack overflow on malformed/oversized text is a
 * separate native ABI boundary. */
int fx_display_special_real_result(fx_render *render, uint16_t value_address,
                                   fx_box *final_box);

#endif
