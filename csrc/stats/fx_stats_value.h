/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_STATS_VALUE_H
#define FX_STATS_VALUE_H
#include "../numeric/fx_numeric.h"

/* Prepared dynamic constant57 (raw8A), native13448. The physical table
 * layout is selected from the full segment-zero RAM view, independently of
 * the requested Y field. Numeric errors use the native status/record pair.
 * No persistent table/cache field is written. Output must be separate from
 * RAM. A negative return identifies an unsupported host contract/data case,
 * rather than inventing a native Math error for an unchecked raw record. */
int fx_stats_mean_y_prepared(fx_number *out, const uint8_t *ram, size_t ram_size);

#endif
