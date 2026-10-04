/* Paired Pol/Rec, quotient/remainder and SOLVE result display.
 * GPL-3.0-or-later. */
#ifndef FX_RESULT_PAIR_H
#define FX_RESULT_PAIR_H
#include "fx_render.h"

/* B070 with80FFbit4 set. Input is two consecutive ten-byte scalar records.
 * Status bytes17/18/19/20 select Rect/Pol/SOLVE/Qrem labels; all other
 * bit4 bytes use the native fallback label. Ordinary modes1/65/129/193/
 * 196/136 admit legacy and persistent natural output. Cached natural
 * results bypass source access except status19, which invalidates cache.
 * Return1 success,0 formatting/layout failure,-1 untranslated context.
 * Source records must be disjoint from persistent state, framebuffer,
 * history and output. Native numeric scratch and inactive metrics are
 * separate. A required scroll whose byte-valued total height exceeds62
 * returns-1 after prior formatting writes: native3922 wraps its byte count
 * and overwrites CPU return-frame memory outside this portable API. */
int fx_display_pair_result(fx_render *render, uint16_t value_address,
                            fx_box *final_box);
#endif
