/* Persistent statistics moment cache. GPL-3.0-or-later. */
#ifndef FX_STATS_CACHE_H
#define FX_STATS_CACHE_H
#include "fx_stats.h"

/* Cache order: sum(x²y), sum(x⁴), sum(x³), sum(xy), sum(y²), sum(y),
 * sum(x²), sum(x), using the regression model's transformed/centered data.
 * Original cache82 9e..82ed contains eight10-byte records. */
typedef struct { fx_number records[8]; } fx_stats_cache;
void fx_stats_cache_load(const uint8_t memory[65536], fx_stats_cache *out);
void fx_stats_cache_store(uint8_t memory[65536], const fx_stats_cache *cache);

#endif
