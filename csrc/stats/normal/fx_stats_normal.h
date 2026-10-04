/* Statistics normal-distribution functions. GPL-3.0-or-later. */
#ifndef FX_STATS_NORMAL_H
#define FX_STATS_NORMAL_H
#include "../fx_stats.h"

typedef enum {
    FX_STATS_NORMAL_P = 0, /* integral from minus infinity to x */
    FX_STATS_NORMAL_Q = 1, /* integral from zero to abs(x) */
    FX_STATS_NORMAL_R = 2  /* integral from x to plus infinity */
} fx_stats_normal_function;

/* Native probability functions round to five significant stored digits.
 * Return the original firmware error nibble, or -1 for invalid host pointers. */
int fx_stats_normal_probability(fx_number *out, const fx_number *input,
                                fx_stats_normal_function function);
/* Original one-variable t conversion: (input - mean(x)) / population_std(x). */
int fx_stats_standardize(fx_number *out, const fx_stats_table *table,
                         const fx_number *input);
#endif
