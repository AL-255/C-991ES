/* Readable statistics arithmetic; no instruction/ROM execution.
 * GPL-3.0-or-later. */
#include "fx_stats.h"
#include "../numeric/fx_transcend.h"
#include "../numeric/fx_transcend_internal.h"

static int valid(const fx_stats_table *table) {
    return table && table->variables >= 1 && table->variables <= 2 &&
           table->frequency <= 1 && (!table->rows || table->cells);
}
static const fx_number *cell(const fx_stats_table *table, unsigned row, unsigned axis) {
    return table->cells + row * (table->variables + table->frequency) + axis;
}
static int numeric_error(const fx_number *n) {
    return n->bytes[0] >= 0xf0 ? n->bytes[0] & 15 : 0;
}
static int failed(const fx_number *n) { return n->bytes[0] >= 0xf0; }

/* Table operands have the evaluation-context marker cleared at 1cec0. */
static int plain(fx_number *out, const fx_number *in) {
    *out = *in;
    if ((out->bytes[0] & 0xf0) == 0x40) out->bytes[0] &= 0xbf;
    return 0;
}
static int binary(fx_number *out, const fx_number *a, const fx_number *b,
                  fx_binary_op op) {
    fx_number x, y;
    int status;
    /* Statistics uses the real arithmetic wrappers, which collapse incoming
     * error records to Math error rather than preserving evaluator errors. */
    if (failed(a) || failed(b)) { fx_number_error(out, 3); return 0; }
    /* These real wrappers accept rational conversion, but reject stored
     * surds. The transcendental ln entry has a broader input contract. */
    if (fx_number_kind(a) == FX_NUMBER_SURD || fx_number_kind(b) == FX_NUMBER_SURD) {
        fx_number_error(out, 3); return 0;
    }
    status = fx_number_to_decimal(&x, a);
    if (!status) status = fx_number_to_decimal(&y, b);
    if (status) return status;
    if ((a->bytes[0] & 0xf0) == 0x60) x.bytes[0] |= 0x40;
    if ((b->bytes[0] & 0xf0) == 0x60) y.bytes[0] |= 0x40;
    if (op == FX_SUBTRACT) return fx_decimal_subtract_cancel(out, &x, &y);
    return fx_decimal_binary(out, &x, &y, op);
}
static int real_conversion(fx_number *out, const fx_number *in) {
    if (failed(in) || fx_number_kind(in) == FX_NUMBER_SURD ||
        (in->bytes[0] & 0xf0) == 0x60) {
        fx_number_error(out, 3); return 0;
    }
    return fx_number_to_decimal(out, in);
}
static int real_power(fx_number *out, const fx_number *base, const fx_number *exponent) {
    fx_number b = *base, e = *exponent;
    if (fx_number_kind(base) == FX_NUMBER_SURD || fx_number_kind(exponent) == FX_NUMBER_SURD) {
        fx_number_error(out, 3); return 0;
    }
    if ((b.bytes[0] & 0xf0) == 0x40 || (b.bytes[0] & 0xf0) == 0x60) b.bytes[0] &= 0xbf;
    if ((e.bytes[0] & 0xf0) == 0x40 || (e.bytes[0] & 0xf0) == 0x60) e.bytes[0] &= 0xbf;
    return fx_transcend_power_decimal(out, &b, &e);
}
static int transformed(fx_number *out, const fx_number *in, fx_stats_transform t) {
    fx_number one;
    int status = plain(out, in);
    if (status) return status;
    if (t & FX_STATS_RECIPROCAL) {
        fx_decimal_from_u8(&one, 1);
        status = binary(out, &one, out, FX_DIVIDE);
    }
    if (!status && (t & FX_STATS_LOG)) status = fx_number_ln(out, out);
    return status;
}
static int pair_status(const fx_number *first, const fx_number *second,
                       int preserve_error1) {
    if (preserve_error1 && numeric_error(first) == 1) return 1;
    return (failed(first) ? 0x0f : 0) | (failed(second) ? 0xf0 : 0);
}
static int accumulate_weight(fx_number *value, const fx_stats_table *table,
                             unsigned row) {
    fx_number weight;
    int status;
    if (!table->frequency) return 0;
    status = plain(&weight, cell(table, row, table->variables));
    if (!status) status = binary(value, value, &weight, FX_MULTIPLY);
    return status;
}

int fx_stats_count(fx_number *out, const fx_stats_table *table) {
    fx_number total, weight;
    unsigned row;
    int status;
    if (!out || !valid(table)) return -1;
    if (!table->rows) { fx_number_error(out, 3); return 0xf0; }
    if (!table->frequency) {
        fx_decimal_from_u8(out, table->rows);
        return 0;
    }
    fx_number_zero(&total);
    for (row = 0; row < table->rows; ++row) {
        status = plain(&weight, cell(table, row, table->variables));
        if (!status) status = binary(&total, &total, &weight, FX_ADD);
        if (status) return status;
    }
    *out = total;
    /* The count kernel returns zero even when an accumulated record failed. */
    return 0;
}

static int compare(const fx_number *a, const fx_number *b) {
    fx_decimal x, y;
    if (failed(a) || failed(b)) return 0;
    if (fx_decimal_decode(&x, a) || fx_decimal_decode(&y, b)) return 0;
    if (!x.mantissa && !y.mantissa) return 0;
    if (!x.mantissa) return y.sign > 0 ? -1 : 1;
    if (!y.mantissa) return x.sign > 0 ? 1 : -1;
    if (x.sign != y.sign) return x.sign;
    if (x.exponent != y.exponent) return (x.exponent > y.exponent ? 1 : -1) * x.sign;
    if (x.mantissa != y.mantissa) return (x.mantissa > y.mantissa ? 1 : -1) * x.sign;
    return 0;
}

int fx_stats_extreme(fx_number *out, const fx_stats_table *table,
                     unsigned axis, fx_stats_transform transform, int maximum) {
    fx_number best, value;
    unsigned row;
    int status, order;
    if (!out || !valid(table) || axis >= table->variables || (unsigned)transform > 3) return -1;
    if (!table->rows) { fx_number_error(out, 3); return 3; }
    /* Reciprocal changes ordering, whereas ln is applied only after selection. */
    status = plain(&best, cell(table, 0, axis));
    if (!status) status = real_conversion(&best, &best);
    if (!status && (transform & FX_STATS_RECIPROCAL)) status = transformed(&best, &best, FX_STATS_RECIPROCAL);
    if (status) return status;
    if (failed(&best)) fx_number_error(&best, 3);
    for (row = 0; row < table->rows; ++row) {
        status = plain(&value, cell(table, row, axis));
        if (!status) status = real_conversion(&value, &value);
        if (!status && (transform & FX_STATS_RECIPROCAL)) status = transformed(&value, &value, FX_STATS_RECIPROCAL);
        if (status) return status;
        if (failed(&value)) fx_number_error(&value, 3);
        order = compare(&best, &value);
        if ((!maximum && order > 0) || (maximum && order < 0)) best = value;
    }
    if (transform & FX_STATS_LOG) {
        status = fx_number_ln(&best, &best);
        if (status) return status;
    }
    *out = best;
    return numeric_error(out);
}

int fx_stats_moments(fx_number *sum, fx_number *squares,
                     const fx_stats_table *table, unsigned axis,
                     fx_stats_transform transform, const fx_number *center) {
    fx_number total, second, value, square;
    unsigned row;
    int status;
    if (!sum || !squares || sum == squares || !valid(table) ||
        axis >= table->variables || (unsigned)transform > 3) return -1;
    if (!table->rows) { fx_number_error(sum, 3); fx_number_error(squares, 3); return 0xff; }
    fx_number_zero(&total); fx_number_zero(&second);
    for (row = 0; row < table->rows; ++row) {
        status = transformed(&value, cell(table, row, axis), transform);
        if (!status && center) status = binary(&value, &value, center, FX_SUBTRACT);
        if (!status) status = binary(&square, &value, &value, FX_MULTIPLY);
        if (!status) status = accumulate_weight(&value, table, row);
        if (!status) status = accumulate_weight(&square, table, row);
        if (!status) status = binary(&total, &total, &value, FX_ADD);
        if (!status) status = binary(&second, &second, &square, FX_ADD);
        if (status) return status;
        if (failed(&total) && failed(&second)) break;
    }
    *sum = total; *squares = second;
    return pair_status(sum, squares, 1);
}

int fx_stats_cross(fx_number *out, const fx_stats_table *table,
                   fx_stats_transform x_transform, int log_y,
                   const fx_number *x_center, const fx_number *y_center) {
    fx_number total, x, y;
    unsigned row;
    int status;
    if (!out || !valid(table) || table->variables != 2 ||
        (unsigned)x_transform > 3 || (!!x_center != !!y_center)) return -1;
    if (!table->rows) { fx_number_error(out, 3); return 3; }
    fx_number_zero(&total);
    for (row = 0; row < table->rows; ++row) {
        status = transformed(&x, cell(table, row, 0), x_transform);
        if (!status) status = transformed(&y, cell(table, row, 1), log_y ? FX_STATS_LOG : FX_STATS_IDENTITY);
        if (!status && x_center) status = binary(&x, &x, x_center, FX_SUBTRACT);
        if (!status && y_center) status = binary(&y, &y, y_center, FX_SUBTRACT);
        if (!status) status = accumulate_weight(&x, table, row);
        if (!status) status = binary(&x, &x, &y, FX_MULTIPLY);
        if (!status) status = binary(&total, &total, &x, FX_ADD);
        if (status) return status;
        if (numeric_error(&total)) break;
    }
    *out = total;
    return numeric_error(out);
}

int fx_stats_higher_moments(fx_number *cubes, fx_number *fourths,
                            const fx_stats_table *table, const fx_number *center) {
    fx_number third, fourth, x, square, cube, power4;
    unsigned row;
    int status;
    if (!cubes || !fourths || cubes == fourths || !valid(table)) return -1;
    if (!table->rows) { fx_number_error(cubes, 3); fx_number_error(fourths, 3); return 0xff; }
    fx_number_zero(&third); fx_number_zero(&fourth);
    for (row = 0; row < table->rows; ++row) {
        status = plain(&x, cell(table, row, 0));
        if (!status && center) status = binary(&x, &x, center, FX_SUBTRACT);
        if (!status) status = binary(&square, &x, &x, FX_MULTIPLY);
        if (!status) status = binary(&cube, &square, &x, FX_MULTIPLY);
        if (!status) status = binary(&power4, &x, &cube, FX_MULTIPLY);
        if (!status) status = accumulate_weight(&cube, table, row);
        if (!status) status = accumulate_weight(&power4, table, row);
        if (!status) status = binary(&third, &third, &cube, FX_ADD);
        if (!status) status = binary(&fourth, &fourth, &power4, FX_ADD);
        if (status) return status;
        if (numeric_error(&third) && numeric_error(&fourth)) break;
    }
    *cubes = third; *fourths = fourth;
    return pair_status(cubes, fourths, 0);
}

int fx_stats_square_cross(fx_number *out, const fx_stats_table *table,
                          const fx_number *x_center, const fx_number *y_center) {
    fx_number total, x, y;
    unsigned row;
    int status;
    if (!out || !valid(table) || table->variables != 2 || (!!x_center != !!y_center)) return -1;
    if (!table->rows) { fx_number_error(out, 3); return 3; }
    fx_number_zero(&total);
    for (row = 0; row < table->rows; ++row) {
        status = plain(&x, cell(table, row, 0));
        if (!status) status = plain(&y, cell(table, row, 1));
        if (!status && x_center) status = binary(&x, &x, x_center, FX_SUBTRACT);
        if (!status && y_center) status = binary(&y, &y, y_center, FX_SUBTRACT);
        if (!status) status = binary(&x, &x, &x, FX_MULTIPLY);
        if (!status) status = accumulate_weight(&x, table, row);
        if (!status) status = binary(&x, &x, &y, FX_MULTIPLY);
        if (!status) status = binary(&total, &total, &x, FX_ADD);
        if (status) return status;
        if (numeric_error(&total)) break;
    }
    *out = total;
    return numeric_error(out);
}

int fx_stats_mean(fx_number *out, const fx_stats_table *table, unsigned axis) {
    fx_number count, sum, squares;
    int status;
    if (!out || !valid(table) || axis >= table->variables) return -1;
    status = fx_stats_count(&count, table);
    if (status < 0) return status;
    if (status) { fx_number_error(out, 3); return 3; }
    status = fx_stats_moments(&sum, &squares, table, axis, FX_STATS_IDENTITY, 0);
    if (status < 0) return status;
    status = binary(out, &sum, &count, FX_DIVIDE);
    return status ? status : numeric_error(out);
}

int fx_stats_deviations(fx_number *population, fx_number *sample,
                        const fx_stats_table *table, unsigned axis) {
    fx_number mean, count, total, x, one, sample_divisor, pop;
    fx_decimal value;
    unsigned row;
    int status;
    if (!population || !sample || population == sample || !valid(table) ||
        axis >= table->variables) return -1;
    if (!table->rows) {
        fx_number_error(population, 3); fx_number_error(sample, 3); return 0xff;
    }
    status = fx_stats_mean(&mean, table, axis);
    if (status < 0) return status;
    status = fx_stats_count(&count, table);
    if (status < 0) return status;
    fx_number_zero(&total);
    for (row = 0; row < table->rows; ++row) {
        status = plain(&x, cell(table, row, axis));
        if (!status) status = binary(&x, &x, &mean, FX_SUBTRACT);
        if (!status) status = binary(&x, &x, &x, FX_MULTIPLY);
        if (!status) status = accumulate_weight(&x, table, row);
        if (!status) status = binary(&total, &total, &x, FX_ADD);
        if (status) return status;
        if (numeric_error(&total)) break;
    }
    pop = total;
    /* Nonpositive variance returns zero. For positive variance the
     * population and sample denominators diverge. */
    if (fx_decimal_decode(&value, &total) == 0 && value.sign > 0) {
        status = binary(&pop, &pop, &count, FX_DIVIDE);
        if (!status) status = fx_decimal_sqrt(&pop, &pop);
        fx_decimal_from_u8(&one, 1);
        if (!status) status = binary(&sample_divisor, &count, &one, FX_SUBTRACT);
        if (!status) status = binary(&total, &total, &sample_divisor, FX_DIVIDE);
        if (!status) status = fx_decimal_sqrt(&total, &total);
        if (status) return status;
    } else if (fx_decimal_decode(&value, &total) == 0) {
        fx_number_zero(&pop); fx_number_zero(&total);
    }
    *population = pop; *sample = total;
    return pair_status(population, sample, 0);
}

typedef struct {
    fx_number count, min_x, min_y, sx, sy, sxx, syy, sxy;
} centered_sums;

static int prepare_centered(centered_sums *s, const fx_stats_table *table,
                             fx_stats_transform xt, int log_y) {
    int status;
    status = fx_stats_extreme(&s->min_x, table, 0, xt, 0);
    if (status) return status;
    status = fx_stats_extreme(&s->min_y, table, 1,
                             log_y ? FX_STATS_LOG : FX_STATS_IDENTITY, 0);
    if (status) return status;
    status = fx_stats_count(&s->count, table);
    if (status) return status;
    status = fx_stats_moments(&s->sx, &s->sxx, table, 0, xt, &s->min_x);
    if (status) return status;
    status = fx_stats_moments(&s->sy, &s->syy, table, 1,
                             log_y ? FX_STATS_LOG : FX_STATS_IDENTITY, &s->min_y);
    if (status) return status;
    return fx_stats_cross(&s->sxy, table, xt, log_y, &s->min_x, &s->min_y);
}

static int regression_slope(fx_number *out, const centered_sums *s) {
    fx_number numerator, denominator, product;
    fx_decimal count;
    int status;
    if (fx_decimal_decode(&count, &s->count) || count.sign <= 0) {
        fx_number_error(out, 3); return 3;
    }
    status = binary(&numerator, &s->count, &s->sxy, FX_MULTIPLY);
    if (!status) status = binary(&product, &s->sx, &s->sy, FX_MULTIPLY);
    if (!status) status = binary(&numerator, &numerator, &product, FX_SUBTRACT);
    if (!status) status = binary(&denominator, &s->count, &s->sxx, FX_MULTIPLY);
    if (!status) status = binary(&product, &s->sx, &s->sx, FX_MULTIPLY);
    if (!status) status = binary(&denominator, &denominator, &product, FX_SUBTRACT);
    if (!status) status = binary(out, &numerator, &denominator, FX_DIVIDE);
    if (!status) status = fx_decimal_integer_cleanup(out);
    return status ? status : numeric_error(out);
}

static int regression_intercept(fx_number *out, const centered_sums *s,
                                 const fx_number *slope) {
    fx_number product;
    int status;
    status = binary(&product, slope, &s->sx, FX_MULTIPLY);
    if (!status) status = binary(out, &s->sy, &product, FX_SUBTRACT);
    if (!status) status = binary(out, out, &s->count, FX_DIVIDE);
    if (!status) status = fx_decimal_integer_cleanup(out);
    if (!status) status = binary(&product, slope, &s->min_x, FX_MULTIPLY);
    if (!status) status = binary(out, out, &product, FX_SUBTRACT);
    if (!status) status = binary(out, out, &s->min_y, FX_ADD);
    return status ? status : numeric_error(out);
}

static int regression_correlation(fx_number *out, const centered_sums *s) {
    fx_number vx, vy, product, numerator, one, minus_one;
    fx_decimal count;
    int status;
    if (fx_decimal_decode(&count, &s->count) || count.sign <= 0) {
        fx_number_error(out, 3); return 3;
    }
    status = binary(&vx, &s->count, &s->sxx, FX_MULTIPLY);
    if (!status) status = binary(&product, &s->sx, &s->sx, FX_MULTIPLY);
    if (!status) status = binary(&vx, &vx, &product, FX_SUBTRACT);
    if (!status) status = binary(&vy, &s->count, &s->syy, FX_MULTIPLY);
    if (!status) status = binary(&product, &s->sy, &s->sy, FX_MULTIPLY);
    if (!status) status = binary(&vy, &vy, &product, FX_SUBTRACT);
    if (!status) status = binary(&vy, &vy, &vx, FX_MULTIPLY);
    if (!status) status = fx_decimal_sqrt(&vy, &vy);
    if (!status) status = binary(&numerator, &s->count, &s->sxy, FX_MULTIPLY);
    if (!status) status = binary(&product, &s->sx, &s->sy, FX_MULTIPLY);
    if (!status) status = binary(&numerator, &numerator, &product, FX_SUBTRACT);
    if (!status) status = binary(out, &numerator, &vy, FX_DIVIDE);
    if (status) return status;
    fx_decimal_from_u8(&one, 1); fx_number_negate(&minus_one, &one);
    if (compare(out, &one) > 0) *out = one;
    else if (compare(out, &minus_one) < 0) *out = minus_one;
    status = fx_decimal_integer_cleanup(out);
    return status ? status : numeric_error(out);
}

static int quadratic_fit(fx_stats_fit *fit, const centered_sums *s,
                         const fx_stats_table *table) {
    fx_number cubes, fourths, xxy, dxx, dxy, dxx2, dx2x2, dx2y;
    fx_number product, determinant, b_centered, c, a, t, two;
    fx_decimal count;
    int status;
    if (fx_decimal_decode(&count, &s->count) || count.sign <= 0) return 3;
    status = fx_stats_higher_moments(&cubes, &fourths, table, &s->min_x);
    if (!status) status = fx_stats_square_cross(&xxy, table, &s->min_x, &s->min_y);
    if (status) return status;
    /* Normal equations are formed from moments centered at the observed
     * minimum. The native sequence keeps each 15-digit rounded intermediate. */
    status = binary(&product, &s->sx, &s->sx, FX_MULTIPLY);
    if (!status) status = binary(&dxx, &s->sxx, &s->count, FX_MULTIPLY);
    if (!status) status = binary(&dxx, &dxx, &product, FX_SUBTRACT);
    if (!status) status = numeric_error(&dxx);
    if (status) return status;
    status = binary(&product, &s->sx, &s->sy, FX_MULTIPLY);
    if (!status) status = binary(&dxy, &s->sxy, &s->count, FX_MULTIPLY);
    if (!status) status = binary(&dxy, &dxy, &product, FX_SUBTRACT);
    if (!status) status = numeric_error(&dxy);
    if (status) return status;
    status = binary(&product, &s->sx, &s->sxx, FX_MULTIPLY);
    if (!status) status = binary(&dxx2, &cubes, &s->count, FX_MULTIPLY);
    if (!status) status = binary(&dxx2, &dxx2, &product, FX_SUBTRACT);
    if (!status) status = numeric_error(&dxx2);
    if (status) return status;
    status = binary(&product, &s->sxx, &s->sxx, FX_MULTIPLY);
    if (!status) status = binary(&dx2x2, &fourths, &s->count, FX_MULTIPLY);
    if (!status) status = binary(&dx2x2, &dx2x2, &product, FX_SUBTRACT);
    if (!status) status = numeric_error(&dx2x2);
    if (status) return status;
    status = binary(&product, &s->sxx, &s->sy, FX_MULTIPLY);
    if (!status) status = binary(&dx2y, &xxy, &s->count, FX_MULTIPLY);
    if (!status) status = binary(&dx2y, &dx2y, &product, FX_SUBTRACT);
    if (!status) status = numeric_error(&dx2y);
    if (status) return status;
    status = binary(&determinant, &dxx, &dx2x2, FX_MULTIPLY);
    if (!status) status = binary(&product, &dxx2, &dxx2, FX_MULTIPLY);
    if (!status) status = binary(&determinant, &determinant, &product, FX_SUBTRACT);
    if (!status) status = binary(&b_centered, &dxy, &dx2x2, FX_MULTIPLY);
    if (!status) status = binary(&product, &dx2y, &dxx2, FX_MULTIPLY);
    if (!status) status = binary(&b_centered, &b_centered, &product, FX_SUBTRACT);
    if (!status) status = binary(&b_centered, &b_centered, &determinant, FX_DIVIDE);
    if (!status) status = fx_decimal_integer_cleanup(&b_centered);
    if (!status) status = numeric_error(&b_centered);
    if (status) return status;
    status = binary(&c, &dx2y, &dxx, FX_MULTIPLY);
    if (!status) status = binary(&product, &dxy, &dxx2, FX_MULTIPLY);
    if (!status) status = binary(&c, &c, &product, FX_SUBTRACT);
    if (!status) status = binary(&c, &c, &determinant, FX_DIVIDE);
    if (!status) status = fx_decimal_integer_cleanup(&c);
    if (!status) status = numeric_error(&c);
    if (status) return status;
    status = binary(&product, &b_centered, &s->sx, FX_MULTIPLY);
    if (!status) status = binary(&a, &s->sy, &product, FX_SUBTRACT);
    if (!status) status = binary(&product, &c, &s->sxx, FX_MULTIPLY);
    if (!status) status = binary(&a, &a, &product, FX_SUBTRACT);
    if (!status) status = binary(&a, &a, &s->count, FX_DIVIDE);
    if (!status) status = fx_decimal_integer_cleanup(&a);
    if (!status) status = numeric_error(&a);
    if (status) return status;
    status = binary(&product, &b_centered, &s->min_x, FX_MULTIPLY);
    if (!status) status = binary(&a, &a, &product, FX_SUBTRACT);
    if (!status) status = binary(&t, &s->min_x, &s->min_x, FX_MULTIPLY);
    if (!status) status = binary(&t, &t, &c, FX_MULTIPLY);
    if (!status) status = binary(&a, &a, &t, FX_ADD);
    if (!status) status = binary(&a, &a, &s->min_y, FX_ADD);
    if (!status) status = fx_decimal_integer_cleanup(&a);
    if (!status) status = numeric_error(&a);
    if (status) return status;
    fx_decimal_from_u8(&two, 2);
    status = binary(&product, &two, &c, FX_MULTIPLY);
    if (!status) status = binary(&product, &product, &s->min_x, FX_MULTIPLY);
    if (!status) status = binary(&fit->b, &b_centered, &product, FX_SUBTRACT);
    if (!status) status = fx_decimal_integer_cleanup(&fit->b);
    if (!status) status = numeric_error(&fit->b);
    if (status) return status;
    fit->a = a; fit->c = c;
    return 0;
}

int fx_stats_regression(fx_stats_fit *out, const fx_stats_table *table,
                        fx_stats_model model) {
    centered_sums s;
    fx_stats_fit fit;
    fx_stats_transform xt;
    int status, log_y;
    if (!out || !valid(table) || table->variables != 2 || model < 2 || model > 8) return -1;
    xt = (model == FX_STATS_INVERSE ? FX_STATS_RECIPROCAL :
          model == FX_STATS_LOGARITHMIC || model == FX_STATS_POWER ? FX_STATS_LOG : FX_STATS_IDENTITY);
    log_y = model == FX_STATS_EXPONENTIAL_E || model == FX_STATS_EXPONENTIAL_BASE || model == FX_STATS_POWER;
    fx_number_zero(&fit.c);
    status = prepare_centered(&s, table, xt, log_y);
    /* Correlation has its own return record even if coefficient computation
     * later fails. The public scalar wrappers report each result separately. */
    if (status < 0) return status;
    if (status) {
        fx_number_error(&fit.a, status == 1 ? 1 : 3);
        fit.b = fit.a; fit.correlation = fit.a;
        if (model == FX_STATS_QUADRATIC) fit.c = fit.a;
        *out = fit;
        return status == 1 ? 1 : 3;
    }
    status = regression_correlation(&fit.correlation, &s);
    if (status < 0) return status;
    if (model == FX_STATS_QUADRATIC) {
        status = quadratic_fit(&fit, &s, table);
        if (status < 0) return status;
        if (status) {
            fx_number_error(&fit.a, status == 1 ? 1 : 3);
            fit.b = fit.a; fit.c = fit.a;
        }
        *out = fit;
        return status == 1 ? 1 : status ? 3 : 0;
    }
    status = regression_slope(&fit.b, &s);
    if (!status) status = regression_intercept(&fit.a, &s, &fit.b);
    if (!status && model == FX_STATS_EXPONENTIAL_BASE) {
        status = fx_number_exp(&fit.b, &fit.b);
        if (!status) status = fx_decimal_integer_cleanup(&fit.b);
        if (!status) status = numeric_error(&fit.b);
    }
    if (!status && log_y) status = fx_number_exp(&fit.a, &fit.a);
    if (!status) status = fx_decimal_integer_cleanup(&fit.a);
    if (!status) status = numeric_error(&fit.a);
    if (status < 0) return status;
    if (status) {
        fx_number_error(&fit.a, status == 1 ? 1 : 3); fit.b = fit.a;
    }
    *out = fit;
    return status;
}

int fx_stats_predict(fx_number *out, const fx_stats_fit *fit,
                     fx_stats_model model, const fx_number *value,
                     int inverse, int second_root) {
    fx_number x, y, t, divisor, integer;
    int status;
    if (!out || !fit || !value || model < 2 || model > 8) return -1;
    /* The original public prediction entries return existing input errors
     * before querying/refreshing the regression dataset. */
    if (failed(value)) { *out = *value; return numeric_error(out); }
    if (failed(&fit->a) || failed(&fit->b) ||
        (model == FX_STATS_QUADRATIC && failed(&fit->c))) {
        int code = numeric_error(&fit->a) == 1 || numeric_error(&fit->b) == 1 ||
                   (model == FX_STATS_QUADRATIC && numeric_error(&fit->c) == 1) ? 1 : 3;
        fx_number_error(out, code); return code;
    }
    x = *value; status = 0;
    if (!inverse) {
        switch (model) {
        case FX_STATS_QUADRATIC:
            status = binary(&y, &x, &x, FX_MULTIPLY);
            if (!status) status = binary(&y, &y, &fit->c, FX_MULTIPLY);
            if (!status) status = binary(&t, &x, &fit->b, FX_MULTIPLY);
            if (!status) status = binary(&y, &y, &t, FX_ADD);
            if (!status) status = binary(&y, &y, &fit->a, FX_ADD);
            break;
        case FX_STATS_EXPONENTIAL_E:
            status = binary(&y, &x, &fit->b, FX_MULTIPLY);
            if (!status) status = fx_number_exp(&y, &y);
            if (!status) status = binary(&y, &y, &fit->a, FX_MULTIPLY);
            break;
        case FX_STATS_EXPONENTIAL_BASE:
            status = real_power(&y, &fit->b, &x);
            if (!status) status = binary(&y, &y, &fit->a, FX_MULTIPLY);
            break;
        case FX_STATS_POWER:
            status = real_power(&y, &x, &fit->b);
            if (!status) status = binary(&y, &y, &fit->a, FX_MULTIPLY);
            break;
        case FX_STATS_INVERSE:
            status = binary(&y, &fit->b, &x, FX_DIVIDE);
            if (!status) status = binary(&y, &y, &fit->a, FX_ADD);
            break;
        default:
            y = x;
            if (model == FX_STATS_LOGARITHMIC) status = fx_number_ln(&y, &y);
            if (!status) status = binary(&y, &y, &fit->b, FX_MULTIPLY);
            if (!status) status = binary(&y, &y, &fit->a, FX_ADD);
            break;
        }
    } else {
        switch (model) {
        case FX_STATS_QUADRATIC:
            status = binary(&t, &fit->a, &x, FX_SUBTRACT);
            if (!status) status = binary(&t, &t, &fit->c, FX_MULTIPLY);
            fx_decimal_from_u8(&integer, 4);
            if (!status) status = binary(&t, &integer, &t, FX_MULTIPLY);
            if (!status) status = binary(&y, &fit->b, &fit->b, FX_MULTIPLY);
            if (!status) status = binary(&y, &y, &t, FX_SUBTRACT);
            if (!status) status = fx_decimal_sqrt(&y, &y);
            if (!status && second_root) status = fx_number_negate(&y, &y);
            if (!status) status = binary(&y, &y, &fit->b, FX_SUBTRACT);
            fx_decimal_from_u8(&integer, 2);
            if (!status) status = binary(&divisor, &integer, &fit->c, FX_MULTIPLY);
            if (!status) status = binary(&y, &y, &divisor, FX_DIVIDE);
            break;
        case FX_STATS_EXPONENTIAL_E:
        case FX_STATS_EXPONENTIAL_BASE:
            y = x; t = fit->a;
            status = fx_number_ln(&y, &y);
            if (!status) status = fx_number_ln(&t, &t);
            if (!status) status = binary(&y, &y, &t, FX_SUBTRACT);
            divisor = fit->b;
            if (!status && model == FX_STATS_EXPONENTIAL_BASE) status = fx_number_ln(&divisor, &divisor);
            if (!status) status = binary(&y, &y, &divisor, FX_DIVIDE);
            break;
        case FX_STATS_POWER:
            y = x; t = fit->a;
            status = fx_number_ln(&y, &y);
            if (!status) status = fx_number_ln(&t, &t);
            if (!status) status = binary(&y, &y, &t, FX_SUBTRACT);
            if (!status) status = binary(&y, &y, &fit->b, FX_DIVIDE);
            if (!status) status = fx_number_exp(&y, &y);
            break;
        case FX_STATS_INVERSE:
            status = binary(&t, &x, &fit->a, FX_SUBTRACT);
            if (!status) status = binary(&y, &fit->b, &t, FX_DIVIDE);
            break;
        default:
            status = binary(&y, &x, &fit->a, FX_SUBTRACT);
            if (!status) status = binary(&y, &y, &fit->b, FX_DIVIDE);
            if (!status && model == FX_STATS_LOGARITHMIC) status = fx_number_exp(&y, &y);
            break;
        }
    }
    if (!status) status = fx_decimal_integer_cleanup(&y);
    if (status) return status;
    *out = y;
    return numeric_error(out);
}
