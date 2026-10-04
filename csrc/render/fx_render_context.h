#ifndef FX_RENDER_CONTEXT_H
#define FX_RENDER_CONTEXT_H

#include "fx_render.h"

/* 0x5264: selected setup item from mode, page and submode settings. */
uint8_t fx_display_setup_item(const fx_render *render);
/* 0x3876 / 0xc328 / 0xc340 / 0xc35e. These predicates are read-only;
 * context 9 consults the selected ROM setup item rather than rejecting all
 * setup screens. Selection 14/15 permits natural results independently of
 * the ordinary Math input setting. */
int fx_display_is_special_view(const fx_render *render);
int fx_display_has_formula_view(const fx_render *render);
int fx_display_has_natural_input(const fx_render *render);
int fx_display_has_natural_result(const fx_render *render);

#endif
