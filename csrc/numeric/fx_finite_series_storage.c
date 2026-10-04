/* Readable original042AE/043A2 finite series. SPDX-License-Identifier: GPL-3.0-only.
 * No CPU, instruction interpretation, host float or original ROM execution. */
#include "fx_finite_series_storage.h"
#include "../parse/fx_eval_surd_workspace.h"
#include "../platform/fx_platform.h"
#include <string.h>

enum { ACCUMULATOR, INITIAL_X, END_X, SPILLED_COMPANION };

static int overlaps(const void *left, size_t left_size,
                    const void *right, size_t right_size)
{
    uintptr_t a = (uintptr_t)left, b = (uintptr_t)right;
    return a >= b ? a - b < right_size : b - a < left_size;
}
static int valid_storage(const fx_finite_series_storage *s)
{
    return s && s->ram && s->ram_size == 65536u &&
        !overlaps(s, sizeof *s, s->ram, s->ram_size);
}
static int in_ram(const fx_finite_series_storage *s, const void *object, size_t size)
{
    return overlaps(object, size, s->ram, s->ram_size);
}
static int valid_state(const fx_finite_series_state *state,
                        const fx_finite_series_storage *s)
{
    return state && valid_storage(s) && !in_ram(s, state, sizeof *state) &&
        !overlaps(state, sizeof *state, s, sizeof *s) &&
        state->kind <= FX_FINITE_PRODUCT;
}
static int valid_argument(const fx_finite_series_state *state,
                          const fx_finite_series_storage *s,
                          const fx_complex *value)
{
    return value && !in_ram(s, value, sizeof *value) &&
        !overlaps(value, sizeof *value, state, sizeof *state) &&
        !overlaps(value, sizeof *value, s, sizeof *s);
}
static int valid_control(const fx_finite_series_state *state,
                         const fx_finite_series_storage *s,
                         const fx_calculus_control *control)
{
    return !control || (!in_ram(s, control, sizeof *control) &&
        !overlaps(control, sizeof *control, state, sizeof *state) &&
        !overlaps(control, sizeof *control, s, sizeof *s));
}
static uint8_t read_byte(const fx_finite_series_storage *s, unsigned address)
{
    return address < 0x8000 ? s->rom[address] : s->ram[address];
}
static int readable(const fx_finite_series_storage *s, unsigned address)
{
    return address <= 65516u &&
        (address >= 0x8000 || (s->rom && s->rom_size >= 0x8000));
}
static void load_record(fx_number *value, const fx_finite_series_storage *s,
                        unsigned address)
{
    for (unsigned i = 0; i < 8; ++i) value->bytes[i] = read_byte(s, address + i);
    unsigned tail = address + 8u - (address & 1u);
    value->bytes[8] = read_byte(s, tail);
    value->bytes[9] = read_byte(s, tail + 1);
}
static void store_record(fx_finite_series_storage *s, unsigned address,
                         const fx_number *value)
{
    memcpy(s->ram + address, value->bytes, 8);
    memcpy(s->ram + address + 8u - (address & 1u), value->bytes + 8, 2);
}
fx_numeric_status fx_finite_series_transfer(fx_finite_series_storage *s,
    uint16_t destination, uint16_t source)
{
    fx_number value;
    if (!valid_storage(s) || destination < 0x8000 || destination > 65516u ||
        !readable(s, source)) return FX_NUMERIC_INVALID;
    load_record(&value, s, source);
    store_record(s, destination, &value);
    if (s->ram[0x80f9] == 0xc4) {
        load_record(&value, s, (unsigned)source + 10u);
        store_record(s, (unsigned)destination + 10u, &value);
    }
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_finite_series_publish_x(fx_finite_series_storage *s,
    uint16_t source)
{
    if (!valid_storage(s) || !readable(s, source)) return FX_NUMERIC_INVALID;
    for (unsigned i = 0; i < 10; ++i)
        s->ram[0x8276 + i] = read_byte(s, (unsigned)source + i);
    if (s->ram[0x80f9] == 0xc4)
        for (unsigned i = 0; i < 10; ++i)
            s->ram[0x8458 + i] = read_byte(s, (unsigned)source + 10u + i);
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_finite_series_begin(fx_finite_series_state *state,
    fx_finite_series_kind kind)
{
    if (!state || (kind != FX_FINITE_SUM && kind != FX_FINITE_PRODUCT))
        return FX_NUMERIC_INVALID;
    memset(state, 0, sizeof *state);
    state->kind = (uint8_t)kind;
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_finite_series_lower(fx_finite_series_state *state,
    fx_finite_series_storage *s, const fx_complex *lower)
{
    if (!valid_state(state, s) || !valid_argument(state, s, lower) ||
        state->phase != FX_FINITE_EMPTY) return FX_NUMERIC_INVALID;
    state->records[INITIAL_X] = lower->real;
    if (s->ram[0x80f9] == 0xc4)
        state->records[END_X] = lower->imaginary;
    state->value = *lower;
    state->phase = FX_FINITE_LOWER_STAGED;
    return FX_NUMERIC_OK;
}
/*0429C checks RAW fractional status first; it does not convert a fraction,
 * radical or marked decimal before that gate. ADD F0 rejects exponent10+. */
static fx_numeric_status integer_bound(int *valid, const fx_number *value)
{
    unsigned trailing = 0, sign = value->bytes[9], exponent = value->bytes[8];
    *valid = 0;
    /*194F2 accepts a zero leading byte before examining any other payload.
     * The separate042A8 exponent-carry test still applies to that record. */
    if (!value->bytes[0]) { *valid = exponent < 0x10; return FX_NUMERIC_OK; }
    if (value->bytes[0] >= 10 || exponent >= 0x10) return FX_NUMERIC_OK;
    /* The raw0A..0E bytes are admitted by the packed subtraction as scales
     * 10..14; raw0F needs255 trailing digits and rejects a nonzero header.
     * Passing this gate does not make that record a canonical decimal. */
    if (exponent == 15) return FX_NUMERIC_OK;
    if (sign >= 5) sign -= 5;
    if (!sign) return FX_NUMERIC_OK;
    for (unsigned index = 8; index; --index) {
        unsigned byte = value->bytes[index - 1];
        if (byte & 15u) break;
        ++trailing;
        if (byte) break;
        ++trailing;
    }
    *valid = trailing >= 14u - exponent;
    return FX_NUMERIC_OK;
}
/*1CD60 accepts ordinary unmarked scalar headers, then ordinary subtraction.
 * Only comparison1 is equality; F0 is a distinct invalid comparison. */
static fx_numeric_status compare(uint8_t *condition, const fx_number *left,
                                 const fx_number *right)
{
    fx_number difference;
    fx_decimal a, b, d;
    if ((left->bytes[0] & 0xf0) || (right->bytes[0] & 0xf0)) {
        *condition = 0xf0;
        return FX_NUMERIC_OK;
    }
    /* A live callback may inject an invalid first decimal digit. Its native
     * loaded coordinate is outside the strict arithmetic proof; do not
     * misclassify that raw0A..0F case as an unsupported record type. */
    if (left->bytes[0] >= 10 || right->bytes[0] >= 10)
        return FX_NUMERIC_UNIMPLEMENTED;
    /*18CB8 compares the raw sign classes before subtracting. This can
     * finish a comparison even when a sign byte is not canonically encoded. */
    if ((left->bytes[9] >= 5) != (right->bytes[9] >= 5)) {
        *condition = left->bytes[9] >= 5 ? 2 : 4;
        return FX_NUMERIC_OK;
    }
    if (fx_decimal_decode(&a, left) != FX_NUMERIC_OK ||
        fx_decimal_decode(&b, right) != FX_NUMERIC_OK)
        return FX_NUMERIC_UNIMPLEMENTED;
    fx_numeric_status status = fx_decimal_binary(&difference, left, right, FX_SUBTRACT);
    if (status != FX_NUMERIC_OK) return status == FX_NUMERIC_INVALID ?
        FX_NUMERIC_UNIMPLEMENTED : status;
    if (fx_decimal_decode(&d, &difference) != FX_NUMERIC_OK)
        return FX_NUMERIC_UNIMPLEMENTED;
    *condition = d.sign < 0 ? 2 : d.sign > 0 ? 4 : 1;
    return FX_NUMERIC_OK;
}
static void finish_condition(fx_finite_series_state *state, uint8_t condition)
{
    state->native_status = condition;
    state->phase = FX_FINITE_NUMERIC_FINISHED;
}
fx_numeric_status fx_finite_series_upper(fx_finite_series_state *state,
    fx_finite_series_storage *s, const fx_complex *upper, uint16_t after_arguments)
{
    fx_number ending, starting;
    uint8_t condition;
    int valid;
    fx_numeric_status status;
    if (!valid_state(state, s) || !valid_argument(state, s, upper) ||
        state->phase != FX_FINITE_LOWER_STAGED) return FX_NUMERIC_INVALID;
    state->value = *upper;
    state->source = after_arguments;
    /* The gate order is upper, lower; the conversion order is also upper,
     * lower. Invalid bounds leave the lower paired transfer already made. */
    status = integer_bound(&valid, &upper->real);
    if (status != FX_NUMERIC_OK) return status;
    if (!valid) {
        finish_condition(state, 8);
        return FX_NUMERIC_OK;
    }
    status = integer_bound(&valid, &state->records[INITIAL_X]);
    if (status != FX_NUMERIC_OK) return status;
    if (!valid) {
        finish_condition(state, 8);
        return FX_NUMERIC_OK;
    }
    status = fx_number_to_decimal(&ending, &upper->real);
    if (status != FX_NUMERIC_OK) return status;
    state->value.real = ending;
    status = fx_number_to_decimal(&starting, &state->records[INITIAL_X]);
    if (status != FX_NUMERIC_OK) return status;
    state->records[INITIAL_X] = starting;
    status = compare(&condition, &starting, &ending);
    if (status != FX_NUMERIC_OK) return status;
    if (condition == 4) {
        finish_condition(state, 8);
        return FX_NUMERIC_OK;
    }
    fx_platform platform = {s->rom, s->rom_size, s->ram, 0, FX_MEMORY_OK};
    /* Native054E6 writes6 once even when SCREEN.bit4 is set. The shared
     * sleep entry supplies that write for bit4 clear; fill its guarded case. */
    if (s->ram[0x80fc] & 0x10) s->ram[0xf031] = 6;
    fx_display_port_sleep(&platform);
    state->records[END_X] = ending;
    if (s->ram[0x80f9] == 0xc4) {
        state->records[SPILLED_COMPANION] = upper->imaginary;
        state->spilled = 1;
    }
    fx_decimal_from_u8(&state->records[ACCUMULATOR], state->kind == FX_FINITE_PRODUCT);
    if (s->ram[0x80f9] == 0xc4)
        fx_decimal_from_u8(&state->records[INITIAL_X],
            state->kind == FX_FINITE_PRODUCT ? 2 : 1);
    /*522A publishes ten bytes, rereads mode, then publishes the adjacent
     * ten-byte record. The state is named/private, so its bytes cannot alias X. */
    memcpy(s->ram + 0x8276, &state->records[INITIAL_X], 10);
    if (s->ram[0x80f9] == 0xc4)
        memcpy(s->ram + 0x8458, &state->records[END_X], 10);
    state->phase = FX_FINITE_READY;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_finite_series_store_result(fx_finite_series_state *state,
    fx_finite_series_storage *s, uint16_t working_address)
{
    if (!valid_state(state, s) || working_address < 0x8000 ||
        working_address > 65516u || state->phase != FX_FINITE_NUMERIC_FINISHED ||
        state->native_status) return FX_NUMERIC_INVALID;
    store_record(s, working_address, &state->records[ACCUMULATOR]);
    if (s->ram[0x80f9] == 0xc4)
        store_record(s, (unsigned)working_address + 10u, &state->records[INITIAL_X]);
    load_record(&state->value.real, s, working_address);
    load_record(&state->value.imaginary, s, (unsigned)working_address + 10u);
    return FX_NUMERIC_OK;
}

/* Callable scalar1C6A4/1C6CC differs from utilities on F-valued records.
 * Compact dispatch runs first and commits its mathematical pool stages;
 * ordinary F admission then produces canonical Math3, regardless of tag. */
static fx_numeric_status binary_leaf(fx_number *out, fx_finite_series_storage *s,
    const fx_number *current, const fx_number *other,
    uint16_t physical_current, fx_binary_op operation)
{
    int radical = fx_number_kind(current) == FX_NUMBER_SURD ||
                  fx_number_kind(other) == FX_NUMBER_SURD;
    int error = fx_number_kind(current) == FX_NUMBER_ERROR ||
                fx_number_kind(other) == FX_NUMBER_ERROR;
    if (error && !radical) {
        fx_number_error(out, 3);
        return FX_NUMERIC_OK;
    }
    fx_numeric_status status = radical ?
        fx_eval_surd_workspace_binary(out, s->ram, current, other,
            physical_current, 0, operation) :
        fx_number_binary(out, current, other, operation);
    if (status == FX_NUMERIC_OK && error) fx_number_error(out, 3);
    return status;
}
static int poll(fx_finite_series_storage *s, const fx_calculus_control *control)
{
    fx_platform platform = {s->rom, s->rom_size, s->ram, 0, FX_MEMORY_OK};
    s->ram[0x8e00] = 2;
    fx_timer_start(&platform, 0x129a);
    int cancelled = control && control->cancelled &&
        control->cancelled(control->userdata);
    if (cancelled) { s->ram[0x80f2] = 4; s->ram[0x80f3] = 16; }
    s->ram[0x8e00] = 0;
    return cancelled;
}
fx_numeric_status fx_finite_series_step(fx_finite_series_state *state,
    fx_finite_series_storage *s, fx_finite_series_function function,
    void *userdata, const fx_calculus_control *control)
{
    fx_number live, incremented, one;
    fx_complex x;
    fx_finite_series_evaluation evaluation;
    uint8_t condition;
    fx_numeric_status status;
    if (!valid_state(state, s) || !function || !valid_control(state, s, control) ||
        (state->phase != FX_FINITE_READY && state->phase != FX_FINITE_ACTIVE))
        return FX_NUMERIC_INVALID;
    state->phase = FX_FINITE_ACTIVE;
    if (poll(s, control)) { finish_condition(state, 1); return FX_NUMERIC_OK; }
    memcpy(&x.real, s->ram + 0x8276, 10);
    fx_number_zero(&x.imaginary);
    if (s->ram[0x80f9] == 0xc4) memcpy(&x.imaginary, s->ram + 0x8458, 10);
    memset(&evaluation, 0, sizeof evaluation);
    evaluation.condition = FX_FINITE_EXPRESSION_COMPLETE;
    status = function(&evaluation, &x, userdata);
    if (status != FX_NUMERIC_OK) return status;
    if (evaluation.error_sink_written)
        state->records[ACCUMULATOR] = evaluation.error_sink;
    state->value = evaluation.value;
    state->body_source = evaluation.source;
    if (evaluation.condition != FX_FINITE_EXPRESSION_COMPLETE) {
        finish_condition(state, evaluation.condition);
        return FX_NUMERIC_OK;
    }
    status = binary_leaf(&state->records[ACCUMULATOR], s,
        &state->records[ACCUMULATOR], &state->value.real, 0,
        state->kind == FX_FINITE_PRODUCT ? FX_MULTIPLY : FX_ADD);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_decimal_integer_cleanup(&state->records[ACCUMULATOR]);
    if (status != FX_NUMERIC_OK) return status;
    if (state->records[ACCUMULATOR].bytes[0] >= 0xf0) {
        finish_condition(state, state->records[ACCUMULATOR].bytes[0] & 15u);
        return FX_NUMERIC_OK;
    }
    memcpy(&live, s->ram + 0x8276, 10);
    status = compare(&condition, &live, &state->records[END_X]);
    if (status != FX_NUMERIC_OK) return status;
    if (condition == 1) {
        if (state->kind == FX_FINITE_PRODUCT &&
            fx_number_kind(&state->records[ACCUMULATOR]) == FX_NUMBER_DECIMAL)
            state->records[ACCUMULATOR].bytes[0] &= (uint8_t)~0x40;
        state->value.real = state->records[ACCUMULATOR];
        if (s->ram[0x80f9] == 0xc4)
            state->value.imaginary = state->records[INITIAL_X];
        finish_condition(state, 0);
    } else {
        fx_decimal_from_u8(&one, 1);
        status = binary_leaf(&incremented, s, &live, &one, 0x8276, FX_ADD);
        if (status != FX_NUMERIC_OK) return status;
        /*0437A/0446E's NUMERICAL return is ignored. A new F-valued X
         * still reaches the next5550; only a host implementation gap stops. */
        memcpy(s->ram + 0x8276, &incremented, 10);
    }
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_finite_series_run(fx_finite_series_state *state,
    fx_finite_series_storage *s, fx_finite_series_function function,
    void *userdata, const fx_calculus_control *control, size_t max_samples)
{
    size_t samples = 0;
    if (!valid_state(state, s) || !function || !valid_control(state, s, control))
        return FX_NUMERIC_INVALID;
    while (state->phase == FX_FINITE_READY || state->phase == FX_FINITE_ACTIVE) {
        if (max_samples && samples == max_samples) return FX_NUMERIC_UNIMPLEMENTED;
        fx_numeric_status status = fx_finite_series_step(state, s, function, userdata, control);
        if (status != FX_NUMERIC_OK) return status;
        ++samples;
    }
    return state->phase == FX_FINITE_NUMERIC_FINISHED ? FX_NUMERIC_OK : FX_NUMERIC_INVALID;
}
