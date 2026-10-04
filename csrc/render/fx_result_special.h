#ifndef FX_RESULT_SPECIAL_H
#define FX_RESULT_SPECIAL_H
#include "fx_render.h"
#include "../numeric/fx_numeric.h"

/* 0x37bc, also B070's E844 special-view branch. A nonzero address names a
 * ten-byte real record; address zero clears the numeric line. The current
 * font and selected framebuffer remain in effect. BASE-N uses the full
 * 80FA byte (1/7/9/15); address zero permits the original title lookup for
 * all byte values. Returns 1 on success,
 * 0 for a formatter failure, or -1 for an untranslated input context.
 * Unused native numeric workspace bytes within 0x8000..0x80DB are not
 * exposed by the record formatter. CPU-stack overflow on oversized text is a
 * separate native ABI boundary. */
int fx_display_special_real_result(fx_render *render, uint16_t value_address,
                                   fx_box *final_box);

/* The same controller with an external real record, for callers whose
 * temporary values have no emulated RAM address. NULL clears the line. */
int fx_display_special_real_number(fx_render *render, const fx_number *value,
                                   fx_box *final_box);

#endif
