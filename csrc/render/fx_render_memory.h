#ifndef FX_RENDER_MEMORY_H
#define FX_RENDER_MEMORY_H

#include "fx_render.h"

/* 0x38ce: bit 0 selects all 384 RAM bytes; bit 1 selects all 512 LCD
 * bytes, including row padding. Higher selection bits have no effect. */
void fx_fill_display(fx_render *render, uint8_t pattern, uint8_t selection);
/* 0x38b0: clear from a byte-valued row through the framebuffer end. */
void fx_clear_from_row(fx_render *render, uint8_t row);
/* 0x3922: retain row zero, move row (removed + 1) to row one, and clear
 * the vacated rows. Byte arithmetic and 16-bit address/count wrap remain.
 * Rows outside 0..31 can reach native CPU-stack memory. The high-level API
 * models explicit address-space writes, rather than native stack aliasing. */
void fx_scroll_previous_rows(fx_render *render, uint8_t removed);
/* 0x10e5c: reserve result height and reset previous-height state. */
void fx_make_result_space(fx_render *render, uint8_t requested_height);

#endif
