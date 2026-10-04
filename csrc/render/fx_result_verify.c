/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_result_verify.h"

static uint8_t data_byte(const fx_render *render, uint16_t address)
{
    if (address >= 0x8000) return render->memory[address];
    return address < render->rom_size ? render->rom[address] : 0;
}

fx_format_status fx_format_verify_result(const fx_render *render,
    const fx_number *value, uint8_t *tokens, size_t capacity,
    fx_format_result *result)
{
    if (!render || !render->memory || (!render->rom && render->rom_size) ||
        !value || !result ||
        (capacity && !tokens)) return FX_FORMAT_INVALID;
    result->length = 0;
    result->kind = 0;
    result->recognized = 0;
    if (capacity) tokens[0] = 0;

    /* 1CCF6 returns class1 on these two raw-record branches only. Compact
     * SURDs, including cancellation to decimal zero, stay on its sign
     * branch and therefore cannot produce class1. Unsupported noncompact
     * tags return classF0, also TRUE. This is the exact Boolean projection,
     * not approximate evaluation of the record's mathematical value. */
    unsigned header = value->bytes[0] & 0xf0;
    int zero = !value->bytes[0] ||
        (header < 0x50 && !(value->bytes[8] | value->bytes[9]));
    uint16_t pointer_address = zero ? 0x8df2 : 0x8df4;
    uint16_t source = (uint16_t)(data_byte(render, pointer_address) |
                     (uint16_t)data_byte(render, pointer_address + 1) << 8);
    if (!source) return capacity ? FX_FORMAT_OK : FX_FORMAT_BUFFER_TOO_SMALL;

    for (size_t length = 0; length < FX_RENDER_MEMORY_BYTES; ++length) {
        uint8_t byte = data_byte(render, (uint16_t)(source + length));
        if (!byte) {
            result->length = length;
            if (capacity) tokens[length < capacity ? length : capacity - 1] = 0;
            return length < capacity ? FX_FORMAT_OK : FX_FORMAT_BUFFER_TOO_SMALL;
        }
        if (length + 1 < capacity) tokens[length] = byte;
    }
    result->length = FX_RENDER_MEMORY_BYTES;
    if (capacity) tokens[capacity - 1] = 0;
    return FX_FORMAT_UNIMPLEMENTED;
}
