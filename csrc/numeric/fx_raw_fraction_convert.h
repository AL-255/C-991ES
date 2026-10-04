/* Prepared unchecked rational conversion used by rich-token selection.
 * GPL-3.0-or-later. */
#ifndef FX_RAW_FRACTION_CONVERT_H
#define FX_RAW_FRACTION_CONVERT_H
#include "fx_numeric.h"
fx_numeric_status fx_raw_fraction_convert(fx_number *out,
                                           const fx_number *input);
#endif
