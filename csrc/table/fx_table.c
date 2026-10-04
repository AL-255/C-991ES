/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_table.h"
#include <stddef.h>
#include <string.h>

static uint16_t read_word(const uint8_t *ram, uint16_t address) {
    return (uint16_t)(ram[address] | (uint16_t)ram[(uint16_t)(address + 1)] << 8);
}
static void write_word(uint8_t *ram, uint16_t address, uint16_t value) {
    ram[address] = (uint8_t)value;
    ram[(uint16_t)(address + 1)] = (uint8_t)(value >> 8);
}
static fx_number read_number(const uint8_t *ram, uint16_t address) {
    fx_number value; unsigned i;
    for (i = 0; i < 10; ++i) value.bytes[i] = ram[(uint16_t)(address + i)];
    return value;
}
static void write_number(uint8_t *ram, uint16_t address, const fx_number *value) {
    unsigned i;
    for (i = 0; i < 10; ++i) ram[(uint16_t)(address + i)] = value->bytes[i];
}
static int compare_decimal(const fx_decimal *a, const fx_decimal *b) {
    int magnitude;
    if (a->sign != b->sign) return a->sign > b->sign ? 1 : -1;
    if (!a->sign) return 0;
    if (a->exponent != b->exponent) magnitude = a->exponent > b->exponent ? 1 : -1;
    else if (a->mantissa != b->mantissa) magnitude = a->mantissa > b->mantissa ? 1 : -1;
    else magnitude = 0;
    return a->sign * magnitude;
}
static fx_table_status decimal_parameter(fx_decimal *out, const fx_number *in) {
    unsigned header = in->bytes[0] & 0xf0u;
    if (header || fx_decimal_decode(out, in) != FX_NUMERIC_OK) return FX_TABLE_MATH;
    return FX_TABLE_OK;
}
static fx_table_status decode_step(fx_number *plain, fx_decimal *value,
                                   const fx_number *stored) {
    unsigned header = stored->bytes[0] & 0xf0u;
    /* The decimal arithmetic wrapper accepts both rational tags. Admission
     * before the first row applies its separate sign-class rule below. */
    if (header == 0x20u || header == 0x60u) {
        if (fx_number_to_decimal(plain, stored) != FX_NUMERIC_OK ||
            fx_decimal_decode(value, plain) != FX_NUMERIC_OK) return FX_TABLE_MATH;
        return FX_TABLE_OK;
    }
    *plain = *stored;
    if ((header != 0 && header != 0x40u) ||
        fx_decimal_decode(value, plain) != FX_NUMERIC_OK) return FX_TABLE_MATH;
    return FX_TABLE_OK;
}
static unsigned floor_small_nonnegative(const fx_decimal *value) {
    uint64_t divisor = 1; int places;
    if (!value->sign || value->exponent < 0) return 0;
    if (value->exponent >= 2) return 100;
    places = 14 - value->exponent;
    while (places--) divisor *= 10;
    return (unsigned)(value->mantissa / divisor);
}
static void initialize_table(uint8_t *ram, unsigned rows) {
    ram[0x80de] = (uint8_t)rows;
    ram[0x811c] = ram[0x811d] = ram[0x811e] = 1;
    ram[0x80fe] = ram[0x80ff] = 0;
    ram[0x8101] = ram[0x8100] = ram[0x8130] = 0;
    ram[0x80df] = 0;
    memset(ram + 0x82ee, 0, 600);
}
static int commit(uint8_t *ram, unsigned column, unsigned row,
                  const fx_number *number) {
    unsigned stride;
    if (row > ram[0x80de]) return 0;
    stride = !ram[0x810e] || (ram[0x8138] & 0x80u) ? 2 : 3;
    write_number(ram, (uint16_t)(0x82eeu + 10u * (stride * (row - 1u) + column)), number);
    return 1;
}
static fx_table_status generate_source(uint8_t ram[65536],
    uint16_t beginning, const fx_table_control *control,
    fx_table_result *result)
{
    fx_number start, end, step, quotient, difference, output, x;
    fx_decimal start_value, end_value, step_value, quotient_value;
    fx_table_status status;
    fx_table_result progress = {0, 0, 0, 0, 0};
    uint16_t cursor; unsigned rows, row;
    int evaluator_status, poll_status, committed;
    if (!ram || !control || !control->evaluate || !result) return FX_TABLE_INVALID;
    if (ram[0x80f9] != 0x88) return FX_TABLE_UNIMPLEMENTED;
    cursor = beginning;
    progress.source = cursor;
    start = read_number(ram, 0x829e); end = read_number(ram, 0x82a8);
    step = read_number(ram, 0x82b2);
    status = decimal_parameter(&start_value, &start);
    if (status != FX_TABLE_OK) goto finish;
    status = decimal_parameter(&end_value, &end);
    if (status != FX_TABLE_OK) goto finish;
    if (compare_decimal(&start_value, &end_value) > 0) {
        status = FX_TABLE_MATH; goto finish;
    }
    /* A marked rational has no admitted Step sign class. A callback may
     * later install that record, which the X-increment arithmetic accepts. */
    if ((step.bytes[0] & 0xf0u) == 0x60u) {
        status = FX_TABLE_MATH; goto finish;
    }
    status = decode_step(&step, &step_value, &step);
    if (status != FX_TABLE_OK) goto finish;
    if (step_value.sign <= 0) { status = FX_TABLE_MATH; goto finish; }
    /* The original subtract/divide/cleanup sequence avoids an extra missing
     * endpoint caused by tiny decimal cancellation or division residue. */
    if (fx_decimal_subtract_cancel(&difference, &end, &start) != FX_NUMERIC_OK ||
        fx_decimal_binary(&quotient, &difference, &step, FX_DIVIDE) != FX_NUMERIC_OK ||
        fx_number_kind(&quotient) == FX_NUMBER_ERROR ||
        fx_decimal_integer_cleanup(&quotient) != FX_NUMERIC_OK ||
        fx_decimal_decode(&quotient_value, &quotient) != FX_NUMERIC_OK) {
        status = FX_TABLE_MATH; goto finish;
    }
    rows = floor_small_nonnegative(&quotient_value) + 1;
    if (rows > ((ram[0x810e] & 1u) ? 20u : 30u)) {
        status = FX_TABLE_RANGE; goto finish;
    }
    progress.planned_rows = (uint8_t)rows;
    if (!ram[0x810e] || !(ram[0x8138] & 1u)) initialize_table(ram, rows);
    write_number(ram, 0x8276, &start);
    for (row = 1; row <= rows; ++row) {
        cursor = beginning;
        ram[0x8125] = 0;
        fx_number_zero(&output);
        evaluator_status = control->evaluate(control->userdata, ram,
            ram[0x80f9], 1, &cursor, &output);
        if (evaluator_status < 0) { status = FX_TABLE_UNIMPLEMENTED; goto finish; }
        ++progress.evaluated_rows;
        if (evaluator_status != 255) {
            cursor = (uint16_t)(cursor - 1);
            if (evaluator_status != 3) {
                status = (fx_table_status)evaluator_status; goto finish;
            }
            fx_number_error(&output, 3);
        }
        if (!ram[0x810e] || !(ram[0x8138] & 1u)) {
            x = read_number(ram, 0x8276);
            committed = commit(ram, 0, row, &x);
            committed |= commit(ram, 1, row, &output);
        } else committed = commit(ram, 2, row, &output);
        if (committed) ++progress.committed_rows;
        if (row == rows) { status = FX_TABLE_OK; goto finish; }
        ++progress.polls;
        poll_status = control->poll ? control->poll(control->userdata, ram) : 0;
        if (poll_status) { status = (fx_table_status)poll_status; goto finish; }
        x = read_number(ram, 0x8276); step = read_number(ram, 0x82b2);
        if (decode_step(&step, &step_value, &step) != FX_TABLE_OK ||
            fx_decimal_binary(&x, &x, &step, FX_ADD) != FX_NUMERIC_OK ||
            fx_number_kind(&x) == FX_NUMBER_ERROR ||
            fx_decimal_integer_cleanup(&x) != FX_NUMERIC_OK) {
            fx_number_zero(&x); write_number(ram, 0x8276, &x);
            status = FX_TABLE_MATH; goto finish;
        }
        write_number(ram, 0x8276, &x);
    }
    status = FX_TABLE_OK;
finish:
    progress.source = cursor;
    *result = progress;
    return status;
}

/* The named source is host-owned, replacing only F12A's CPU-local word.
 * Mathematical row effects and external callbacks use the same live RAM. */
fx_table_status fx_table_generate_source(uint8_t ram[65536],
    uint16_t *source, const fx_table_control *control, fx_table_result *result)
{
    fx_table_status status;
    if (!ram || !source || !control || !control->evaluate || !result)
        return FX_TABLE_INVALID;
    if (ram[0x80f9] != 0x88) return FX_TABLE_UNIMPLEMENTED;
    status = generate_source(ram, *source, control, result);
    *source = result->source;
    return status;
}

/* The old physical-word ABI preserves every live alias and final writeback. */
fx_table_status fx_table_generate(uint8_t ram[65536],
    uint16_t source_pointer_word, const fx_table_control *control,
    fx_table_result *result)
{
    fx_table_status status;
    if (!ram || !control || !control->evaluate || !result) return FX_TABLE_INVALID;
    if (source_pointer_word < 0x8000 || source_pointer_word == 0xffff ||
        ram[0x80f9] != 0x88) return FX_TABLE_UNIMPLEMENTED;
    status = generate_source(ram, read_word(ram, source_pointer_word), control, result);
    write_word(ram, source_pointer_word, result->source);
    return status;
}
