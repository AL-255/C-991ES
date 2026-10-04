/* High-level implementation of firmware numeric storage. GPL-3.0-or-later. */
#include "fx_numeric.h"
#include <ctype.h>
#include <limits.h>
#include <string.h>

static unsigned bcd(unsigned n) { return (n / 10u) * 16u + n % 10u; }
static unsigned unbcd(unsigned n) { return (n >> 4) * 10u + (n & 15u); }
static int valid_bcd(unsigned n) { return (n >> 4) <= 9 && (n & 15) <= 9; }
static uint64_t power10(unsigned n) {
    uint64_t p = 1;
    while (n--) p *= 10;
    return p;
}
static uint64_t gcd64(uint64_t a, uint64_t b) {
    while (b) { uint64_t t = a % b; a = b; b = t; }
    return a;
}
static uint64_t abs64(int64_t n) {
    return n < 0 ? (uint64_t)(-(n + 1)) + 1 : (uint64_t)n;
}

fx_number_type fx_number_kind(const fx_number *n) {
    switch (n->bytes[0] >> 4) {
    case 0: case 4: return FX_NUMBER_DECIMAL;
    case 2: case 6: return FX_NUMBER_RATIONAL;
    case 8: return FX_NUMBER_SURD;
    case 15: return FX_NUMBER_ERROR;
    default: return FX_NUMBER_UNSUPPORTED;
    }
}
int fx_number_has_special_marker(const fx_number *n) {
    return (n->bytes[0] & 15) >= 10 || (n->bytes[9] & 0xf0) != 0;
}
void fx_number_zero(fx_number *out) { memset(out, 0, sizeof *out); }
void fx_number_error(fx_number *out, unsigned code) {
    fx_number_zero(out); out->bytes[0] = (uint8_t)(0xf0 | (code & 15));
}
void fx_number_copy(fx_number *out, const fx_number *in) { memmove(out, in, sizeof *out); }
void fx_number_copy_complex(fx_number out[2], const fx_number in[2]) {
    memmove(out, in, 2 * sizeof *out);
}

fx_numeric_status fx_decimal_decode(fx_decimal *out, const fx_number *in) {
    unsigned i, sign = in->bytes[9];
    uint64_t mantissa = in->bytes[0] & 15;
    if (fx_number_kind(in) != FX_NUMBER_DECIMAL || mantissa > 9 ||
        !valid_bcd(in->bytes[8]) || (sign != 0 && sign != 1 && sign != 5 && sign != 6))
        return FX_NUMERIC_INVALID;
    for (i = 1; i < 8; ++i) {
        if (!valid_bcd(in->bytes[i])) return FX_NUMERIC_INVALID;
        mantissa = mantissa * 100 + unbcd(in->bytes[i]);
    }
    out->mantissa = mantissa;
    out->sign = mantissa == 0 ? 0 : sign >= 5 ? -1 : 1;
    out->exponent = (int)unbcd(in->bytes[8]);
    if (sign == 0 || sign == 5) out->exponent -= 100;
    if (mantissa == 0) out->exponent = 0;
    out->flags = in->bytes[0] & 0x40;
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_decimal_encode(fx_number *out, const fx_decimal *in) {
    uint64_t mantissa = in->mantissa;
    int exponent = in->exponent, i;
    fx_number value;
    fx_number_zero(&value);
    if (!mantissa || !in->sign) { value.bytes[0] = in->flags & 0x40; *out = value; return FX_NUMERIC_OK; }
    if (mantissa < UINT64_C(100000000000000) || mantissa >= UINT64_C(1000000000000000))
        return FX_NUMERIC_INVALID;
    if (exponent < -99) { *out = value; return FX_NUMERIC_OK; }
    if (exponent > 99) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
    for (i = 7; i >= 1; --i) {
        value.bytes[i] = (uint8_t)bcd((unsigned)(mantissa % 100)); mantissa /= 100;
    }
    value.bytes[0] = (uint8_t)(mantissa | (in->flags & 0x40));
    value.bytes[8] = (uint8_t)bcd((unsigned)(exponent < 0 ? exponent + 100 : exponent));
    value.bytes[9] = (uint8_t)((exponent < 0 ? 0 : 1) + (in->sign < 0 ? 5 : 0));
    *out = value;
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_decimal_parse(fx_number *out, const char *text) {
    fx_decimal d = {1, 0, 0, 0};
    int point = 0, seen = 0, before = 0, leading = 0, captured = 0, explicit_exp = 0;
    const unsigned char *s = (const unsigned char *)text;
    if (*s == '+' || *s == '-') { if (*s == '-') d.sign = -1; ++s; }
    while (*s) {
        if (*s == '.' && !point) { point = 1; ++s; continue; }
        if (!isdigit(*s)) break;
        seen = 1;
        if (!point) ++before;
        if (*s == '0' && captured == 0) ++leading;
        else if (captured < 15) { d.mantissa = d.mantissa * 10 + (*s - '0'); ++captured; }
        ++s;
    }
    if (*s == 'e' || *s == 'E') {
        int esign = 1;
        ++s;
        if (*s == '+' || *s == '-') { if (*s == '-') esign = -1; ++s; }
        if (!isdigit(*s)) return FX_NUMERIC_INVALID;
        while (isdigit(*s)) { if (explicit_exp < 10000) explicit_exp = explicit_exp * 10 + (*s - '0'); ++s; }
        explicit_exp *= esign;
    }
    if (*s || !seen) return FX_NUMERIC_INVALID;
    if (!captured) { fx_number_zero(out); return FX_NUMERIC_OK; }
    d.exponent = before - leading - 1 + explicit_exp;
    while (captured++ < 15) d.mantissa *= 10;
    return fx_decimal_encode(out, &d);
}
fx_numeric_status fx_decimal_from_integer(fx_number *out, int64_t value) {
    fx_decimal d = {value < 0 ? -1 : 1, 0, abs64(value), 0};
    uint64_t work = d.mantissa;
    if (!work) { fx_number_zero(out); return FX_NUMERIC_OK; }
    while (work >= 10) { work /= 10; ++d.exponent; }
    if (d.exponent > 14) d.mantissa /= power10((unsigned)(d.exponent - 14));
    else d.mantissa *= power10((unsigned)(14 - d.exponent));
    return fx_decimal_encode(out, &d);
}
void fx_decimal_from_u8(fx_number *out, uint8_t value) { (void)fx_decimal_from_integer(out, value); }
fx_numeric_status fx_decimal_to_integer(int64_t *out, const fx_number *in) {
    fx_decimal d;
    uint64_t n, scale;
    if (fx_decimal_decode(&d, in) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    if (d.sign == 0) { *out = 0; return FX_NUMERIC_OK; }
    if (d.exponent < 0 || d.exponent > 18) return FX_NUMERIC_UNREPRESENTABLE;
    n = d.mantissa;
    if (d.exponent < 14) {
        scale = power10((unsigned)(14 - d.exponent));
        if (n % scale) return FX_NUMERIC_UNREPRESENTABLE;
        n /= scale;
    } else {
        scale = power10((unsigned)(d.exponent - 14));
        if (n > (uint64_t)INT64_MAX / scale) return FX_NUMERIC_UNREPRESENTABLE;
        n *= scale;
    }
    if (n > (uint64_t)INT64_MAX) return FX_NUMERIC_UNREPRESENTABLE;
    *out = d.sign < 0 ? -(int64_t)n : (int64_t)n;
    return FX_NUMERIC_OK;
}
int fx_number_exponent(const fx_number *in) {
    unsigned e = unbcd(in->bytes[8]);
    if (in->bytes[0] >= 0x0a) return 0x5000;
    /* The original routine tests the complete field, including metadata. */
    return in->bytes[9] == 1 || in->bytes[9] == 6 ? (int)e : e ? (int)e - 100 : 0;
}

static unsigned get_nibble(const fx_number *n, unsigned i) {
    return i & 1 ? n->bytes[i / 2] & 15 : n->bytes[i / 2] >> 4;
}
static void set_nibble(fx_number *n, unsigned i, unsigned value) {
    if (i & 1) n->bytes[i / 2] = (uint8_t)((n->bytes[i / 2] & 0xf0) | value);
    else n->bytes[i / 2] = (uint8_t)((n->bytes[i / 2] & 15) | (value << 4));
}
fx_numeric_status fx_rational_decode(fx_rational *out, const fx_number *in) {
    uint64_t part[3] = {0, 0, 0};
    unsigned length = unbcd(in->bytes[8]), i, p = 0, sign = in->bytes[9] & 15;
    if (fx_number_kind(in) != FX_NUMBER_RATIONAL || length > 15 || !length ||
        (sign != 1 && sign != 6)) return FX_NUMERIC_INVALID;
    for (i = 1; i <= length; ++i) {
        unsigned v = get_nibble(in, i);
        if (v == 10) { if (++p > 2) return FX_NUMERIC_INVALID; }
        else if (v <= 9) part[p] = part[p] * 10 + v;
        else return FX_NUMERIC_INVALID;
    }
    if (!p || !part[p]) return FX_NUMERIC_INVALID;
    if (p == 2) part[0] = part[0] * part[2] + part[1];
    if (part[0] > (uint64_t)INT64_MAX) return FX_NUMERIC_UNREPRESENTABLE;
    out->numerator = sign == 6 ? -(int64_t)part[0] : (int64_t)part[0];
    out->denominator = part[p]; out->flags = in->bytes[0] & 0x40;
    return FX_NUMERIC_OK;
}
static unsigned decimal_digits(uint64_t n, uint8_t *out) {
    uint8_t reverse[20]; unsigned count = 0, i;
    do { reverse[count++] = (uint8_t)(n % 10); n /= 10; } while (n);
    for (i = 0; i < count; ++i) out[i] = reverse[count - 1 - i];
    return count;
}
fx_numeric_status fx_rational_encode(fx_number *out, const fx_rational *in) {
    uint64_t n = abs64(in->numerator), denominator = in->denominator, common;
    unsigned count = 0, i;
    uint8_t digits[64]; fx_number value;
    if (!denominator) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
    /* 0x1cabe excludes exponents15 onward before rational reduction. */
    if (n >= UINT64_C(1000000000000000) || denominator >= UINT64_C(1000000000000000)) {
        fx_number numerator_value, denominator_value;
        if (denominator > (uint64_t)INT64_MAX) return FX_NUMERIC_UNREPRESENTABLE;
        (void)fx_decimal_from_integer(&numerator_value, in->numerator);
        (void)fx_decimal_from_integer(&denominator_value, (int64_t)denominator);
        fx_numeric_status status = fx_decimal_binary(out, &numerator_value, &denominator_value, FX_DIVIDE);
        if (status != FX_NUMERIC_OK) return status;
        return fx_decimal_integer_cleanup(out);
    }
    common = gcd64(n, denominator); n /= common; denominator /= common;
    if (denominator == 1) {
        int64_t integer = in->numerator < 0 ? -(int64_t)(n-1)-1 : (int64_t)n;
        return fx_decimal_from_integer(out, integer);
    }
    if (n >= denominator) {
        count += decimal_digits(n / denominator, digits + count); digits[count++] = 10;
        count += decimal_digits(n % denominator, digits + count);
    } else count += decimal_digits(n, digits + count);
    digits[count++] = 10; count += decimal_digits(denominator, digits + count);
    if (count > 10) {
        fx_number numerator_value, denominator_value;
        if (denominator > (uint64_t)INT64_MAX) return FX_NUMERIC_UNREPRESENTABLE;
        (void)fx_decimal_from_integer(&numerator_value, in->numerator);
        (void)fx_decimal_from_integer(&denominator_value, (int64_t)in->denominator);
        fx_numeric_status status = fx_decimal_binary(out, &numerator_value, &denominator_value, FX_DIVIDE);
        if (status != FX_NUMERIC_OK) return status;
        return fx_decimal_integer_cleanup(out);
    }
    fx_number_zero(&value); value.bytes[0] = (uint8_t)(0x20 | (in->flags & 0x40));
    for (i = 0; i < count; ++i) set_nibble(&value, i + 1, digits[i]);
    value.bytes[8] = (uint8_t)bcd(count); value.bytes[9] = (uint8_t)(in->numerator < 0 ? 6 : 1);
    *out = value; return FX_NUMERIC_OK;
}

fx_numeric_status fx_surd_unpack(fx_number out[6], const fx_number *in) {
    unsigned term;
    if (fx_number_kind(in) != FX_NUMBER_SURD) return FX_NUMERIC_INVALID;
    for (term = 0; term < 2; ++term) {
        unsigned base = term * 4;
        unsigned coeff = unbcd(in->bytes[base + 2]);
        unsigned rad = (in->bytes[base] & 15) * 100 + unbcd(in->bytes[base + 1]);
        unsigned den = unbcd(in->bytes[base + 3]);
        fx_decimal_from_u8(&out[term * 3], (uint8_t)coeff);
        out[term * 3].bytes[9] = in->bytes[9 - term];
        (void)fx_decimal_from_integer(&out[term * 3 + 1], rad);
        fx_decimal_from_u8(&out[term * 3 + 2], (uint8_t)den);
        if (!rad) out[term * 3 + 1].bytes[9] = 1;
        if (!den) out[term * 3 + 2].bytes[9] = 1;
    }
    /* 0x178ba uses canonical empty-first-term workspace for coefficient zero. */
    if (!in->bytes[2]) {
        fx_number_zero(&out[0]); fx_number_zero(&out[1]); fx_decimal_from_u8(&out[2], 1);
    }
    return FX_NUMERIC_OK;
}
static fx_numeric_status surd_components_to_decimal(fx_number *out, const fx_number components[6]) {
    fx_number terms[2]; unsigned i;
    for (i = 0; i < 2; ++i) {
        fx_decimal coefficient;
        fx_numeric_status status = fx_decimal_decode(&coefficient, &components[i*3]);
        if (status != FX_NUMERIC_OK) return status;
        if (!i && !coefficient.sign) { fx_number_zero(&terms[i]); continue; }
        status = fx_decimal_sqrt(&terms[i], &components[i*3+1]);
        if (status != FX_NUMERIC_OK) return status;
        status = fx_decimal_binary(&terms[i], &terms[i], &components[i*3], FX_MULTIPLY);
        if (status != FX_NUMERIC_OK) return status;
        status = fx_decimal_binary(&terms[i], &terms[i], &components[i*3+2], FX_DIVIDE);
        if (status != FX_NUMERIC_OK) return status;
    }
    return fx_decimal_binary(out, &terms[0], &terms[1], FX_ADD);
}
fx_numeric_status fx_surd_pack(fx_number *out, const fx_number components[6]) {
    int64_t vals[6]; unsigned i; fx_number value;
    for (i = 0; i < 6; ++i) {
        if (fx_decimal_to_integer(&vals[i], &components[i]) != FX_NUMERIC_OK)
            return FX_NUMERIC_UNREPRESENTABLE;
    }
    if (!vals[0] && !vals[3]) { fx_number_zero(out); return FX_NUMERIC_OK; }
    if (!vals[0] && vals[4] == 1 && vals[5] > 0) {
        fx_rational rational = {vals[3], (uint64_t)vals[5], 0};
        return fx_rational_encode(out, &rational);
    }
    for (i = 0; i < 6; ++i) {
        if ((i % 3 == 1 && (vals[i] < 0 || vals[i] > 999)) ||
            (i % 3 == 2 && (vals[i] < 1 || vals[i] > 99)) ||
            (i % 3 == 0 && abs64(vals[i]) > 99)) return surd_components_to_decimal(out, components);
    }
    fx_number_zero(&value);
    for (i = 0; i < 2; ++i) {
        unsigned base = i * 4, c = i * 3;
        value.bytes[base] = (uint8_t)(vals[c + 1] / 100);
        value.bytes[base + 1] = (uint8_t)bcd((unsigned)(vals[c + 1] % 100));
        value.bytes[base + 2] = (uint8_t)bcd((unsigned)abs64(vals[c]));
        value.bytes[base + 3] = (uint8_t)bcd((unsigned)vals[c + 2]);
        value.bytes[9 - i] = components[c].bytes[9];
    }
    if (!vals[0]) { value.bytes[0] = 0; value.bytes[1] = 0; value.bytes[3] = 1; }
    value.bytes[0] |= 0x80; *out = value; return FX_NUMERIC_OK;
}

/* Decimal arithmetic has a sixteen-digit alignment workspace and stores the
 * leading fifteen digits. Multiplication uses schoolbook decimal digits. */
static fx_numeric_status from_digits(fx_number *out, const unsigned char *digits,
                                    unsigned count, int scale, int sign, uint8_t flags) {
    fx_decimal d;
    unsigned i, kept;
    while (count && !digits[count - 1]) --count;
    if (!count) { fx_number_zero(out); return FX_NUMERIC_OK; }
    d.sign = sign; d.exponent = scale + (int)count - 1; d.flags = flags;
    d.mantissa = 0; kept = count < 15 ? count : 15;
    for (i = 0; i < kept; ++i) d.mantissa = d.mantissa * 10 + digits[count - 1 - i];
    for (; kept < 15; ++kept) d.mantissa *= 10;
    return fx_decimal_encode(out, &d);
}
static fx_numeric_status from_scaled_integer(fx_number *out, uint64_t value,
                                             int scale, int sign, uint8_t flags) {
    unsigned char digits[20] = {0}; unsigned count = 0;
    while (value) { digits[count++] = (unsigned char)(value % 10); value /= 10; }
    return from_digits(out, digits, count, scale, sign, flags);
}
static fx_numeric_status binary_plain(fx_number *out, const fx_number *a,
                                     const fx_number *b, fx_binary_op op) {
    fx_decimal x, y;
    uint8_t flags = 0;
    if (fx_number_kind(a) == FX_NUMBER_ERROR) { *out = *a; return FX_NUMERIC_OK; }
    if (fx_number_kind(b) == FX_NUMBER_ERROR) { *out = *b; return FX_NUMERIC_OK; }
    if (fx_decimal_decode(&x, a) != FX_NUMERIC_OK || fx_decimal_decode(&y, b) != FX_NUMERIC_OK)
        return FX_NUMERIC_INVALID;
    if (op == FX_SUBTRACT) y.sign = -y.sign;
    if (op == FX_ADD || op == FX_SUBTRACT) {
        uint64_t xv, yv, magnitude; int gap, sign;
        if (!x.sign) { y.flags = flags; return fx_decimal_encode(out, &y); }
        if (!y.sign) { x.flags = flags; return fx_decimal_encode(out, &x); }
        if (y.exponent > x.exponent) { fx_decimal t = x; x = y; y = t; }
        gap = x.exponent - y.exponent;
        xv = x.mantissa * 10;
        yv = gap > 15 ? 0 : y.mantissa * 10 / power10((unsigned)gap);
        if (x.sign == y.sign) { magnitude = xv + yv; sign = x.sign; }
        else if (xv >= yv) { magnitude = xv - yv; sign = x.sign; }
        else { magnitude = yv - xv; sign = y.sign; }
        return from_scaled_integer(out, magnitude, x.exponent - 15, sign, flags);
    }
    if (op == FX_MULTIPLY) {
        unsigned char xd[15], yd[15], product[31] = {0};
        unsigned i, j; uint64_t xm = x.mantissa, ym = y.mantissa;
        for (i = 0; i < 15; ++i) { xd[i] = (unsigned char)(xm % 10); xm /= 10; yd[i] = (unsigned char)(ym % 10); ym /= 10; }
        for (i = 0; i < 15; ++i) {
            unsigned carry = 0;
            for (j = 0; j < 15; ++j) {
                unsigned v = product[i + j] + xd[i] * yd[j] + carry;
                product[i + j] = (unsigned char)(v % 10); carry = v / 10;
            }
            product[i + 15] = (unsigned char)carry;
        }
        return from_digits(out, product, 30, x.exponent + y.exponent - 28, x.sign * y.sign, flags);
    }
    if (op == FX_DIVIDE) {
        unsigned i; uint64_t rem; fx_decimal result;
        if (!y.sign) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
        if (!x.sign) { fx_number_zero(out); return FX_NUMERIC_OK; }
        result.sign = x.sign * y.sign; result.flags = flags;
        result.exponent = x.exponent - y.exponent; result.mantissa = 0;
        rem = x.mantissa;
        if (rem < y.mantissa) { rem *= 10; --result.exponent; }
        for (i = 0; i < 15; ++i) {
            result.mantissa = result.mantissa * 10 + rem / y.mantissa;
            rem = (rem % y.mantissa) * 10;
        }
        return fx_decimal_encode(out, &result);
    }
    return FX_NUMERIC_INVALID;
}
fx_numeric_status fx_decimal_binary(fx_number *out, const fx_number *a,
                                   const fx_number *b, fx_binary_op op) {
    unsigned markers = (a->bytes[0] & 0x40) + (b->bytes[0] & 0x40);
    fx_numeric_status status = binary_plain(out, a, b, op);
    fx_decimal result;
    if (status == FX_NUMERIC_OK &&
        ((op == FX_ADD || op == FX_SUBTRACT) ? markers == 0x80 : markers == 0x40) &&
        fx_decimal_decode(&result, out) == FX_NUMERIC_OK &&
        (!result.sign || result.exponent < 7)) out->bytes[0] |= 0x40;
    return status;
}

fx_numeric_status fx_decimal_integer_cleanup(fx_number *number) {
    fx_decimal d; uint64_t tail;
    if (fx_number_kind(number) != FX_NUMBER_DECIMAL) return FX_NUMERIC_OK;
    if (fx_decimal_decode(&d, number) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    tail = d.mantissa % 10000;
    if (tail >= 9991) d.mantissa += 10000 - tail;
    else if (tail < 10) d.mantissa -= tail;
    if (d.mantissa >= UINT64_C(1000000000000000)) { d.mantissa /= 10; ++d.exponent; }
    if (d.exponent >= 7) d.flags = 0;
    return fx_decimal_encode(number, &d);
}
int fx_number_fractional_status(const fx_number *number) {
    fx_decimal d;
    if (fx_decimal_decode(&d, number) != FX_NUMERIC_OK || d.flags) return 0xf0;
    if (!d.sign) return 0;
    if (d.exponent < 0 || d.exponent > 14) return 0xf0;
    if (d.exponent >= 14) return 0;
    return d.mantissa % power10((unsigned)(14 - d.exponent)) ? 0xf0 : 0;
}

/* 0x10962 selects the simplest rational in a forty-mantissa-unit interval.
 * The Euclidean interval recursion below is equivalent to that continued
 * fraction search. At exponents-8..-5 the scale10^22 exceeds uint64_t; only
 * its initial reciprocal step needs decimal long division. All later
 * Euclidean remainders fit within the original fifteen-digit mantissa. */
typedef struct { uint64_t numerator, denominator; } recognition_fraction;
static recognition_fraction interval_join(uint64_t integer, recognition_fraction inner) {
    recognition_fraction fail = {0,0}; uint64_t numerator;
    if (!inner.denominator || !inner.numerator ||
        (integer && inner.numerator > UINT64_MAX/integer)) return fail;
    numerator = integer*inner.numerator;
    if (numerator > UINT64_MAX-inner.denominator) return fail;
    recognition_fraction result = {numerator+inner.denominator,inner.numerator};
    return result;
}
static recognition_fraction simplest_interval(uint64_t ln, uint64_t ld,
                                               uint64_t un, uint64_t ud, unsigned depth) {
    recognition_fraction fail = {0,0};
    if (!ld || !ud || depth > 40) return fail;
    uint64_t a = ln/ld, b = un/ud;
    if (ln%ld == 0) { recognition_fraction result = {a,1}; return result; }
    if (a != b) { recognition_fraction result = {a+1,1}; return result; }
    return interval_join(a,simplest_interval(ud,un%ud,ld,ln%ld,depth+1));
}
static void divide_decimal_power(unsigned power, uint64_t divisor,
                                 uint64_t *quotient, uint64_t *remainder) {
    uint64_t q = 0, r = 1;
    while (power--) { r *= 10; q = q*10+r/divisor; r %= divisor; }
    *quotient = q; *remainder = r;
}
static unsigned digits_count(uint64_t n) {
    unsigned count = 1; while (n >= 10) { n /= 10; ++count; } return count;
}
int fx_number_recognize_rational(fx_rational *out, const fx_number *in) {
    fx_decimal d; recognition_fraction fraction;
    if (fx_decimal_decode(&d,in) != FX_NUMERIC_OK || d.flags || !d.sign ||
        d.exponent < -8 || d.exponent > 6) return 0;
    if (d.exponent >= -1) {
        uint64_t unit = power10((unsigned)(14-d.exponent));
        uint64_t tail = d.mantissa%100;
        uint64_t mantissa = d.mantissa-tail+(tail < 50 ? 0 : 99);
        uint64_t remainder = mantissa%unit;
        if (!remainder || remainder+1 == unit) {
            out->numerator = (int64_t)(mantissa/unit+!!remainder)*d.sign;
            out->denominator = 1; out->flags = 0; return 1;
        }
    }
    if (d.exponent == 6) return 0;
    unsigned power = (unsigned)(14-d.exponent);
    uint64_t lower = d.mantissa-40, upper = d.mantissa+40;
    if (power <= 18) {
        uint64_t scale = power10(power);
        fraction = simplest_interval(lower,scale,upper,scale,0);
    } else {
        uint64_t a,ar,b,br;
        divide_decimal_power(power,upper,&a,&ar);
        divide_decimal_power(power,lower,&b,&br);
        recognition_fraction inverse;
        if (!ar) { inverse.numerator = a; inverse.denominator = 1; }
        else if (a != b) { inverse.numerator = a+1; inverse.denominator = 1; }
        else inverse = interval_join(a,simplest_interval(lower,br,upper,ar,1));
        fraction.numerator = inverse.denominator; fraction.denominator = inverse.numerator;
    }
    if (!fraction.denominator || fraction.numerator > (uint64_t)INT64_MAX) return 0;
    uint64_t whole = fraction.numerator/fraction.denominator;
    unsigned numerator_digits = digits_count(fraction.numerator%fraction.denominator);
    unsigned denominator_digits = digits_count(fraction.denominator);
    if (numerator_digits > 8 || denominator_digits > 8 ||
        (whole ? digits_count(whole)+numerator_digits+denominator_digits > 8 :
                 numerator_digits+denominator_digits > 9)) return 0;
    out->numerator = (int64_t)fraction.numerator*d.sign;
    out->denominator = fraction.denominator; out->flags = 0; return 1;
}
fx_numeric_status fx_decimal_sqrt(fx_number *out, const fx_number *in) {
    fx_decimal x, result; unsigned char digits[30] = {0};
    uint64_t mantissa, remainder = 0, root = 0;
    unsigned shift, i;
    if (fx_number_kind(in) == FX_NUMBER_ERROR) { *out = *in; return FX_NUMERIC_OK; }
    if (fx_decimal_decode(&x, in) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
    if (x.sign < 0) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
    if (!x.sign) { fx_number_zero(out); return FX_NUMERIC_OK; }
    result.exponent = x.exponent >= 0 ? x.exponent / 2 : -((-x.exponent + 1) / 2);
    shift = (unsigned)(14 + x.exponent - 2 * result.exponent);
    mantissa = x.mantissa;
    for (i = 0; i < 15; ++i) { digits[shift + i] = (unsigned char)(mantissa % 10); mantissa /= 10; }
    /* The original digit algorithm shifts a combined exponent/mantissa
     * workspace (0x1b718 -> 0x1affe). For an even exponent the first shift
     * restores the divided-by-two half digit and the second injects the low
     * digit of the normalized exponent prefix. Preserve that small bias. */
    if (x.exponent % 2 == 0) {
        unsigned prefix = (unsigned)(((x.exponent + 100) / 20 + 5) % 10);
        digits[12] = (unsigned char)(2 * prefix % 10);
        digits[13] = (unsigned char)(2 * prefix / 10);
    }
    for (i = 15; i > 0; --i) {
        unsigned digit = 9;
        remainder = remainder * 100 + digits[2*i - 1] * 10 + digits[2*i - 2];
        while ((20 * root + digit) * digit > remainder) --digit;
        remainder -= (20 * root + digit) * digit; root = root * 10 + digit;
    }
    result.sign = 1; result.mantissa = root; result.flags = 0;
    return fx_decimal_encode(out, &result);
}
fx_numeric_status fx_number_to_decimal(fx_number *out, const fx_number *in) {
    fx_number a, b;
    fx_rational rational;
    switch (fx_number_kind(in)) {
    case FX_NUMBER_DECIMAL: case FX_NUMBER_ERROR: *out = *in; return FX_NUMERIC_OK;
    case FX_NUMBER_RATIONAL:
        if (fx_rational_decode(&rational, in) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
        if (rational.denominator > (uint64_t)INT64_MAX) return FX_NUMERIC_UNREPRESENTABLE;
        (void)fx_decimal_from_integer(&a, rational.numerator);
        (void)fx_decimal_from_integer(&b, (int64_t)rational.denominator);
        {
            fx_numeric_status status = fx_decimal_binary(out, &a, &b, FX_DIVIDE);
            /* 0x19f1a -> 0x1a06a applies the shared cleanup after rational
             * conversion, including values just below a decimal boundary. */
            if (status == FX_NUMERIC_OK) status = fx_decimal_integer_cleanup(out);
            return status;
        }
    case FX_NUMBER_SURD: {
        fx_number components[6];
        if (fx_surd_unpack(components, in) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
        return surd_components_to_decimal(out, components);
    }
    default: return FX_NUMERIC_UNIMPLEMENTED;
    }
}

/* Bounded exact algebra. A term is numerator * sqrt(radicand) / denominator.
 * The external record admits two terms; wider temporary results either reduce
 * to that representation or follow the original numeric fallback. */
typedef struct { int64_t numerator; uint64_t denominator, radicand; } exact_term;
typedef struct { exact_term terms[8]; unsigned count; } exact_value;

static int mul_signed(int64_t a, int64_t b, int64_t *out) {
    uint64_t aa = abs64(a), bb = abs64(b);
    if (bb && aa > (uint64_t)INT64_MAX / bb) return 0;
    *out = (a < 0) != (b < 0) ? -(int64_t)(aa * bb) : (int64_t)(aa * bb);
    return 1;
}
static int mul_unsigned(uint64_t a, uint64_t b, uint64_t *out) {
    if (b && a > (uint64_t)INT64_MAX / b) return 0;
    *out = a * b; return 1;
}
static void square_factors(uint64_t value, uint64_t *coefficient, uint64_t *radicand) {
    uint64_t p;
    *coefficient = 1; *radicand = value;
    /* 0x17a46 tries 28 wheel candidates, ending at 97. */
    for (p = 2; p <= 97 && p <= *radicand / p; ++p) {
        uint64_t square = p * p;
        while (*radicand % square == 0) { *radicand /= square; *coefficient *= p; }
    }
}
static int normalize_term(exact_term *t) {
    uint64_t square, common;
    int64_t numerator;
    if (!t->denominator) return 0;
    if (!t->numerator || !t->radicand) { t->numerator = 0; t->denominator = 1; t->radicand = 1; return 1; }
    square_factors(t->radicand, &square, &t->radicand);
    if (!mul_signed(t->numerator, (int64_t)square, &numerator)) return 0;
    t->numerator = numerator;
    common = gcd64(abs64(t->numerator), t->denominator);
    t->numerator /= (int64_t)common; t->denominator /= common; return 1;
}
static int append_term(exact_value *value, exact_term t) {
    unsigned i;
    if (!t.denominator) return 0;
    if (!t.numerator || !t.radicand) return 1;
    for (i = 0; i < value->count; ++i) {
        exact_term *existing = &value->terms[i];
        if (existing->radicand == t.radicand) {
            uint64_t common = gcd64(existing->denominator, t.denominator), denominator;
            int64_t a, b, sum;
            if (!mul_unsigned(existing->denominator, t.denominator/common, &denominator) ||
                !mul_signed(existing->numerator, (int64_t)(t.denominator/common), &a) ||
                !mul_signed(t.numerator, (int64_t)(existing->denominator/common), &b)) return 0;
            if ((b > 0 && a > INT64_MAX-b) || (b < 0 && a < INT64_MIN-b)) return 0;
            sum = a + b; existing->numerator = sum; existing->denominator = denominator;
            if (!normalize_term(existing)) return 0;
            if (!existing->numerator) {
                memmove(existing, existing + 1, (value->count - i - 1) * sizeof *existing); --value->count;
            }
            return 1;
        }
    }
    if (value->count == 8) return 0;
    i = value->count++;
    while (i && value->terms[i-1].radicand > t.radicand) {
        value->terms[i] = value->terms[i-1]; --i;
    }
    value->terms[i] = t; return 1;
}
static int extract_exact(exact_value *out, const fx_number *number) {
    fx_number components[6]; exact_term t; unsigned i;
    out->count = 0;
    if (fx_number_kind(number) == FX_NUMBER_SURD) {
        if (fx_surd_unpack(components, number) != FX_NUMERIC_OK) return 0;
        for (i = 0; i < 2; ++i) {
            int64_t rad, den;
            if (fx_decimal_to_integer(&t.numerator, &components[3*i]) != FX_NUMERIC_OK ||
                fx_decimal_to_integer(&rad, &components[3*i+1]) != FX_NUMERIC_OK ||
                fx_decimal_to_integer(&den, &components[3*i+2]) != FX_NUMERIC_OK) return 0;
            if (!t.numerator) continue;
            if (rad < 1 || den < 1) return 0;
            t.radicand = (uint64_t)rad; t.denominator = (uint64_t)den;
            if (!append_term(out, t)) return 0;
        }
        return 1;
    }
    t.radicand = 1;
    if (fx_number_kind(number) == FX_NUMBER_RATIONAL) {
        fx_rational r;
        if (fx_rational_decode(&r, number) != FX_NUMERIC_OK) return 0;
        t.numerator = r.numerator; t.denominator = r.denominator;
    } else {
        fx_decimal d;
        if (fx_decimal_decode(&d, number) != FX_NUMERIC_OK || d.flags ||
            fx_decimal_to_integer(&t.numerator, number) != FX_NUMERIC_OK) return 0;
        t.denominator = 1;
    }
    return append_term(out, t);
}
static int multiply_exact(exact_value *out, const exact_value *a, const exact_value *b) {
    unsigned i, j; out->count = 0;
    for (i = 0; i < a->count; ++i) for (j = 0; j < b->count; ++j) {
        exact_term t = {0, 0, 0};
        uint64_t g1 = gcd64(abs64(a->terms[i].numerator), b->terms[j].denominator);
        uint64_t g2 = gcd64(abs64(b->terms[j].numerator), a->terms[i].denominator);
        if (!mul_signed(a->terms[i].numerator/(int64_t)g1, b->terms[j].numerator/(int64_t)g2, &t.numerator) ||
            !mul_unsigned(a->terms[i].denominator/g2, b->terms[j].denominator/g1, &t.denominator) ||
            !mul_unsigned(a->terms[i].radicand, b->terms[j].radicand, &t.radicand) ||
            !normalize_term(&t) ||
            !append_term(out, t)) return 0;
    }
    return 1;
}
static fx_numeric_status exact_to_decimal(fx_number *out, const exact_value *value) {
    unsigned i; fx_number sum; fx_number_zero(&sum);
    for (i = 0; i < value->count; ++i) {
        fx_number coefficient, radicand, denominator, term;
        if (value->terms[i].radicand > (uint64_t)INT64_MAX || value->terms[i].denominator > (uint64_t)INT64_MAX)
            return FX_NUMERIC_UNREPRESENTABLE;
        (void)fx_decimal_from_integer(&coefficient, value->terms[i].numerator);
        (void)fx_decimal_from_integer(&radicand, (int64_t)value->terms[i].radicand);
        (void)fx_decimal_from_integer(&denominator, (int64_t)value->terms[i].denominator);
        (void)fx_decimal_sqrt(&term, &radicand);
        (void)fx_decimal_binary(&term, &term, &coefficient, FX_MULTIPLY);
        (void)fx_decimal_binary(&term, &term, &denominator, FX_DIVIDE);
        (void)fx_decimal_binary(&sum, &sum, &term, FX_ADD);
    }
    *out = sum; return FX_NUMERIC_OK;
}
static fx_numeric_status pack_exact(fx_number *out, const exact_value *value) {
    fx_number components[6]; unsigned i, start;
    if (!value->count) { fx_number_zero(out); return FX_NUMERIC_OK; }
    if (value->count == 1 && value->terms[0].radicand == 1) {
        fx_rational r = {value->terms[0].numerator, value->terms[0].denominator, 0};
        return fx_rational_encode(out, &r);
    }
    if (value->count > 2) return exact_to_decimal(out, value);
    for (i = 0; i < 6; ++i) fx_number_zero(&components[i]);
    fx_decimal_from_u8(&components[2], 1);
    start = value->count == 1 ? 1 : 0;
    for (i = 0; i < value->count; ++i) {
        const exact_term *t = &value->terms[i]; unsigned offset = (i+start)*3;
        if (abs64(t->numerator) > 99 || t->denominator > 99 || t->radicand > 999) return exact_to_decimal(out, value);
        (void)fx_decimal_from_integer(&components[offset], t->numerator);
        (void)fx_decimal_from_integer(&components[offset+1], (int64_t)t->radicand);
        (void)fx_decimal_from_integer(&components[offset+2], (int64_t)t->denominator);
    }
    return fx_surd_pack(out, components);
}
fx_numeric_status fx_number_negate(fx_number *out, const fx_number *in) {
    fx_number value = *in; fx_number_type kind = fx_number_kind(in);
    if (kind == FX_NUMBER_ERROR) { *out = value; return FX_NUMERIC_OK; }
    if (kind == FX_NUMBER_SURD) {
        if (value.bytes[9]) value.bytes[9] = (uint8_t)((value.bytes[9]+5)%10);
        value.bytes[8] = (uint8_t)((value.bytes[8]+5)%10);
    } else if (kind == FX_NUMBER_DECIMAL || kind == FX_NUMBER_RATIONAL) {
        if ((value.bytes[0] & 15) || kind == FX_NUMBER_RATIONAL)
            value.bytes[9] = (uint8_t)((value.bytes[9]+5)%10);
    } else return FX_NUMERIC_UNIMPLEMENTED;
    *out = value; return FX_NUMERIC_OK;
}
fx_numeric_status fx_number_sqrt(fx_number *out, const fx_number *in, int exact_math) {
    fx_number source = *in;
    exact_value value; exact_term t;
    if (exact_math && (source.bytes[0] & 0xf0) == 0 && source.bytes[9] <= 1 &&
        (source.bytes[9] == 0 || source.bytes[8] < 7)) {
        fx_rational recognized;
        /* 0x1c852 -> 0x11110 recognizes a short fraction before attempting
         * the bounded exact root. The original operand is replaced even
         * when the final radical cannot fit the compact surd record. */
        if (fx_number_recognize_rational(&recognized, &source))
            (void)fx_rational_encode(&source, &recognized);
    }
    in = &source;
    if (exact_math && extract_exact(&value, in) && value.count <= 1 &&
        (!value.count || value.terms[0].radicand == 1)) {
        uint64_t num_square, num_rad, den_square, den_rad;
        if (!value.count) { fx_number_zero(out); return FX_NUMERIC_OK; }
        t = value.terms[0];
        if (t.numerator < 0) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
        if (t.numerator < 10000000 && t.denominator < 10000) {
            square_factors((uint64_t)t.numerator, &num_square, &num_rad);
            square_factors(t.denominator, &den_square, &den_rad);
            value.count = 0; t.numerator = (int64_t)num_square;
            t.denominator = den_square * den_rad; t.radicand = num_rad * den_rad;
            if (append_term(&value, t)) {
                fx_numeric_status status = pack_exact(out, &value);
                if (status != FX_NUMERIC_OK || fx_number_kind(in) != FX_NUMBER_RATIONAL ||
                    fx_number_kind(out) == FX_NUMBER_RATIONAL || fx_number_kind(out) == FX_NUMBER_SURD) return status;
            }
        }
    }
    {
        fx_number decimal;
        if (fx_number_kind(in) == FX_NUMBER_RATIONAL) {
            fx_rational rational; fx_number numerator, denominator;
            if (fx_rational_decode(&rational, in) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
            if (rational.numerator < 0) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
            if (rational.denominator > (uint64_t)INT64_MAX) return FX_NUMERIC_UNREPRESENTABLE;
            (void)fx_decimal_from_integer(&numerator, rational.numerator);
            (void)fx_decimal_from_integer(&denominator, (int64_t)rational.denominator);
            (void)fx_decimal_sqrt(&numerator, &numerator);
            (void)fx_decimal_integer_cleanup(&numerator);
            (void)fx_decimal_sqrt(&denominator, &denominator);
            (void)fx_decimal_integer_cleanup(&denominator);
            return fx_decimal_binary(out, &numerator, &denominator, FX_DIVIDE);
        }
        fx_numeric_status status = fx_number_to_decimal(&decimal, in);
        if (status != FX_NUMERIC_OK) return status;
        return fx_decimal_sqrt(out, &decimal);
    }
}
fx_numeric_status fx_number_binary(fx_number *out, const fx_number *a,
                                  const fx_number *b, fx_binary_op op) {
    exact_value x, y, result;
    fx_number prepared_a = *a, prepared_b = *b;
    if (fx_number_kind(a) == FX_NUMBER_SURD || fx_number_kind(b) == FX_NUMBER_SURD) {
        fx_rational recognized;
        /* 0x17b88 calls0x11110 before selecting the surd arithmetic path. */
        if (fx_number_recognize_rational(&recognized,a))
            (void)fx_rational_encode(&prepared_a,&recognized);
        if (fx_number_recognize_rational(&recognized,b))
            (void)fx_rational_encode(&prepared_b,&recognized);
    }
    a = &prepared_a; b = &prepared_b;
    int exact_operand = fx_number_kind(a) == FX_NUMBER_RATIONAL || fx_number_kind(a) == FX_NUMBER_SURD ||
                        fx_number_kind(b) == FX_NUMBER_RATIONAL || fx_number_kind(b) == FX_NUMBER_SURD;
    if (fx_number_kind(a) == FX_NUMBER_SURD || fx_number_kind(b) == FX_NUMBER_SURD) {
        fx_decimal plain;
        if ((fx_decimal_decode(&plain,a) == FX_NUMERIC_OK && plain.exponent > 7) ||
            (fx_decimal_decode(&plain,b) == FX_NUMERIC_OK && plain.exponent > 7)) exact_operand = 0;
    }
    if (exact_operand && extract_exact(&x, a) && extract_exact(&y, b)) {
        unsigned i; int ok = 1;
        if (op == FX_ADD || op == FX_SUBTRACT) {
            result = x;
            for (i = 0; i < y.count; ++i) {
                exact_term t = y.terms[i]; if (op == FX_SUBTRACT) t.numerator = -t.numerator;
                if (!append_term(&result, t)) { ok = 0; break; }
            }
        } else if (op == FX_MULTIPLY) ok = multiply_exact(&result, &x, &y);
        else if (op == FX_DIVIDE) {
            exact_value reciprocal;
            reciprocal.count = 0;
            if (!y.count) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
            if (y.count == 1) {
                exact_term t = y.terms[0]; uint64_t denominator;
                if (!mul_unsigned(abs64(t.numerator), t.radicand, &denominator)) ok = 0;
                else {
                    t.numerator = t.numerator < 0 ? -(int64_t)t.denominator : (int64_t)t.denominator;
                    t.denominator = denominator; ok = normalize_term(&t) && append_term(&reciprocal, t);
                    if (ok) ok = multiply_exact(&result, &x, &reciprocal);
                }
            } else if (y.count == 2) {
                exact_value conjugate = y, denominator;
                conjugate.terms[1].numerator = -conjugate.terms[1].numerator;
                denominator.count = 0;
                /* 0x17e5a builds the conjugate denominator from each
                 * coefficient square times its original radicand. It does
                 * not send sqrt(r)*sqrt(r) through the bounded square-factor
                 * normalizer, which would miss prime factors above 97. */
                for (i = 0; i < 2; ++i) {
                    exact_term squared = {0, 0, 1};
                    if (!mul_signed(y.terms[i].numerator, y.terms[i].numerator, &squared.numerator) ||
                        !mul_signed(squared.numerator, (int64_t)y.terms[i].radicand, &squared.numerator) ||
                        !mul_unsigned(y.terms[i].denominator, y.terms[i].denominator, &squared.denominator)) {
                        ok = 0; break;
                    }
                    if (i) squared.numerator = -squared.numerator;
                    if (!append_term(&denominator, squared)) { ok = 0; break; }
                }
                if (!ok || denominator.count != 1 || denominator.terms[0].radicand != 1) ok = 0;
                else {
                    exact_term d = denominator.terms[0];
                    exact_value scaled;
                    scaled.count = 0; d.radicand = 1;
                    if (!d.numerator) { fx_number_error(out, 3); return FX_NUMERIC_OK; }
                    {
                        uint64_t den = abs64(d.numerator);
                        d.numerator = d.numerator < 0 ? -(int64_t)d.denominator : (int64_t)d.denominator;
                        d.denominator = den;
                    }
                    ok = append_term(&scaled, d);
                    if (ok) ok = multiply_exact(&reciprocal, &x, &conjugate);
                    if (ok) {
                        /* 0x17ec2 applies the scalar denominator only after
                         * the numerator terms have been combined. Its
                         * component eligibility check (0x17d14) compares the
                         * packed BCD exponent byte with 14, so exponent10
                         * (byte0x10) already exceeds the limit. Check raw
                         * products before cancellation, as that routine does. */
                        for (i = 0; i < reciprocal.count; ++i) {
                            uint64_t raw_denominator; int64_t raw_numerator;
                            if (!mul_signed(reciprocal.terms[i].numerator, d.numerator, &raw_numerator) ||
                                !mul_unsigned(reciprocal.terms[i].denominator, d.denominator, &raw_denominator) ||
                                abs64(raw_numerator) >= UINT64_C(10000000000) ||
                                raw_denominator >= UINT64_C(10000000000)) { ok = 0; break; }
                        }
                    }
                    if (ok) ok = multiply_exact(&result, &reciprocal, &scaled);
                }
            } else ok = 0;
        } else return FX_NUMERIC_INVALID;
        if (ok && result.count <= 2) return pack_exact(out, &result);
    }
    {
        fx_number x_decimal, y_decimal;
        fx_numeric_status status = fx_number_to_decimal(&x_decimal, a);
        if (status != FX_NUMERIC_OK) return status;
        status = fx_number_to_decimal(&y_decimal, b);
        if (status != FX_NUMERIC_OK) return status;
        return fx_decimal_binary(out, &x_decimal, &y_decimal, op);
    }
}
fx_numeric_status fx_number_integer_power(fx_number *out, const fx_number *in, int exponent) {
    fx_number result, source = *in, one;
    if (exponent != -1 && exponent != 0 && exponent != 2 && exponent != 3)
        return FX_NUMERIC_UNIMPLEMENTED;
    if (fx_number_kind(in) == FX_NUMBER_ERROR) { *out = *in; return FX_NUMERIC_OK; }
    if (fx_number_kind(&source) == FX_NUMBER_DECIMAL || fx_number_kind(&source) == FX_NUMBER_RATIONAL)
        source.bytes[0] &= (uint8_t)~0x40;
    fx_decimal_from_u8(&one, 1);
    if (exponent == 0) {
        fx_number decimal; fx_decimal value;
        if (fx_number_to_decimal(&decimal, &source) != FX_NUMERIC_OK ||
            fx_decimal_decode(&value, &decimal) != FX_NUMERIC_OK) return FX_NUMERIC_INVALID;
        if (!value.sign) fx_number_error(out, 3); else *out = one;
        return FX_NUMERIC_OK;
    }
    if (exponent == -1) return fx_number_binary(out, &one, &source, FX_DIVIDE);
    {
        fx_numeric_status status = fx_number_binary(&result, &source, &source, FX_MULTIPLY);
        if (status != FX_NUMERIC_OK) return status;
    }
    if (exponent == 3) return fx_number_binary(out, &result, &source, FX_MULTIPLY);
    *out = result; return FX_NUMERIC_OK;
}
fx_numeric_status fx_number_divmod(fx_number *remainder, fx_number *quotient,
                                  const fx_number *dividend, const fx_number *divisor) {
    fx_decimal a, b;
    uint64_t remaining, q = 0;
    int exponent, quotient_exponent = 14;
    if (fx_decimal_decode(&a, dividend) != FX_NUMERIC_OK || fx_decimal_decode(&b, divisor) != FX_NUMERIC_OK ||
        a.flags || b.flags) return FX_NUMERIC_UNIMPLEMENTED;
    /* The original routine does not terminate with a zero divisor. */
    if (!b.sign) return FX_NUMERIC_INVALID;
    if (b.sign < 0) { *remainder = *dividend; fx_number_zero(quotient); return FX_NUMERIC_OK; }
    remaining = a.mantissa; exponent = a.exponent;
    while (exponent >= b.exponent) {
        unsigned digit;
        if (q >= UINT64_C(100000000000000)) {
            quotient_exponent = 15 + exponent - b.exponent; break;
        }
        q *= 10; digit = (unsigned)(remaining / b.mantissa);
        remaining %= b.mantissa; q += digit;
        remaining *= 10; --exponent;
    }
    (void)from_scaled_integer(remainder, remaining, exponent - 14, a.sign, 0);
    {
        fx_numeric_status status = from_scaled_integer(quotient, q, quotient_exponent - 14, a.sign, 0);
        if (fx_number_kind(quotient) == FX_NUMBER_ERROR && a.sign < 0) quotient->bytes[9] = 5;
        return status;
    }
}
