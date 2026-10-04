/* Readable scalar combinatorics for fx-991ES PLUS C. GPL-3.0-or-later. */
#ifndef FX_COMBINATORICS_H
#define FX_COMBINATORICS_H
#include "fx_numeric.h"

/* Canonical real records; native domain and overflow errors are F3 records
 * with FX_NUMERIC_OK, while malformed external records use host API errors. */
fx_numeric_status fx_number_factorial(fx_number *out, const fx_number *in);
fx_numeric_status fx_number_permutation(fx_number *out, const fx_number *n,
                                        const fx_number *r);
fx_numeric_status fx_number_combination(fx_number *out, const fx_number *n,
                                        const fx_number *r);
/* Evaluator percent leaf16182 clears the input's metadata marker and divides
 * by100 through the exact arithmetic dispatcher. */
fx_numeric_status fx_number_percent(fx_number *out, const fx_number *in);
#endif
