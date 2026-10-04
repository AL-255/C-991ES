/* Ordered compact-radical component emission and prepared conversion.
 * SPDX-License-Identifier: GPL-3.0-or-later */
#include "fx_surd_components.h"
#include "fx_raw_decimal_divide.h"
#include "fx_raw_decimal_multiply_add.h"
#include <string.h>

enum { COMPONENT_POOL = 0x8640 };

/* Decimal construction preserves the packed pair and raw positive-zero
 * sign. An aliased source can supply a zero coefficient with sign2. */
static fx_number packed_pair(uint8_t pair, uint8_t sign)
{
    fx_number out = {{0}};
    if (pair < 10) out.bytes[0] = pair;
    else {
        out.bytes[0] = pair >> 4;
        out.bytes[1] = (uint8_t)((pair & 15) << 4);
        out.bytes[8] = 1;
    }
    out.bytes[9] = sign;
    return out;
}

static fx_number packed_radical(uint8_t high, uint8_t low)
{
    fx_number out;
    high &= 15;
    if (!high) return packed_pair(low, 1);
    memset(&out, 0, sizeof(out));
    out.bytes[0] = high; out.bytes[1] = low;
    out.bytes[8] = 2; out.bytes[9] = 1;
    return out;
}

static void commit_component(uint8_t ram[65536], unsigned index,
                              const fx_number *number)
{
    memcpy(ram + COMPONENT_POOL + 10 * index, number->bytes, 10);
}

static void emit_components(uint8_t ram[65536], const uint8_t *source)
{
    fx_number component;
    uint8_t coefficient = source[2];
    if (!coefficient) {
        memset(&component, 0, sizeof(component));
        commit_component(ram, 0, &component);
        commit_component(ram, 1, &component);
        component = packed_pair(1, 1);
        commit_component(ram, 2, &component);
    } else {
        component = packed_pair(coefficient, source[9]);
        commit_component(ram, 0, &component);
        component = packed_radical(source[0], source[1]);
        commit_component(ram, 1, &component);
        component = packed_pair(source[3], 1);
        commit_component(ram, 2, &component);
    }
    /* Each preceding commit can change these live source fields. There is
     * no second-term empty-triple shortcut in the native prepared emitter. */
    component = packed_pair(source[6], source[8]);
    commit_component(ram, 3, &component);
    component = packed_radical(source[4], source[5]);
    commit_component(ram, 4, &component);
    component = packed_pair(source[7], 1);
    commit_component(ram, 5, &component);
}

fx_numeric_status fx_surd_components_emit_live(uint8_t ram[65536],
                                                 uint16_t source)
{
    if (!ram || source > 65526u) return FX_NUMERIC_INVALID;
    emit_components(ram, ram + source);
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_surd_components_emit_copy(uint8_t ram[65536],
                                                 const fx_number *source)
{
    fx_number saved;
    if (!ram || !source) return FX_NUMERIC_INVALID;
    saved = *source;
    emit_components(ram, saved.bytes);
    return FX_NUMERIC_OK;
}

static void coordinate(uint8_t out[10], const fx_number *in)
{
    out[0] = in->bytes[8]; out[1] = in->bytes[9];
    for (unsigned i = 0; i < 8; ++i) out[2+i] = in->bytes[7-i];
}

static void record(fx_number *out, const uint8_t in[10])
{
    out->bytes[8] = in[0]; out->bytes[9] = in[1];
    for (unsigned i = 0; i < 8; ++i) out->bytes[7-i] = in[2+i];
}

fx_numeric_status fx_surd_components_decimal(fx_number *out,
                                              const fx_number components[6])
{
    uint8_t terms[2][10] = {{0}}, root_coordinate[10], coefficient[10];
    uint8_t denominator[10], product[10], sum[10];
    fx_number root;
    fx_numeric_status status;
    if (!out || !components) return FX_NUMERIC_INVALID;
    for (unsigned term = 0; term < 2; ++term) {
        unsigned index = 3 * term;
        if (!term && !components[0].bytes[0]) continue;
        status = fx_numeric_component_sqrt(&root, &components[index+1]);
        if (status != FX_NUMERIC_OK) return status;
        coordinate(root_coordinate, &root);
        coordinate(coefficient, &components[index]);
        coordinate(denominator, &components[index+2]);
        status = fx_raw_decimal_multiply(product, root_coordinate, coefficient);
        if (status == FX_NUMERIC_OK)
            status = fx_raw_decimal_divide(terms[term], product, denominator);
        if (status != FX_NUMERIC_OK) return status;
    }
    /* Native175DC retains the second term as the left operand, which also
     * determines which numerical error survives when both terms fail. */
    status = fx_raw_decimal_add(sum, terms[1], terms[0]);
    if (status == FX_NUMERIC_OK) record(out, sum);
    return status;
}

fx_numeric_status fx_surd_components_convert_live(uint8_t ram[65536],
                                                    uint16_t source,
                                                    uint16_t destination)
{
    fx_number components[6], result;
    fx_numeric_status status;
    if (!ram || source > 65526u || destination > 65526u)
        return FX_NUMERIC_INVALID;
    fx_surd_components_emit_live(ram, source);
    memcpy(components, ram + COMPONENT_POOL, sizeof(components));
    status = fx_surd_components_decimal(&result, components);
    if (status == FX_NUMERIC_OK) memcpy(ram + destination, result.bytes, 10);
    return status;
}

fx_numeric_status fx_surd_components_convert_copy(uint8_t ram[65536],
                                                    fx_number *out,
                                                    const fx_number *source)
{
    fx_number components[6];
    if (!ram || !out || !source) return FX_NUMERIC_INVALID;
    fx_surd_components_emit_copy(ram, source);
    memcpy(components, ram + COMPONENT_POOL, sizeof(components));
    return fx_surd_components_decimal(out, components);
}
