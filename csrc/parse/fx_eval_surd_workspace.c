/* SPDX-License-Identifier: GPL-3.0-only */
/* Ordered mathematical workspace for exact surd arithmetic. The 32 live
 * decimal records at8640..877F overlap physical rich payloads, so copies and
 * reductions happen while computing each result, before a caller reads its
 * next element. This is numeric data storage, not an emulated CPU frame.
 */
#include "fx_eval_surd_workspace.h"
#include <stdint.h>
#include <string.h>

typedef struct { uint8_t *ram; int host_gap; } pool;
static unsigned address(unsigned index) { return 0x8640u + 10u * index; }
static fx_number read_number(const pool *p, unsigned i) {
    fx_number n; memcpy(&n, p->ram + address(i), sizeof n); return n;
}
static void write_number(pool *p, unsigned i, const fx_number *n) {
    memcpy(p->ram + address(i), n, sizeof *n);
}
static fx_number physical_number(const pool *p, uint16_t a) {
    fx_number n; unsigned i;
    for (i = 0; i < 10; ++i) n.bytes[i] = p->ram[(uint16_t)(a + i)];
    return n;
}
static void integer(pool *p, unsigned i, int64_t value) {
    fx_number n; (void)fx_decimal_from_integer(&n, value); write_number(p, i, &n);
}
static void copy_number(pool *p, unsigned from, unsigned to) {
    fx_number n = read_number(p, from); write_number(p, to, &n);
}
static void copy_term(pool *p, unsigned from, unsigned to) {
    unsigned i;
    for (i = 0; i < 30; ++i)
        p->ram[address(to) + i] = p->ram[address(from) + i];
}
static void swap_terms(pool *p, unsigned a, unsigned b) {
    copy_term(p, a, 27); copy_term(p, b, a); copy_term(p, 27, b);
}
/* Empty terms retain denominator1; a plain zero triple is not equivalent
 * to the native representation during later sorting and reduction. */
static void empty_term(pool *p, unsigned i) {
    integer(p, i, 0); integer(p, i + 1, 0); integer(p, i + 2, 1);
}
static int zero_coefficient(const pool *p, unsigned i) {
    return p->ram[address(i)] == 0;
}
static int64_t component_integer(const pool *p, unsigned i, int *okay) {
    fx_number n = read_number(p, i); int64_t value = 0;
    if (fx_decimal_to_integer(&value, &n) != FX_NUMERIC_OK) *okay = 0;
    return value;
}
static int equal_radicals(const pool *p, unsigned a, unsigned b) {
    int okay = 1;
    int64_t x = component_integer(p, a + 1, &okay);
    int64_t y = component_integer(p, b + 1, &okay);
    return okay && x == y;
}
static int greater_radical(const pool *p, unsigned a, unsigned b) {
    int okay = 1;
    int64_t x = component_integer(p, a + 1, &okay);
    int64_t y = component_integer(p, b + 1, &okay);
    return okay && x > y;
}
static int radical_zero(const pool *p, unsigned i) {
    return p->ram[address(i + 1)] == 0;
}
static fx_numeric_status arithmetic(pool *p, unsigned a, unsigned b,
                                     unsigned out, fx_binary_op op) {
    fx_number x = read_number(p, a), y = read_number(p, b), z;
    fx_numeric_status status;
    if (op == FX_MULTIPLY && y.bytes[0] == 1 && !y.bytes[8] &&
        (y.bytes[9] == 1 || y.bytes[9] == 6)) {
        z = x;
        if (y.bytes[9] == 6 && (z.bytes[8] || z.bytes[9]))
            z.bytes[9] = (uint8_t)((z.bytes[9] + 5u) % 10u);
        status = FX_NUMERIC_OK;
    } else if (op == FX_ADD) status = fx_decimal_add_plain(&z, &x, &y);
    else status = fx_decimal_binary(&z, &x, &y, op);
    if (status == FX_NUMERIC_OK) write_number(p, out, &z);
    return status;
}
static uint64_t magnitude(int64_t v) {
    return v < 0 ? (uint64_t)(-(v + 1)) + 1u : (uint64_t)v;
}
static uint64_t gcd(uint64_t a, uint64_t b) {
    while (b) { uint64_t r = a % b; a = b; b = r; } return a;
}
static int reduce_fraction(pool *p, unsigned numerator, unsigned denominator) {
    fx_number n = read_number(p, numerator), d = read_number(p, denominator);
    fx_decimal nv, dv; int64_t ni, di; uint64_t common; fx_number divisor;
    if (d.bytes[9] == 6) {
        d.bytes[9] = 1;
        if (n.bytes[8] || n.bytes[9]) n.bytes[9] = (uint8_t)((n.bytes[9] + 5u) % 10u);
    }
    if (fx_decimal_decode(&nv, &n) != FX_NUMERIC_OK ||
        fx_decimal_decode(&dv, &d) != FX_NUMERIC_OK) return 0;
    if (nv.sign && dv.sign) {
        if (fx_decimal_to_integer(&ni, &n) != FX_NUMERIC_OK ||
            fx_decimal_to_integer(&di, &d) != FX_NUMERIC_OK) {
            p->host_gap = 1; return 0;
        }
        common = gcd(magnitude(ni), magnitude(di));
        if (common > INT64_MAX) { p->host_gap = 1; return 0; }
        (void)fx_decimal_from_integer(&divisor, (int64_t)common);
        if (fx_decimal_binary(&n, &n, &divisor, FX_DIVIDE) != FX_NUMERIC_OK ||
            fx_decimal_binary(&d, &d, &divisor, FX_DIVIDE) != FX_NUMERIC_OK) return 0;
    }
    write_number(p, numerator, &n); write_number(p, denominator, &d); return 1;
}
static int eligible_fraction(const pool *p, unsigned i) {
    return p->ram[address(i) + 8] <= 14 && p->ram[address(i + 2) + 8] <= 14;
}
static int factor_radical(pool *p) {
    fx_number original = read_number(p, 29), residual;
    int64_t raw; uint64_t value, factor = 1, divisor;
    integer(p, 27, 1);
    if (fx_decimal_to_integer(&raw, &original) != FX_NUMERIC_OK) {
        p->host_gap = 1; return 0;
    }
    if (raw < 0) return 0;
    value = (uint64_t)raw;
    for (divisor = 2; divisor <= 97 && divisor <= value / divisor; ++divisor) {
        uint64_t square = divisor * divisor;
        while (value % square == 0) { value /= square; factor *= divisor; }
    }
    integer(p, 27, (int64_t)factor);
    if (raw <= 1) residual = original;
    else (void)fx_decimal_from_integer(&residual, (int64_t)value);
    write_number(p, 28, &residual); return 1;
}
static int product_term(pool *p, unsigned a, unsigned b, unsigned out) {
    if (arithmetic(p, a + 1, b + 1, 29, FX_MULTIPLY) != FX_NUMERIC_OK ||
        !factor_radical(p)) return 0;
    copy_number(p, 28, out + 1);
    if (arithmetic(p, a, b, out, FX_MULTIPLY) != FX_NUMERIC_OK ||
        arithmetic(p, out, 27, out, FX_MULTIPLY) != FX_NUMERIC_OK ||
        arithmetic(p, a + 2, b + 2, out + 2, FX_MULTIPLY) != FX_NUMERIC_OK) return 0;
    return eligible_fraction(p, out) && reduce_fraction(p, out, out + 2);
}
static int sum_terms(pool *p, unsigned a, unsigned b, unsigned out) {
    if (arithmetic(p, a, b + 2, 27, FX_MULTIPLY) != FX_NUMERIC_OK ||
        arithmetic(p, a + 2, b, 28, FX_MULTIPLY) != FX_NUMERIC_OK ||
        arithmetic(p, 27, 28, out, FX_ADD) != FX_NUMERIC_OK) return 0;
    copy_number(p, a + 1, out + 1);
    if (arithmetic(p, a + 2, b + 2, out + 2, FX_MULTIPLY) != FX_NUMERIC_OK) return 0;
    return eligible_fraction(p, out) && reduce_fraction(p, out, out + 2);
}
static int scalar_term(pool *p, unsigned scalar, unsigned term, unsigned out) {
    if (arithmetic(p, scalar, term, out, FX_MULTIPLY) != FX_NUMERIC_OK) return 0;
    copy_number(p, term + 1, out + 1); copy_number(p, term + 2, out + 2);
    return eligible_fraction(p, out) && reduce_fraction(p, out, out + 2);
}
static int normalize_pair(pool *p) {
    if (zero_coefficient(p, 0)) empty_term(p, 0);
    if (zero_coefficient(p, 3)) {
        copy_term(p, 0, 3);
        empty_term(p, 0);
    }
    return 1;
}
static int reduce_four(pool *p) {
    unsigned pass, i;
    for (pass = 0; pass < 3; ++pass) for (i = 0; i < 3 - pass; ++i)
        if (greater_radical(p, 12 + 3 * i, 15 + 3 * i))
            swap_terms(p, 12 + 3 * i, 15 + 3 * i);
    if (radical_zero(p, 15)) {
        copy_term(p, 18, 0); copy_term(p, 21, 3);
    } else if (radical_zero(p, 12)) {
        if (equal_radicals(p, 15, 18)) {
            if (!sum_terms(p, 15, 18, 0)) return 0;
            copy_term(p, 21, 3);
        } else if (equal_radicals(p, 18, 21)) {
            copy_term(p, 15, 0); if (!sum_terms(p, 18, 21, 3)) return 0;
        } else return 0;
    } else if (equal_radicals(p, 12, 15)) {
        if (!sum_terms(p, 12, 15, 0)) return 0;
        if (equal_radicals(p, 12, 18)) {
            if (!sum_terms(p, 18, 0, 0)) return 0;
            copy_term(p, 21, 3);
        } else if (equal_radicals(p, 18, 21)) {
            if (!sum_terms(p, 18, 21, 3)) return 0;
        } else if (zero_coefficient(p, 0)) {
            copy_term(p, 18, 0); copy_term(p, 21, 3);
        } else return 0;
    } else if (equal_radicals(p, 15, 18)) {
        copy_term(p, 12, 0); if (!sum_terms(p, 15, 18, 3)) return 0;
        if (equal_radicals(p, 15, 21)) {
            if (!sum_terms(p, 3, 21, 3)) return 0;
        } else if (zero_coefficient(p, 3)) copy_term(p, 21, 3);
        else return 0;
    } else if (equal_radicals(p, 18, 21)) {
        if (!sum_terms(p, 18, 21, 0) || !zero_coefficient(p, 0)) return 0;
        copy_term(p, 12, 0); copy_term(p, 15, 3);
    } else return 0;
    if (!normalize_pair(p)) return 0;
    if (equal_radicals(p, 0, 3)) {
        if (!sum_terms(p, 3, 0, 3)) return 0;
        empty_term(p, 0);
    }
    return 1;
}
static int four_products(pool *p) {
    return product_term(p, 6, 0, 12) && product_term(p, 9, 0, 15) &&
        product_term(p, 3, 6, 18) && product_term(p, 3, 9, 21);
}
/* Classify both saved values before emitting either term expansion. Native
 * combined flags reject unsupported/error forms without touching term pools.
 */
static unsigned classify(pool *p, unsigned input) {
    fx_number n = read_number(p, input); fx_rational rational;
    unsigned header;
    if (fx_number_recognize_rational(&rational, &n)) {
        if (fx_rational_encode(&n, &rational) != FX_NUMERIC_OK) return 64;
        write_number(p, input, &n);
    }
    header = n.bytes[0] & 0xf0u;
    if (header == 0x80) return 1;
    if (header == 0x20) return 4;
    if (header == 0 && !fx_number_fractional_status(&n) && n.bytes[8] <= 7)
        return 16;
    return 64;
}
static int expand_number(pool *p, const fx_number *number, unsigned out) {
    fx_number n = *number, parts[6]; fx_rational rational;
    unsigned i, header = n.bytes[0] & 0xf0u; int64_t numerator;
    if (header == 0x80) {
        if (fx_surd_unpack(parts, &n) != FX_NUMERIC_OK) return 0;
        for (i = 0; i < 6; ++i) write_number(p, out + i, &parts[i]);
        return 1;
    }
    if (header == 0) {
        fx_decimal decimal;
        if (fx_decimal_decode(&decimal, &n) != FX_NUMERIC_OK || n.bytes[8] > 7) return 0;
        write_number(p, out + 3, &n);
        integer(p, out + 5, 1); integer(p, out + 4, decimal.sign ? 1 : 0);
    } else if (header == 0x20) {
        if (fx_rational_decode(&rational, &n) != FX_NUMERIC_OK || rational.denominator > INT64_MAX) return 0;
        numerator = rational.numerator;
        integer(p, out + 3, numerator); integer(p, out + 5, (int64_t)rational.denominator);
        integer(p, out + 4, 1);
    } else return 0;
    empty_term(p, out); return 1;
}
static int expand(pool *p, unsigned input, unsigned out) {
    fx_number number = read_number(p, input);
    return expand_number(p, &number, out);
}
static fx_numeric_status fallback(pool *p, uint16_t physicalcurrent,
                                  fx_number *out, fx_binary_op op) {
    fx_number a, b, parts[6], converted; unsigned i;
    a = read_number(p, 30);
    if (fx_number_kind(&a) == FX_NUMBER_SURD) {
        if (fx_surd_unpack(parts, &a) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
        for (i = 0; i < 6; ++i) write_number(p, i, &parts[i]);
        if (fx_number_to_decimal(&converted, &a) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
        write_number(p, 30, &converted); a = converted;
    }
    /*173FA converts header80 only. Rational/plain/error saved operands stay
     * raw for the final ordinary arithmetic dispatcher; decimalizing a saved
     * rational here would change the physical record31 payload alias. */
    /* Converting saved-left commits it to the original current destination
     * before saved-right is unfolded. That unfolding may overwrite current
     * when current itself occupies8640..867B. Reread it afterward. */
    if (physicalcurrent) for (i = 0; i < 10; ++i)
        p->ram[(uint16_t)(physicalcurrent + i)] = a.bytes[i];
    b = read_number(p, 31);
    if (fx_number_kind(&b) == FX_NUMBER_SURD) {
        if (fx_surd_unpack(parts, &b) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
        for (i = 0; i < 6; ++i) write_number(p, i, &parts[i]);
        if (fx_number_to_decimal(&converted, &b) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
        write_number(p, 31, &converted); b = converted;
    }
    if (physicalcurrent) a = physical_number(p, physicalcurrent);
    /* Ordinary arithmetic admission maps any error operand to MathError3.
     * This happens after conversion/copy aliases, not before surd expansion.
     */
    if (fx_number_kind(&a) == FX_NUMBER_ERROR || fx_number_kind(&b) == FX_NUMBER_ERROR) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    return fx_number_binary(out, &a, &b, op);
}
/* Scalar results use the rational constructor; compact surd packing would
 * retain a surd header for results such as sqrt2*sqrt2. The existing numeric
 * constructor owns rational/plain representation and integer cleanup.
 * The mathematical GCD seam currently requires integer components to fit
 * int64; larger finite cases return an explicit implementation gap.
 */
static fx_numeric_status pack_pair(pool *p, fx_number *out) {
    fx_number parts[6]; unsigned i; int64_t numerator, denominator, radical;
    if (zero_coefficient(p, 0) && zero_coefficient(p, 3)) {
        fx_number_zero(out); return FX_NUMERIC_OK;
    }
    for (i = 0; i < 6; ++i) parts[i] = read_number(p, i);
    if (zero_coefficient(p, 0) &&
        fx_decimal_to_integer(&radical, &parts[4]) == FX_NUMERIC_OK && radical == 1) {
        fx_rational rational;
        if (fx_decimal_to_integer(&numerator, &parts[3]) != FX_NUMERIC_OK ||
            fx_decimal_to_integer(&denominator, &parts[5]) != FX_NUMERIC_OK ||
            denominator < 0) return FX_NUMERIC_UNIMPLEMENTED;
        rational.numerator = numerator; rational.denominator = (uint64_t)denominator;
        rational.flags = 0;
        return fx_rational_encode(out, &rational);
    }
    return fx_surd_pack(out, parts);
}
/* Native saving order is visible when operands alias the pool: current is
 * saved first; only then is the other physical operand reread and saved.
 */
fx_numeric_status fx_eval_surd_workspace_binary(fx_number *out,
    uint8_t ram[65536], const fx_number *current, const fx_number *other,
    uint16_t physicalcurrent, uint16_t physicalother, fx_binary_op operation)
{
    pool p = {ram, 0}; fx_number a, b; unsigned leftflag = 0, rightflag = 0, i;
    int okay;
    if (!ram || !current || !other || !out) return FX_NUMERIC_INVALID;
    a = physicalcurrent ? physical_number(&p, physicalcurrent) : *current;
    b = physicalother ? physical_number(&p, physicalother) : *other;
    if (fx_number_kind(&a) != FX_NUMBER_SURD && fx_number_kind(&b) != FX_NUMBER_SURD)
        return fx_number_binary(out, &a, &b, operation);
    write_number(&p, 30, &a);
    b = physicalother ? physical_number(&p, physicalother) : *other;
    write_number(&p, 31, &b);
    if (operation == FX_SUBTRACT) {
        (void)fx_number_negate(&b, &b); write_number(&p, 31, &b);
    }
    leftflag = classify(&p, 30); rightflag = classify(&p, 31);
    okay = leftflag + 2 * rightflag < 64;
    if (okay && (operation == FX_ADD || operation == FX_SUBTRACT)) {
        okay = expand(&p, 30, 12) && expand(&p, 31, 18) && reduce_four(&p);
    } else if (okay) {
        okay = expand(&p, 30, 0) && expand(&p, 31, 6);
        if (okay && operation == FX_MULTIPLY) {
            if (leftflag == 16) okay = scalar_term(&p, 30, 6, 0) && scalar_term(&p, 30, 9, 3);
            else okay = four_products(&p) && reduce_four(&p);
        } else if (okay && operation == FX_DIVIDE) {
            if (radical_zero(&p, 6)) {
                if (radical_zero(&p, 9)) okay = 0;
                else {
                    copy_number(&p, 11, 6); copy_number(&p, 10, 7);
                    okay = arithmetic(&p, 9, 10, 8, FX_MULTIPLY) == FX_NUMERIC_OK &&
                        product_term(&p, 6, 0, 0) && product_term(&p, 3, 6, 3) && normalize_pair(&p);
                    if (okay && greater_radical(&p, 0, 3)) swap_terms(&p, 0, 3);
                }
            } else {
                okay = arithmetic(&p, 8, 11, 24, FX_MULTIPLY) == FX_NUMERIC_OK &&
                    arithmetic(&p, 24, 24, 24, FX_MULTIPLY) == FX_NUMERIC_OK &&
                    arithmetic(&p, 6, 11, 26, FX_MULTIPLY) == FX_NUMERIC_OK &&
                    arithmetic(&p, 26, 26, 26, FX_MULTIPLY) == FX_NUMERIC_OK &&
                    arithmetic(&p, 26, 7, 26, FX_MULTIPLY) == FX_NUMERIC_OK &&
                    arithmetic(&p, 9, 8, 25, FX_MULTIPLY) == FX_NUMERIC_OK &&
                    arithmetic(&p, 25, 25, 25, FX_MULTIPLY) == FX_NUMERIC_OK &&
                    arithmetic(&p, 25, 10, 25, FX_MULTIPLY) == FX_NUMERIC_OK &&
                    arithmetic(&p, 26, 25, 26, FX_SUBTRACT) == FX_NUMERIC_OK && reduce_fraction(&p, 24, 26);
                if (okay) {
                    b = read_number(&p, 9); (void)fx_number_negate(&b, &b); write_number(&p, 9, &b);
                    okay = four_products(&p) && reduce_four(&p);
                }
                for (i = 0; okay && i < 6; i += 3) if (!radical_zero(&p, i)) {
                    okay = arithmetic(&p, i, 24, i, FX_MULTIPLY) == FX_NUMERIC_OK &&
                        arithmetic(&p, i + 2, 26, i + 2, FX_MULTIPLY) == FX_NUMERIC_OK &&
                        eligible_fraction(&p, i) && reduce_fraction(&p, i, i + 2);
                }
            }
        } else okay = 0;
    }
    if (!okay) {
        if (p.host_gap) return FX_NUMERIC_UNIMPLEMENTED;
        return fallback(&p, physicalcurrent, out,
                        operation == FX_SUBTRACT ? FX_ADD : operation);
    }
    return pack_pair(&p, out);
}

/*17A46 initializes the coefficient before factoring the supplied radicand.
 * All factoring temporaries are private mathematical values; the committed
 * coefficient/radicand pair belongs to the actual SURD component pool. */
static int normalize_square_root(pool *p, unsigned input, unsigned output)
{
    fx_number original = read_number(p, input), residual;
    int64_t raw;
    uint64_t remaining, coefficient = 1;
    integer(p, output, 1);
    write_number(p, output + 1, &original);
    if (fx_decimal_to_integer(&raw, &original) != FX_NUMERIC_OK || raw < 0)
        return 0;
    remaining = (uint64_t)raw;
    for (uint64_t divisor = 2; divisor <= 97 && divisor <= remaining / divisor; ++divisor) {
        uint64_t square = divisor * divisor;
        while (remaining % square == 0) {
            remaining /= square;
            coefficient *= divisor;
        }
    }
    integer(p, output, (int64_t)coefficient);
    if (raw <= 1) residual = original;
    else (void)fx_decimal_from_integer(&residual, (int64_t)remaining);
    write_number(p, output + 1, &residual);
    return 1;
}

fx_numeric_status fx_eval_surd_workspace_sqrt(fx_number *out,
    uint8_t ram[65536], const fx_number *input, int exact_math)
{
    pool p = {ram, 0};
    fx_number source;
    fx_rational fraction;
    fx_numeric_status status;
    if (!out || !ram || !input) return FX_NUMERIC_INVALID;
    source = *input;
    if (!exact_math) return fx_number_sqrt(out, &source, 0);
    if ((source.bytes[0] & 0xf0) == 0 && source.bytes[9] <= 1 &&
        (source.bytes[9] == 0 || source.bytes[8] < 7)) {
        /*11110 finishes its bounded rational recognition before17820.
         * The recognized source remains the fallback input too. */
        if (!fx_number_recognize_rational(&fraction, &source))
            return fx_number_sqrt(out, &source, 1);
        status = fx_rational_encode(&source, &fraction);
        if (status != FX_NUMERIC_OK) return status;
    }
    if (source.bytes[0] & 0xf0) {
        if ((source.bytes[0] & 0xf0) != 0x20 || source.bytes[9] != 1)
            return fx_number_sqrt(out, &source, 1);
    } else if (source.bytes[9] > 1 || (source.bytes[9] == 1 && source.bytes[8] >= 7))
        return fx_number_sqrt(out, &source, 1);
    if (!expand_number(&p, &source, 0)) return FX_NUMERIC_UNIMPLEMENTED;
    /*1C7B0 checks representability after the initial six component writes. */
    if (ram[address(3) + 8] >= 7 || ram[address(5) + 8] >= 4)
        return fx_number_sqrt(out, &source, 1);
    copy_number(&p, 3, 0);
    if (!normalize_square_root(&p, 0, 3)) return FX_NUMERIC_UNIMPLEMENTED;
    copy_number(&p, 5, 0);
    if (!normalize_square_root(&p, 0, 5)) return FX_NUMERIC_UNIMPLEMENTED;
    status = arithmetic(&p, 4, 6, 4, FX_MULTIPLY);
    if (status == FX_NUMERIC_OK) status = arithmetic(&p, 5, 6, 5, FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) return status;
    copy_number(&p, 1, 0);
    write_number(&p, 6, &source);
    /* Only now is the result packed. A format fallback retains all writes. */
    status = pack_pair(&p, out);
    return status == FX_NUMERIC_OK ? status : fx_number_sqrt(out, &source, 1);
}
