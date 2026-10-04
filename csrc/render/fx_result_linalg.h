/* Prepared fixed-stride matrix/vector display. GPL-3.0-or-later. */
#ifndef FX_RESULT_LINALG_H
#define FX_RESULT_LINALG_H
#include "fx_render.h"
#include "../linalg/fx_linalg.h"

/* Display APIs return1 after drawing,0 on formatting failure, or-1 for an
 * unsupported prepared context. Numeric input/backing is never modified.
 * Native3EC0: one-based row/column; NULL renders an empty field.
 * Rows/columns above three are outside the fixed matrix display API. */
int fx_display_linalg_cell(fx_render *render, const fx_number *number,
                            uint8_t row, uint8_t column, uint8_t selected);
/* Native 3E74. Only active cells are read. The selected coordinates are
 * one-based; an out-of-range selection leaves every field unhighlighted. */
int fx_display_linalg_grid(fx_render *render, const fx_linalg_value *value,
                            uint8_t selected_row, uint8_t selected_column);
/* Native EEB4/EEDA; slot0..2 displays MatA/B/C or VctA/B/C through the
 * unchanged data table, slot3 displays the answer caption. */
int fx_display_linalg_caption(fx_render *render, uint8_t slot);
int fx_display_linalg_border(fx_render *render, uint8_t rows, uint8_t columns);
/* Prepared ED64 current-slot view: caption, brackets, active-cell grid and
 * full selected-cell value. This includes8140/814A selection-cache writes.
 * Coordinate parameters resolve the existing811D/811E state; this renderer
 * does not itself change that state. Foreign6x/9x cell records, small/extended
 * exponent line contexts and native text length>=26 return-1 before drawing.
 * Physical editor key scanning and user-slot switching are separate. */
int fx_display_linalg_value(fx_render *render, const fx_linalg_value *value,
                             uint8_t slot, uint8_t selected_row,
                             uint8_t selected_column);
/* EDEC cursor movement only. Return0 after movement,1 at a boundary or for
 * unrecognized keys. Store resets (51AA) remain a separate controller action. */
int fx_linalg_move_selection(uint8_t rows, uint8_t columns,
                              uint8_t key, uint8_t *row, uint8_t *column);
/* Prepared EDEC event including51AA selection/cache reset after movement.
 * Coordinates are taken from811D/811E; physical key scan is excluded. */
int fx_linalg_selection_event(fx_render *render, uint8_t rows,
                               uint8_t columns, uint8_t key);
#endif
