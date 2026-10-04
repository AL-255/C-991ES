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

/* Prepared dynamic X third/fourth moments133E2/133B2. Power is3 or4;
 * the physical row geometry and frequency mapping match05110. No cache
 * fields are written by these leaves. Output must be separate from RAM. */
int fx_stats_higher_x_prepared(fx_number *out, const uint8_t *ram,
                             size_t ram_size, unsigned power);

#endif
