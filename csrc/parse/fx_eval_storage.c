/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_eval_storage.h"
#include <string.h>

static int valid(const fx_eval_storage *s)
{
    return s && s->ram && s->ram_size == 65536u;
}
static uint8_t read_byte(const fx_eval_storage *s, unsigned address)
{
    return address >= 0x8000u ? s->ram[address] : s->rom[address];
}
static void copy_word(fx_eval_storage *s, unsigned destination, unsigned source)
{
    uint8_t low = read_byte(s, source), high = read_byte(s, source + 1u);
    s->ram[destination] = low;
    s->ram[destination + 1u] = high;
}
uint8_t fx_eval_storage_first_free(uint8_t mask)
{
    unsigned identity;
    for (identity = 4; identity <= 8; ++identity)
        if (!(mask & (0x80u >> (identity - 4u)))) return (uint8_t)identity;
    return 0;
}
static uint8_t identity_bit(uint8_t identity)
{
    return (uint8_t)(0x80u >> ((identity - 4u) & 7u));
}
uint8_t fx_eval_storage_reserve(uint8_t mask, uint8_t identity)
{
    return (uint8_t)(mask | identity_bit(identity));
}
uint8_t fx_eval_storage_release(uint8_t mask, uint8_t identity)
{
    return (uint8_t)(mask & (uint8_t)~identity_bit(identity));
}
fx_numeric_status fx_eval_storage_copy_slot(fx_eval_storage *s,
    uint8_t destination_header, uint8_t source_header)
{
    unsigned source = source_header & 15u, destination = destination_header & 15u;
    unsigned index, input = 0x829eu + 90u * source;
    unsigned output = 0x829eu + 90u * destination;
    if (!valid(s)) return FX_NUMERIC_INVALID;
    copy_word(s, 0x80e0u + 2u * destination, 0x80e0u + 2u * source);
    for (index = 0; index < 90; index += 2)
        copy_word(s, output + index, input + index);
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_eval_storage_copy_bytes(fx_eval_storage *s,
    uint16_t destination, uint16_t source, size_t length)
{
    size_t index;
    if (!valid(s)) return FX_NUMERIC_INVALID;
    if (length > 65536u - destination || length > 65536u - source ||
        (length && destination < 0x8000u) ||
        (length && source < 0x8000u && (!s->rom ||
            s->rom_size < (length < 0x8000u - source ? source + length : 0x8000u))))
        return FX_NUMERIC_UNIMPLEMENTED;
    for (index = 0; index < length; ++index)
        s->ram[destination + index] = read_byte(s, (unsigned)(source + index));
    return FX_NUMERIC_OK;
}
static fx_numeric_status temporary(fx_eval_storage *s, uint8_t *reference,
    uint8_t *mask, uint8_t *native_status)
{
    uint8_t destination = fx_eval_storage_first_free(*mask), original;
    *native_status = destination ? 0 : 7;
    if (!destination) return FX_NUMERIC_OK;
    original = *reference;
    *mask = fx_eval_storage_reserve(*mask, destination);
    *reference = (uint8_t)((original & 0xf0u) | destination);
    (void)fx_eval_storage_copy_slot(s, *reference, original);
    s->ram[0x8125] = *mask;
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_eval_storage_temporary(fx_eval_storage *s,
    fx_number *reference, uint8_t *mask, uint8_t *native_status)
{
    if (!valid(s) || !reference || !mask || !native_status) return FX_NUMERIC_INVALID;
    return temporary(s, reference->bytes, mask, native_status);
}
fx_numeric_status fx_eval_storage_temporary_address(fx_eval_storage *s,
    uint16_t reference, uint8_t *mask, uint8_t *native_status)
{
    if (!valid(s) || !mask || !native_status) return FX_NUMERIC_INVALID;
    if (reference < 0x8000u || reference > 65526u) return FX_NUMERIC_UNIMPLEMENTED;
    return temporary(s, s->ram + reference, mask, native_status);
}
static int rich(uint8_t header)
{
    return header >= 0x90u || (header >= 0x60u && header < 0x80u);
}
static int prepared_operands(uint8_t count, uint8_t depth)
{
    return (count == 1 || count == 2 || count == 0xffu) &&
        (depth < 10 || (count == 1 && depth == 10));
}
/* Native copies load a complete component before storing it. They read the
 * imaginary component after real writes, which matters for partial aliases. */
static void copy_pair(fx_eval_storage *s, uint8_t *destination, const uint8_t *source)
{
    uint8_t component[10];
    uintptr_t base = (uintptr_t)s->ram, input = (uintptr_t)source;
    uintptr_t output = (uintptr_t)destination;
    unsigned input_tail = input >= base && input < base + 65536u ?
        8u - (unsigned)((input - base) & 1u) : 8u;
    unsigned output_tail = output >= base && output < base + 65536u ?
        8u - (unsigned)((output - base) & 1u) : 8u;
    /* EA+ advances to an even address after the eight-byte transfer. An
     * odd physical reference therefore reads/writes its tail at offset7. */
    memcpy(component, source, 8);
    memcpy(component + 8, source + input_tail, 2);
    memcpy(destination, component, 8);
    memcpy(destination + output_tail, component + 8, 2);
    if (s->ram[0x80f9] == 0xc4u) {
        memcpy(component, source + 10, 8);
        memcpy(component + 8, source + 10 + input_tail, 2);
        memcpy(destination + 10, component, 8);
        memcpy(destination + 10 + output_tail, component + 8, 2);
    }
}
fx_numeric_status fx_eval_storage_save_operand(fx_eval_storage *s,
    const fx_number value[2], uint8_t *count, uint8_t *native_status)
{
    if (!valid(s) || !value || !count || !native_status) return FX_NUMERIC_INVALID;
    if (*count >= 10) { *native_status = 7; return FX_NUMERIC_OK; }
    unsigned destination = 0x8078u + 10u * *count;
    ++*count;
    if (s->ram[0x80f9] == 0xc4u) ++*count;
    copy_pair(s, s->ram + destination, (const uint8_t *)value);
    *native_status = 0; return FX_NUMERIC_OK;
}
fx_numeric_status fx_eval_storage_restore_operand(fx_eval_storage *s,
    fx_number value[2], uint8_t *count, uint8_t *native_status)
{
    if (!valid(s) || !value || !count || !native_status) return FX_NUMERIC_INVALID;
    if (!*count) { *native_status = 7; return FX_NUMERIC_OK; }
    --*count;
    if (s->ram[0x80f9] == 0xc4u) --*count;
    unsigned source = 0x8078u + 10u * *count;
    copy_pair(s, (uint8_t *)value, s->ram + source);
    *native_status = 0; return FX_NUMERIC_OK;
}
static void release_reference(uint8_t *mask, uint8_t header)
{
    if (rich(header) && (header & 15u) >= 4u)
        *mask = fx_eval_storage_release(*mask, (uint8_t)(header & 15u));
}
static fx_numeric_status stage(fx_eval_storage *s, uint8_t *current,
    uint8_t *other, uint8_t operation, uint8_t count, uint8_t depth,
    uint8_t *mask, fx_eval_storage_result *result)
{
    uint8_t header = *current, other_header = *other, source = header & 15u;
    uint8_t status = 0, mapped = operation, allocation_operation = operation;
    int binary = 0, allocate = 0, copy_current_to_other = 0;
    result->operation = operation; result->native_status = 0;
    result->route = FX_EVAL_STORAGE_SCALAR;
    if (operation == 3) return FX_NUMERIC_OK;
    if (!rich(header)) {
        if (count == 1 || !rich(other_header)) return FX_NUMERIC_OK;
        if (operation != 45) {
            result->route = FX_EVAL_STORAGE_ERROR; result->native_status = 3;
            return FX_NUMERIC_OK;
        }
        /*15BDA saves the other operand in the numerical data stack, then
         * swaps the records. The stack payload remains observable afterward. */
        uint8_t saved_header = header;
        uint8_t after_push = (uint8_t)(depth + 1u + (s->ram[0x80f9] == 0xc4u));
        uint8_t pop_depth;
        copy_pair(s, s->ram + 0x8078u + 10u * depth, other);
        copy_pair(s, other, current);
        pop_depth = (uint8_t)(after_push - 1u - (s->ram[0x80f9] == 0xc4u));
        copy_pair(s, current, s->ram + 0x8078u + 10u * pop_depth);
        /*164C8..164CC swaps the saved type bytes, rather than rereading
         * records that an alias may have changed during the data transfers. */
        header = other_header; other_header = saved_header;
        source = header & 15u;
        binary = 1;
    } else if (count == 0xffu) binary = 1;
    else if (header < 0x80u) {
        if (operation != 122 && operation != 123) {
            mapped = (uint8_t)(operation - 10u);
            if (mapped == 3) {
                release_reference(mask, header);
                goto finish;
            }
            if (mapped >= 98) {
                allocate = 1; copy_current_to_other = 1;
                allocation_operation = mapped;
                mapped = (uint8_t)(mapped - 91u);
            }
        }
    } else {
        mapped = (uint8_t)(operation - 11u);
        if (!mapped) { release_reference(mask, header); goto finish; }
        ++mapped;
    }
    if (binary) {
        if (operation == 47) {
            mapped = 13; release_reference(mask, header); goto finish;
        }
        if (operation == 45) {
            if (other_header >= 0x90u) mapped = (uint8_t)(mapped + 3u);
            else if (other_header >= 0x60u && other_header < 0x80u)
                mapped = (uint8_t)(mapped + 4u);
        }
        mapped = (uint8_t)(mapped - 34u);
        allocation_operation = mapped;
        allocate = source < 4;
    } else if (!copy_current_to_other) {
        allocate = source < 4;
        allocation_operation = mapped;
        if (mapped == 122 || mapped == 123) mapped = (uint8_t)(mapped - 106u);
        else if (mapped >= 85) {
            if (mapped == 85) mapped = (uint8_t)(mapped + 11u);
            mapped = (uint8_t)(mapped - 91u);
        }
    }
    if (allocate) {
        uint8_t destination = fx_eval_storage_first_free(*mask);
        if (!destination) {
            result->route = FX_EVAL_STORAGE_ERROR; result->native_status = 7;
            result->operation = allocation_operation; return FX_NUMERIC_OK;
        }
        header = *current;
        *mask = fx_eval_storage_reserve(*mask, destination);
        if (copy_current_to_other) copy_pair(s, other, current);
        *current = (uint8_t)((*current & 0xf0u) | destination);
        (void)fx_eval_storage_copy_slot(s, *current, header);
        if (copy_current_to_other && (header & 15u) >= 4u)
            *mask = fx_eval_storage_release(*mask, (uint8_t)(header & 15u));
    }
finish:
    if (binary) release_reference(mask, other_header);
    s->ram[0x8125] = *mask;
    result->operation = mapped; result->native_status = status;
    result->route = FX_EVAL_STORAGE_RICH;
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_eval_storage_stage(fx_eval_storage *s,
    fx_number current[2], fx_number other[2], uint8_t operation,
    uint8_t count, uint8_t depth, uint8_t *mask, fx_eval_storage_result *result)
{
    if (!valid(s) || !current || !other || !mask || !result) return FX_NUMERIC_INVALID;
    if (!prepared_operands(count, depth))
        return FX_NUMERIC_UNIMPLEMENTED;
    return stage(s, (uint8_t *)current, (uint8_t *)other, operation, count, depth, mask, result);
}
fx_numeric_status fx_eval_storage_stage_address(fx_eval_storage *s,
    uint16_t pair, uint8_t operation, uint8_t count, uint8_t depth,
    uint8_t *mask, fx_eval_storage_result *result)
{
    if (!valid(s) || !mask || !result) return FX_NUMERIC_INVALID;
    if (pair < 0x8000u || pair > 65496u ||
        !prepared_operands(count, depth))
        return FX_NUMERIC_UNIMPLEMENTED;
    return stage(s, s->ram + pair, s->ram + pair + 20u, operation, count, depth, mask, result);
}
