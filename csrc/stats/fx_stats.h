/* Statistics kernels recovered from the original decimal firmware.
 * GPL-3.0-or-later. Firmware execution is confined to the test oracle. */
#ifndef FX_STATS_H
#define FX_STATS_H
#include "../numeric/fx_numeric.h"

/* Cells are row-major: x[, y][, frequency]. Frequency is the last column.
 * The original row count is an unsigned byte. The caller supplies at least
 * rows * (variables + frequency) cells; zero rows permits a NULL pointer. */
typedef struct {
    const fx_number *cells;
    uint8_t rows;
    uint8_t variables;                 /* 1 or 2 */
    uint8_t frequency;                 /* 0 or 1 */
} fx_stats_table;

typedef enum {
    FX_STATS_IDENTITY = 0,
    FX_STATS_RECIPROCAL = 1,
    FX_STATS_LOG = 2,
    FX_STATS_LOG_RECIPROCAL = 3
} fx_stats_transform;

/* Firmware statistics model values in80fa. */
typedef enum {
    FX_STATS_LINEAR = 2, FX_STATS_QUADRATIC = 3, FX_STATS_LOGARITHMIC = 4,
    FX_STATS_EXPONENTIAL_E = 5, FX_STATS_EXPONENTIAL_BASE = 6,
    FX_STATS_POWER = 7, FX_STATS_INVERSE = 8
} fx_stats_model;
typedef struct { fx_number a, b, c, correlation; } fx_stats_fit;

/* Native numeric status (0 success, 1 interruption/error1, 3 Math error).
 * Paired moment outputs use low/high nibbles: 0x0f first failure,
 * 0xf0 second failure, 0xff both failures. Host argument errors return -1.
 * Error records, decimal rounding, row order and zero frequencies are kept. */
int fx_stats_count(fx_number *out, const fx_stats_table *table);
int fx_stats_extreme(fx_number *out, const fx_stats_table *table,
                     unsigned axis, fx_stats_transform transform, int maximum);
int fx_stats_moments(fx_number *sum, fx_number *squares,
                     const fx_stats_table *table, unsigned axis,
                     fx_stats_transform transform, const fx_number *center);
int fx_stats_cross(fx_number *out, const fx_stats_table *table,
                   fx_stats_transform x_transform, int log_y,
                   const fx_number *x_center, const fx_number *y_center);
int fx_stats_higher_moments(fx_number *cubes, fx_number *fourths,
                            const fx_stats_table *table, const fx_number *center);
int fx_stats_square_cross(fx_number *out, const fx_stats_table *table,
                          const fx_number *x_center, const fx_number *y_center);
int fx_stats_mean(fx_number *out, const fx_stats_table *table, unsigned axis);
int fx_stats_deviations(fx_number *population, fx_number *sample,
                        const fx_stats_table *table, unsigned axis);
/* Coefficients and linearized correlation use the original centered sums,
 * short-circuit error policy, and final numeric cleanup. */
int fx_stats_regression(fx_stats_fit *out, const fx_stats_table *table,
                        fx_stats_model model);
/* Predict y from x, or x from y when inverse is nonzero. Quadratic inverse
 * second_root selects the negative square-root numerator from131fc. */
int fx_stats_predict(fx_number *out, const fx_stats_fit *fit,
                     fx_stats_model model, const fx_number *value,
                     int inverse, int second_root);

#endif
