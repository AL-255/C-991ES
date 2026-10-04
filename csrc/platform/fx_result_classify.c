/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_result_classify.h"
#include <string.h>

static uint8_t read_byte(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void write_byte(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

static void write_word(fx_platform *p, uint16_t address, uint16_t value)
{
    write_byte(p, address, (uint8_t)value);
    write_byte(p, (uint16_t)(address+1), (uint8_t)(value >> 8));
}

static fx_number load_number(fx_platform *p, uint16_t address)
{
    fx_number value;
    value.bytes[0] = read_byte(p, address);
    value.bytes[1] = read_byte(p, (uint16_t)(address+1));
    /* The packed field loader advances to an even tail address after its
     * first two-byte field, including a caller's odd-address alias. */
    uint16_t tail = (uint16_t)((address+2u) & 0xfffeu);
    for (unsigned n = 2; n < 10; ++n)
        value.bytes[n] = read_byte(p, (uint16_t)(tail+n-2));
    return value;
}

static void store_number(fx_platform *p, uint16_t address, const fx_number *value)
{
    for (unsigned n = 0; n < 10; ++n)
        write_byte(p, (uint16_t)(address+n), value->bytes[n]);
}

static void store_operand(fx_platform *p, uint16_t address, const fx_number *value)
{
    /* Finite arithmetic keeps exponent/sign first and the packed mantissa
     * least-significant byte first. The external record has the reverse order. */
    write_byte(p, address, value->bytes[8]);
    write_byte(p, (uint16_t)(address+1), value->bytes[9]);
    for (unsigned n = 0; n < 8; ++n)
        write_byte(p, (uint16_t)(address+2+n), value->bytes[7-n]);
}

static void store_window(fx_platform *p, uint16_t address, uint64_t mantissa,
                         uint8_t guard)
{
    write_byte(p, address, 0);
    write_byte(p, (uint16_t)(address+1), guard);
    for (unsigned n = 0; n < 8; ++n) {
        unsigned pair = (unsigned)(mantissa % 100);
        write_byte(p, (uint16_t)(address+2+n), (uint8_t)((pair/10)*16+pair%10));
        mantissa /= 100;
    }
}

static uint64_t power10(unsigned exponent)
{
    uint64_t value = 1;
    while (exponent--) value *= 10;
    return value;
}

static uint8_t guard_byte(uint64_t window, unsigned next_digit)
{
    return (uint8_t)(window >= UINT64_C(1000000000000000)
                    ? (window%10)*16+next_digit : next_digit*16);
}

static void store_normalization_count(fx_platform *p, uint64_t window)
{
    if (!window || window >= UINT64_C(1000000000000000)) return;
    unsigned padding = 0;
    while (window < UINT64_C(100000000000000)) { window *= 10; ++padding; }
    write_byte(p, 0x800b, (uint8_t)padding);
}

static fx_numeric_status scaled_integer(fx_number *out, uint64_t value,
                                        int scale, int sign)
{
    if (!value) { fx_number_zero(out); return FX_NUMERIC_OK; }
    unsigned count = 0;
    for (uint64_t remaining = value; remaining; remaining /= 10) ++count;
    fx_decimal number = {sign, scale+(int)count-1, value, 0};
    while (count < 15) { number.mantissa *= 10; ++count; }
    while (count > 15) { number.mantissa /= 10; --count; }
    return fx_decimal_encode(out, &number);
}

static int canonical_surd(const fx_number *value, uint16_t source)
{
    if ((source >= 0x7ff7 && source < 0x8060) ||
        (source >= 0x8637 && source < 0x867c) || source >= 0xfff7) return 0;
    for (unsigned n = 0; n < 8; ++n) {
        uint8_t byte = value->bytes[n];
        if (n == 0 || n == 4) {
            if ((byte & 15) > 9) return 0;
        } else if ((byte & 15) > 9 || (byte >> 4) > 9) return 0;
    }
    return (value->bytes[8] == 1 && value->bytes[9] == 6) ||
           (value->bytes[8] == 6 && value->bytes[9] == 1);
}

static fx_numeric_status component_root(fx_platform *p, fx_number *out,
                                        const fx_number *radicand)
{
    fx_decimal input;
    fx_numeric_status status = fx_decimal_decode(&input, radicand);
    if (status) return status;
    if (!input.mantissa && radicand->bytes[9] == 1) {
        /* The raw positive-zero radical enters the unguarded digit root.
         * Its exponent prefix injects 10^13 into the root window. */
        uint64_t root = 0, remainder = UINT64_C(10000000000000);
        uint64_t low = 0, high = UINT64_C(10000000);
        while (low+1 < high) {
            uint64_t middle = low+(high-low)/2;
            if (middle <= remainder/middle) low = middle; else high = middle;
        }
        root = low;
        fx_number_zero(out);
        for (unsigned n = 7; n > 0; --n) {
            unsigned pair = (unsigned)(root%100);
            out->bytes[n] = (uint8_t)((pair/10)*16+pair%10);
            root /= 100;
        }
        out->bytes[0] = (uint8_t)root;
        out->bytes[8] = 0x50;
        out->bytes[9] = 1;
    } else {
        status = fx_decimal_sqrt(out, radicand);
        if (status) return status;
    }
    fx_number zero = {{0}}, root_window = *out;
    store_operand(p, 0x8010, &zero);
    store_window(p, 0x8020, input.mantissa*2, 0);
    write_byte(p, 0x8020, out->bytes[8]);
    write_byte(p, 0x8021, out->bytes[9]);
    root_window.bytes[8] = 0;
    root_window.bytes[9] = 0x50;
    store_operand(p, 0x8030, &root_window);
    store_operand(p, 0x8000, out);
    return FX_NUMERIC_OK;
}

static fx_numeric_status component_product(fx_platform *p, fx_number *out,
    const fx_number *root, const fx_number *coefficient)
{
    fx_decimal a, b;
    if (fx_decimal_decode(&a, root) || fx_decimal_decode(&b, coefficient)) return FX_NUMERIC_INVALID;
    /* Schoolbook multiplication exposes the same fixed mantissa window
     * while keeping the actual operands as readable decimal values. */
    uint8_t product[31] = {0}, left[15], right[15];
    uint64_t m = a.mantissa, n = b.mantissa;
    for (unsigned i = 0; i < 15; ++i) {
        left[i] = (uint8_t)(m%10); m /= 10;
        right[i] = (uint8_t)(n%10); n /= 10;
    }
    for (unsigned i = 0; i < 15; ++i) {
        unsigned carry = 0;
        for (unsigned j = 0; j < 15; ++j) {
            unsigned digit = product[i+j]+left[i]*right[j]+carry;
            product[i+j] = (uint8_t)(digit%10); carry = digit/10;
        }
        product[i+15] = (uint8_t)carry;
    }
    uint64_t window = 0;
    for (unsigned i = 30; i > 14; --i) window = window*10+product[i-1];
    fx_numeric_status status = scaled_integer(out, window,
        a.exponent+b.exponent-14, a.sign*b.sign);
    if (status) return status;
    store_normalization_count(p, window);
    store_operand(p, 0x8010, coefficient);
    store_window(p, 0x8020, a.mantissa, guard_byte(window, product[13]));
    store_operand(p, 0x8000, out);
    return FX_NUMERIC_OK;
}

static fx_numeric_status component_quotient(fx_platform *p, fx_number *out,
    const fx_number *numerator, const fx_number *denominator)
{
    fx_decimal a, b;
    if (fx_decimal_decode(&a, numerator) || fx_decimal_decode(&b, denominator)) return FX_NUMERIC_INVALID;
    store_operand(p, 0x8010, denominator);
    write_word(p, 0x8020, 0);
    fx_numeric_status status = fx_decimal_binary(out, numerator, denominator, FX_DIVIDE);
    if (status) return status;
    if (b.mantissa) {
        uint64_t window = a.mantissa/b.mantissa, remainder = a.mantissa%b.mantissa;
        for (unsigned n = 0; n < 15; ++n) {
            remainder *= 10;
            window = window*10+remainder/b.mantissa;
            remainder %= b.mantissa;
        }
        unsigned next_digit = (unsigned)(remainder*10/b.mantissa);
        store_normalization_count(p, window);
        store_window(p, 0x8020, window, guard_byte(window, next_digit));
    }
    store_operand(p, 0x8000, out);
    return FX_NUMERIC_OK;
}

static fx_numeric_status add_terms(fx_platform *p, fx_number *out,
                                  const fx_number *second, const fx_number *first)
{
    store_operand(p, 0x8010, first);
    if (fx_number_kind(second) == FX_NUMBER_ERROR || fx_number_kind(first) == FX_NUMBER_ERROR) {
        *out = fx_number_kind(second) == FX_NUMBER_ERROR ? *second : *first;
        store_operand(p, 0x8000, out);
        return FX_NUMERIC_OK;
    }
    fx_decimal a, b;
    if (fx_decimal_decode(&a, second) || fx_decimal_decode(&b, first)) return FX_NUMERIC_INVALID;
    if (!a.mantissa) a.exponent = -100;
    if (!b.mantissa) b.exponent = -100;
    write_byte(p, 0x803b, 0);
    int a_negative = second->bytes[9] >= 5, b_negative = first->bytes[9] >= 5;
    int opposite = a_negative != b_negative;
    write_byte(p, 0x800a, (uint8_t)(opposite ? 6 : 0));
    fx_number smaller = *first;
    if (b.exponent > a.exponent || (b.exponent == a.exponent && b.mantissa > a.mantissa)) {
        fx_decimal temporary = a; a = b; b = temporary;
        smaller = *second;
        a_negative = b_negative;
    }
    unsigned gap = (unsigned)(a.exponent-b.exponent);
    smaller.bytes[9] = (uint8_t)((smaller.bytes[9] >= 5 ? smaller.bytes[9]-5 : smaller.bytes[9])
                               + (a_negative ? 5 : 0));
    store_operand(p, 0x8010, &smaller);
    int shift = (int)gap-(opposite ? 1 : 0);
    if (shift <= 16) {
        uint64_t aligned = shift < 0 ? b.mantissa*10 : b.mantissa/power10((unsigned)shift);
        if (shift > 0) {
            /* The alignment window includes the sign byte below the mantissa.
             * Discarded mantissa digits therefore replace its sign nibbles. */
            uint64_t shifted = (b.mantissa*100+smaller.bytes[9])/power10((unsigned)shift);
            unsigned pair = (unsigned)(shifted%100);
            write_byte(p, 0x8011, (uint8_t)((pair/10)*16+pair%10));
        }
        write_byte(p, 0x800b, (uint8_t)(shift > 0 ? shift : 0));
        uint64_t small = aligned;
        for (unsigned n = 0; n < 8; ++n) {
            unsigned pair = (unsigned)(aligned%100);
            write_byte(p, (uint16_t)(0x8012+n), (uint8_t)((pair/10)*16+pair%10));
            aligned /= 100;
        }
        uint64_t large = a.mantissa*(opposite ? 10 : 1);
        store_normalization_count(p, opposite ? large-small : large+small);
    } else {
        store_normalization_count(p, a.mantissa*(opposite ? 10 : 1));
    }
    fx_numeric_status status = fx_decimal_add_plain(out, second, first);
    if (!status) store_operand(p, 0x8000, out);
    return status;
}

static fx_numeric_status convert_opposite_surd(fx_platform *p, fx_number *out,
                                              const fx_number *source)
{
    fx_number components[6], first = {{0}}, second, root, product;
    fx_numeric_status status = fx_surd_unpack(components, source);
    if (status) return status;
    for (unsigned n = 0; n < 6; ++n) store_number(p, (uint16_t)(0x8640+10*n), &components[n]);
    write_word(p, 0x805c, 0x8640); write_word(p, 0x805e, 0x8640);
    if (components[0].bytes[0]) {
        store_operand(p, 0x8010, &components[2]);
        store_operand(p, 0x8050, &components[2]);
        store_operand(p, 0x803c, &components[0]);
        status = component_root(p, &root, &components[1]);
        if (!status) status = component_product(p, &product, &root, &components[0]);
        if (!status) status = component_quotient(p, &first, &product, &components[2]);
        if (status) return status;
    }
    store_operand(p, 0x8046, &first);
    store_operand(p, 0x8010, &components[5]);
    store_operand(p, 0x8050, &components[5]);
    store_operand(p, 0x803c, &components[3]);
    status = component_root(p, &root, &components[4]);
    if (!status) status = component_product(p, &product, &root, &components[3]);
    if (!status) status = component_quotient(p, &second, &product, &components[5]);
    if (!status) status = add_terms(p, out, &second, &first);
    if (!status) store_number(p, 0x8640, out);
    return status;
}

fx_numeric_status fx_result_classify_address(fx_platform *p,
    uint16_t source, uint16_t companion, fx_result_classification *result)
{
    if (!p || !p->ram || !result ||
        (source >= 0x8cf7 && source < 0x8dee)) return FX_NUMERIC_INVALID;
    write_word(p, 0x805c, source);
    write_word(p, 0x805e, companion);
    fx_number value = load_number(p, source);
    store_operand(p, 0x8000, &value);
    result->continuation = companion;
    unsigned header = value.bytes[0] & 0xf0;
    if (!value.bytes[0]) result->classification = 1;
    else if (header == 0x80) {
        uint8_t sign = value.bytes[9] ? (uint8_t)(value.bytes[8]+value.bytes[9]) : value.bytes[8];
        if (value.bytes[9] && sign == 7) {
            fx_number compact;
            for (unsigned n = 0; n < 10; ++n)
                compact.bytes[n] = read_byte(p, (uint16_t)(source+n));
            if (!canonical_surd(&compact, source)) return FX_NUMERIC_UNIMPLEMENTED;
            fx_number decimal;
            fx_numeric_status status = convert_opposite_surd(p, &decimal, &compact);
            if (status) return status;
            sign = decimal.bytes[9];
            result->continuation = (uint16_t)(read_byte(p, 0x8002) |
                                      (uint16_t)read_byte(p, 0x8003) << 8);
        }
        result->classification = sign >= 4 ? 2 : 4;
    } else if (header >= 0x50) result->classification = 0xf0;
    else if (!(value.bytes[8] | value.bytes[9])) result->classification = 1;
    else result->classification = value.bytes[9] >= 4 ? 2 : 4;
    return FX_NUMERIC_OK;
}
