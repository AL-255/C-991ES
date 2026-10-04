/* High-level output serialization, independently implemented from observed
 * numeric records and AB8E/C060/B99C. GPL-3.0-or-later.
 * No instruction decoding, firmware execution or host floating point. */
#include "fx_format.h"
#include <limits.h>
#include <string.h>

typedef struct { uint8_t *data; size_t capacity, length; } writer;
static void byte(writer *w, unsigned value) {
    if (w->length + 1 < w->capacity) w->data[w->length] = (uint8_t)value;
    ++w->length;
}
static void finish(writer *w) {
    if (w->capacity) w->data[w->length < w->capacity ? w->length : w->capacity - 1] = 0;
}
static void integer(writer *w, uint64_t value) {
    char digits[21]; size_t count = 0;
    do { digits[count++] = (char)('0' + value % 10); value /= 10; } while (value);
    while (count) byte(w, (unsigned)digits[--count]);
}
static uint64_t magnitude(int64_t value) {
    return value < 0 ? (uint64_t)(-(value + 1)) + 1 : (uint64_t)value;
}
static uint64_t gcd(uint64_t a, uint64_t b) {
    while (b) { uint64_t r = a % b; a = b; b = r; } return a;
}
static uint64_t power10(unsigned n) {
    uint64_t v = 1; while (n--) v *= 10; return v;
}
/* The firmware's 10B60 integer probe overwrites the last BCD pair with 00
 * or 99 before cleaning extremely small residue. The resulting threshold
 * is expressed in stored mantissa units, not host floating point. */
static int clean_integer(fx_decimal d, int64_t *value) {
    if (d.exponent < -1 || d.exponent > 14) return 0;
    uint64_t unit = power10((unsigned)(14 - d.exponent));
    uint64_t tail = d.mantissa % 100;
    uint64_t mantissa = d.mantissa - tail + (tail < 50 ? 0 : 99);
    uint64_t remainder = mantissa % unit;
    if (remainder && remainder + 1 != unit) return 0;
    uint64_t n = mantissa / unit + !!remainder;
    if (n > INT64_MAX) return 0;
    *value = d.sign < 0 ? -(int64_t)n : (int64_t)n;
    return 1;
}
static unsigned digit_count(uint64_t n) {
    unsigned count = 1; while (n >= 10) { n /= 10; ++count; } return count;
}
/* Fixed-width wide integers accommodate the [-8,6] recognition range's
 * 22-place denominator exactly. They are used only for rational arithmetic.
 * GCC and Clang support this C integer extension on the targeted hosts. */
typedef unsigned __int128 wide;
typedef struct { wide n, d; } interval_fraction;
static interval_fraction simplest_interval(wide ln, wide ld, wide un, wide ud,
                                           unsigned depth) {
    wide a = ln / ld, b = un / ud;
    if (depth > 40) { interval_fraction fail = {0, 0}; return fail; }
    if (ln % ld == 0) { interval_fraction whole = {a, 1}; return whole; }
    if (a != b) { interval_fraction whole = {a + 1, 1}; return whole; }
    interval_fraction inner = simplest_interval(ud, un % ud, ld, ln % ld, depth + 1);
    if (!inner.d) return inner;
    interval_fraction out = {a * inner.n + inner.d, inner.n}; return out;
}
static int recognize_rational(const fx_number *number, fx_rational *result) {
    fx_decimal d;
    if (fx_decimal_decode(&d, number) != FX_NUMERIC_OK || !d.mantissa ||
        d.exponent < -8 || d.exponent > 6) return 0;
    int64_t whole;
    if (clean_integer(d, &whole)) {
        result->numerator = whole; result->denominator = 1; result->flags = d.flags;
        return 1;
    }
    if (d.exponent >= 6) return 0;
    wide denominator = 1;
    for (int i = 0; i < 14 - d.exponent; ++i) denominator *= 10;
    /* 10962 constructs x +/- 4*10^(exponent-13), a radius of 40 stored
     * mantissa units, then finds the fraction with the simplest denominator. */
    interval_fraction f = simplest_interval((wide)d.mantissa - 40, denominator,
                                            (wide)d.mantissa + 40, denominator, 0);
    if (!f.d || f.n > INT64_MAX || f.d > UINT64_MAX) return 0;
    uint64_t n = (uint64_t)f.n, den = (uint64_t)f.d;
    uint64_t integer_part = n / den, remainder = n % den;
    unsigned numerator_digits = digit_count(remainder), denominator_digits = digit_count(den);
    if (numerator_digits > 8 || denominator_digits > 8 ||
        (integer_part ? digit_count(integer_part) + numerator_digits + denominator_digits > 8
                      : numerator_digits + denominator_digits > 9)) return 0;
    result->numerator = d.sign < 0 ? -(int64_t)n : (int64_t)n;
    result->denominator = den; result->flags = d.flags; return 1;
}
static int recognize_pi(const fx_number *number, fx_rational *coefficient) {
    fx_decimal d;
    if (fx_decimal_decode(&d, number) != FX_NUMERIC_OK || !d.mantissa ||
        d.exponent < -7 || d.exponent >= 6) return 0;
    fx_number pi = {{0x03,0x14,0x15,0x92,0x65,0x35,0x89,0x80,0x00,0x01}};
    fx_number scale = {{0x02,0x52,0,0,0,0,0,0,0x04,0x01}};
    fx_number absolute, ratio, scaled;
    int sign = d.sign; d.sign = 1;
    if (fx_decimal_encode(&absolute, &d) != FX_NUMERIC_OK ||
        fx_decimal_binary(&ratio, &absolute, &pi, FX_DIVIDE) != FX_NUMERIC_OK ||
        fx_decimal_binary(&scaled, &ratio, &scale, FX_MULTIPLY) != FX_NUMERIC_OK ||
        fx_decimal_decode(&d, &scaled) != FX_NUMERIC_OK) return 0;
    int64_t numerator;
    if (!clean_integer(d, &numerator)) return 0;
    uint64_t common = gcd((uint64_t)numerator, 25200);
    coefficient->numerator = sign * (numerator / (int64_t)common);
    coefficient->denominator = 25200 / common; coefficient->flags = 0;
    return 1;
}
static void mantissa_digits(uint64_t value, unsigned char out[15]) {
    for (int i = 14; i >= 0; --i) { out[i] = (unsigned char)(value % 10); value /= 10; }
}
/* All rounding is decimal half up; the 15-digit value remains an integer. */
static void round_digits(fx_decimal *d, int significant) {
    if (!d->mantissa || significant >= 15) return;
    fx_decimal original = *d;
    if (significant < 0) { d->mantissa = 0; d->sign = 0; d->exponent = 0; return; }
    if (!significant) {
        if (d->mantissa >= UINT64_C(500000000000000)) {
            d->mantissa = UINT64_C(100000000000000); ++d->exponent;
        } else { d->mantissa = 0; d->sign = 0; d->exponent = 0; }
        return;
    }
    uint64_t unit = power10((unsigned)(15 - significant));
    d->mantissa = ((d->mantissa + unit / 2) / unit) * unit;
    if (d->mantissa >= UINT64_C(1000000000000000)) {
        /* CC90 retries overflow beyond exponent99 by truncating the original
         * record at the requested precision, rather than carrying to100. */
        if (d->exponent == 99) {
            *d = original; d->mantissa = (d->mantissa / unit) * unit; return;
        }
        d->mantissa /= 10; ++d->exponent;
    }
}
static void scientific_exponent(writer *w, int exponent) {
    byte(w, 0x90); byte(w, exponent < 0 ? 0x92 : 0x91);
    unsigned value = (unsigned)(exponent < 0 ? -exponent : exponent);
    unsigned digits[4], count = 0;
    do { digits[count++] = value % 10; value /= 10; } while (value);
    while (count) byte(w, 0xa0 + digits[--count]);
}
static void emit_decimal(writer *w, fx_decimal d, const fx_format_options *o) {
    int scientific = o->display_mode == 9;
    int significant = scientific ? (o->digits ? o->digits : 10) : 10;
    /* C060 clears contexts4..6 only after exact serialization declines the
     * record. They retain grouping for exact coefficients and use the full
     * decimal width for numeric fallback (C154..C15C). */
    int compact_scientific = o->format_context && o->format_context < 4 &&
                             !scientific && o->display_mode != 8 &&
                             (d.exponent < -9 || d.exponent > 9);
    if (compact_scientific) significant = 9;
    if (o->display_mode == 8) {
        significant = d.exponent + 1 + o->digits;
        if (significant > 10) significant = 10;
    }
    round_digits(&d, significant);
    if (!scientific && (d.exponent >= 10 ||
        (o->display_mode != 8 && d.exponent < (o->display_mode == 4 ? -9 : -2))))
        scientific = 1;
    unsigned char digits[15]; mantissa_digits(d.mantissa, digits);
    if (d.mantissa && d.sign < 0) byte(w, 0x60);
    unsigned point = o->decimal_dot ? '.' : ',';
    if (scientific) {
        byte(w, '0' + digits[0]);
        int count = o->display_mode == 9 ? (o->digits ? o->digits : 10) : compact_scientific ? 9 : 10;
        if (o->display_mode != 9) while (count > 1 && !digits[count - 1]) --count;
        if (count > 1) {
            byte(w, point);
            for (int i = 1; i < count; ++i) byte(w, '0' + digits[i]);
        }
        scientific_exponent(w, d.exponent);
        return;
    }
    int places = o->display_mode == 8 ? o->digits : -1;
    int last = 9;
    if (places >= 0) {
        last = d.exponent + places;
        if (last > 9) last = 9;
    } else {
        /* B99C bounds the fixed-point output to eleven decimal places.
         * Its preceding rounding still uses ten significant digits. */
        if (d.exponent < -2 && last > 11 + d.exponent) last = 11 + d.exponent;
        while (last > 0 && !digits[last]) --last;
    }
    if (d.exponent < 0) {
        byte(w, '0');
        if (places != 0) {
            byte(w, point);
            int zeros = -d.exponent - 1;
            if (places >= 0 && zeros > places) zeros = places;
            for (int i = 0; i < zeros; ++i) byte(w, '0');
            int count = places < 0 ? last + 1 : places + d.exponent + 1;
            for (int i = 0; i < count; ++i) byte(w, '0' + (i < 15 ? digits[i] : 0));
        }
        return;
    }
    for (int i = 0; i <= d.exponent; ++i) byte(w, '0' + (i < 15 ? digits[i] : 0));
    if (last > d.exponent || (places >= 0 && d.exponent < 10)) {
        byte(w, point);
        for (int i = d.exponent + 1; i <= last; ++i) byte(w, '0' + digits[i]);
    }
}
static fx_format_status emit_engineering(writer *w, fx_decimal d,
                                          const fx_format_options *o, fx_format_result *result) {
    /* Fix handles an original zero before the ENG exponent adjustment. */
    if (!d.mantissa && o->display_mode == 8) {
        emit_decimal(w, d, o); return FX_FORMAT_OK;
    }
    int scientific = o->display_mode == 9;
    int significant = scientific ? (o->digits ? o->digits : 10) : 10;
    if (o->display_mode == 8) {
        significant = d.exponent + 1 + o->digits;
        if (significant > 10) significant = 10;
    }
    if (o->format_context && o->format_context < 4 &&
        ((o->display_mode == 8 && d.exponent > 9) ||
         (o->display_mode != 8 && (!scientific || significant == 10) &&
          (d.exponent < -9 || d.exponent > 9)))) {
        scientific = 1; significant = 9;
    }
    round_digits(&d, significant);
    int selection = o->selection & 15, previous = o->selection >> 4;
    int exponent = d.exponent, engineering_exponent;
    int remainder = exponent % 3;
    if (remainder < 0) remainder += 3;
    if (!d.mantissa) { selection = 6; engineering_exponent = 0; }
    else if (selection <= 5) {
        if (!remainder && previous == 6 && selection == 5) --selection;
        engineering_exponent = exponent - remainder + 3 * (selection - 5);
        if (engineering_exponent < -99 || exponent - engineering_exponent >= 10) {
            ++selection; engineering_exponent += 3;
        }
    } else {
        if (!remainder && previous == 5 && selection == 6) ++selection;
        engineering_exponent = exponent + (remainder ? 3 - remainder : 0) + 3 * (selection - 6);
        if (engineering_exponent > 99 || engineering_exponent - exponent >= 10) {
            --selection; engineering_exponent -= 3;
        }
    }
    int relative_exponent = d.mantissa ? exponent - engineering_exponent : 0;
    unsigned char digits[15]; mantissa_digits(d.mantissa, digits);
    int count;
    if (!scientific && o->display_mode != 8)
        count = relative_exponent < 0 ? 10 + relative_exponent : 11;
    else {
        /* 10DCA preserves the integer positions and limits the fractional
         * positions to the ten-column display budget before zero trimming. */
        count = scientific ? significant : 10;
        if (relative_exponent < 0) {
            count += 1 - relative_exponent;
            if (count > relative_exponent + 10) count = relative_exponent + 10;
        } else if (count <= relative_exponent) count = relative_exponent + 1;
        if (count > 11) count = 11;
    }
    int last = count - 1;
    while (last > (relative_exponent > 0 ? relative_exponent : 0) && !digits[last]) --last;
    if (d.mantissa && d.sign < 0) byte(w, 0x60);
    if (relative_exponent < 0) {
        byte(w, '0'); byte(w, o->decimal_dot ? '.' : ',');
        for (int i = 0; i < -relative_exponent - 1; ++i) byte(w, '0');
        for (int i = 0; i <= last; ++i) byte(w, '0' + digits[i]);
    } else {
        for (int i = 0; i <= relative_exponent; ++i) byte(w, '0' + digits[i]);
        if (last > relative_exponent) {
            byte(w, o->decimal_dot ? '.' : ',');
            for (int i = relative_exponent + 1; i <= last; ++i) byte(w, '0' + digits[i]);
        }
    }
    /* 3374 writes the quotient and remainder of a division by ten.  ENG
     * adjustment can leave an exponent above99, where the quotient is still
     * one token (A0+10 for102), rather than a three-digit exponent. */
    unsigned magnitude = (unsigned)(engineering_exponent < 0 ?
                                   -engineering_exponent : engineering_exponent);
    byte(w, 0x90); byte(w, engineering_exponent < 0 ? 0x92 : 0x91);
    if (magnitude / 10) byte(w, 0xa0 + magnitude / 10);
    byte(w, 0xa0 + magnitude % 10);
    result->kind = (uint8_t)selection;
    return FX_FORMAT_OK;
}
static fx_numeric_status split_positive(fx_number *fraction, uint64_t *whole,
                                        const fx_number *number) {
    fx_decimal d;
    if (fx_decimal_decode(&d, number) != FX_NUMERIC_OK || d.exponent > 14)
        return FX_NUMERIC_INVALID;
    *whole = d.exponent < 0 ? 0 : d.mantissa / power10((unsigned)(14 - d.exponent));
    fx_number integral;
    if (fx_decimal_from_integer(&integral, (int64_t)*whole) != FX_NUMERIC_OK)
        return FX_NUMERIC_INVALID;
    return fx_decimal_binary(fraction, number, &integral, FX_SUBTRACT);
}
static fx_format_status emit_sexagesimal(writer *w, const fx_number *number,
                                         const fx_format_options *o, fx_format_result *r) {
    fx_number absolute, fraction, minute_value, minute_fraction, second_value, scaled;
    fx_decimal d;
    if (fx_number_to_decimal(&absolute, number) != FX_NUMERIC_OK ||
        fx_decimal_decode(&d, &absolute) != FX_NUMERIC_OK) return FX_FORMAT_UNIMPLEMENTED;
    int negative = d.sign < 0, exponent = d.exponent;
    d.sign = d.mantissa ? 1 : 0; d.flags = 0;
    if (exponent >= 7) {
        d.sign = negative ? -1 : d.sign; r->kind = 10; emit_decimal(w, d, o); return FX_FORMAT_OK;
    }
    if (fx_decimal_encode(&absolute, &d) != FX_NUMERIC_OK) return FX_FORMAT_INVALID;
    uint64_t degrees, minutes, hundredths;
    if (split_positive(&fraction, &degrees, &absolute) != FX_NUMERIC_OK) return FX_FORMAT_INVALID;
    int degree_gap = exponent - fx_number_exponent(&fraction);
    fx_number sixty, hundred;
    fx_decimal_from_integer(&sixty, 60); fx_decimal_from_integer(&hundred, 100);
    if (fx_decimal_binary(&minute_value, &fraction, &sixty, FX_MULTIPLY) != FX_NUMERIC_OK ||
        fx_decimal_integer_cleanup(&minute_value) != FX_NUMERIC_OK) return FX_FORMAT_INVALID;
    int minute_exponent = fx_number_exponent(&minute_value);
    if (split_positive(&minute_fraction, &minutes, &minute_value) != FX_NUMERIC_OK)
        return FX_FORMAT_INVALID;
    int minute_gap = minute_exponent - fx_number_exponent(&minute_fraction);
    if (fx_decimal_binary(&second_value, &minute_fraction, &sixty, FX_MULTIPLY) != FX_NUMERIC_OK ||
        fx_decimal_integer_cleanup(&second_value) != FX_NUMERIC_OK ||
        fx_decimal_decode(&d, &second_value) != FX_NUMERIC_OK) return FX_FORMAT_INVALID;
    round_digits(&d, (uint8_t)(14 - degree_gap - minute_gap));
    if (fx_decimal_encode(&second_value, &d) != FX_NUMERIC_OK ||
        fx_decimal_binary(&scaled, &second_value, &hundred, FX_MULTIPLY) != FX_NUMERIC_OK ||
        fx_decimal_decode(&d, &scaled) != FX_NUMERIC_OK) return FX_FORMAT_INVALID;
    round_digits(&d, d.exponent + 1);
    if (fx_decimal_encode(&scaled, &d) != FX_NUMERIC_OK ||
        split_positive(&fraction, &hundredths, &scaled) != FX_NUMERIC_OK) return FX_FORMAT_INVALID;
    if (hundredths >= 6000) {
        hundredths -= 6000; ++minutes;
        if (minutes >= 60) { minutes -= 60; ++degrees; }
    }
    if (degrees >= 10000000) {
        fx_decimal_decode(&d, &absolute); d.sign = negative ? -1 : d.sign;
        r->kind = 10; emit_decimal(w, d, o); return FX_FORMAT_OK;
    }
    if (negative && (degrees || minutes || hundredths)) byte(w, 0x60);
    integer(w, degrees); byte(w, 0x85); integer(w, minutes); byte(w, '\'');
    integer(w, hundredths / 100);
    unsigned places = degrees >= 100000 ? 0 : degrees >= 10000 ? 1 : 2;
    /* The original writer always retains at least one significant second
     * digit, including fractional seconds at the widest degree magnitudes. */
    unsigned minimum = hundredths && hundredths < 10 ? 2 : hundredths && hundredths < 100 ? 1 : 0;
    if (places < minimum) places = minimum;
    unsigned fraction_digits = (unsigned)(hundredths % 100);
    if (places == 1) fraction_digits = fraction_digits / 10 * 10;
    if (places && fraction_digits) {
        byte(w, o->decimal_dot ? '.' : ','); byte(w, '0' + fraction_digits / 10);
        if (places == 2 && fraction_digits % 10) byte(w, '0' + fraction_digits % 10);
    }
    byte(w, '"'); r->kind = 1; return FX_FORMAT_OK;
}
static void fraction_begin(writer *w) { byte(w, 0xae); byte(w, 0xbb); byte(w, 0xb8); }
static void fraction_middle(writer *w) { byte(w, 0xb9); byte(w, 0xb8); }
static void fraction_end(writer *w) { byte(w, 0xb9); byte(w, 0xbc); }
static void emit_rational(writer *w, fx_rational r, const fx_format_options *o,
                          fx_format_result *result, int pi) {
    uint64_t n = magnitude(r.numerator), d = r.denominator;
    uint64_t common = gcd(n, d); n /= common; d /= common;
    if (r.numerator < 0) byte(w, 0x60);
    if (d == 1) {
        if (!pi || n != 1) integer(w, n);
        result->kind = pi ? 13 : 10;
    } else {
        uint64_t whole = n / d, remainder = n % d;
        unsigned selection = o->selection & 15;
        int mixed = selection == 12 ||
            ((selection == 0 || selection == 13) && o->mixed_fraction);
        if (mixed && whole) {
            if (o->math_output) {
                byte(w, 0x7c); byte(w, 0xbd); byte(w, 0xbb); byte(w, 0xb8);
                integer(w, whole); fraction_middle(w); integer(w, remainder);
                fraction_middle(w); integer(w, d); fraction_end(w);
            } else {
                integer(w, whole); byte(w, 0x93); integer(w, remainder);
                byte(w, 0x93); integer(w, d);
            }
            result->kind = pi ? 13 : 12;
        } else {
            if (o->math_output) fraction_begin(w);
            integer(w, n);
            if (o->math_output) fraction_middle(w); else byte(w, 0x93);
            integer(w, d);
            if (o->math_output) fraction_end(w);
            result->kind = pi ? 13 : 11;
        }
    }
    if (pi) byte(w, 0x82);
}
/* Long division is bounded by the original 100-byte result buffer. A period
 * is identified by a repeated remainder; finite decimals use ordinary output.
 * A4/B8/B9 delimit the recurring segment for the textbook renderer. */
static int emit_recurring(writer *w, fx_rational r, const fx_format_options *o,
                          fx_format_result *result) {
    uint64_t n = magnitude(r.numerator), denominator = r.denominator;
    uint64_t whole = n / denominator, remainder = n % denominator;
    if (!remainder) return 0;
    unsigned prefix_length = digit_count(whole) + 1 + (r.numerator < 0);
    if (prefix_length >= 97) return 0;
    unsigned limit = 100 - prefix_length - 3;
    uint64_t states[100]; unsigned char digits[100]; unsigned count = 0, start = 0;
    int repeated = 0;
    while (count < limit && remainder) {
        for (start = 0; start < count; ++start)
            if (states[start] == remainder) { repeated = 1; break; }
        if (repeated) break;
        states[count] = remainder;
        wide expanded = (wide)remainder * 10;
        digits[count++] = (unsigned char)(expanded / denominator);
        remainder = (uint64_t)(expanded % denominator);
    }
    if (!repeated) return 0;
    if (r.numerator < 0) byte(w, 0x60);
    integer(w, whole); byte(w, o->decimal_dot ? '.' : ',');
    for (unsigned i = 0; i < start; ++i) byte(w, '0' + digits[i]);
    byte(w, 0xa4); byte(w, 0xb8);
    for (unsigned i = start; i < count; ++i) byte(w, '0' + digits[i]);
    byte(w, 0xb9); result->kind = 14; return 1;
}
/* 13C66 tries the 168 primes through997 using finite decimal division. An
 * unfactored remainder is enclosed in parentheses by7EE0, even when prime.
 * The finite quotient is essential for large records: replacing it with
 * arbitrary-precision integer division changes the original factorization. */
static fx_format_status emit_prime_factors(writer *w, const fx_number *number,
                                           const fx_format_options *o,
                                           fx_format_result *result) {
    fx_decimal value;
    if (fx_decimal_decode(&value, number) != FX_NUMERIC_OK || value.flags)
        return FX_FORMAT_UNIMPLEMENTED;
    fx_number remaining = *number;
    result->kind = 15;
    int emitted = 0;
    for (unsigned candidate = 2; candidate <= 997; ++candidate) {
        int prime = 1;
        for (unsigned d = 2; d * d <= candidate; ++d)
            if (candidate % d == 0) { prime = 0; break; }
        if (!prime) continue;
        fx_number divisor, remainder, quotient;
        (void)fx_decimal_from_integer(&divisor, candidate);
        unsigned exponent = 0; int quotient_zero;
        do {
            if (fx_number_divmod(&remainder, &quotient, &remaining, &divisor) != FX_NUMERIC_OK)
                return FX_FORMAT_UNIMPLEMENTED;
            quotient_zero = !quotient.bytes[0];
            if (remainder.bytes[0]) break;
            exponent = (exponent + 1) & 255;
            remaining = quotient;
        } while (!quotient_zero);
        if (exponent) {
            if (emitted) byte(w, '$');
            integer(w, candidate);
            if (exponent > 1) {
                byte(w, '^'); byte(w, 0xb8); integer(w, exponent); byte(w, 0xb9);
            }
            emitted = 1;
        }
        if (quotient_zero) return FX_FORMAT_OK;
    }
    if (emitted) byte(w, '$');
    byte(w, '(');
    if (fx_decimal_decode(&value, &remaining) != FX_NUMERIC_OK) return FX_FORMAT_INVALID;
    fx_format_options normal = fx_format_default_options();
    normal.selection = 10; normal.decimal_dot = o->decimal_dot;
    emit_decimal(w, value, &normal); byte(w, ')');
    return FX_FORMAT_OK;
}
static void emit_surd_term(writer *w, int64_t coefficient, uint64_t radicand,
                           int subsequent) {
    if (subsequent) byte(w, coefficient < 0 ? '-' : '+');
    else if (coefficient < 0) byte(w, 0x60);
    uint64_t c = magnitude(coefficient);
    if (radicand == 1 || c != 1) integer(w, c);
    if (radicand != 1) {
        byte(w, 0x98); byte(w, 0xb8); integer(w, radicand); byte(w, 0xb9);
    }
}
static int surd_exact_zero(const fx_number *number) {
    fx_number parts[6]; int64_t values[6];
    if (fx_surd_unpack(parts, number) != FX_NUMERIC_OK) return 0;
    for (unsigned i = 0; i < 6; ++i)
        if (fx_decimal_to_integer(&values[i], &parts[i]) != FX_NUMERIC_OK) return 0;
    if (values[1] <= 0 || values[4] <= 0 || values[2] <= 0 || values[5] <= 0 ||
        (values[0] < 0) == (values[3] < 0)) return 0;
    wide a = (wide)magnitude(values[0]) * (uint64_t)values[5];
    wide b = (wide)magnitude(values[3]) * (uint64_t)values[2];
    return a * a * (uint64_t)values[1] == b * b * (uint64_t)values[4];
}
static fx_format_status emit_surd(writer *w, const fx_number *number,
                                 const fx_format_options *o, fx_format_result *r) {
    if (!o->math_output || (o->selection & 15) != 13) return FX_FORMAT_UNIMPLEMENTED;
    fx_number parts[6]; int64_t v[6];
    if (fx_surd_unpack(parts, number) != FX_NUMERIC_OK) return FX_FORMAT_INVALID;
    for (unsigned i = 0; i < 6; ++i)
        if (fx_decimal_to_integer(&v[i], &parts[i]) != FX_NUMERIC_OK) return FX_FORMAT_UNIMPLEMENTED;
    if (v[2] <= 0 || v[5] <= 0) return FX_FORMAT_INVALID;
    uint64_t d1 = (uint64_t)v[2], d2 = (uint64_t)v[5];
    uint64_t d = d1 / gcd(d1, d2) * d2;
    int64_t a = v[3] * (int64_t)(d / d2), c = v[0] * (int64_t)(d / d1);
    uint64_t radicand_a = (uint64_t)v[4], radicand_c = (uint64_t)v[1];
    /* The common-denominator expander18176 places the rational term before
     * a radical. Two radical terms retain the compact record's reverse order. */
    if (radicand_c == 1 && radicand_a != 1) {
        int64_t coefficient = a; a = c; c = coefficient;
        uint64_t radicand = radicand_a; radicand_a = radicand_c; radicand_c = radicand;
    }
    uint64_t reduce = gcd(gcd(magnitude(a), magnitude(c)), d);
    a /= (int64_t)reduce; c /= (int64_t)reduce; d /= reduce;
    int factor_negative = (a < 0 && (!c || (c < 0 && (d != 1 || o->format_context)))) ||
                          (!a && c < 0);
    if (factor_negative) { byte(w, 0x60); a = -a; c = -c; }
    int parentheses = d == 1 && a && c && o->format_context;
    if (d != 1) fraction_begin(w);
    if (parentheses) byte(w, '(');
    if (a) emit_surd_term(w, a, radicand_a, 0);
    if (c) emit_surd_term(w, c, radicand_c, !!a);
    if (!a && !c) byte(w, '0');
    if (parentheses) byte(w, ')');
    if (d != 1) { fraction_middle(w); integer(w, d); fraction_end(w); }
    r->kind = 13; return FX_FORMAT_OK;
}
fx_format_options fx_format_default_options(void) {
    fx_format_options o = {13, 1, 0, 0, 0, 0, 0, 0}; return o;
}
static fx_format_status result_status(writer *w, fx_format_result *r,
                                      fx_format_status status) {
    finish(w); r->length = w->length;
    if (status == FX_FORMAT_OK && w->length >= w->capacity) return FX_FORMAT_BUFFER_TOO_SMALL;
    return status;
}
/* If exact output declines a record, C060 restores a preceding DMS or ENG
 * selection from8100's high nibble before formatting the numeric value. */
static fx_format_status numeric_fallback(const fx_number *number,
                                        const fx_format_options *options,
                                        uint8_t *tokens, size_t capacity,
                                        fx_format_result *result) {
    unsigned selection = options->selection & 15, previous = options->selection >> 4;
    if (selection > 10 && previous == 1) {
        writer w = {tokens, capacity, 0};
        return result_status(&w, result, emit_sexagesimal(&w, number, options, result));
    }
    fx_format_options resolved = *options;
    if (selection > 10 && previous >= 2 && previous <= 9)
        resolved.selection = (uint8_t)((options->selection & 0xf0) | previous);
    return fx_format_decimal(number, &resolved, tokens, capacity, result);
}
fx_format_status fx_format_decimal(const fx_number *number,
                                   const fx_format_options *options,
                                   uint8_t *tokens, size_t capacity,
                                   fx_format_result *result) {
    if (!number || !options || !result || (!tokens && capacity)) return FX_FORMAT_INVALID;
    writer w = {tokens, capacity, 0}; memset(result, 0, sizeof(*result));
    unsigned selection = options->selection & 15;
    result->kind = selection >= 2 && selection <= 10 ? (uint8_t)selection : 10;
    fx_decimal d;
    if (options->format_context > 6 || options->display_mode > 9 || options->digits > 9)
        return result_status(&w, result, FX_FORMAT_UNIMPLEMENTED);
    if (fx_decimal_decode(&d, number) != FX_NUMERIC_OK)
        return result_status(&w, result, FX_FORMAT_INVALID);
    if (selection >= 2 && selection <= 9)
        return result_status(&w, result, emit_engineering(&w, d, options, result));
    emit_decimal(&w, d, options); return result_status(&w, result, FX_FORMAT_OK);
}
fx_format_status fx_format_number(const fx_number *number,
                                  const fx_format_options *options,
                                  uint8_t *tokens, size_t capacity,
                                  fx_format_result *result) {
    if (!number || !options || !result || (!tokens && capacity)) return FX_FORMAT_INVALID;
    writer w = {tokens, capacity, 0}; memset(result, 0, sizeof(*result));
    unsigned selection = options->selection & 15, previous = options->selection >> 4;
    if (selection == 1 ||
        ((selection == 0 || (selection == 13 && !previous)) && (number->bytes[0] & 0xf0) == 0x40))
        return result_status(&w, result, emit_sexagesimal(&w, number, options, result));
    if (selection == 15)
        return result_status(&w, result, emit_prime_factors(&w, number, options, result));
    if (selection >= 2 && selection <= 10) {
        fx_number decimal;
        if (fx_number_to_decimal(&decimal, number) != FX_NUMERIC_OK)
            return result_status(&w, result, FX_FORMAT_UNIMPLEMENTED);
        return fx_format_decimal(&decimal, options, tokens, capacity, result);
    }
    switch (fx_number_kind(number)) {
    case FX_NUMBER_DECIMAL: {
        fx_rational rational;
        if (selection > 10 && recognize_rational(number, &rational)) {
            result->recognized = 1;
            if (selection == 14) {
                if (emit_recurring(&w, rational, options, result))
                    return result_status(&w, result, FX_FORMAT_OK);
                return numeric_fallback(number, options, tokens, capacity, result);
            }
            if (rational.denominator == 1)
                return numeric_fallback(number, options, tokens, capacity, result);
            emit_rational(&w, rational, options, result, 0);
            return result_status(&w, result, FX_FORMAT_OK);
        }
        if (selection >= 13 && (options->math_output || selection == 14) &&
            recognize_pi(number, &rational)) {
            result->recognized = 2;
            fx_format_options resolved = *options; resolved.math_output = 1;
            emit_rational(&w, rational, &resolved, result, 1);
            return result_status(&w, result, FX_FORMAT_OK);
        }
        return numeric_fallback(number, options, tokens, capacity, result);
    }
    case FX_NUMBER_RATIONAL: {
        fx_rational r;
        if (selection == 10) {
            fx_number decimal;
            if (fx_number_to_decimal(&decimal, number) != FX_NUMERIC_OK)
                return result_status(&w, result, FX_FORMAT_UNIMPLEMENTED);
            return fx_format_decimal(&decimal, options, tokens, capacity, result);
        }
        if (fx_rational_decode(&r, number) != FX_NUMERIC_OK) return result_status(&w, result, FX_FORMAT_INVALID);
        if (selection == 14) {
            if (emit_recurring(&w, r, options, result)) return result_status(&w, result, FX_FORMAT_OK);
            fx_number decimal;
            if (fx_number_to_decimal(&decimal, number) != FX_NUMERIC_OK)
                return result_status(&w, result, FX_FORMAT_UNIMPLEMENTED);
            return numeric_fallback(&decimal, options, tokens, capacity, result);
        }
        emit_rational(&w, r, options, result, 0); return result_status(&w, result, FX_FORMAT_OK);
    }
    case FX_NUMBER_SURD:
        if (surd_exact_zero(number)) {
            fx_number zero; fx_number_zero(&zero);
            return numeric_fallback(&zero, options, tokens, capacity, result);
        }
        if (!options->math_output || selection != 13) {
            fx_number decimal;
            if (fx_number_to_decimal(&decimal, number) != FX_NUMERIC_OK)
                return result_status(&w, result, FX_FORMAT_UNIMPLEMENTED);
            return numeric_fallback(&decimal, options, tokens, capacity, result);
        }
        return result_status(&w, result, emit_surd(&w, number, options, result));
    case FX_NUMBER_ERROR: return result_status(&w, result, FX_FORMAT_UNIMPLEMENTED);
    default: return result_status(&w, result, FX_FORMAT_INVALID);
    }
}
