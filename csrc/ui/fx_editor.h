/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_EDITOR_H
#define FX_EDITOR_H
#include "fx_keys.h"

/* Context policies shared by the input editor and result controller. */
uint8_t fx_editor_is_special_view(fx_platform *platform);
uint8_t fx_editor_has_formula_view(fx_platform *platform);
uint8_t fx_editor_has_natural_input(fx_platform *platform);
uint8_t fx_editor_has_natural_result(fx_platform *platform);
/* Display-token category at a position, including compact constructs whose
 * next byte changes cursor behavior (89d2/8a08). */
uint8_t fx_editor_cursor_category(fx_platform *platform, uint16_t position);
uint8_t fx_editor_navigation_category(fx_platform *platform, uint16_t position);
/* Select the cursor glyph from the expression at8154, cursor index8114 and
 * insert/overwrite flag80f8. Return -1 for an unterminated 64KiB string; the
 * original would loop indefinitely. Other calls return zero. */
int fx_editor_refresh_cursor(fx_platform *platform);
int fx_editor_place_cursor(fx_platform *platform, uint8_t x, uint8_t y);
/* Complete1dcf4, including EC's temporary cursor-refresh state. */
int fx_editor_update_modifiers(fx_platform *platform, uint8_t token);
/* Move across the B8..BD construct-control bytes used by the natural editor.
 * The returned address is the new position. A cycle returns zero. */
uint16_t fx_editor_step(fx_platform *platform, uint8_t forward);
uint16_t fx_editor_resolve_position(fx_platform *platform, uint8_t forward);
/* A3e0 with the ordinary-byte input flag: insert/overwrite a byte, replacing
 * a natural-editor placeholder and preserving its caret attachment rules.
 * Return1 for an edit,0 at capacity, or -1 for a bounded malformed buffer. */
int fx_editor_insert_byte(fx_platform *platform, uint8_t token);
/* A3e0 structured input branch. Build a natural display construct, optionally
 * wrapping the current/previous atom and placing the cursor in its next field.
 * The return convention is the same as ordinary insertion. */
int fx_editor_insert_construct(fx_platform *platform, uint8_t token);
/* A846 ordinary text branch: E0/E1 to beginning/end, E2/E3 forward/back,
 * FE delete according to overwrite mode. Natural input uses construct-aware
 * field navigation and deletion. Return0 after handling, -1 for bounded
 * malformed buffers. */
int fx_editor_text_action(fx_platform *platform, uint8_t token);
/* Natural A846 branch, exposed for prepared-context differential tests. */
int fx_editor_natural_action(fx_platform *platform, uint8_t token);
#endif
