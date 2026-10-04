/* Native compact/table and inequality decimal serialization. GPL-3.0-or-later. */
#ifndef FX_FORMAT_BUDGET_H
#define FX_FORMAT_BUDGET_H
#include "fx_format.h"

/* 0x3500: the two firmware callers supply budgets6 (small table cells) and
 * 12 (inequality results). The record is converted to decimal and rounded
 * to ten significant digits (native precision byte11) before the selected
 * width truncates digits.
 * small_exponent resolves8127==1; extended_norm resolves80FF==20. The other
 * display-mode settings do not affect this routine. A marked rational6x
 * produces ERROR, as does a native header above4F after surd conversion.
 * A null number emits an
 * empty string, as does a native null source pointer. The result kind is10.
 * Capacity/length/NUL conventions are identical to fx_format_number. */
fx_format_status fx_format_budget(const fx_number *number, uint8_t budget,
                                  uint8_t small_exponent, uint8_t extended_norm,
                                  uint8_t decimal_dot, uint8_t *tokens,
                                  size_t capacity, fx_format_result *result);
#endif
